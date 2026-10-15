import getpass
import hashlib
import logging
import os
import platform
import re
import secrets
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from aistack.bootstrap.configuration.settings.settings_config import (
    LocalSettings,
    Settings,
    resolved_invite_code,
)
from aistack.bootstrap.hardware import hardware_id
from aistack.commons.exceptions import AIStackError, Conflict, NeedsNewerRelease
from aistack.commons.release import UPDATE_AND_RESTART
from aistack.db.engine import build_engine, build_read_session_factory, build_session_factory
from aistack.db.schema import NewerSchema, guard_schema, migrate_schema
from aistack.db.models.machine import Machine
from aistack.mcp.auth.failure_limiter import (
    FAILURE_LIMIT,
    FAILURE_WINDOW_SECONDS,
    REFUSED_JOIN_LIMIT,
    REFUSED_JOIN_WINDOW_SECONDS,
    FailureLimiter,
)
from aistack.mcp.auth.principal import MachinePrincipal
from aistack.services.library_repo import LibraryRepo, validate_repository
from aistack.services.library_sharing import LibrarySharing
from aistack.services.local_identity import local_machine
from aistack.services.transfer_ticket import SIGNING_KEY_BYTES, TicketSigner, token_prefix

logger = logging.getLogger(__name__)

# Assembly owns these singletons; importing modules never connects to the database.
_settings: Settings | None = None
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
# For a request that only reads: on SQLite it neither waits for nor blocks a writer (ADR-0030).
_read_session_factory: sessionmaker[Session] | None = None
_ticket_signer: TicketSigner | None = None
_failure_limiter: FailureLimiter | None = None
_join_limiter: FailureLimiter | None = None
# Local mode only: the one caller every tool call comes from.
_local_principal: MachinePrincipal | None = None
# What the dashboard says about where the Library lives; never the address itself.
_library: dict[str, str] = {"kind": "server"}
# A Library on GitHub (ADR-0025): the clone and the copy kept in step with it.
_sharing: LibrarySharing | None = None
# Local mode on a Library a newer release changed beyond what this one can run on (ADR-0024).
_local_refusal: str | None = None
# Local mode's AISTACK_HOME, where this computer's id lives.
_local_home: Path | None = None
# The refusal is one a newer release fixes, so local mode updates itself at once.
_needs_newer_release = False
_local_settings: LocalSettings | None = None

_MACHINE_ID_FILE = "machine-id"
# Beside the id: a hash of it with the hardware's, and the id a restored home folder came with.
_FINGERPRINT_FILE = "machine-fingerprint"
_RESTORED_FILE = "restored-from"
_LIBRARY_CLONE = "library"

_OPERATING_SYSTEMS = {"Darwin": "MACOS", "Windows": "WINDOWS"}

# Named on the dashboard by the end of the database's host name.
_PROVIDERS = {".neon.tech": "Neon", ".supabase.com": "Supabase", ".supabase.co": "Supabase"}

_NOT_BUILT = ("The application context has not been built. Call build_application_context() "
              "before serving requests.")


def build_application_context(settings: Settings) -> None:
    """Assemble the database and MCP authentication from explicit settings."""
    global _settings, _engine, _session_factory, _read_session_factory, _ticket_signer

    invite_code = resolved_invite_code(settings)

    _settings = settings
    _engine = build_engine(settings.database_url)
    migrate_schema(_engine)
    _session_factory = build_session_factory(_engine)
    guard_schema(_session_factory, _server_refusal)
    _read_session_factory = build_read_session_factory(_engine)
    # A fresh key per process (ADR-0010): a restart invalidates every outstanding transfer
    # URL, and there is no key to store, leak, or rotate.
    _ticket_signer = TicketSigner(secrets.token_bytes(SIGNING_KEY_BYTES))
    _build_failure_limiters()

    # Tools import this module; defer MCP imports to avoid a circular import.
    from aistack.mcp.auth.aistack_token_verifier import AIStackTokenVerifier
    from aistack.mcp.mcp import mcp

    mcp.auth = AIStackTokenVerifier(invite_code, _read_session_factory, _failure_limiter)

    # Confirm configuration without revealing the invite code or its length.
    logger.info("Application context built. Invite code: 'configured'.")


def build_local_context(settings: LocalSettings) -> None:
    """Assemble local mode: the Library's database, and which machine and user this is.

    Never attaches a token verifier, and the local server takes none: over stdio the caller
    is whoever could start this process (ADR-0020).
    """
    global _engine, _session_factory, _read_session_factory, _ticket_signer, _local_principal
    global _local_refusal, _library, _sharing, _local_home, _needs_newer_release, _local_settings

    _local_settings = settings
    settings.home.mkdir(parents=True, exist_ok=True)
    _local_home = settings.home
    if settings.library_repo:
        try:
            validate_repository(settings.library_repo)
        except AIStackError as error:
            _local_refusal = error.message
            logger.error(error.message)
            return
    _library = ({"kind": "github", "repository": settings.library_repo}
                if settings.library_repo else _described(settings.library_url()))
    _engine = build_engine(settings.library_url())
    try:
        migrate_schema(_engine)
    except NewerSchema as error:
        # Still serve, so the agent can say why in chat: its user never sees this log.
        _local_refusal = _local_upgrade_sentence(error)
        _needs_newer_release = True
        logger.error(str(error))
        return
    _session_factory = build_session_factory(_engine)
    guard_schema(_session_factory, _refuse_locally)
    _read_session_factory = build_read_session_factory(_engine)
    # Signs `aistack dashboard`'s sign-in link and session, fresh per process as on a server.
    _ticket_signer = TicketSigner(secrets.token_bytes(SIGNING_KEY_BYTES))
    _build_failure_limiters()

    first_start = False
    if settings.library_repo:
        repo = LibraryRepo(settings.home / _LIBRARY_CLONE, settings.library_repo)
        _sharing = LibrarySharing(repo, _engine, _session_factory)
        first_start = not (repo.folder / ".git").is_dir()
        try:
            # Only a first start reaches the network, to clone. Any other start replays what
            # the last pull brought and answers at once: an agent may send its first request
            # before a slow start finishes, and the tools pull before they read anyway.
            if first_start:
                _sharing.catch_up(force=True)
            else:
                _sharing.replay_clone()
        except AIStackError as error:
            # A log this release cannot replay, such as a change of a kind a newer release
            # made: still serve, so the agent tells its user what to do.
            _local_refusal = error.message
            _needs_newer_release = isinstance(error, NeedsNewerRelease)
            logger.error(error.message)
            return
        if first_start and not (repo.folder / ".git").is_dir():
            # Without the log, this computer would start a second Library of its own.
            _local_refusal = (
                f"This computer has not read your Library from GitHub yet, and could not reach "
                f"{settings.library_repo}. Check the internet connection and that `gh auth "
                "status` shows you signed in, then restart your coding agent.")
            return

    machine_id = _this_computer(settings.home,
                                _claimed_machine_id(settings.home / _MACHINE_ID_FILE))
    # Asked before the transaction, and only for a computer the Library does not know yet:
    # reading the hardware can take a second, and nothing slow runs inside a transaction.
    with _session_factory() as session:
        known = session.get(Machine, machine_id) is not None
    machine_name = "computer" if known else _computer_name()
    for attempt in range(2):
        try:
            with _session_factory.begin() as session:
                machine = local_machine(
                    session, machine_id,
                    username=settings.username or _login_name(),
                    machine_name=machine_name,
                    os=_OPERATING_SYSTEMS.get(platform.system(), "LINUX"))
                principal = MachinePrincipal(machine_id=machine.machine_id,
                                             user_id=machine.user_id,
                                             token_prefix=token_prefix(machine.token_hash))
            break
        except (IntegrityError, Conflict):
            # Another process on this computer registered the same id first, in a database
            # that let both look before either wrote (PostgreSQL). Its row is there now.
            if attempt:
                raise

    _local_principal = principal
    if _sharing is not None and first_start:
        # A new computer is announced at once, so the check setup runs proves it can push.
        _sharing.publish()
    logger.info(f"Local mode context built. Machine: '{principal.machine_id}'.")


def _local_upgrade_sentence(error: NewerSchema) -> str:
    return (f"The Library was updated by {error.upgraded_by} on another computer, and this "
            f"computer runs an older AIStack that cannot use it. {UPDATE_AND_RESTART} "
            "Nothing was changed.")


def _refuse_locally(error: NewerSchema) -> AIStackError:
    """A newer release migrated the Library while this process ran: refuse from now on."""
    global _local_refusal
    _local_refusal = _local_upgrade_sentence(error)
    _update_for_the_library()
    return AIStackError(_local_refusal)


def _server_refusal(error: NewerSchema) -> AIStackError:
    return AIStackError(
        f"This server's database was upgraded by {error.upgraded_by}, and this server process "
        "runs an older release that cannot use it. Ask whoever runs the server to restart "
        "it on the new release. Nothing was changed.")


def library_before_read(force: bool = False) -> None:
    """For a GitHub Library: catch the copy up on what other computers pushed."""
    global _local_principal
    if _sharing is None or _local_principal is None:
        return
    try:
        _sharing.catch_up(force)
    except NeedsNewerRelease:
        _update_for_the_library()
        raise
    # A rebuild can fold this computer under the person's first user (library_log), and
    # gives its row a new token, which the dashboard's links are bound to.
    with _session_factory.begin() as session:
        machine = session.get(Machine, _local_principal.machine_id)
        if machine is not None and (
                machine.user_id != _local_principal.user_id
                or token_prefix(machine.token_hash) != _local_principal.token_prefix):
            _local_principal = MachinePrincipal(machine.machine_id, machine.user_id,
                                                token_prefix(machine.token_hash))


def library_after_write() -> bool:
    """For a GitHub Library: push what this computer recorded. False when it could not, and
    the change reaches the other computers only with a later push."""
    return _sharing is None or _sharing.publish()


def needs_newer_release() -> bool:
    return _needs_newer_release


def _update_for_the_library() -> None:
    """Another computer moved the Library to a newer release while this one ran: install it
    now rather than after the daily wait, once, unless the person turned updates off."""
    global _needs_newer_release
    if _needs_newer_release:
        return
    _needs_newer_release = True
    if _local_settings is not None and _local_settings.auto_update:
        from aistack.bootstrap import self_update

        self_update.start_in_background(_local_settings.home, force=True)


def is_local_mode() -> bool:
    return _local_principal is not None or _local_refusal is not None


def _computer_name() -> str:
    """What a person calls this computer: "MacBook Pro M4 Pro", not the host name macOS makes
    from their account ("Marias-MacBook-Pro") or the one Windows makes up."""
    system = platform.system()
    if system == "Darwin":
        try:
            hardware = subprocess.run(["system_profiler", "SPHardwareDataType"],
                                      capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.TimeoutExpired):
            hardware = ""
        model = re.search(r"Model Name: (.+)", hardware)
        chip = re.search(r"Chip: (?:Apple )?(.+)", hardware)
        if model:
            return " ".join(found.group(1).strip() for found in (model, chip) if found)
    if system == "Windows":
        return "Windows PC"
    return socket.gethostname().split(".")[0] or "computer"


def library_description() -> dict[str, Any]:
    """Where the Library lives, for the dashboard: the kind, and a host but never a password.
    For GitHub, also whether it was reached last time and how many changes wait here."""
    if _sharing is None:
        return _library
    return _library | {"problem": _sharing.problem, "unpublished": _sharing.unpublished()}


def library_problem() -> str | None:
    """Why the Library's repository could not be reached the last time it was tried; None
    for a Library that is not on GitHub, or one that answered."""
    return None if _sharing is None else _sharing.problem


def _described(database_url: str) -> dict[str, str]:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        return {"kind": "this_computer"}
    host = url.host or ""
    provider = next((name for suffix, name in _PROVIDERS.items() if host.endswith(suffix)),
                    "PostgreSQL")
    return {"kind": "postgresql", "provider": provider, "host": host}


def get_public_url() -> str | None:
    """The server's configured address; local mode has none, and serves on 127.0.0.1."""
    return None if is_local_mode() else get_settings().public_url


def get_local_principal() -> MachinePrincipal:
    if _local_refusal is not None:
        raise AIStackError(_local_refusal)
    if _local_principal is None:
        raise RuntimeError(_NOT_BUILT)
    return _local_principal


def _claimed_machine_id(id_file: Path) -> uuid.UUID:
    """This computer's machine id. The first process ever to start here claims one, and every
    other, even one starting in the same instant, reads that same id."""
    known = _read_machine_id(id_file)
    if known is not None:
        return known
    staged = id_file.with_name(f"{id_file.name}.{uuid.uuid4().hex}.tmp")
    staged.write_text(f"{uuid.uuid4()}\n")
    try:
        # A hard link is made whole or not at all, and fails if the name is taken: the first
        # process to link owns the id, and a reader never sees half of it.
        os.link(staged, id_file)
    except FileExistsError:
        if _read_machine_id(id_file) is None:
            # Not a claim in progress, since a claim is never partial: a damaged file, by
            # hand or a full disk.
            os.replace(staged, id_file)
    finally:
        staged.unlink(missing_ok=True)
    return _read_machine_id(id_file)


def _this_computer(home: Path, machine_id: uuid.UUID) -> uuid.UUID:
    """`machine_id`, unless this home folder was restored onto another computer from a backup:
    then a new id, so the two computers stop being one (LH-02).

    The new id is derived from the old one and the hardware, so every process starting on the
    new computer arrives at the same one without a lock. The fingerprint is written before the
    id, so a process that reads the old id after it still derives the same new one.
    """
    hardware = hardware_id()
    if hardware is None:
        return machine_id
    fingerprint_file = home / _FINGERPRINT_FILE
    try:
        recorded = fingerprint_file.read_text().strip()
    except FileNotFoundError:
        recorded = None
    if recorded is None or recorded == _fingerprint(machine_id, hardware):
        if recorded is None:
            _write_whole(fingerprint_file, _fingerprint(machine_id, hardware))
        return machine_id

    restored = uuid.uuid5(machine_id, hardware)
    _write_whole(home / _RESTORED_FILE, f"{machine_id}\n")
    _write_whole(fingerprint_file, _fingerprint(restored, hardware))
    _write_whole(home / _MACHINE_ID_FILE, f"{restored}\n")
    logger.info(f"This home folder came from another computer. Machine: '{restored}'.")
    return restored


def _fingerprint(machine_id: uuid.UUID, hardware: str) -> str:
    # Salted with the id, so the file says nothing about the hardware on its own.
    return hashlib.sha256(f"{machine_id}:{hardware}".encode()).hexdigest()


def _write_whole(path: Path, text: str) -> None:
    """Replace a file in one step, so a reader sees the old text or the new, never part.

    Processes starting together all write the same text. Windows refuses a replace while
    another one of the same file is under way, so a refusal is fine once the text is there.
    """
    staged = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    staged.write_text(text)
    try:
        for attempt in range(50):
            try:
                os.replace(staged, path)
                return
            except PermissionError:
                if _holds(path, text):
                    return
                if attempt == 49:
                    raise
                time.sleep(0.01)
    finally:
        staged.unlink(missing_ok=True)


def _holds(path: Path, text: str) -> bool:
    try:
        return path.read_text() == text
    except OSError:
        return False


def restored_here() -> bool:
    """True from the start that found this home folder restored onto a new computer until the
    next sync has said so. `sync` reports it, then calls `restore_reported`."""
    return _local_home is not None and (_local_home / _RESTORED_FILE).exists()


def restore_reported() -> None:
    if _local_home is not None:
        (_local_home / _RESTORED_FILE).unlink(missing_ok=True)


def _read_machine_id(id_file) -> uuid.UUID | None:
    try:
        return uuid.UUID(id_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _login_name() -> str:
    """This computer's login name, as a valid username: `Maria Lopez` becomes `maria-lopez`."""
    name = re.sub(r"[^a-z0-9]+", "-", getpass.getuser().lower()).strip("-")
    return name or "me"


def get_settings() -> Settings:
    if _settings is None:
        raise RuntimeError(_NOT_BUILT)
    return _settings


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        raise RuntimeError(_NOT_BUILT)
    return _session_factory


def get_read_session_factory() -> sessionmaker[Session]:
    """Sessions that only read and may not write (ADR-0030). Anything that changes state,
    and anything that reads in order to decide a write, uses `get_session_factory()`."""
    if _read_session_factory is None:
        raise RuntimeError(_NOT_BUILT)
    return _read_session_factory


def get_ticket_signer() -> TicketSigner:
    if _ticket_signer is None:
        raise RuntimeError(_NOT_BUILT)
    return _ticket_signer


def _build_failure_limiters() -> None:
    """Fresh per process, like the signing key: a restart forgets who was turned away."""
    global _failure_limiter, _join_limiter
    _failure_limiter = FailureLimiter(FAILURE_LIMIT, FAILURE_WINDOW_SECONDS)
    _join_limiter = FailureLimiter(REFUSED_JOIN_LIMIT, REFUSED_JOIN_WINDOW_SECONDS)


def get_failure_limiter() -> FailureLimiter:
    """Refused credentials per client address."""
    if _failure_limiter is None:
        raise RuntimeError(_NOT_BUILT)
    return _failure_limiter


def get_join_limiter() -> FailureLimiter:
    """Refused joins per address and per team invite code (SEC-08)."""
    if _join_limiter is None:
        raise RuntimeError(_NOT_BUILT)
    return _join_limiter


def dispose_application_context() -> None:
    """Drop the engine and its pool. Used by tests between temporary databases."""
    global _settings, _engine, _session_factory, _read_session_factory, _ticket_signer
    global _local_principal, _local_refusal, _library, _sharing, _local_home
    global _failure_limiter, _join_limiter, _needs_newer_release, _local_settings

    if _engine is not None:
        _engine.dispose()
    _settings = None
    _engine = None
    _session_factory = None
    _read_session_factory = None
    _ticket_signer = None
    _failure_limiter = None
    _join_limiter = None
    _local_principal = None
    _local_refusal = None
    _needs_newer_release = False
    _local_settings = None
    _library = {"kind": "server"}
    _sharing = None
    _local_home = None
