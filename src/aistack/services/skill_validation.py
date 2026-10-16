"""Push validation: `docs/DESIGN.md` §4, rule for rule.

Pure functions over the files an archive contained. Each returns a validated value or raises
ValidationError with a message that says what to fix and what was received. Nothing here
opens a session, so the whole trust boundary can be tested without a database.
"""

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import yaml

from aistack.commons.exceptions import ValidationError
from aistack.commons.text import loggable
from aistack.db.models.skill import (
    SKILL_DESCRIPTION_MAX_LENGTH,
    SKILL_NAME_MAX_LENGTH,
    SKILL_ORIGIN_MAX_LENGTH,
)
from aistack.db.models.skill_file import SKILL_FILE_PATH_MAX_LENGTH
from aistack.db.models.skill_version import SKILL_VERSION_MAX_LENGTH
from aistack.services.content_hash import canonical_content_hash, file_digest, normalized_path
from aistack.services.skill_archive import MAX_FILE_COUNT, ArchivedFile

SKILL_DOCUMENT = "SKILL.md"
MAX_PATH_DEPTH = 8

# The Agent Skills specification's rule, so a valid name is a valid folder in every harness.
_SKILL_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

# Claude Code downloads claude.ai skills into this folder and overwrites edits to it. It is
# not the user's to push and not AIStack's to manage.
CLAUDE_CODE_FOLDER = "synced"

_HTTP_URL = re.compile(r"https?://[^\s/]+(/\S*)?")

# Characters Windows cannot put in a filename. A skill pushed from macOS must still install.
_WINDOWS_FORBIDDEN = frozenset('<>:"|?*')
_WINDOWS_DEVICE_NAMES = frozenset(
    ["con", "prn", "aux", "nul", "conin$", "conout$"]
    + [f"com{number}" for number in range(1, 10)]
    + [f"lpt{number}" for number in range(1, 10)]
)
# NTFS gives a long name a short alias such as SCRIPT~1.SH. A file named like one can land on
# another file of the skill on Windows, so what installs there differs from what was reviewed.
_SHORT_NAME = re.compile(r"[^.]*~[0-9]", re.ASCII)
# Windows also reserves COM¹, COM², COM³ and their LPT twins.
_SUPERSCRIPT_DIGITS = str.maketrans("¹²³", "123")

# What one directory entry may weigh. Linux counts bytes and stops at 255; the character
# limit on the whole path would let 255 four-byte characters through.
_MAX_SEGMENT_BYTES = 255

# Version-control metadata is never part of a skill, and a hook stored in it would arrive
# on every machine with its executable bit set.
_VERSION_CONTROL_FOLDERS = frozenset([".git", ".hg", ".svn"])
_ENVIRONMENT_TEMPLATES = frozenset([".env.example", ".env.sample", ".env.template"])

_FRONTMATTER_FENCE = "---"
# Enough for any real frontmatter, and a hard stop for one built to expand (see _measured).
_MAX_FRONTMATTER_NODES = 500
_MAX_FRONTMATTER_DEPTH = 8


@dataclass(frozen=True)
class ValidatedFile:
    path: str
    content: str
    sha256: str
    executable: bool


@dataclass(frozen=True)
class ValidatedSkill:
    """A pushed skill that passed every rule and is ready to store."""

    name: str
    description: str
    version: str | None
    frontmatter: dict[str, Any]
    files: tuple[ValidatedFile, ...]
    content_hash: str


def validated_skill_name(name: str) -> str:
    if not isinstance(name, str):
        raise ValidationError(f"name must be text, but a {type(name).__name__} arrived.")
    if len(name) > SKILL_NAME_MAX_LENGTH:
        raise ValidationError(
            f"The skill name is {len(name)} characters long, and the limit is "
            f"{SKILL_NAME_MAX_LENGTH}. Received: '{loggable(name)}'."
        )
    if not _SKILL_NAME.fullmatch(name):
        raise ValidationError(
            "A skill name is lowercase letters and digits in groups joined by single hyphens, "
            f"like 'code-review'. Received: '{loggable(name)}'. Use the 'name' from the "
            "skill's SKILL.md frontmatter."
        )
    # The name becomes a folder in every machine's skills directory, and installing replaces
    # whatever folder is already there.
    if name == CLAUDE_CODE_FOLDER:
        raise ValidationError(
            f"A skill cannot be named '{name}': Claude Code keeps claude.ai skills in a folder "
            "of that name, and installing this one would replace them. Rename the skill."
        )
    if name in _WINDOWS_DEVICE_NAMES:
        raise ValidationError(
            f"A skill cannot be named '{name}': Windows reserves it for a device, so the "
            "skill's folder could not exist there. Rename the skill."
        )
    return name


def validated_origin(origin: str | None) -> str | None:
    """The optional source URL: trimmed, bounded, and free of control characters."""
    if origin is None:
        return None
    if not isinstance(origin, str):
        raise ValidationError(f"origin must be text, but a {type(origin).__name__} arrived.")
    origin = origin.strip()
    if not origin:
        return None
    if len(origin) > SKILL_ORIGIN_MAX_LENGTH:
        raise ValidationError(
            f"origin is {len(origin)} characters long, and the limit is "
            f"{SKILL_ORIGIN_MAX_LENGTH}. Give the repository or page URL without a query string."
        )
    if not origin.isprintable():
        raise ValidationError(
            f"origin contains control characters. Received: '{loggable(origin)}'."
        )
    # It will be shown as a link, so it has to be one a browser opens as a page.
    if not _HTTP_URL.fullmatch(origin):
        raise ValidationError(
            "origin must be an http:// or https:// URL, like the repository or page the "
            f"skill came from. Omit it otherwise. Received: '{loggable(origin)}'."
        )
    return origin


def validated_skill(name: str, archived: Sequence[ArchivedFile]) -> ValidatedSkill:
    """Apply every content rule to the files of one pushed skill."""
    files = _validated_files(archived)

    document = next((file for file in files if file.path == SKILL_DOCUMENT), None)
    if document is None:
        raise ValidationError(
            f"The archive has no {SKILL_DOCUMENT} at its top level. Archive the skill's own "
            f"folder (tar -C <skill folder> .), so {SKILL_DOCUMENT} is not inside a subfolder, "
            "and check the filename's capitalization."
        )
    frontmatter = _parsed_frontmatter(document.content)
    _require_declared_name(frontmatter, name)

    return ValidatedSkill(
        name=name,
        description=_validated_description(frontmatter),
        version=_validated_version(frontmatter),
        frontmatter=frontmatter,
        files=files,
        content_hash=canonical_content_hash({file.path: file.sha256 for file in files}),
    )


def refusal_from_listing(name: str, paths: Sequence[str]) -> str | None:
    """Why a push of the skill `name` with these files would be refused, as far as the name
    and paths alone show, or None. Sync says it once instead of listing the skill for a backup
    that cannot succeed (IMP-16); the push itself still checks everything."""
    try:
        validated_skill_name(name)
        if len(paths) > MAX_FILE_COUNT:
            raise ValidationError(f"It holds {len(paths)} files, and a skill may hold "
                                  f"{MAX_FILE_COUNT}. If a node_modules folder is inside it, "
                                  "move that out.")
        checked = [_validated_path(path) for path in paths]
        _reject_colliding_paths(checked)
        if SKILL_DOCUMENT not in checked:
            raise ValidationError(f"It has no {SKILL_DOCUMENT} at its top level, so it is not "
                                  "a skill.")
    except ValidationError as error:
        return error.message
    return None


def _validated_files(archived: Sequence[ArchivedFile]) -> tuple[ValidatedFile, ...]:
    files = [
        ValidatedFile(
            path=(path := _validated_path(file.path)),
            content=_decoded(path, file.content),
            sha256=file_digest(file.content),
            executable=file.executable,
        )
        for file in archived
    ]
    _reject_colliding_paths([file.path for file in files])
    return tuple(sorted(files, key=lambda file: file.path.encode("utf-8")))


def _validated_path(raw: str) -> str:
    """One relative path that every supported filesystem can hold."""
    path = normalized_path(raw)
    shown = loggable(path)

    try:
        path.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValidationError(f"The filename '{shown}' is not valid UTF-8. Rename the "
                              "file.") from error
    if not path.isprintable():
        raise ValidationError(f"The path '{shown}' contains control characters. Rename "
                              "the file.")
    if path.startswith("/"):
        raise ValidationError(f"The path '{shown}' is absolute. Paths are relative to the "
                              "skill folder; create the archive with 'tar -C <skill folder> .'.")
    if len(path) > SKILL_FILE_PATH_MAX_LENGTH:
        raise ValidationError(f"The path '{shown}' is {len(path)} characters long, and the "
                              f"limit is {SKILL_FILE_PATH_MAX_LENGTH}.")

    segments = path.split("/")
    if len(segments) > MAX_PATH_DEPTH:
        raise ValidationError(f"The path '{shown}' is {len(segments)} levels deep, and the "
                              f"limit is {MAX_PATH_DEPTH}.")
    for segment in segments:
        _validate_segment(segment, shown)
    return path


def _validate_segment(segment: str, shown_path: str) -> None:
    if segment in ("", ".", ".."):
        raise ValidationError(
            f"The path '{shown_path}' has an empty, '.', or '..' segment. Every file must sit "
            "inside the skill folder under a plain name."
        )
    if _WINDOWS_FORBIDDEN.intersection(segment):
        raise ValidationError(
            f"The path '{shown_path}' uses one of < > : \" | ? * which Windows cannot store. "
            "Rename the file so the skill installs on every machine."
        )
    if segment.endswith((".", " ")):
        raise ValidationError(
            f"The path '{shown_path}' has a name ending in a dot or a space, which Windows "
            "silently strips. Rename the file."
        )
    if _SHORT_NAME.match(segment):
        raise ValidationError(
            f"The path '{shown_path}' is named like a Windows short name (a '~' and a digit "
            "before the extension), which can stand for another file of the skill there. "
            "Rename the file."
        )
    if _device_stem(segment) in _WINDOWS_DEVICE_NAMES:
        raise ValidationError(
            f"The path '{shown_path}' uses a name Windows reserves for a device (CON, PRN, "
            "AUX, NUL, COM1-9, LPT1-9). Rename the file."
        )
    if len(segment.encode("utf-8")) > _MAX_SEGMENT_BYTES:
        raise ValidationError(
            f"The path '{shown_path}' has a name longer than {_MAX_SEGMENT_BYTES} bytes, "
            "which no filesystem can create. Shorten it."
        )
    if _is_environment_file(segment.casefold()):
        raise ValidationError(
            f"The path '{shown_path}' is an environment file, which is where secrets are "
            "kept, and a skill is copied to every computer and team it reaches. Leave it out "
            "of the skill."
        )
    if segment.casefold() in _VERSION_CONTROL_FOLDERS:
        raise ValidationError(
            f"The path '{shown_path}' is version-control metadata, not part of the skill. "
            "Leave it out: 'tar --exclude .git -czf <file> -C <skill folder> .'."
        )


def _is_environment_file(name: str) -> bool:
    """`.env` and its per-environment variants, but not the templates meant to be shared."""
    return name == ".env" or (name.startswith(".env.") and name not in _ENVIRONMENT_TEMPLATES)


def _device_stem(segment: str) -> str:
    """The part of a name Windows compares against its device list.

    Windows ignores everything from the first dot and any spaces before it, so `aux .txt` and
    `NUL.tar.gz` are both devices.
    """
    return segment.split(".", 1)[0].rstrip(" ").casefold().translate(_SUPERSCRIPT_DIGITS)


def _collision_key(path: str) -> str:
    """Two paths with the same key are one file on a case-insensitive filesystem.

    NTFS matches names by their uppercase form, and `casefold()` alone keeps `i` and the
    dotless `ı` apart although both uppercase to `I`. Uppercasing first folds every pair
    either rule would.
    """
    return unicodedata.normalize("NFC", path.upper().casefold())


def _reject_colliding_paths(paths: Sequence[str]) -> None:
    """Two names a case-insensitive filesystem would merge, or a file where a folder must be."""
    seen: dict[str, str] = {}
    for path in paths:
        folded = _collision_key(path)
        if folded in seen:
            raise ValidationError(
                f"'{loggable(seen[folded])}' and '{loggable(path)}' are the same file on "
                "macOS and Windows, which ignore case. Rename or remove one."
            )
        seen[folded] = path

    for path in paths:
        segments = _collision_key(path).split("/")
        for depth in range(1, len(segments)):
            folder = "/".join(segments[:depth])
            if folder in seen:
                raise ValidationError(
                    f"'{loggable(seen[folder])}' is a file, and '{loggable(path)}' needs it "
                    "to be a folder. Rename one of them."
                )


def _decoded(path: str, content: bytes) -> str:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError(
            f"'{loggable(path)}' is not UTF-8 text. AIStack stores text files only; leave "
            "binary files (images, archives, compiled output) out of the skill."
        ) from error
    if "\x00" in text:
        raise ValidationError(f"'{loggable(path)}' contains a NUL character, so it is not a "
                              "text file. Leave it out of the skill.")
    return text


def _parsed_frontmatter(document: str) -> dict[str, Any]:
    """The YAML mapping between the two `---` lines, with every scalar kept as a string.

    BaseLoader builds only strings, lists, and dicts: it cannot construct an object, and it
    does not turn `version: 1.10` into the float 1.1.
    """
    # Split on line feeds only. splitlines() also breaks on U+2028, U+0085, and form feed,
    # which a harness does not, so a fence could be closed where no reader sees a line end.
    lines = [line.removesuffix("\r") for line in document.removeprefix("\ufeff").split("\n")]
    if not lines or lines[0].strip() != _FRONTMATTER_FENCE:
        raise ValidationError(
            f"{SKILL_DOCUMENT} does not start with frontmatter. Its first line must be '---', "
            "followed by 'name:' and 'description:' and a closing '---'."
        )
    try:
        closing = next(index for index, line in enumerate(lines[1:], start=1)
                       if line.strip() == _FRONTMATTER_FENCE)
    except StopIteration:
        raise ValidationError(f"{SKILL_DOCUMENT} frontmatter is never closed. Add a line "
                              "containing only '---' after the last field.") from None

    try:
        frontmatter = yaml.load("\n".join(lines[1:closing]), Loader=_FrontmatterLoader)
    except yaml.YAMLError as error:
        raise ValidationError(f"{SKILL_DOCUMENT} frontmatter is not valid YAML: "
                              f"{loggable(error)}") from error
    except RecursionError as error:
        # PyYAML's parser is recursive, and a few thousand nested brackets exhaust the stack
        # before the node budget below ever sees the result.
        raise _oversized_frontmatter() from error
    if not isinstance(frontmatter, dict):
        raise ValidationError(f"{SKILL_DOCUMENT} frontmatter must be 'key: value' fields, "
                              "starting with 'name:' and 'description:'.")

    _measured(frontmatter, depth=1, budget=[_MAX_FRONTMATTER_NODES])
    try:
        json.dumps(frontmatter)
    except (TypeError, ValueError) as error:
        raise ValidationError(f"{SKILL_DOCUMENT} frontmatter uses a YAML construct that has "
                              "no plain equivalent. Use simple keys and values.") from error
    return frontmatter


class _FrontmatterLoader(yaml.BaseLoader):
    """BaseLoader that refuses a key written twice.

    YAML says duplicate keys are an error and PyYAML keeps the last one. A reader who keeps
    the first would then see a different `name` or `description` than the one validated here.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        keys = [self.construct_object(key_node, deep=True) for key_node, _ in node.value]
        duplicates = sorted(key for key in set(map(str, keys)) if list(map(str, keys)).count(key) > 1)
        if duplicates:
            raise yaml.constructor.ConstructorError(
                None, None, f"the key '{duplicates[0]}' appears more than once",
                node.start_mark)
        return super().construct_mapping(node, deep=deep)


def _oversized_frontmatter() -> ValidationError:
    return ValidationError(
        f"{SKILL_DOCUMENT} frontmatter is too large or too deeply nested. It should be a "
        "handful of fields; move anything long into the body."
    )


def _measured(node: Any, depth: int, budget: list[int]) -> None:
    """Walk the parsed frontmatter, refusing anything outsized before it is serialized.

    YAML aliases let a few hundred bytes describe a structure with billions of nodes. PyYAML
    shares the aliased objects, so parsing is cheap and the cost lands on whoever walks or
    serializes the result. This walk pays per visit and stops at the budget.
    """
    budget[0] -= 1
    if budget[0] < 0 or depth > _MAX_FRONTMATTER_DEPTH:
        raise _oversized_frontmatter()
    if isinstance(node, str):
        # Postgres cannot store U+0000 in text or JSONB, and SQLite can: reject it for both.
        if "\x00" in node:
            raise ValidationError(f"{SKILL_DOCUMENT} frontmatter contains a NUL character "
                                  "(a '\\0' escape). Remove it.")
        # A YAML escape such as "\ud800" produces half of a surrogate pair. That is a Python
        # string and not text: nothing can encode it, and the two databases disagree on it.
        try:
            node.encode("utf-8")
        except UnicodeEncodeError:
            raise ValidationError(
                f"{SKILL_DOCUMENT} frontmatter contains a character that is not valid "
                "Unicode (an unpaired surrogate escape). Remove it."
            ) from None
    elif isinstance(node, dict):
        for key, value in node.items():
            _measured(key, depth + 1, budget)
            _measured(value, depth + 1, budget)
    elif isinstance(node, list):
        for item in node:
            _measured(item, depth + 1, budget)


def _require_declared_name(frontmatter: dict[str, Any], name: str) -> None:
    """The folder a skill installs into is its name, so the two must not disagree."""
    declared = frontmatter.get("name")
    if declared != name:
        raise ValidationError(
            f"{SKILL_DOCUMENT} declares name '{loggable(declared)}', but the push is for "
            f"'{name}'. Push it under the name in its frontmatter, or change the frontmatter."
        )


def _validated_description(frontmatter: dict[str, Any]) -> str:
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValidationError(
            f"{SKILL_DOCUMENT} frontmatter has no 'description'. It is required: the "
            "description is how an agent decides when to use the skill."
        )
    # One line. The description is shown in listings and read by other people's agents, so
    # a block scalar's line breaks become spaces and nothing else unprintable may remain.
    description = " ".join(description.split())
    if not description.isprintable():
        raise ValidationError(
            f"The description contains control characters. Received: "
            f"'{loggable(description)}'. Keep it to plain text."
        )
    if len(description) > SKILL_DESCRIPTION_MAX_LENGTH:
        raise ValidationError(
            f"The description is {len(description)} characters long, and the limit is "
            f"{SKILL_DESCRIPTION_MAX_LENGTH}. Shorten it; detail belongs in the body."
        )
    return description


def _validated_version(frontmatter: dict[str, Any]) -> str | None:
    version = frontmatter.get("version")
    if version is None:
        return None
    if not isinstance(version, str):
        raise ValidationError("The frontmatter 'version' must be a single value such as "
                              "'1.2.0', not a list or a mapping.")
    if len(version) > SKILL_VERSION_MAX_LENGTH:
        raise ValidationError(
            f"The frontmatter 'version' is {len(version)} characters long, and the limit is "
            f"{SKILL_VERSION_MAX_LENGTH}. Received: '{loggable(version)}'."
        )
    return version or None
