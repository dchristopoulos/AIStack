import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.timestamps import utc_now


class MachineProjectSkill(Base):
    """Desired state in a project folder, as `MachineSkill` is in a global one (ADR-0026).

    A row with `enabled = False` is an explicit disable, and no row is no decision (ADR-0006).
    Kept apart from `machine_skill`, because every release before ADR-0026 reads that table
    by machine and harness alone, and would take a project placement for a global one.
    """

    __tablename__ = "machine_project_skill"

    machine_project_skill_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                                                default=uuid.uuid4)
    machine_project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("machine_project.machine_project_id", ondelete="CASCADE"),
        nullable=False,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skill.skill_id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # The revision last installed or pushed in this folder: what an edited copy was edited
    # from. Null until one of the two happens.
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
    updated_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("machine_project_id", "skill_id",
                         name="uq_machine_project_skill_folder_skill"),
    )
