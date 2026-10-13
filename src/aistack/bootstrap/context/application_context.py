import logging
import secrets

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from aistack.bootstrap.configuration.settings.settings_config import (
    Settings,
    validate_invite_code,
)
from aistack.db.engine import build_engine, build_session_factory
from aistack.db.schema import migrate_schema
from aistack.services.transfer_ticket import SIGNING_KEY_BYTES, TicketSigner

logger = logging.getLogger(__name__)

# Assembly owns these singletons; importing modules never connects to the database.
_settings: Settings | None = None
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_ticket_signer: TicketSigner | None = None

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
    global _settings, _engine, _session_factory, _ticket_signer

    if _engine is not None:
        _engine.dispose()
    _settings = None
    _engine = None
    _session_factory = None
    _ticket_signer = None
