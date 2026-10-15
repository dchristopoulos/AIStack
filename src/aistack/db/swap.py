"""Replace a SQLite database's rows with another file's, in one short transaction."""

from pathlib import Path

from sqlalchemy import Engine, delete

from aistack.db.models import Base

# Each file keeps its own record of the schema it is at.
_SCHEMA_TABLES = ("alembic_version", "schema_compatibility")


def swap_in(engine: Engine, source: Path, unless: str) -> bool:
    """Make every table in `engine`'s database hold exactly the rows `source` holds, unless
    the query `unless` returns a row. False, changing nothing, when it does.

    Both files are at this release's schema. The rows are copied by SQL inside the database,
    so the write lock is held for as long as copying them takes, not for however long it took
    to build `source`. `unless` runs in the same transaction and sees `source` as `rebuilt`,
    so it can refuse a copy that would lose a row written while `source` was being built.
    Connections elsewhere keep their file and see the new rows at their next transaction.
    """
    tables = [table for table in Base.metadata.sorted_tables if table.name not in _SCHEMA_TABLES]
    with engine.connect() as connection:
        driver = connection.connection.driver_connection
        # Refused inside a transaction, so attached before SQLAlchemy begins one.
        driver.execute("ATTACH DATABASE ? AS rebuilt", (str(source),))
        try:
            with connection.begin() as transaction:
                if connection.exec_driver_sql(unless).first() is not None:
                    transaction.rollback()
                    return False
                # Children before parents, so no row is left pointing at one that is gone.
                for table in reversed(tables):
                    connection.execute(delete(table))
                for table in tables:
                    columns = ", ".join(f'"{column.name}"' for column in table.columns)
                    connection.exec_driver_sql(
                        f'INSERT INTO main."{table.name}" ({columns}) '
                        f'SELECT {columns} FROM rebuilt."{table.name}"')
            return True
        finally:
            driver.execute("DETACH DATABASE rebuilt")
