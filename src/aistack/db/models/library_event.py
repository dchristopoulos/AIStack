import uuid

from sqlalchemy import Boolean, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base

SORT_KEY_LENGTH = 128
KIND_MAX_LENGTH = 32


class LibraryEvent(Base):
    """One change to a local mode Library, as it is shared through a GitHub log (ADR-0025).

    Recorded in the same transaction as the change, so a change that is in the database is in
    the log, and published to the repository afterwards.
    """

    __tablename__ = "library_event"

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    # Time, machine id and event id: the order every computer replays the log in.
    sort_key: Mapped[str] = mapped_column(String(SORT_KEY_LENGTH), nullable=False)
    kind: Mapped[str] = mapped_column(String(KIND_MAX_LENGTH), nullable=False)
    # The whole event as JSON, exactly as it is written to the repository.
    body: Mapped[str] = mapped_column(Text, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_library_event_sort_key", "sort_key", unique=True),
    )
