"""The git repository a GitHub Library's log lives in, driven through the `git` command
(ADR-0025).

AIStack stores no credential: git uses whatever the person's `gh` login set up. Every
operation here is file and network work, so callers run it outside any transaction. One
lock per clone keeps two agent sessions on one computer from running git at once.
"""

import contextlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.parse
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


def validate_repository(repository: str) -> None:
    """Refuse a repository git would misread, or one that carries a credential. The value is
    shown in the dashboard and in `aistack check`, so the refusal never repeats it."""
    if repository.startswith("-"):
        # git would read it as an option, such as --upload-pack, which runs a command.
        raise ValidationError("AISTACK_LIBRARY_REPO must be a repository, as owner/name, and "
                              "cannot start with '-'.")
    address = urllib.parse.urlsplit(repository)
    if address.password or (address.scheme in ("http", "https") and address.username):
        raise ValidationError("AISTACK_LIBRARY_REPO holds a username or token. Set it to "
                              "owner/name alone: AIStack reaches GitHub through your gh login.")


class LibraryRepo:
    def __init__(self, folder: Path, repository: str):
        validate_repository(repository)
        self.folder = folder
        self.remote = remote_url(repository)
        # For GitHub, the person's gh login and nothing else: a helper configured on the
        # system first (macOS's keychain, set by Homebrew's git) could answer with a stale
        # password, or wait on a prompt nobody sees. The empty value clears the list.
        self._credentials = (
            ["-c", "credential.helper=", "-c",
             f"credential.helper=!{shlex.quote(gh_command())} auth git-credential"]
            if self.remote.startswith("https://github.com/") else [])

    def events(self) -> list[Event]:
        """Every event in the clone, as the last pull left it.

        Anyone who can write to the repository can add a file, so an event must sit where its
        own computer would have written it: a file under another computer's folder cannot
        speak for that computer. Links are skipped; git checks them out as plain files
        anyway (`core.symlinks=false`), but a clone made by hand may hold one.
        """
        log = self.folder / LOG_FOLDER
        if not log.is_dir() or log.is_symlink():
            return []
        events = []
        for path in sorted(log.glob("*/*.json")):
            if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(log).as_posix()
            try:
                event = Event.from_json(path.read_bytes())
            except ValidationError as error:
                raise ValidationError(f"log/{relative} in the Library's repository: "
                                      f"{error.message}") from None
            if event.path != relative:
                raise ValidationError(f"log/{relative} in the Library's repository is not "
                                      f"where its computer writes. Remove it from the "
                                      f"repository.")
            events.append(event)
        return events

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
            log = (self.folder / LOG_FOLDER).resolve()
            for event in events:
                path = self.folder / LOG_FOLDER / event.path
                path.parent.mkdir(parents=True, exist_ok=True)
                # A link in the clone would take the file elsewhere: written, marked published,
                # and never pushed. Unpublished, it goes out once the clone is fixed.
                if path.parent.resolve() != log / str(event.machine_id):
                    raise RepoUnavailable(f"{path.parent} leads outside the clone; remove it.")
                path.write_text(event.to_json(), encoding="utf-8")
            # With no events there is nothing to add, and a new repository has no log folder
            # for `git add` to name.
            if events:
                self._git("add", LOG_FOLDER)
            # Nothing to commit means another session on this computer published them first.
            if events and self._git("status", "--porcelain", LOG_FOLDER).strip():
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
        if self.folder.exists() and any(self.folder.iterdir()):
            # Not a clone, and not ours: AISTACK_HOME may be a folder people keep things in,
            # and on a disk that ignores case `library` is macOS's `~/Library`.
            raise ValidationError(f"{self.folder} already holds files that are not the "
                                  f"Library's clone. Move them, or set AISTACK_HOME to "
                                  f"another folder, then start again.")
        partial = self.folder.with_name(f"{self.folder.name}.cloning")
        shutil.rmtree(partial, ignore_errors=True)
        self._git("clone", "--quiet", "--", self.remote, str(partial), cwd=self.folder.parent)
        # A new repository has no branch yet; every computer writes to the same one.
        self._git("checkout", "--quiet", "-B", BRANCH, cwd=partial)
        self._git("config", "user.name", "AIStack", cwd=partial)
        self._git("config", "user.email", "aistack@localhost", cwd=partial)
        if self.folder.exists():
            self.folder.rmdir()
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
                 "-c", "core.symlinks=false", *self._credentials, *arguments],
                cwd=cwd or self.folder, capture_output=True, text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                env=_git_environment(),
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


def gh_command() -> str:
    """The gh command, found where installers put it when an agent started from a desktop
    app runs this process without those folders on its path."""
    found = shutil.which("gh")
    if found:
        return found
    for folder in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin",
                   str(Path.home() / ".local" / "bin")):
        candidate = Path(folder) / "gh"
        if candidate.is_file():
            return str(candidate)
    return "gh"


def _git_environment() -> dict[str, str]:
    """This process's environment without git's own variables. A git hook that starts an
    agent passes GIT_DIR down, and git would then commit and push in that project instead."""
    environment = {name: value for name, value in os.environ.items()
                   if not name.upper().startswith("GIT_")}
    # Never wait on a password prompt nobody can see.
    return environment | {"GIT_TERMINAL_PROMPT": "0"}


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
