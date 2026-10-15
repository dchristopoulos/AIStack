import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.harness import Harness, harness_type
from aistack.db.models.timestamps import utc_now


class MachineSkill(Base):
    """Desired state: whether one skill should be in one harness on one machine (ADR-0004,
    ADR-0018).

    A row with `enabled = False` is an explicit disable. No row is no decision. Sync treats
    the two differently (ADR-0006), so a disable never deletes the row. Each harness on a
    machine is a separate decision.
    """

    __tablename__ = "machine_skill"

    machine_skill_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                                        default=uuid.uuid4)
    # Revoking a machine is deleting its row; its decisions go with it.
    machine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("machine.machine_id", ondelete="CASCADE"),
        nullable=False,
    )
    harness: Mapped[Harness] = mapped_column(harness_type("ck_machine_skill_harness"),
                                             nullable=False)
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skill.skill_id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # The revision last installed here or pushed from here: what a local copy that matches no
    # revision was edited from. Null until one of the two happens.
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
    updated_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now, onupdate=utc_now)

    __table_args__ = (
        UniqueConstraint("machine_id", "harness", "skill_id",
                         name="uq_machine_skill_machine_harness_skill"),
        # Removing a skill from the Library updates its placements on every computer.
        Index("ix_machine_skill_skill_id", "skill_id"),
    )
