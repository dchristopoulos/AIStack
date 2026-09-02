import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.timestamps import utc_now

USERNAME_MAX_LENGTH = 64


class User(Base):
    __tablename__ = "user"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(USERNAME_MAX_LENGTH), nullable=False, unique=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)

    __table_args__ = (
        # The sole enforcer of "exactly one admin" (ADR-0008). The guarded UPDATE in the
        # service is a fast path that skips a routine constraint error; it is not a check.
        # SQLAlchemy has no portable partial-index kwarg, so the predicate is spelled per
        # dialect and the dialect that is not in use ignores its twin.
        Index("ix_user_single_admin", "is_admin", unique=True,
              sqlite_where=(is_admin.is_(True)),
              postgresql_where=(is_admin.is_(True))),
    )
