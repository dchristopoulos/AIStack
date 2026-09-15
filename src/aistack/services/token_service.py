import hashlib
import hmac
import secrets

from pydantic import SecretStr

# Recognizable prefix; entropy comes entirely from the random suffix.
TOKEN_PREFIX = "aist_"
TOKEN_ENTROPY_BYTES = 32


def generate_machine_token() -> str:
    """Mint a machine token. Return it once to the caller; store only its hash."""
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)}"


def hash_token(token: str) -> str:
    """Return the lowercase sha256 hex digest of the complete token, including its prefix."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def matches_invite_code(presented: str, configured: SecretStr) -> bool:
    """Compare fixed-length digests without exposing the invite code in object reprs.

    Machine tokens use an indexed database lookup instead. See ADR-0003.
    """
    return hmac.compare_digest(
        hash_token(presented), hash_token(configured.get_secret_value())
    )
