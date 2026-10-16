import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.timestamps import utc_now

PROJECT_KEY_MAX_LENGTH = 255
PROJECT_NAME_MAX_LENGTH = 64


class Project(Base):
    """A git repository one person manages skills in (ADR-0026).

    Known by its key: the normalised remote, the same on every computer, or `local/…` for a
    repository of one computer. A row exists only once its owner added the project.
    """

    __tablename__ = "project"

    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Every foreign key in the project tables cascades: an older release that rebuilds a
    # GitHub Library's copy empties only the tables it knows (ADR-0025, ADR-0026).
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(PROJECT_KEY_MAX_LENGTH), nullable=False)
    # Display only: the last segment of the key or of the top level.
    name: Mapped[str] = mapped_column(String(PROJECT_NAME_MAX_LENGTH), nullable=False)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_project_user_key"),
    )
