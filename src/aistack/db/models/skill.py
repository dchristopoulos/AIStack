import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.timestamps import utc_now

SKILL_NAME_MAX_LENGTH = 64
SKILL_DESCRIPTION_MAX_LENGTH = 1024
SKILL_ORIGIN_MAX_LENGTH = 255


class Skill(Base):
    """A canonical skill's identity in the vault. Its content lives in SkillVersion rows."""

    __tablename__ = "skill"

    skill_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # The team whose vault holds it. A name is unique within a team, not across the server.
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("team.team_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(SKILL_NAME_MAX_LENGTH), nullable=False)
    # Denormalized from the latest revision at push, so listing the vault reads one table.
    description: Mapped[str] = mapped_column(String(SKILL_DESCRIPTION_MAX_LENGTH), nullable=False)
    # First-push-only: later pushes are compared against it and never overwrite it.
    origin: Mapped[str | None] = mapped_column(String(SKILL_ORIGIN_MAX_LENGTH), nullable=True)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
    # Who first pushed it into the vault. Provenance, never authorship: the vault holds
    # third-party skills, so this is never rendered as "author" or "created by".
    pushed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.user_id"), nullable=False)
    # In a team: the group it sits in, or null for the whole team.
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("team_group.group_id", ondelete="SET NULL"), nullable=True)
    # In a personal team: the team skill this one was taken from or shared to, and that
    # skill's revision at the time. A newer revision there is an update on offer, never one
    # applied unasked. Null for a skill that has only ever been the user's own.
    source_skill_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skill.skill_id", ondelete="SET NULL"), nullable=True)
    source_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Removed from the Library by its user. The row stays so that sync does not mistake the
    # folder still on a computer for a new skill and back it up again.
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("team_id", "name", name="uq_skill_team_name"),
    )
