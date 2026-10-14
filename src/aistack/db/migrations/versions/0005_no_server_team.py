"""The server's own team, `everyone`, becomes an ordinary team (ADR-0019).

No new account joins it. Where people are in it or skills are in it, it stays as a shared team
with the server's admin as its admin, so nothing anyone could see disappears and anyone may
leave. A server where it is still empty, as on a fresh install, loses it altogether.
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"

# Only the columns this migration reads or writes. A migration never imports a model.
_user = sa.table("user", sa.column("user_id", sa.Uuid()), sa.column("is_admin", sa.Boolean()))
_team = sa.table("team", sa.column("team_id", sa.Uuid()), sa.column("kind", sa.String()),
                 sa.column("created_by", sa.Uuid()))
_member = sa.table("team_member", sa.column("team_id", sa.Uuid()),
                   sa.column("user_id", sa.Uuid()), sa.column("role", sa.String()))
_skill = sa.table("skill", sa.column("skill_id", sa.Uuid()), sa.column("team_id", sa.Uuid()))
_group = sa.table("team_group", sa.column("group_id", sa.Uuid()),
                  sa.column("team_id", sa.Uuid()))
_group_rows = [sa.table(name, sa.column("group_id", sa.Uuid()))
               for name in ("group_member", "group_unsubscribed")]


def upgrade() -> None:
    connection = op.get_bind()
    server_team = connection.scalar(sa.select(_team.c.team_id).where(_team.c.kind == "SERVER"))
    if server_team is not None:
        _retire(connection, server_team)

    # On SQLite this rebuilds the table, which migrate_schema runs with foreign keys off.
    with op.batch_alter_table("team") as batch:
        batch.drop_constraint("ck_team_kind", type_="check")
        batch.create_check_constraint("ck_team_kind",
                                      sa.column("kind").in_(("PERSONAL", "SHARED")))


def _retire(connection, team_id) -> None:
    def count(table) -> int:
        return connection.scalar(sa.select(sa.func.count()).select_from(table)
                                 .where(table.c.team_id == team_id))

    if count(_member) == 0 and count(_skill) == 0:
        # Deleted by hand, children first: migrate_schema runs with foreign keys off on
        # SQLite, so nothing cascades.
        groups = sa.select(_group.c.group_id).where(_group.c.team_id == team_id)
        for table in _group_rows:
            connection.execute(sa.delete(table).where(table.c.group_id.in_(groups)))
        connection.execute(sa.delete(_group).where(_group.c.team_id == team_id))
        connection.execute(sa.delete(_team).where(_team.c.team_id == team_id))
        return

    admin = connection.scalar(sa.select(_user.c.user_id).where(_user.c.is_admin.is_(True)))
    connection.execute(sa.update(_team).where(_team.c.team_id == team_id)
                       .values(kind="SHARED", created_by=admin))
    if admin is not None:
        connection.execute(sa.update(_member)
                           .where(_member.c.team_id == team_id, _member.c.user_id == admin)
                           .values(role="ADMIN"))
