import getpass
import logging
import os
import platform
import re
import secrets
import socket
import uuid

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from aistack.bootstrap.configuration.settings.settings_config import (
    LocalSettings,
    Settings,
    validate_invite_code,
)
from aistack.commons.exceptions import AIStackError
from aistack.db.engine import build_engine, build_session_factory
from aistack.db.schema import NewerSchema, migrate_schema
from aistack.mcp.auth.principal import MachinePrincipal
from aistack.services.local_identity import local_machine
from aistack.services.transfer_ticket import SIGNING_KEY_BYTES, TicketSigner

logger = logging.getLogger(__name__)

# Assembly owns these singletons; importing modules never connects to the database.
_settings: Settings | None = None
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_ticket_signer: TicketSigner | None = None
# Local mode only: the one caller every tool call comes from.
_local_principal: MachinePrincipal | None = None
# Local mode on a Library a newer release changed beyond what this one can run on (ADR-0024).
_local_refusal: str | None = None

_MACHINE_ID_FILE = "machine-id"

_OPERATING_SYSTEMS = {"Darwin": "MACOS", "Windows": "WINDOWS"}

_NOT_BUILT = ("The application context has not been built. Call build_application_context() "
              "before serving requests.")


def build_application_context(settings: Settings) -> None:
    """Assemble the database and MCP authentication from explicit settings."""
    global _settings, _engine, _session_factory, _ticket_signer

    validate_invite_code(settings.invite_code)

    _settings = settings
    _engine = build_engine(settings.database_url)
    migrate_schema(_engine)
    _session_factory = build_session_factory(_engine)
    # A fresh key per process (ADR-0010): a restart invalidates every outstanding transfer
    # URL, and there is no key to store, leak, or rotate.
    _ticket_signer = TicketSigner(secrets.token_bytes(SIGNING_KEY_BYTES))

    # Tools import this module; defer MCP imports to avoid a circular import.
    from aistack.mcp.auth.aistack_token_verifier import AIStackTokenVerifier
    from aistack.mcp.mcp import mcp

    mcp.auth = AIStackTokenVerifier(settings.invite_code, _session_factory)

    # Confirm configuration without revealing the invite code or its length.
    logger.info("Application context built. Invite code: 'configured'.")


def build_local_context(settings: LocalSettings) -> None:
    """Assemble local mode: the Library's database, and which machine and user this is.

    Never attaches a token verifier, and the local server takes none: over stdio the caller
    is whoever could start this process (ADR-0020).
    """
    global _engine, _session_factory, _ticket_signer, _local_principal, _local_refusal

    settings.home.mkdir(parents=True, exist_ok=True)
    _engine = build_engine(settings.library_url())
    try:
        migrate_schema(_engine)
    except NewerSchema as error:
        # Still serve, so the agent can say why in chat: its user never sees this log.
        _local_refusal = (
            f"The Library was updated by {error.upgraded_by} on another computer, and "
            "this computer runs an older AIStack that cannot use it. Restart your coding agent "
            "to update AIStack here; if this message comes back, run "
            "`uvx aistack-mcp@latest` once in a terminal. Nothing was changed.")
        logger.error(str(error))
        return
    _session_factory = build_session_factory(_engine)
    # Signs `aistack dashboard`'s sign-in link and session, fresh per process as on a server.
    _ticket_signer = TicketSigner(secrets.token_bytes(SIGNING_KEY_BYTES))

    id_file = settings.home / _MACHINE_ID_FILE
    known_id = _read_machine_id(id_file)
    with _session_factory.begin() as session:
        machine = local_machine(session, known_id,
                                username=settings.username or _login_name(),
                                machine_name=socket.gethostname().split(".")[0] or "computer",
                                os=_OPERATING_SYSTEMS.get(platform.system(), "LINUX"))
        principal = MachinePrincipal(machine_id=machine.machine_id, user_id=machine.user_id)
    if principal.machine_id != known_id:
        # ponytail: two first starts in the same second each register a machine and the
        # last write wins, leaving one unused row; a lock file would close that.
        staged = id_file.with_suffix(".tmp")
        staged.write_text(f"{principal.machine_id}\n")
        os.replace(staged, id_file)

    _local_principal = principal
    logger.info(f"Local mode context built. Machine: '{principal.machine_id}'.")


def is_local_mode() -> bool:
    return _local_principal is not None or _local_refusal is not None


def get_public_url() -> str | None:
    """The server's configured address; local mode has none, and serves on 127.0.0.1."""
    return None if is_local_mode() else get_settings().public_url


def get_local_principal() -> MachinePrincipal:
    if _local_refusal is not None:
        raise AIStackError(_local_refusal)
    if _local_principal is None:
        raise RuntimeError(_NOT_BUILT)
    return _local_principal


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


def get_ticket_signer() -> TicketSigner:
    if _ticket_signer is None:
        raise RuntimeError(_NOT_BUILT)
    return _ticket_signer


def dispose_application_context() -> None:
    """Drop the engine and its pool. Used by tests between temporary databases."""
    global _settings, _engine, _session_factory, _ticket_signer, _local_principal
    global _local_refusal

    if _engine is not None:
        _engine.dispose()
    _settings = None
    _engine = None
    _session_factory = None
    _ticket_signer = None
    _local_principal = None
    _local_refusal = None
