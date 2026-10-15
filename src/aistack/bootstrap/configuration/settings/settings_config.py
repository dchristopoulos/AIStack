import json
import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import make_url

from aistack.commons.urls import is_plain_http_url

# Reject the public placeholder shipped in .env.example.
PLACEHOLDER_INVITE_CODE = "change-me"

MINIMUM_INVITE_CODE_LENGTH = 16

# Where this computer's Library lives, in AISTACK_HOME: what the agent's settings say, for the
# commands a person runs in a terminal without them.
LIBRARY_FILE = "library.toml"


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


class LocalSettings(BaseSettings):
    """Local mode (ADR-0020): `aistack` started by a coding agent on the person's computer.

    Every variable is AISTACK_-prefixed and nothing is read from a .env file. The agent starts
    this process in whatever project is open, and that project's own DATABASE_URL or .env
    names its application's database, which AIStack would otherwise migrate.
    """

    model_config = SettingsConfigDict(
        case_sensitive=False,
        hide_input_in_errors=True,
        extra="ignore"
    )

    home: Path = Field(
        default=Path.home() / ".aistack",
        validation_alias="aistack_home",
        description="Where this computer keeps its machine id, and the SQLite Library by "
                    "default."
    )

    database_url: str | None = Field(
        default=None,
        repr=False,
        validation_alias="aistack_database_url",
        description="The Library's database, shared by the person's computers: a "
                    "postgresql+psycopg:// URL. Unset, a SQLite file in AISTACK_HOME, which "
                    "only this computer sees."
    )

    library_repo: str | None = Field(
        default=None,
        validation_alias="aistack_library_repo",
        description="A private GitHub repository, as owner/name, that holds the Library's log "
                    "(ADR-0025). Each computer keeps its own copy in AISTACK_HOME. Instead of "
                    "AISTACK_DATABASE_URL, not with it."
    )

    username: str | None = Field(
        default=None,
        validation_alias="aistack_username",
        description="The name the Library is created under, on the first computer only. "
                    "Unset, this computer's login name."
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="WARNING",
        validation_alias="aistack_log_level",
        description="Root log level. The coding agent keeps what the process writes to "
                    "stderr, so the default is quiet."
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper() if isinstance(value, str) else value

    def place(self) -> dict[str, str] | None:
        """Where the environment says the Library lives, with no password; None when it
        says nothing."""
        if self.library_repo:
            return {"kind": "github", "repository": self.library_repo}
        if self.database_url:
            url = make_url(self.database_url)
            if url.get_backend_name() == "sqlite":
                return {"kind": "sqlite", "path": url.database or ""}
            return {"kind": "postgresql", "host": url.host or "", "database": url.database or ""}
        return None

    def resolved(self, record: bool) -> "LocalSettings":
        """These settings, with the place from AISTACK_HOME's library file when the
        environment names none.

        `record` is for what the agent's settings start, the server and `check`: their place
        is the Library's, and is written down for the rest. Any other command refuses a place
        that disagrees with it, instead of opening a second Library.
        """
        file = self.home / LIBRARY_FILE
        place = self.place()
        if place is not None and record:
            _write_place(file, place)
            return self
        recorded = _read_place(file)
        if place is not None:
            if recorded is not None and recorded != place:
                raise ValueError(
                    f"Your coding agent's Library lives {described(recorded)}, and this "
                    f"command was given {described(place)}. Run it without "
                    "AISTACK_LIBRARY_REPO and AISTACK_DATABASE_URL to use the agent's Library.")
            return self
        if recorded is None or recorded["kind"] == "this_computer":
            if record and recorded is None:
                _write_place(file, {"kind": "this_computer"})
            return self
        if recorded["kind"] == "github":
            return self.model_copy(update={"library_repo": recorded["repository"]})
        if recorded["kind"] == "sqlite":
            return self.model_copy(update={"database_url": f"sqlite:///{recorded['path']}"})
        # A database address holds a password, which is never written here.
        raise ValueError(
            f"Your Library lives {described(recorded)}. Set AISTACK_DATABASE_URL to the "
            "address your coding agent's settings hold, then run this again.")

    def library_url(self) -> str:
        if self.library_repo and self.database_url:
            raise ValueError("Set AISTACK_LIBRARY_REPO or AISTACK_DATABASE_URL, not both: the "
                             "Library lives in one place.")
        if self.library_repo:
            # The copy this computer replays the repository's log into.
            return f"sqlite:///{(self.home / 'github-copy.db').as_posix()}"
        return self.database_url or f"sqlite:///{(self.home / 'aistack.db').as_posix()}"


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


def _read_place(file: Path) -> dict[str, str] | None:
    try:
        place = tomllib.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"{file} cannot be read. Delete it, then start your coding agent "
                         "again to write it anew.") from error
    if place.get("kind") not in ("this_computer", "github", "postgresql", "sqlite") or not all(
            isinstance(value, str) for value in place.values()):
        raise ValueError(f"{file} does not say where a Library lives. Delete it, then start "
                         "your coding agent again to write it anew.")
    return place


def record_place(home: Path, place: dict[str, str]) -> None:
    """Write down where the Library lives now, as a move does."""
    _write_place(home / LIBRARY_FILE, place)


def _write_place(file: Path, place: dict[str, str]) -> None:
    try:
        if _read_place(file) == place:
            return
    except ValueError:
        pass  # Garbled: the agent's settings say where the Library is, so it is rewritten.
    file.parent.mkdir(parents=True, exist_ok=True)
    # JSON string escapes are valid TOML basic strings.
    lines = [f"{key} = {json.dumps(value)}" for key, value in place.items()]
    # Its own name, so two agents starting at once never write into one file.
    temporary = file.with_name(f"{file.name}.{os.getpid()}.tmp")
    temporary.write_text("# Where this computer's AIStack Library lives, as its coding agent "
                         "last started it.\n" + "\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(file)


def described(place: dict[str, str]) -> str:
    """Where `place` is, as a sentence ends: "in the GitHub repository maria/skills"."""
    kind = place["kind"]
    if kind == "github":
        return f"in the GitHub repository {place['repository']}"
    if kind == "postgresql":
        return f"in the PostgreSQL database {place['database']} at {place['host']}"
    if kind == "sqlite":
        return f"in the SQLite file {place['path']}"
    return "on this computer only"
