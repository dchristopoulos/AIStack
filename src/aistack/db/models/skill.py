import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
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
    name: Mapped[str] = mapped_column(String(SKILL_NAME_MAX_LENGTH), nullable=False, unique=True)
    # Denormalized from the latest revision at push, so listing the vault reads one table.
    description: Mapped[str] = mapped_column(String(SKILL_DESCRIPTION_MAX_LENGTH), nullable=False)
    # First-push-only: later pushes are compared against it and never overwrite it.
    origin: Mapped[str | None] = mapped_column(String(SKILL_ORIGIN_MAX_LENGTH), nullable=True)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
    # Who first pushed it into the vault. Provenance, never authorship: the vault holds
    # third-party skills, so this is never rendered as "author" or "created by".
    pushed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.user_id"), nullable=False)
