import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.timestamps import utc_now

TEAM_NAME_MAX_LENGTH = 64
GROUP_NAME_MAX_LENGTH = 64
# 'backend/aistack/api': a group's name with every group above it.
GROUP_PATH_MAX_LENGTH = 255
GROUP_MAX_DEPTH = 8

# sha256 hex, like a machine token's.
INVITE_HASH_LENGTH = 64


class TeamKind(StrEnum):
    """What a team is for. Code asks this, never the team's name, so a rename changes nothing."""

    # The one team every account on the server joins. It is what "the vault" was before teams.
    SERVER = "SERVER"
    # One per user, created at join: the Library. Mirrors what is on their computers, and is
    # the only team a machine ever installs from.
    PERSONAL = "PERSONAL"
    # Created by a user, joined with the team's own invite code.
    SHARED = "SHARED"


class TeamRole(StrEnum):
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class Team(Base):
    """The boundary a skill lives in (ADR-0015)."""

    __tablename__ = "team"

    team_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(TEAM_NAME_MAX_LENGTH), nullable=False, unique=True)
    kind: Mapped[TeamKind] = mapped_column(
        Enum(TeamKind, native_enum=False, create_constraint=True, length=16,
             validate_strings=True, name="ck_team_kind"),
        nullable=False
    )
    # The personal team's user, or whoever created a shared one. Null for the server's team,
    # which nobody created.
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.user_id"),
                                                         nullable=True)
    # Only the sha256 of the team's invite code is stored, and joining is one indexed lookup,
    # exactly as a machine token is resolved. Null until an admin asks for a code.
    invite_hash: Mapped[str | None] = mapped_column(String(INVITE_HASH_LENGTH), nullable=True,
                                                    unique=True)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)


class TeamMember(Base):
    __tablename__ = "team_member"

    team_member_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                                      default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("team.team_id", ondelete="CASCADE"),
                                               nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.user_id"), nullable=False)
    role: Mapped[TeamRole] = mapped_column(
        Enum(TeamRole, native_enum=False, create_constraint=True, length=16,
             validate_strings=True, name="ck_team_member_role"),
        nullable=False
    )
    # Sees the skills of every group in the team, private ones included, without being added
    # to each. Reading only: sharing into a group still takes membership of it.
    sees_all_groups: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # May make the team's invite link, and nothing else an admin can (ADR-0019).
    can_invite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)

    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_member_team_user"),
    )


class TeamGroup(Base):
    """A named set of skills and members inside a team, like a channel (ADR-0015).

    Groups nest to any useful depth: `backend` may hold `backend/aistack`. A group is
    identified by its path, which is fixed when it is made, so the groups above it are read
    from the path and there is no tree to walk in the database.
    """

    __tablename__ = "team_group"

    group_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("team.team_id", ondelete="CASCADE"),
                                               nullable=False)
    path: Mapped[str] = mapped_column(String(GROUP_PATH_MAX_LENGTH), nullable=False)
    # Private: only the group's own members see its skills. Otherwise everyone who can see
    # the group above it does, or the whole team for a group at the top.
    private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)

    __table_args__ = (
        UniqueConstraint("team_id", "path", name="uq_team_group_team_path"),
    )


class GroupMember(Base):
    __tablename__ = "group_member"

    group_member_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                                       default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("team_group.group_id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.user_id"), nullable=False)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)

    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_member_group_user"),
    )


class GroupUnsubscribed(Base):
    """A user who does not want to hear about changes in a group, or in the groups under it.

    Unsubscribing hides nothing: the skills are still listed and can still be taken. It only
    stops sync from offering their updates.
    """

    __tablename__ = "group_unsubscribed"

    group_unsubscribed_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                                             default=uuid.uuid4)
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("team_group.group_id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.user_id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_unsubscribed_group_user"),
    )
