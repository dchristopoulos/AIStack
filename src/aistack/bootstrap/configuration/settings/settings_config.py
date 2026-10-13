from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from aistack.commons.urls import is_plain_http_url

# Reject the public placeholder shipped in .env.example.
PLACEHOLDER_INVITE_CODE = "change-me"

MINIMUM_INVITE_CODE_LENGTH = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        hide_input_in_errors=True,
        extra="ignore"
    )

    # Keep DATABASE_URL unprefixed for hosting platforms.
    database_url: str = Field(
        default="sqlite:///./aistack.db",
        repr=False,
        description="SQLAlchemy URL. SQLite by default (ADR-0002); a postgresql+psycopg:// "
                    "URL switches to Postgres. Synchronous drivers only (ADR-0005)."
    )

    # Mask the invite code in object representations as well as validation output.
    invite_code: SecretStr = Field(
        validation_alias="aistack_invite_code",
        description="Team invite code, presented by new users as a bootstrap bearer token "
                    "(ADR-0003). Operator-supplied; never generated, printed, or logged."
    )

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

    public_url: str | None = Field(
        default=None,
        validation_alias="aistack_public_url",
        description="The address clients reach this server at, e.g. https://aistack.example.com. "
                    "Unset, it is taken from each request, which is wrong behind a reverse "
                    "proxy that rewrites the host or terminates TLS."
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        validation_alias="aistack_log_level",
        description="Root log level for the server."
    )

    @field_validator("public_url")
    @classmethod
    def normalize_public_url(cls, value: str | None) -> str | None:
        """Keep one spelling, so every URL built from it joins with a single slash."""
        if value is None or not value.strip():
            return None
        value = value.strip().rstrip("/")
        # The same rule a request-derived address has to pass: this value is pasted into
        # a shell command too, and an operator's typo should fail at startup, not there.
        if not is_plain_http_url(value):
            raise ValueError(
                "AISTACK_PUBLIC_URL must be a plain http:// or https:// address such as "
                "https://aistack.example.com, with no credentials, query, or spaces."
            )
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper() if isinstance(value, str) else value


def validate_invite_code(invite_code: SecretStr) -> None:
    """Reject an unusable invite code during context assembly, without echoing it.

    Keep this outside Pydantic validators so rejected secrets never enter their errors.
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
