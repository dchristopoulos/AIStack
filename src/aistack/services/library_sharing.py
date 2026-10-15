"""Keeping a local copy and its GitHub log in step (ADR-0025).

Before a tool reads, the copy catches up on what other computers pushed; after a tool writes,
what this computer recorded is pushed. Either can fail without network, and the Library
carries on from its copy: unpublished events stay recorded and go out with the next push.
"""

import logging
import time

from sqlalchemy.orm import Session, sessionmaker

from aistack.services import library_log
from aistack.services.library_repo import LibraryRepo, RepoUnavailable

logger = logging.getLogger(__name__)

# A copy read again within this many seconds is not pulled again; sync always pulls.
_PULL_INTERVAL_SECONDS = 15


class LibrarySharing:
    def __init__(self, repo: LibraryRepo, session_factory: sessionmaker[Session]):
        self.repo = repo
        self.session_factory = session_factory
        self._pulled_at = float("-inf")

    def catch_up(self, force: bool = False) -> None:
        """Pull, and apply what other computers added. Offline, keep the copy as it is."""
        if not force and time.monotonic() - self._pulled_at < _PULL_INTERVAL_SECONDS:
            return
        try:
            self.repo.pull()
        except RepoUnavailable as error:
            logger.warning(f"The Library's repository could not be reached, so this computer "
                           f"works from its copy for now. {error}")
            return
        self._pulled_at = time.monotonic()
        self.replay_clone()
        # Online again: what an earlier, failed push left behind goes out now.
        self.publish()

    def replay_clone(self) -> None:
        """Apply what the clone holds, without the network."""
        events = self.repo.events()
        with self.session_factory.begin() as session:
            if library_log.catch_up(session, events):
                logger.info("The Library's copy was rebuilt from the log.")

    def publish(self) -> bool:
        """Push every recorded event not yet in the repository. False when some could not
        go out, and wait for the next push."""
        with self.session_factory.begin() as session:
            pending = library_log.unpublished(session)
        try:
            self.repo.publish(pending)
        except RepoUnavailable as error:
            logger.warning(f"The Library's repository could not be reached; "
                           f"{len(pending)} changes go out with the next push. {error}")
            return False
        if pending:
            with self.session_factory.begin() as session:
                library_log.mark_published(session, [event.event_id for event in pending])
        return True
