"""Name constraints the way the models do, on both databases.

0002 named the skill table's three new foreign keys `fk_skill_<column>_<table>`. Every other
constraint on PostgreSQL carries the name PostgreSQL gives one nobody named, which the models'
naming convention now spells out, so those three are renamed to match. SQLite stored no name
for most constraints. The tables whose unique constraints alembic compares by name are rebuilt
with the convention; the large ones (revisions, files, placements) are left as they are,
because a name there changes nothing and the rebuild would copy every file. Names only, so
every release that knows 0010 keeps working.
"""

from alembic import op

revision = "0011"
down_revision = "0010"

older_releases_compatible = True

# The models' convention as of this migration, copied rather than imported (AGENTS.md).
_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}

_RENAMED = (
    ("fk_skill_team_id_team", "skill_team_id_fkey", "team", "team_id", "team_id", None),
    ("fk_skill_group_id_team_group", "skill_group_id_fkey", "team_group", "group_id",
     "group_id", "SET NULL"),
    ("fk_skill_source_skill_id_skill", "skill_source_skill_id_fkey", "skill",
     "source_skill_id", "skill_id", "SET NULL"),
)

_SQLITE_REBUILT = ("user", "machine", "team", "invite")


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for old, new, *_ in _RENAMED:
            op.execute(f'ALTER TABLE skill RENAME CONSTRAINT "{old}" TO "{new}"')
        return
    # SQLite cannot rename a constraint, so each table is rebuilt with the names.
    with op.batch_alter_table("skill", naming_convention=_NAMING_CONVENTION,
                              recreate="always") as batch:
        for old, new, referred, local, remote, ondelete in _RENAMED:
            batch.drop_constraint(old, type_="foreignkey")
            batch.create_foreign_key(new, referred, [local], [remote], ondelete=ondelete)
    for table in _SQLITE_REBUILT:
        with op.batch_alter_table(table, naming_convention=_NAMING_CONVENTION,
                                  recreate="always"):
            pass
