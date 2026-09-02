import hashlib
import hmac
import secrets

from pydantic import SecretStr

# Prefixed so a leaked string is recognizable as an AIStack credential by a secret scanner,
# and so a user pasting the wrong value into their MCP config gets an obvious mismatch.
TOKEN_PREFIX = "aist_"

# 32 bytes of urlsafe entropy. The prefix is not part of the entropy budget.
TOKEN_ENTROPY_BYTES = 32


def generate_machine_token() -> str:
    """Mint a permanent machine token.

    The plaintext exists only in this return value and the tool result that carries it to the
    user. Nothing stores, logs, or echoes it — only `hash_token` of it reaches the database.
    """
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)}"


def hash_token(token: str) -> str:
    """sha256 of the complete token, lowercase hex.

    The whole token including the prefix is hashed, so verification never has to parse or
    strip anything before comparing.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def matches_invite_code(presented: str, configured: SecretStr) -> bool:
    """Compare a presented bearer against the configured invite code in constant time.

    The configured code stays a SecretStr right up to this comparison. Unwrapping it earlier —
    into a plain attribute on the verifier, say — would put it back in every repr and traceback
    frame that touches the object, which is what SecretStr was chosen to prevent.

    Digests rather than the raw strings: compare_digest leaks length, and the invite code's
    length is operator-chosen. Machine tokens deliberately do NOT go through this — they are
    resolved by a unique index on token_hash, where nothing is compared in Python at all, and
    turning that into a constant-time scan of every row would be strictly worse.
    """
    return hmac.compare_digest(hash_token(presented),
                               hash_token(configured.get_secret_value()))
