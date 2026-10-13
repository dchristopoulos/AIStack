"""Teams, groups, and a personal space per user (ADR-0015).

Before this, a server was one vault that everybody shared and installed from. After it:

- the server's own team holds every skill that existed, and every user is in it, so nothing
  anyone could see is hidden;
- each user has a personal team, and each skill one of their machines had a decision about
  is copied into it with its whole history, because from here on a machine installs only
  from its user's personal team. The copy remembers the skill it came from.
"""

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"

SERVER_TEAM_NAME = "everyone"

# Only the columns this migration reads or writes. A migration never imports a model: the
# model describes the schema of the newest release, and this file runs against an older one.
_user = sa.table("user", sa.column("user_id", sa.Uuid()), sa.column("username", sa.String()),
                 sa.column("is_admin", sa.Boolean()))
_team = sa.table("team", sa.column("team_id", sa.Uuid()), sa.column("name", sa.String()),
                 sa.column("kind", sa.String()), sa.column("created_by", sa.Uuid()),
                 sa.column("created_on", sa.DateTime(timezone=True)))
_member = sa.table("team_member", sa.column("team_member_id", sa.Uuid()),
                   sa.column("team_id", sa.Uuid()), sa.column("user_id", sa.Uuid()),
                   sa.column("role", sa.String()), sa.column("sees_all_groups", sa.Boolean()),
                   sa.column("created_on", sa.DateTime(timezone=True)))
_skill = sa.table("skill", sa.column("skill_id", sa.Uuid()), sa.column("team_id", sa.Uuid()),
                  sa.column("name", sa.String()), sa.column("description", sa.String()),
                  sa.column("origin", sa.String()),
                  sa.column("created_on", sa.DateTime(timezone=True)),
                  sa.column("pushed_by", sa.Uuid()), sa.column("source_skill_id", sa.Uuid()),
                  sa.column("source_revision", sa.Integer()),
                  sa.column("archived", sa.Boolean()))
_version = sa.table("skill_version", sa.column("skill_version_id", sa.Uuid()),
                    sa.column("skill_id", sa.Uuid()), sa.column("revision", sa.Integer()),
                    sa.column("version", sa.String()), sa.column("content_hash", sa.String()),
                    sa.column("frontmatter_json", sa.JSON()),
                    sa.column("created_on", sa.DateTime(timezone=True)),
                    sa.column("pushed_by", sa.Uuid()))
_file = sa.table("skill_file", sa.column("skill_file_id", sa.Uuid()),
                 sa.column("skill_version_id", sa.Uuid()), sa.column("path", sa.String()),
                 sa.column("content", sa.Text()), sa.column("sha256", sa.String()),
                 sa.column("executable", sa.Boolean()))
_machine = sa.table("machine", sa.column("machine_id", sa.Uuid()),
                    sa.column("user_id", sa.Uuid()))
_machine_skill = sa.table("machine_skill", sa.column("machine_id", sa.Uuid()),
                          sa.column("skill_id", sa.Uuid()))


def upgrade() -> None:
    op.create_table(
        "team",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.Enum("SERVER", "PERSONAL", "SHARED", name="ck_team_kind",
                                  native_enum=False, create_constraint=True, length=16),
                  nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("invite_hash", sa.String(length=64), nullable=True),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["user.user_id"]),
        sa.PrimaryKeyConstraint("team_id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("invite_hash"),
    )
    op.create_table(
        "team_member",
        sa.Column("team_member_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Enum("ADMIN", "MEMBER", name="ck_team_member_role",
                                  native_enum=False, create_constraint=True, length=16),
                  nullable=False),
        sa.Column("sees_all_groups", sa.Boolean(), nullable=False),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["team.team_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"]),
        sa.PrimaryKeyConstraint("team_member_id"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_member_team_user"),
    )
    op.create_table(
        "team_group",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("private", sa.Boolean(), nullable=False),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["team.team_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id"),
        sa.UniqueConstraint("team_id", "path", name="uq_team_group_team_path"),
    )
    op.create_table(
        "group_member",
        sa.Column("group_member_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_on", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["team_group.group_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"]),
        sa.PrimaryKeyConstraint("group_member_id"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_member_group_user"),
    )
    op.create_table(
        "group_unsubscribed",
        sa.Column("group_unsubscribed_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["team_group.group_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"]),
        sa.PrimaryKeyConstraint("group_unsubscribed_id"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_unsubscribed_group_user"),
    )

    # Nullable while the existing rows are filled in, then required.
    op.add_column("skill", sa.Column("team_id", sa.Uuid(), nullable=True))
    op.add_column("skill", sa.Column("group_id", sa.Uuid(), nullable=True))
    op.add_column("skill", sa.Column("source_skill_id", sa.Uuid(), nullable=True))
    op.add_column("skill", sa.Column("source_revision", sa.Integer(), nullable=True))
    op.add_column("skill", sa.Column("archived", sa.Boolean(), nullable=True))

    # The baseline left the name constraint unnamed, so each database named it itself:
    # PostgreSQL as skill_name_key, SQLite not at all. The convention gives SQLite's a name
    # to drop it by while the table is rebuilt. It goes first: the personal copies made
    # below share their names with the skills they are copied from.
    unnamed = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
    postgresql = op.get_bind().dialect.name == "postgresql"
    if postgresql:
        op.drop_constraint("skill_name_key", "skill", type_="unique")
    else:
        with op.batch_alter_table("skill", naming_convention=unnamed) as batch:
            batch.drop_constraint("uq_skill_name", type_="unique")

    personal_team_of = _create_teams()
    _copy_decided_skills_into_personal_teams(personal_team_of)

    with op.batch_alter_table("skill") as batch:
        batch.alter_column("team_id", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column("archived", existing_type=sa.Boolean(), nullable=False)
        batch.create_foreign_key("fk_skill_team_id_team", "team", ["team_id"], ["team_id"])
        batch.create_foreign_key("fk_skill_group_id_team_group", "team_group", ["group_id"],
                                 ["group_id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_skill_source_skill_id_skill", "skill",
                                 ["source_skill_id"], ["skill_id"], ondelete="SET NULL")
        batch.create_unique_constraint("uq_skill_team_name", ["team_id", "name"])


def _create_teams() -> dict[uuid.UUID, uuid.UUID]:
    """Make the server's team and one personal team per user; return user → personal team."""
    connection = op.get_bind()
    now = datetime.now(timezone.utc)
    users = connection.execute(sa.select(_user.c.user_id, _user.c.username,
                                         _user.c.is_admin)).all()

    server_team_id = uuid.uuid4()
    teams = [{"team_id": server_team_id, "name": SERVER_TEAM_NAME, "kind": "SERVER",
              "created_by": None, "created_on": now}]
    members = []
    personal_team_of = {}
    for user_id, username, is_admin in users:
        # A user who joined before usernames were restricted may be called anything,
        # including the one name the server's team needs.
        personal_name = username if username != SERVER_TEAM_NAME else f"{username}-personal"
        personal_team_of[user_id] = uuid.uuid4()
        teams.append({"team_id": personal_team_of[user_id], "name": personal_name,
                      "kind": "PERSONAL", "created_by": user_id, "created_on": now})
        for team_id, role in ((personal_team_of[user_id], "ADMIN"),
                              (server_team_id, "ADMIN" if is_admin else "MEMBER")):
            members.append({"team_member_id": uuid.uuid4(), "team_id": team_id,
                            "user_id": user_id, "role": role, "sees_all_groups": False,
                            "created_on": now})

    op.bulk_insert(_team, teams)
    if members:
        op.bulk_insert(_member, members)
    # Every skill that exists was shared by the whole server, and stays so.
    op.execute(_skill.update().values(team_id=server_team_id, archived=False))
    return personal_team_of


def _copy_decided_skills_into_personal_teams(personal_team_of: dict) -> None:
    """Give each user their own copy of every skill one of their machines decided about.

    The whole history is copied, not only the latest revision: a machine holding an older,
    unedited copy must still be recognized as behind and updated, not asked about.
    """
    connection = op.get_bind()
    decided = connection.execute(
        sa.select(_machine.c.user_id, _machine_skill.c.skill_id)
        .join(_machine_skill, _machine_skill.c.machine_id == _machine.c.machine_id)
        .distinct()
    ).all()

    for user_id, shared_skill_id in decided:
        shared = connection.execute(
            sa.select(_skill).where(_skill.c.skill_id == shared_skill_id)).one()
        versions = connection.execute(
            sa.select(_version).where(_version.c.skill_id == shared_skill_id)
            .order_by(_version.c.revision)).all()

        personal_skill_id = uuid.uuid4()
        op.bulk_insert(_skill, [{
            "skill_id": personal_skill_id, "team_id": personal_team_of[user_id],
            "name": shared.name, "description": shared.description, "origin": shared.origin,
            "created_on": shared.created_on, "pushed_by": shared.pushed_by,
            "source_skill_id": shared_skill_id, "source_revision": versions[-1].revision,
            "archived": False,
        }])
        for version in versions:
            copied_version_id = uuid.uuid4()
            op.bulk_insert(_version, [{
                "skill_version_id": copied_version_id, "skill_id": personal_skill_id,
                "revision": version.revision, "version": version.version,
                "content_hash": version.content_hash,
                "frontmatter_json": version.frontmatter_json,
                "created_on": version.created_on, "pushed_by": version.pushed_by,
            }])
            files = connection.execute(
                sa.select(_file).where(
                    _file.c.skill_version_id == version.skill_version_id)).all()
            op.bulk_insert(_file, [{
                "skill_file_id": uuid.uuid4(), "skill_version_id": copied_version_id,
                "path": file.path, "content": file.content, "sha256": file.sha256,
                "executable": file.executable,
            } for file in files])

        # The user's machines now follow their own copy.
        op.execute(
            _machine_skill.update()
            .where(_machine_skill.c.skill_id == shared_skill_id,
                   _machine_skill.c.machine_id.in_(
                       sa.select(_machine.c.machine_id).where(_machine.c.user_id == user_id)))
            .values(skill_id=personal_skill_id)
        )
