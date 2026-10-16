"""What a project is: a git repository, known by its remote or, without one, by its path (ADR-0026).

Pure functions: no session, no I/O. A remote can carry a token (`https://user:ghs_…@host/…`),
so nothing here echoes one. The key keeps the host and the path only, and every rejection
says what was wrong with the value without quoting it.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass

from aistack.commons.exceptions import ValidationError

KEY_MAX_LENGTH = 255
NAME_MAX_LENGTH = 64
PATH_MAX_LENGTH = 1024
# A remote longer than this is not one git printed. Checked before any parsing.
_REMOTE_MAX_LENGTH = 2048

_URL = re.compile(r"^(?P<scheme>[a-z][a-z0-9+.-]*)://(?P<rest>.*)$", re.IGNORECASE)
# git's own rule for the scp form: `[user@]host:path`, with no slash before the colon.
_SCP = re.compile(r"^(?:[^@/]*@)?(?P<host>[^@/:]+):(?P<path>.*)$")
_DRIVE = re.compile(r"^[a-z]:[\\/]", re.IGNORECASE)
# The home folder as a session reports it on each system, with or without a trailing slash.
_HOME = re.compile(
    r"^(?:~|\$home|/root|/users/[^/]+|/home/[^/]+|[a-z]:[\\/]users[\\/][^\\/]+)[\\/]?$",
    re.IGNORECASE,
)


def project_key(remote: str) -> str | None:
    """`host/path`, lowercased, for a remote another computer can reach; None for a path.

    Scheme, credentials, port, a trailing `/` and `.git` are dropped, so the https, scp and
    ssh spellings of one repository are one project. A `file://` remote or a path on disk is
    a repository of this computer alone, which `local_project_key` names instead.
    """
    remote = _checked_text(remote, "here.remote", _REMOTE_MAX_LENGTH).strip()
    if not remote:
        raise ValidationError(_UNREADABLE_REMOTE)
    if _is_path(remote):
        return None
    url = _URL.match(remote)
    if url:
        if url["scheme"].lower() == "file":
            return None
        authority, _, path = url["rest"].partition("/")
        # A query or a fragment is no part of the repository, and can carry a token too.
        path = re.split(r"[?#]", path)[0]
        host = authority.rpartition("@")[2]
        if host.startswith("["):
            host = host.partition("]")[0] + "]"
        else:
            host = host.partition(":")[0]
    else:
        scp = _SCP.match(remote)
        if not scp:
            raise ValidationError(_UNREADABLE_REMOTE)
        host, path = scp["host"], scp["path"]
    path = path.strip("/")
    if path.lower().endswith(".git"):
        path = path[:-len(".git")].rstrip("/")
    if not host or not path or "@" in host:
        raise ValidationError(_UNREADABLE_REMOTE)
    key = f"{host}/{path}".lower()
    if len(key) > KEY_MAX_LENGTH or any(character.isspace() for character in key):
        raise ValidationError(_UNREADABLE_REMOTE)
    return key


def local_project_key(machine_id: uuid.UUID, top_level: str) -> str:
    """The key of a repository with no remote another computer can reach: this computer's
    alone, because the same path elsewhere is another repository."""
    digest = hashlib.sha256(top_level.encode("utf-8")).hexdigest()[:16]
    return f"local/{machine_id}/{digest}"


def project_name(key_or_path: str) -> str:
    """What a project is called on the page: its last path segment (`aistack`)."""
    name = re.split(r"[\\/]", key_or_path.rstrip("/\\"))[-1]
    if name.lower().endswith(".git"):
        name = name[:-len(".git")]
    name = name[:NAME_MAX_LENGTH]
    if not name or not name.isprintable():
        raise ValidationError("A project needs a folder name AIStack can show. Send the "
                              "repository's top level, as `git rev-parse --show-toplevel` "
                              "prints it.")
    return name


def validated_key(key: str) -> str:
    """A key as `project_key` or `local_project_key` made it, sent back by an agent or read
    from a Library's log. Checked, never normalised: a key is compared as it is stored."""
    key = _checked_text(key, "project", KEY_MAX_LENGTH)
    if (not key or key != key.lower() or "/" not in key.strip("/")
            or any(character.isspace() or character in "@?#\\" for character in key)):
        raise ValidationError("project is not a project key AIStack made. Send the key sync "
                              "reported under project.")
    return key


def validated_name(name: str) -> str:
    """A project's display name, as `project_name` made it."""
    name = _checked_text(name, "project_name", NAME_MAX_LENGTH)
    if not name.strip():
        raise ValidationError("project_name is empty.")
    return name


@dataclass(frozen=True)
class Here:
    """The repository a session runs in, as its sync skill reported it."""

    path: str
    # None for a repository of this computer alone; `local_project_key` names it.
    key: str | None


def validated_here(path: str, remote: str | None) -> Here:
    """The top level and remote an agent sent, checked before anything is stored.

    The path is for display only: the server never places it in a command. It must be
    absolute or start with `~`, and it may not be the home folder, whose skills folders are
    the global ones.
    """
    path = _checked_text(path, "here.path", PATH_MAX_LENGTH)
    if not path.strip():
        raise ValidationError("here.path is empty. Send the repository's top level, as "
                              "`git rev-parse --show-toplevel` prints it.")
    if _HOME.match(path):
        raise ValidationError("here.path is the home folder, whose skills folders are the "
                              "global ones. A repository kept at the home folder is not a "
                              "project: sync its folders without here.")
    if not (path.startswith(("/", "~", "\\\\")) or _DRIVE.match(path)):
        raise ValidationError("here.path is not an absolute path. Send the repository's top "
                              "level, as `git rev-parse --show-toplevel` prints it.")
    return Here(path=path, key=None if remote is None else project_key(remote))


_UNREADABLE_REMOTE = ("here.remote is not a git remote AIStack can read. Send what "
                      "`git remote get-url origin` prints.")


def _checked_text(value: str, field: str, limit: int) -> str:
    # The value is never quoted back: a remote can carry a token, and a near-miss of one is
    # still one.
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text.")
    if len(value) > limit:
        raise ValidationError(f"{field} is longer than {limit} characters.")
    if not value.isprintable():
        raise ValidationError(f"{field} has a control character in it. Send it as git "
                              "prints it, on one line.")
    return value


def _is_path(remote: str) -> bool:
    # git reads anything with a slash before its first colon, or a drive letter, as a path.
    if remote.startswith(("/", "~", ".", "\\")) or _DRIVE.match(remote):
        return True
    colon, slash = remote.find(":"), remote.find("/")
    return colon == -1 or (slash != -1 and slash < colon and not _URL.match(remote))
