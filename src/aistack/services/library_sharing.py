"""Keeping a local copy and its GitHub log in step (ADR-0025).

Before a tool reads, the copy catches up on what other computers pushed; after a tool writes,
what this computer recorded is pushed. Either can fail without network, and the Library
carries on from its copy: unpublished events stay recorded and go out with the next push.
"""

import logging
import subprocess
import time
import uuid
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from aistack.commons.text import loggable
from aistack.db.engine import build_engine, build_session_factory
from aistack.db.schema import migrate_schema
from aistack.db.swap import swap_in
from aistack.services import library_log
from aistack.services.library_log import Event
from aistack.services.library_repo import LibraryRepo, RepoUnavailable, gh_command

logger = logging.getLogger(__name__)

# A copy read again within this many seconds is not pulled again; sync always pulls.
_PULL_INTERVAL_SECONDS = 15
# A rebuild beside the copy starts over when this computer changed the copy meanwhile. After
# this many, it rebuilds in place, holding the lock, rather than never finishing.
_REBUILD_ATTEMPTS = 3
# What would be lost by swapping in the rebuilt copy: a change recorded here, and not yet
# published, while it was being built.
_RECORDED_MEANWHILE = ("SELECT 1 FROM main.library_event WHERE published = 0 AND event_id "
                       "NOT IN (SELECT event_id FROM rebuilt.library_event) LIMIT 1")


class LibrarySharing:
    def __init__(self, repo: LibraryRepo, engine: Engine,
                 session_factory: sessionmaker[Session]):
        """`engine` is the copy's: a SQLite file in AISTACK_HOME."""
        self.repo = repo
        self.engine = engine
        self.session_factory = session_factory
        self._pulled_at = float("-inf")
        # Why the repository could not be reached the last time it was tried, for the agent
        # and the page to say; None while it answers.
        self.problem: str | None = None

    def catch_up(self, force: bool = False) -> None:
        """Pull, and apply what other computers added. Offline, keep the copy as it is."""
        if not force and time.monotonic() - self._pulled_at < _PULL_INTERVAL_SECONDS:
            return
        try:
            self.repo.pull()
        except RepoUnavailable as error:
            self._unreachable(error)
            return
        self.problem = None
        self._pulled_at = time.monotonic()
        self.replay_clone()
        # Online again: what an earlier, failed push left behind goes out now.
        self.publish()

    def replay_clone(self) -> None:
        """Apply what the clone holds, without the network."""
        events = self.repo.events()
        with self.session_factory.begin() as session:
            new = library_log.arrivals(session, events)
        if not new:
            return
        # Archives are read before the transaction; another process may apply some of these
        # meanwhile, so what is new is asked again inside it.
        validated = library_log.prepared(new)
        with self.session_factory.begin() as session:
            if library_log.append(session, library_log.arrivals(session, events), validated):
                return
        self._rebuild(events, validated)
        logger.info("The Library's copy was rebuilt from the log.")

    def _rebuild(self, events: list[Event],
                 validated: library_log.Prepared) -> None:
        """Replay the whole log into a new file beside the copy, then swap its rows in, so
        other sessions on this computer read the old copy meanwhile instead of waiting."""
        copy = Path(self.engine.url.database)
        for _ in range(_REBUILD_ATTEMPTS):
            with self.session_factory.begin() as session:
                local = library_log.unpublished(session)
            # A name of its own, since two agent sessions can rebuild at once.
            beside = copy.with_name(f"{copy.name}.rebuild-{uuid.uuid4().hex}")
            try:
                engine = build_engine(f"sqlite:///{beside.as_posix()}")
                try:
                    migrate_schema(engine)
                    validated |= library_log.prepared([
                        event for event in [*events, *local] if event.event_id not in validated])
                    with build_session_factory(engine).begin() as session:
                        library_log.rebuild(session, events, local, validated)
                finally:
                    engine.dispose()
                if swap_in(self.engine, beside, unless=_RECORDED_MEANWHILE):
                    return
            finally:
                for leftover in (beside, *(beside.with_name(beside.name + suffix)
                                           for suffix in ("-wal", "-shm", "-journal"))):
                    leftover.unlink(missing_ok=True)
        logger.info("The Library's copy kept changing while it was rebuilt beside; "
                    "rebuilding it in place.")
        with self.session_factory.begin() as session:
            library_log.rebuild(session, events)

    def publish(self) -> bool:
        """Push every recorded event not yet in the repository. False when some could not
        go out, and wait for the next push."""
        with self.session_factory.begin() as session:
            pending = library_log.unpublished(session)
        try:
            self.repo.publish(pending)
        except RepoUnavailable as error:
            self._unreachable(error)
            return False
        self.problem = None
        if pending:
            with self.session_factory.begin() as session:
                library_log.mark_published(session, [event.event_id for event in pending])
        return True

    def unpublished(self) -> int:
        """How many changes made here have not reached the repository yet."""
        with self.session_factory.begin() as session:
            return len(library_log.unpublished(session))

    def _unreachable(self, error: RepoUnavailable) -> None:
        self.problem = unreachable_reason(self.repo.remote)
        logger.warning(
            "The Library's repository could not be reached, so this computer "
            "works from its copy for now. %s",
            loggable(error),
        )


def unreachable_reason(remote: str) -> str:
    """Why a repository could not be reached, as one sentence for its person: signed out of
    GitHub, which they fix, or the network, which they wait out."""
    if remote.startswith("https://github.com/"):
        try:
            signed_in = subprocess.run([gh_command(), "auth", "status", "--hostname",
                                        "github.com"], capture_output=True, timeout=30,
                                       stdin=subprocess.DEVNULL).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            signed_in = False
        if not signed_in:
            return ("This computer is signed out of GitHub, so your Library here may be out "
                    "of date. Run `aistack-mcp github` to sign in again; changes made here "
                    "wait on this computer until then.")
    return ("Your Library's repository could not be reached, so this shows this computer's "
            "copy, which may be out of date. Changes made here go out once it can be reached.")
