import uuid
from datetime import datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.team import INVITE_HASH_LENGTH
from aistack.db.models.timestamps import utc_now

INVITE_LIFETIME = timedelta(days=7)


class Invite(Base):
    """One invite into a team: pending until somebody uses it, then accepted (ADR-0022).

    Only the sha256 of the code is stored, and using it is one indexed lookup, as a machine
    token is resolved. A used, cancelled or expired invite admits nobody.
    """

    __tablename__ = "invite"

    invite_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("team.team_id", ondelete="CASCADE"),
                                               nullable=False)
    code_hash: Mapped[str] = mapped_column(String(INVITE_HASH_LENGTH), nullable=False,
                                           unique=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.user_id"), nullable=False)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
    expires_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.user_id"), nullable=True)
    used_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                          nullable=True)
