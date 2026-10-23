"""A skills folder on this computer, read and written by AIStack itself (local mode, ADR-0020).

In server mode an agent lists digests, packs, and unpacks from a shell, and the bytes cross a
transfer URL. In local mode the process runs on the computer, so it does the same three
things here. They keep the server mode rules: a push reads what `tar --exclude .git` would
send, and an install writes only what passed push validation and re-hashed to the revision's
recorded hash, because anything holding the database's credential could have written it.
"""

import contextlib
import hashlib
import os
import shutil
import uuid
from collections.abc import Iterable
from pathlib import Path

from aistack.commons.exceptions import Busy, NotFound, ValidationError
from aistack.commons.text import loggable
from aistack.db.models.harness import Harness
from aistack.services.harnesses import HARNESSES
from aistack.services.skill_archive import (
    MAX_FILE_BYTES,
    MAX_FILE_COUNT,
    build_archive,
    is_filesystem_noise,
    read_archive,
)
from aistack.services.skill_validation import validated_skill, validated_skill_name

# The same staging folder the server mode install steps use: a dot-folder, so neither a
# harness nor sync takes it for a skill, and on the target's filesystem, so a rename is atomic.
STAGING_FOLDER = ".aistack-staging"
# Renames to retry when concurrent installs of one skill keep landing between ours.
_SWAP_ATTEMPTS = 5

# Claude Code's own folder for claude.ai skills, which sync's shell listing also leaves out.
_CLAUDE_CODE_SYNCED = "synced"


def skills_folder(harness: Harness, home: Path) -> Path:
    return home.joinpath(*HARNESSES[harness].home_relative)


# What shows a coding agent that reads `~/.agents/skills` is installed, beside the folder.
_AGENTS_FOLDER_READERS = (".codex", ".gemini", ".kimi-code", ".cursor", ".copilot",
                          ".config/opencode", ".config/amp")


def folders_in_use(home: Path) -> list[str]:
    """The harnesses this computer has an agent for, Claude Code first: what sync covers."""
    folders = []
    if (home / ".claude").is_dir():
        folders.append(Harness.CLAUDE_CODE.value)
    if (skills_folder(Harness.AGENTS, home).is_dir()
            or any((home / reader).is_dir() for reader in _AGENTS_FOLDER_READERS)):
        folders.append(Harness.AGENTS.value)
    return folders


def observed(folder: Path, excluded: Iterable[str] = ()) -> dict[str, dict[str, str]]:
    """`{skill folder: {relative path: sha256}}`, the listing sync's shell command sends.

    Matches `find -L . -mindepth 2 -type f ! -name .DS_Store ! -path './.*' ! -path
    './synced/*'`, except that `.git` is left out, as push leaves it out. A skill folder may
    itself be a link, as one checked out elsewhere often is.
    """
    if not folder.is_dir():
        return {}
    listing = {}
    for skill in sorted(folder.iterdir()):
        if (skill.name in excluded or skill.name.startswith(".")
                or skill.name == _CLAUDE_CODE_SYNCED or not skill.is_dir()):
            continue
        # Links below the skill folder are not followed: one that loops would never end, and
        # push refuses a skill that contains one anyway.
        listing[skill.name] = {
            path.relative_to(skill).as_posix(): _digest(path)
            for path in _files(skill)
            if path.name != ".DS_Store" and path.is_file()
        }
    return listing


def push_refusals(folder: Path, names: Iterable[str]) -> dict[str, str]:
    """Why push would refuse each of these skill folders, for those it would: everything push
    validation checks, read here before anyone calls push (IMP-16). The names have passed
    `validated_skill_name`, since sync checked them first."""
    refused = {}
    for name in names:
        try:
            validated_skill(name, read_archive(archive(folder, name)))
        except ValidationError as error:
            refused[name] = error.message
    return refused


def archive(folder: Path, name: str) -> bytes:
    """The skill folder `name` packed as push expects it, `.git` left out.

    `name` must already be a validated skill name: it is joined to a path.
    """
    root = folder / name
    if not root.is_dir():
        raise NotFound(f"There is no skill folder '{name}' in {folder}. Check the name "
                       "against the folder sync listed.")
    files = []
    for path in _files(root):
        shown = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValidationError(
                f"'{loggable(shown)}' in '{name}' is a link. A skill may contain only files "
                "and folders; replace the link with a copy of what it points to."
            )
        if is_filesystem_noise(path.name):
            continue
        # Refused before reading, so a stray node_modules costs a stat, not a megabyte each.
        if len(files) == MAX_FILE_COUNT:
            raise ValidationError(
                f"'{name}' holds more than {MAX_FILE_COUNT} files. If a node_modules folder "
                "is inside the skill, leave it out."
            )
        details = path.stat()
        if details.st_size > MAX_FILE_BYTES:
            raise ValidationError(f"'{loggable(shown)}' is {details.st_size} bytes and the "
                                  f"limit per file is {MAX_FILE_BYTES}.")
        files.append((shown, path.read_bytes(), bool(details.st_mode & 0o111)))
    return build_archive(files)


def install(folder: Path, name: str, packed: bytes, content_hash: str) -> None:
    """Install one validated revision whole, flushing its files before replacement.

    `packed` came out of the shared database, so it is validated and re-hashed exactly as an
    upload is before a byte of it is written. The name is checked first: it becomes a folder.
    """
    name = validated_skill_name(name)
    skill = validated_skill(name, read_archive(packed))
    if skill.content_hash != content_hash:
        raise ValidationError(
            f"The stored files of '{name}' do not match the hash recorded when they were "
            "pushed, so nothing was installed. Push the skill again from a computer that has "
            "a good copy."
        )

    staging = folder / STAGING_FOLDER
    staging.mkdir(parents=True, exist_ok=True)
    # A folder of its own per install: two sessions installing one skill at once must not
    # write into, or discard, each other's half-written copy and move it into place.
    staged = staging / f"{name}.{uuid.uuid4().hex}"
    try:
        for file in skill.files:
            # Validated paths: relative, no '..', no drive, no device name.
            target = staged / file.path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as stream:
                stream.write(file.content.encode("utf-8"))
                stream.flush()
                target.chmod(0o755 if file.executable else 0o644)
                os.fsync(stream.fileno())
        # Persist children before their directory entries, then the rename's destination.
        for directory, _, _ in os.walk(staged, topdown=False):
            _flush_directory(Path(directory))
        _flush_directory(staging)
        _swap_in(staged, folder / name, staging)
        _flush_directory(folder)
    finally:
        _discard(staged)


def _flush_directory(folder: Path) -> None:
    # Windows cannot open directories through os.open; its files are still flushed above.
    if os.name == "nt":
        return
    descriptor = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _swap_in(staged: Path, destination: Path, staging: Path) -> None:
    """Put `staged` at `destination` by renames on one filesystem, so the folder is always a
    whole revision. A concurrent install can put its own copy there between the two renames;
    that one is moved out in turn."""
    displaced = []
    for _ in range(_SWAP_ATTEMPTS):
        replaced = staging / f"{destination.name}.{uuid.uuid4().hex}.replaced"
        try:
            if destination.is_symlink() or destination.exists():
                with contextlib.suppress(FileNotFoundError):
                    destination.rename(replaced)
                    displaced.append(replaced)
            staged.rename(destination)
        except OSError:
            # Restore the displaced copy if replacement failed with no contender.
            # Otherwise keep it until this attempt succeeds, or for manual recovery.
            if ((replaced.exists() or replaced.is_symlink())
                    and not destination.exists() and not destination.is_symlink()):
                replaced.rename(destination)
            continue
        for previous in displaced:
            _discard(previous)
        return
    raise Busy(f"Another session kept installing '{destination.name}' at the same moment. "
               f"Try again. Displaced copies, if any, are kept in {staging}.")


def refresh(folder: Path, name: str, document: str) -> None:
    """Make `folder/name/SKILL.md` exactly `document`, swapping the file in whole."""
    target = folder / name / "SKILL.md"
    content = document.encode("utf-8")
    if target.is_file() and target.read_bytes() == content:
        return
    staged = target.with_name("SKILL.md.aistack-new")
    staged.write_bytes(content)
    os.replace(staged, target)


def remove(folder: Path, name: str) -> bool:
    """Take the skill folder `name` off this computer. False when it was not there.

    A folder that is a link loses the link, never what it points to.
    """
    target = folder / validated_skill_name(name)
    if not (target.is_symlink() or target.exists()):
        return False
    removed = folder / STAGING_FOLDER / f"{name}.{uuid.uuid4().hex}.removed"
    removed.parent.mkdir(parents=True, exist_ok=True)
    _discard(removed)
    target.rename(removed)
    _discard(removed)
    return True


def _files(root: Path):
    """Every file below `root`, `.git` folders left out, links below `root` not followed."""
    for directory, folders, names in os.walk(root):
        # A link to a folder is listed under folders and never walked; yield it, so archive
        # can refuse it by name.
        folders[:] = [entry for entry in folders if entry != ".git"]
        for entry in list(folders):
            if (Path(directory) / entry).is_symlink():
                folders.remove(entry)
                yield Path(directory) / entry
        yield from (Path(directory) / entry for entry in names)


def _digest(path: Path) -> str:
    """The same sha256 as `file_digest`, streamed: sync lists folders it has not vetted."""
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _discard(path: Path) -> None:
    """Delete what is at `path`; a link loses the link, never what it points to."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
