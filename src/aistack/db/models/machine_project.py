import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.harness import Harness, harness_type
from aistack.db.models.timestamps import utc_now

PROJECT_PATH_MAX_LENGTH = 1024


class MachineProject(Base):
    """A project folder on a computer: one harness's skills folder at a project's top level
    (ADR-0026).

    The row is the opt-in: a computer manages a project's folder once it exists. Every clone
    and worktree of the project on the computer shares it.
    """

    __tablename__ = "machine_project"

    machine_project_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                                          default=uuid.uuid4)
    machine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("machine.machine_id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    harness: Mapped[Harness] = mapped_column(harness_type("ck_machine_project_harness"),
                                             nullable=False)
    # The top level last seen on this computer, for display only: the server never places it
    # in a command. Null when the folder was added on the dashboard and has not synced yet.
    path: Mapped[str | None] = mapped_column(String(PROJECT_PATH_MAX_LENGTH), nullable=True)
    # The skills folders the repository itself holds here, one name per line, as the last
    # sync of this folder listed them: what the page's Start an agent dialog offers besides
    # the Library's. Null until a release that records them syncs it.
    repository_skills: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
    # Null until the folder's first sync, which is what makes it the first.
    last_synced_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                            nullable=True)

    __table_args__ = (
        UniqueConstraint("machine_id", "project_id", "harness",
                         name="uq_machine_project_machine_project_harness"),
        # The project's folders on the person's other computers, for a first sync's offer.
        Index("ix_machine_project_project_id", "project_id"),
    )
