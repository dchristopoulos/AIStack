import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.harness import Harness, harness_type
from aistack.db.models.timestamps import utc_now


class MachineHarness(Base):
    """A harness this machine has synced, and when it last did (ADR-0018).

    Written by sync. A machine with no row has never synced since harnesses existed, and is
    shown with Claude Code, the only harness there was before.
    """

    __tablename__ = "machine_harness"

    machine_harness_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                                          default=uuid.uuid4)
    machine_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("machine.machine_id", ondelete="CASCADE"),
        nullable=False,
    )
    harness: Mapped[Harness] = mapped_column(harness_type("ck_machine_harness_harness"),
                                             nullable=False)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
    last_synced_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                            nullable=True)

    __table_args__ = (
        UniqueConstraint("machine_id", "harness", name="uq_machine_harness_machine_harness"),
    )
