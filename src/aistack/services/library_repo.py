"""The git repository a GitHub Library's log lives in, driven through the `git` command
(ADR-0025).

AIStack stores no credential: git uses whatever the person's `gh` login set up. Every
operation here is file and network work, so callers run it outside any transaction. One
lock per clone keeps two agent sessions on one computer from running git at once.
"""

import contextlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from aistack.commons.exceptions import ValidationError
from aistack.services.library_log import Event

BRANCH = "main"
LOG_FOLDER = "log"
_PUSH_ATTEMPTS = 5
_GIT_TIMEOUT_SECONDS = 60
# owner/name, as GitHub spells a repository.
_GITHUB_NAME = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")


class RepoUnavailable(Exception):
    """The repository could not be reached; the Library carries on from its copy."""


def remote_url(repository: str) -> str:
    """`owner/name` as a GitHub URL; any other git URL or path as it is."""
    if _GITHUB_NAME.fullmatch(repository):
        return f"https://github.com/{repository.removesuffix('.git')}.git"
    return repository


class LibraryRepo:
    def __init__(self, folder: Path, repository: str):
        self.folder = folder
        self.remote = remote_url(repository)
        # For GitHub, the person's gh login and nothing else: a helper configured on the
        # system first (macOS's keychain, set by Homebrew's git) could answer with a stale
        # password, or wait on a prompt nobody sees. The empty value clears the list.
        self._credentials = (
            ["-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential"]
            if self.remote.startswith("https://github.com/") else [])

    def events(self) -> list[Event]:
        """Every event in the clone, as the last pull left it."""
        log = self.folder / LOG_FOLDER
        if not log.is_dir():
            return []
        return [Event.from_json(path.read_text(encoding="utf-8"))
                for path in sorted(log.glob("*/*.json"))]

    def pull(self) -> None:
        """Bring the clone up to date with the repository, cloning it the first time."""
        with self._locked():
            if not (self.folder / ".git").is_dir():
                self._clone()
            self._fetch_and_rebase()

    def publish(self, events: list[Event]) -> None:
        """Add `events` to the repository: write, commit, and push until the push lands.

        Also pushes commits an earlier, failed push left behind, which a rebuild counts as
        shared because their files are in the clone.
        """
        with self._locked():
            if not (self.folder / ".git").is_dir():
                self._clone()
            for event in events:
                path = self.folder / LOG_FOLDER / str(event.machine_id) / _file_name(event)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(event.to_json(), encoding="utf-8")
            self._git("add", LOG_FOLDER)
            # Nothing to commit means another session on this computer published them first.
            if self._git("status", "--porcelain", LOG_FOLDER).strip():
                self._git("commit", "--quiet", "--no-verify", "-m",
                          f"AIStack: {len(events)} change{'s' if len(events) != 1 else ''}")
            if not self._ahead():
                if events and not self._has_commits():
                    raise RepoUnavailable("The clone has no commit to push.")
                return
            for attempt in range(_PUSH_ATTEMPTS):
                try:
                    self._git("push", "--quiet", "origin", f"HEAD:{BRANCH}")
                    return
                except RepoUnavailable:
                    if attempt == _PUSH_ATTEMPTS - 1:
                        raise
                    # Another computer pushed first. Its files never touch ours, so taking
                    # its commits under ours cannot conflict.
                    self._fetch_and_rebase()

    def _has_commits(self) -> bool:
        try:
            self._git("rev-parse", "--verify", "--quiet", "HEAD")
            return True
        except RepoUnavailable:
            return False

    def _ahead(self) -> bool:
        """True when this clone holds commits the repository does not."""
        if not self._has_commits():
            return False
        try:
            return int(self._git("rev-list", "--count", f"origin/{BRANCH}..HEAD")) > 0
        except RepoUnavailable:
            # The repository has no branch yet: everything here is ahead of it.
            return True

    def _clone(self) -> None:
        """Clone beside the clone's place and move it there whole, so a clone that fails
        halfway never looks like one that worked."""
        self.folder.parent.mkdir(parents=True, exist_ok=True)
        partial = self.folder.with_name(f"{self.folder.name}.cloning")
        shutil.rmtree(partial, ignore_errors=True)
        self._git("clone", "--quiet", self.remote, str(partial), cwd=self.folder.parent)
        # A new repository has no branch yet; every computer writes to the same one.
        self._git("checkout", "--quiet", "-B", BRANCH, cwd=partial)
        self._git("config", "user.name", "AIStack", cwd=partial)
        self._git("config", "user.email", "aistack@localhost", cwd=partial)
        shutil.rmtree(self.folder, ignore_errors=True)
        partial.rename(self.folder)

    def _fetch_and_rebase(self) -> None:
        self._git("fetch", "--quiet", "origin")
        if not self._git("ls-remote", "--heads", "origin", BRANCH).strip():
            return
        if not self._has_commits():
            # Nothing committed here yet: start from the repository's history.
            self._git("checkout", "--quiet", "-B", BRANCH, f"origin/{BRANCH}")
            return
        self._git("rebase", "--quiet", f"origin/{BRANCH}")

    def _git(self, *arguments: str, cwd: Path | None = None) -> str:
        try:
            done = subprocess.run(
                ["git", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false",
                 *self._credentials, *arguments],
                cwd=cwd or self.folder, capture_output=True, text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                # Never wait on a password prompt nobody can see.
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except FileNotFoundError:
            raise ValidationError("A Library on GitHub needs git, and git is not installed on "
                                  "this computer. Install it, then start again.") from None
        except subprocess.TimeoutExpired:
            raise RepoUnavailable(f"git {arguments[0]} took longer than "
                                  f"{_GIT_TIMEOUT_SECONDS} seconds.") from None
        if done.returncode != 0:
            raise RepoUnavailable(f"git {arguments[0]} failed: "
                                  f"{(done.stderr or done.stdout).strip()[-300:]}")
        return done.stdout

    @contextlib.contextmanager
    def _locked(self):
        self.folder.parent.mkdir(parents=True, exist_ok=True)
        with open(self.folder.parent / f"{self.folder.name}.lock", "a+b") as lock:
            _lock(lock)
            try:
                yield
            finally:
                _unlock(lock)


def _file_name(event: Event) -> str:
    # No ':' in the name, which Windows refuses; the order is still the time's.
    compact = event.at.replace("-", "").replace(":", "")
    return f"{compact}-{event.event_id}.json"


if sys.platform == "win32":
    import msvcrt

    def _lock(file) -> None:
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock(file) -> None:
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(file) -> None:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)

    def _unlock(file) -> None:
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)
