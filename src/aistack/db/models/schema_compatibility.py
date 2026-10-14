from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.timestamps import utc_now

REVISION_MAX_LENGTH = 32
RELEASE_MAX_LENGTH = 64


class SchemaCompatibility(Base):
    """One row: the oldest release schema that can still use this database (ADR-0024).

    Written by `migrate_schema` after every upgrade, and read by a release that meets a schema
    newer than it knows, to decide whether it may run on it.
    """

    __tablename__ = "schema_compatibility"

    # Always 1: the table holds one fact, not a history.
    row_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    oldest_compatible_revision: Mapped[str] = mapped_column(String(REVISION_MAX_LENGTH),
                                                            nullable=False)
    written_by_release: Mapped[str] = mapped_column(String(RELEASE_MAX_LENGTH), nullable=False)
    updated_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
