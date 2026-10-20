"""One-use account pairing, with a separate request credential (ADR-0035)."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.timestamps import utc_now


class ComputerCode(Base):
    __tablename__ = "computer_code"

    code_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.user_id"), nullable=False)
    issuing_machine_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    issuing_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    machine_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    options: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    # Reported name, OS and setup result. No credentials or hardware ids.
    request: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    created_on: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    expires_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    denied_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
