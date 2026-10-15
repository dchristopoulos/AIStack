from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# The names PostgreSQL gives a constraint nobody named, so a table made from the models and
# one made by the migrations agree on PostgreSQL, and SQLite gets the same names instead of
# none. Indexes keep SQLAlchemy's own default. CHECK constraints are always named by hand.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    """Declarative base for every AIStack table.

    Models import this rather than each declaring their own, so `Base.metadata` is the one
    description of the schema the migrations are checked against.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
