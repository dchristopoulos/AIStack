import logging

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from aistack.bootstrap.configuration.settings.settings_config import (
    Settings,
    validate_invite_code,
)
from aistack.db.engine import build_engine, build_session_factory, create_schema

logger = logging.getLogger(__name__)

# Assembly owns these singletons; importing modules never connects to the database.
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def build_application_context(settings: Settings) -> None:
    """Assemble the database and MCP authentication from explicit settings."""
    global _engine, _session_factory

    validate_invite_code(settings.invite_code)

    _engine = build_engine(settings.database_url)
    create_schema(_engine)
    _session_factory = build_session_factory(_engine)

    # Tools import this module; defer MCP imports to avoid a circular import.
    from aistack.mcp.auth.aistack_token_verifier import AIStackTokenVerifier
    from aistack.mcp.mcp import mcp

    mcp.auth = AIStackTokenVerifier(settings.invite_code, _session_factory)

    # Confirm configuration without revealing the invite code or its length.
    logger.info("Application context built. Invite code: 'configured'.")


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        raise RuntimeError("The application context has not been built. Call "
                           "build_application_context() before serving requests.")
    return _session_factory


def dispose_application_context() -> None:
    """Drop the engine and its pool. Used by tests between temporary databases."""
    global _engine, _session_factory

    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
