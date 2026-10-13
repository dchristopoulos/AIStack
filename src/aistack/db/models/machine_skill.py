import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.timestamps import utc_now


class MachineSkill(Base):
    """Desired state: whether one skill should exist on one machine (ADR-0004).

    A row with `enabled = False` is an explicit disable. No row is no decision. Sync treats
    the two differently (ADR-0006), so a disable never deletes the row.
    """

    __tablename__ = "machine_skill"

    machine_skill_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                                        default=uuid.uuid4)
    # Revoking a machine is deleting its row; its decisions go with it.
    machine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("machine.machine_id", ondelete="CASCADE"),
        nullable=False,
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skill.skill_id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
    updated_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("machine_id", "skill_id", name="uq_machine_skill_machine_skill"),
    )
