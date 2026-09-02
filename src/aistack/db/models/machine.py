import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.operating_system import OperatingSystem
from aistack.db.models.timestamps import utc_now

MACHINE_NAME_MAX_LENGTH = 64

# sha256 hex, so the width is fixed and the same on both dialects.
TOKEN_HASH_LENGTH = 64


class Machine(Base):
    __tablename__ = "machine"

    machine_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.user_id"), nullable=False)
    name: Mapped[str] = mapped_column(String(MACHINE_NAME_MAX_LENGTH), nullable=False)
    # native_enum=False keeps this a VARCHAR + CHECK on both dialects. A native Postgres enum
    # would need a migration to add a value, which SQLite would not, breaking "runs identically".
    os: Mapped[OperatingSystem] = mapped_column(
        Enum(OperatingSystem, native_enum=False, length=16, validate_strings=True),
        nullable=False
    )
    # Only the sha256 of the bearer token is ever stored. Unique so that authentication is one
    # indexed lookup with nothing compared in Python — see the token service.
    token_hash: Mapped[str] = mapped_column(String(TOKEN_HASH_LENGTH), nullable=False, unique=True)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_machine_user_name"),
    )
