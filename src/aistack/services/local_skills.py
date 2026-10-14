"""A skills folder on this computer, read and written by AIStack itself (local mode, ADR-0020).

In server mode an agent lists digests, packs, and unpacks from a shell, and the bytes cross a
transfer URL. In local mode the process runs on the computer, so it does the same three
things here. They keep the server mode rules: a push reads what `tar --exclude .git` would
send, and an install writes only what passed push validation and re-hashed to the revision's
recorded hash, because anything holding the database's credential could have written it.
"""

import hashlib
import os
import shutil
from pathlib import Path

from aistack.commons.exceptions import NotFound, ValidationError
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
from aistack.services.skill_validation import validated_skill

# The same staging folder the server mode install steps use: a dot-folder, so neither a
# harness nor sync takes it for a skill, and on the target's filesystem, so a rename is atomic.
STAGING_FOLDER = ".aistack-staging"

# Claude Code's own folder for claude.ai skills, which sync's shell listing also leaves out.
_CLAUDE_CODE_SYNCED = "synced"


def skills_folder(harness: Harness, home: Path) -> Path:
    return home.joinpath(*HARNESSES[harness].home_relative)


def observed(folder: Path) -> dict[str, dict[str, str]]:
    """`{skill folder: {relative path: sha256}}`, the listing sync's shell command sends.

    Matches `find -L . -mindepth 2 -type f ! -name .DS_Store ! -path './.*' ! -path
    './synced/*'`, except that `.git` is left out, as push leaves it out. A skill folder may
    itself be a link, as one checked out elsewhere often is.
    """
    if not folder.is_dir():
        return {}
    listing = {}
    for skill in sorted(folder.iterdir()):
        if skill.name.startswith(".") or skill.name == _CLAUDE_CODE_SYNCED or not skill.is_dir():
            continue
        # Links below the skill folder are not followed: one that loops would never end, and
        # push refuses a skill that contains one anyway.
        listing[skill.name] = {
            path.relative_to(skill).as_posix(): _digest(path)
            for path in _files(skill)
            if path.name != ".DS_Store" and path.is_file()
        }
    return listing


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
    """Put one revision at `folder/name`, replacing what is there, or leave the disk as it was.

    `packed` came out of the shared database, so it is validated and re-hashed exactly as an
    upload is before a byte of it is written.
    """
    skill = validated_skill(name, read_archive(packed))
    if skill.content_hash != content_hash:
        raise ValidationError(
            f"The stored files of '{name}' do not match the hash recorded when they were "
            "pushed, so nothing was installed. Push the skill again from a computer that has "
            "a good copy."
        )

    staging = folder / STAGING_FOLDER
    staging.mkdir(parents=True, exist_ok=True)
    staged = staging / name
    _discard(staged)
    for file in skill.files:
        # Validated paths: relative, no '..', no drive, no device name.
        target = staged / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file.content.encode("utf-8"))
        target.chmod(0o755 if file.executable else 0o644)

    destination = folder / name
    replaced = staging / f"{name}.replaced"
    _discard(replaced)
    if destination.is_symlink() or destination.exists():
        destination.rename(replaced)
    staged.rename(destination)
    _discard(replaced)


def remove(folder: Path, name: str) -> bool:
    """Take the skill folder `name` off this computer. False when it was not there.

    A folder that is a link loses the link, never what it points to.
    """
    target = folder / name
    if not (target.is_symlink() or target.exists()):
        return False
    removed = folder / STAGING_FOLDER / f"{name}.removed"
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
