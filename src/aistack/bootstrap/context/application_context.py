import logging

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from aistack.bootstrap.configuration.settings.settings_config import (Settings,
                                                                      validate_invite_code)
from aistack.db.engine import build_engine, build_session_factory, create_schema

logger = logging.getLogger(__name__)

# Application-wide singletons. Nothing here touches a database at import time: the engine is
# built during assembly, so importing a tool module never opens a connection or creates a
# schema as a side effect.
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def build_application_context(settings: Settings) -> None:
    """Assemble the application: engine, schema, session factory, and MCP authentication.

    Takes settings rather than reading the singleton so a test can assemble a context against
    a temporary database without touching the process environment.
    """
    global _engine, _session_factory

    validate_invite_code(settings.invite_code)

    _engine = build_engine(settings.database_url)
    create_schema(_engine)
    _session_factory = build_session_factory(_engine)

    # Imported here rather than at module scope: mcp.mcp imports the tool modules, which import
    # this module for get_session_factory(), and at module scope that is a circular import.
    from aistack.mcp.auth.aistack_token_verifier import AIStackTokenVerifier
    from aistack.mcp.mcp import mcp

    mcp.auth = AIStackTokenVerifier(settings.invite_code.get_secret_value(),
                                    _session_factory)

    # Confirms an invite code is configured without revealing anything about it. Its length is
    # as sensitive as its value here — it is the one hint that narrows a brute force.
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
