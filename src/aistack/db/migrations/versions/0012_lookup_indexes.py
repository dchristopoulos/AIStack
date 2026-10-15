"""Index the columns the services look up by, and allow one Library per user.

Every unique constraint leads with its first column, so none of them finds a user's teams,
groups or unsubscriptions, and PostgreSQL indexes no foreign key on its own. Indexes only, so
every release that knows 0011 keeps working: the unique one admits exactly what every release
already writes, one personal team per user.
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"

older_releases_compatible = True

# Declared here rather than imported: the model describes the newest schema.
_team = sa.table("team", sa.column("created_by", sa.Uuid()), sa.column("kind", sa.String()))

_INDEXES = (
    ("ix_team_member_user_id", "team_member", ["user_id"]),
    ("ix_group_member_user_id", "group_member", ["user_id"]),
    ("ix_group_unsubscribed_user_id", "group_unsubscribed", ["user_id"]),
    ("ix_machine_skill_skill_id", "machine_skill", ["skill_id"]),
    ("ix_skill_source_skill_id", "skill", ["source_skill_id"]),
    ("ix_skill_group_id", "skill", ["group_id"]),
    ("ix_invite_team_id_created_on", "invite", ["team_id", "created_on"]),
)


def upgrade() -> None:
    personal = _team.c.kind == "PERSONAL"
    doubled = op.get_bind().execute(
        sa.select(sa.func.count()).select_from(
            sa.select(_team.c.created_by).where(personal).group_by(_team.c.created_by)
            .having(sa.func.count() > 1).subquery())).scalar()
    if doubled:
        raise RuntimeError(
            f"{doubled} users have more than one personal team, which AIStack never makes. "
            "Keep one personal team for each, then start the server again. Nothing was changed."
        )
    op.create_index("ux_team_personal_owner", "team", ["created_by"], unique=True,
                    sqlite_where=personal, postgresql_where=personal)
    for name, table, columns in _INDEXES:
        op.create_index(name, table, columns)
