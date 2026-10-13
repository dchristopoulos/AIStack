import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.timestamps import utc_now

SKILL_VERSION_MAX_LENGTH = 32

# sha256 hex, so the width is fixed and the same on both dialects.
CONTENT_HASH_LENGTH = 64


class SkillVersion(Base):
    """One immutable revision of a skill. A change is a new row, never an update."""

    __tablename__ = "skill_version"

    skill_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                                        default=uuid.uuid4)
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skill.skill_id"), nullable=False)
    # Server-assigned 1, 2, 3… It orders history; the frontmatter `version` does not.
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    # The author's frontmatter version, verbatim, and absent when they gave none.
    version: Mapped[str | None] = mapped_column(String(SKILL_VERSION_MAX_LENGTH), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(CONTENT_HASH_LENGTH), nullable=False)
    # A queryable convenience only. SKILL.md in SkillFile is the verbatim truth and is never
    # regenerated from this.
    frontmatter_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
    pushed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.user_id"), nullable=False)

    __table_args__ = (
        # What stops two concurrent pushes from both claiming revision 2. The push allocates
        # MAX(revision) + 1 and retries when this fires.
        UniqueConstraint("skill_id", "revision", name="uq_skill_version_skill_revision"),
    )
