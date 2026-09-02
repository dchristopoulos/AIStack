from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The value `.env.example` ships. An operator who copied the file and never edited it would
# otherwise run an internet-reachable server whose invite code is published in the repository.
PLACEHOLDER_INVITE_CODE = "change-me"

MINIMUM_INVITE_CODE_LENGTH = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # DATABASE SETTINGS

    # Unprefixed on purpose: `DATABASE_URL` is the name every hosting platform injects.
    database_url: str = Field(
        default="sqlite:///./aistack.db",
        description="SQLAlchemy URL. SQLite by default (ADR-0002); a postgresql+psycopg:// "
                    "URL switches to Postgres. Synchronous drivers only (ADR-0005)."
    )

    # AUTH SETTINGS

    # SecretStr, not str: pydantic embeds the rejected input in a ValidationError, and this
    # field's whole purpose is a value that must never reach startup output. SecretStr renders
    # as asterisks there and in any repr of the settings object.
    invite_code: SecretStr = Field(
        validation_alias="aistack_invite_code",
        description="Team invite code, presented by new users as a bootstrap bearer token "
                    "(ADR-0003). Operator-supplied; never generated, printed, or logged."
    )

    # MCP SERVER SETTINGS

    host: str = Field(
        default="0.0.0.0",
        validation_alias="aistack_host",
        description="Interface the MCP server binds to."
    )

    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        validation_alias="aistack_port",
        description="Port the MCP server listens on."
    )

    mcp_path: str = Field(
        default="/mcp",
        validation_alias="aistack_mcp_path",
        description="HTTP path the streamable-HTTP transport is mounted at."
    )

    # LOGGING SETTINGS

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        validation_alias="aistack_log_level",
        description="Root log level for the server."
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper() if isinstance(value, str) else value

    @staticmethod
    @lru_cache(maxsize=1)
    def get_settings() -> "Settings":
        return Settings()


def validate_invite_code(invite_code: SecretStr) -> None:
    """Reject an unusable invite code at startup, without ever printing it.

    Deliberately not a pydantic validator: pydantic reports the offending *input* alongside
    any error it raises, and for this field the input is the secret. A validator here would
    write the invite code into the very startup output the secrets rule forbids it from.

    Startup is also the only moment this can be caught. A weak or placeholder code is not an
    error at any later point — it is simply a server that anyone who read the README can join.
    """
    value = invite_code.get_secret_value()

    if value.strip() != value:
        raise ValueError("AISTACK_INVITE_CODE has leading or trailing whitespace. Bearer "
                         "tokens are compared verbatim, so trim it.")
    if value == PLACEHOLDER_INVITE_CODE:
        raise ValueError("AISTACK_INVITE_CODE is still the placeholder from .env.example. Set "
                         "a secret of your own before starting the server.")
    if len(value) < MINIMUM_INVITE_CODE_LENGTH:
        raise ValueError(f"AISTACK_INVITE_CODE is shorter than {MINIMUM_INVITE_CODE_LENGTH} "
                         f"characters. It is a long-lived shared secret on a reachable server, "
                         f"so make it unguessable.")
