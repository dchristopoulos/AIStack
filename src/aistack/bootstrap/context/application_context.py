import getpass
import logging
import os
import platform
import re
import secrets
import socket
import subprocess
import uuid
from pathlib import Path

from sqlalchemy import Engine, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from aistack.bootstrap.configuration.settings.settings_config import (
    LocalSettings,
    Settings,
    validate_invite_code,
)
from aistack.commons.exceptions import AIStackError, Conflict
from aistack.db.engine import build_engine, build_read_session_factory, build_session_factory
from aistack.db.schema import NewerSchema, guard_schema, migrate_schema
from aistack.db.models.machine import Machine
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
# Local mode only: the one caller every tool call comes from.
_local_principal: MachinePrincipal | None = None
# What the dashboard says about where the Library lives; never the address itself.
_library: dict[str, str] = {"kind": "server"}
# A Library on GitHub (ADR-0025): the clone and the copy kept in step with it.
_sharing: LibrarySharing | None = None
# Local mode on a Library a newer release changed beyond what this one can run on (ADR-0024).
_local_refusal: str | None = None

_MACHINE_ID_FILE = "machine-id"
_LIBRARY_CLONE = "library"

_OPERATING_SYSTEMS = {"Darwin": "MACOS", "Windows": "WINDOWS"}

# Named on the dashboard by the end of the database's host name.
_PROVIDERS = {".neon.tech": "Neon", ".supabase.com": "Supabase", ".supabase.co": "Supabase"}

_NOT_BUILT = ("The application context has not been built. Call build_application_context() "
              "before serving requests.")


def build_application_context(settings: Settings) -> None:
    """Assemble the database and MCP authentication from explicit settings."""
    global _settings, _engine, _session_factory, _read_session_factory, _ticket_signer

    validate_invite_code(settings.invite_code)

    _settings = settings
    _engine = build_engine(settings.database_url)
    migrate_schema(_engine)
    _session_factory = build_session_factory(_engine)
    guard_schema(_session_factory, _server_refusal)
    _read_session_factory = build_read_session_factory(_engine)
    # A fresh key per process (ADR-0010): a restart invalidates every outstanding transfer
    # URL, and there is no key to store, leak, or rotate.
    _ticket_signer = TicketSigner(secrets.token_bytes(SIGNING_KEY_BYTES))

    # Tools import this module; defer MCP imports to avoid a circular import.
    from aistack.mcp.auth.aistack_token_verifier import AIStackTokenVerifier
    from aistack.mcp.mcp import mcp

    mcp.auth = AIStackTokenVerifier(settings.invite_code, _read_session_factory)

    # Confirm configuration without revealing the invite code or its length.
    logger.info("Application context built. Invite code: 'configured'.")


def build_local_context(settings: LocalSettings) -> None:
    """Assemble local mode: the Library's database, and which machine and user this is.

    Never attaches a token verifier, and the local server takes none: over stdio the caller
    is whoever could start this process (ADR-0020).
    """
    global _engine, _session_factory, _read_session_factory, _ticket_signer, _local_principal
    global _local_refusal, _library, _sharing

    settings.home.mkdir(parents=True, exist_ok=True)
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
        logger.error(str(error))
        return
    _session_factory = build_session_factory(_engine)
    guard_schema(_session_factory, _refuse_locally)
    _read_session_factory = build_read_session_factory(_engine)
    # Signs `aistack dashboard`'s sign-in link and session, fresh per process as on a server.
    _ticket_signer = TicketSigner(secrets.token_bytes(SIGNING_KEY_BYTES))

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
            logger.error(error.message)
            return
        if first_start and not (repo.folder / ".git").is_dir():
            # Without the log, this computer would start a second Library of its own.
            _local_refusal = (
                f"This computer has not read your Library from GitHub yet, and could not reach "
                f"{settings.library_repo}. Check the internet connection and that `gh auth "
                "status` shows you signed in, then restart your coding agent.")
            return

    machine_id = _claimed_machine_id(settings.home / _MACHINE_ID_FILE)
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
            "computer runs an older AIStack that cannot use it. Run `uv tool upgrade "
            "aistack-mcp` in a terminal, then restart your coding agent. Nothing was changed.")


def _refuse_locally(error: NewerSchema) -> AIStackError:
    """A newer release migrated the Library while this process ran: refuse from now on."""
    global _local_refusal
    _local_refusal = _local_upgrade_sentence(error)
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
    _sharing.catch_up(force)
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


def library_description() -> dict[str, str]:
    """Where the Library lives, for the dashboard: the kind, and a host but never a password."""
    return _library


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


def dispose_application_context() -> None:
    """Drop the engine and its pool. Used by tests between temporary databases."""
    global _settings, _engine, _session_factory, _read_session_factory, _ticket_signer
    global _local_principal, _local_refusal, _library, _sharing

    if _engine is not None:
        _engine.dispose()
    _settings = None
    _engine = None
    _session_factory = None
    _read_session_factory = None
    _ticket_signer = None
    _local_principal = None
    _local_refusal = None
    _library = {"kind": "server"}
    _sharing = None
