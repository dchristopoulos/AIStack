import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base

SKILL_FILE_PATH_MAX_LENGTH = 255

# sha256 hex, so the width is fixed and the same on both dialects.
FILE_DIGEST_LENGTH = 64


class SkillFile(Base):
    """One file of one revision, stored exactly as it was pushed."""

    __tablename__ = "skill_file"

    skill_file_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    skill_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skill_version.skill_version_id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(String(SKILL_FILE_PATH_MAX_LENGTH), nullable=False)
    # UTF-8 only; binary is rejected at push. Nothing is normalized on the way in or out.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(FILE_DIGEST_LENGTH), nullable=False)
    # Stored and re-applied on install, but deliberately not part of the content hash:
    # Windows cannot carry the bit, so hashing it would be a permanent phantom conflict.
    executable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("skill_version_id", "path", name="uq_skill_file_version_path"),
    )
