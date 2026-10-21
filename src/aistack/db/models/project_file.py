import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from aistack.db.models.base import Base
from aistack.db.models.coding_agent import CodingAgent, coding_agent_type
from aistack.db.models.machine_project import PROJECT_PATH_MAX_LENGTH
from aistack.db.models.skill_version import CONTENT_HASH_LENGTH
from aistack.db.models.timestamps import utc_now

SHARE_NOTE_MAX_LENGTH = 4096
PULL_REQUEST_URL_MAX_LENGTH = 2048


class ProjectFile(Base):
    """A Markdown file git tracks in one of a person's projects (ADR-0036): the repository's
    rule, or another file they ticked when adding the project.

    The project is one person's, so whether the file is ticked or turned off is theirs too.
    Only a ticked file is read again; each sync uploads its text when the hash changes, so
    the snapshot is what a computer last saw, never what the server read from a disk.
    """

    __tablename__ = "project_file"

    project_file_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                                       default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    # Relative to the top level, with forward slashes.
    path: Mapped[str] = mapped_column(String(PROJECT_PATH_MAX_LENGTH), nullable=False)
    # The agent whose file it is, from `services/agent_files.py`, or null for any other
    # Markdown file. Several agents can read one file; this is the one it is shown under.
    agent: Mapped[CodingAgent | None] = mapped_column(
        coding_agent_type("ck_project_file_agent"), nullable=True)
    ticked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Turned off for this person through the agent's own settings; the file is never moved.
    turned_off: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Bytes, as listed when the project was added or last snapshotted.
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The last text a computer uploaded, its hash, from which computer, and when. Null until
    # the first upload.
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(CONTENT_HASH_LENGTH), nullable=True)
    snapshot_machine_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("machine.machine_id", ondelete="SET NULL"),
        nullable=True,
    )
    snapshot_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)

    __table_args__ = (
        UniqueConstraint("project_id", "path", name="uq_project_file_project_path"),
        Index("ix_project_file_snapshot_machine_id", "snapshot_machine_id"),
    )


class ProjectFileEdit(Base):
    """An edit to a repository's rule made on the page, waiting to reach a working copy and
    then a pull request (ADR-0036).

    The program writes `text` into the chosen computer's working copy only while the file
    there still hashes to `base_hash`, and asks otherwise. Each step is a timestamp, so the
    row says how far the edit got.
    """

    __tablename__ = "project_file_edit"

    project_file_edit_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                                            default=uuid.uuid4)
    project_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_file.project_file_id", ondelete="CASCADE"),
        nullable=False,
    )
    # The computer whose working copy it goes to. Removing that computer keeps the edit.
    machine_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("machine.machine_id", ondelete="SET NULL"),
        nullable=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(CONTENT_HASH_LENGTH), nullable=False)
    # The hash of the text the edit started from.
    base_hash: Mapped[str] = mapped_column(String(CONTENT_HASH_LENGTH), nullable=False)
    # What the change is about: the commit message, given at Commit….
    note: Mapped[str | None] = mapped_column(String(SHARE_NOTE_MAX_LENGTH), nullable=True)
    pull_request_url: Mapped[str | None] = mapped_column(String(PULL_REQUEST_URL_MAX_LENGTH),
                                                         nullable=True)
    created_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False,
                                                 default=utc_now)
    written_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shared_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_on: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                          nullable=True)

    __table_args__ = (
        Index("ix_project_file_edit_project_file_id", "project_file_id"),
        Index("ix_project_file_edit_machine_id", "machine_id"),
    )
