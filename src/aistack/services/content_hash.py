"""The canonical content hash of a skill revision: the only implementation (ADR-0011).

Push feeds it the digests of the bytes it received; sync feeds it the digests the agent sent.
Both must land on the same value for the same files, so everything that could differ between
them (separators, Unicode form, ordering, framing) is settled here and nowhere else.
"""

import hashlib
import unicodedata
from collections.abc import Mapping

DIGEST_HEX_LENGTH = 64

# The path's byte length, as an unsigned 8-byte big-endian integer (ADR-0009).
_LENGTH_PREFIX_BYTES = 8


def file_digest(content: bytes) -> str:
    """sha256 of a file's exact bytes: no newline translation, no BOM stripping."""
    return hashlib.sha256(content).hexdigest()


def normalized_path(path: str) -> str:
    """One spelling per file, whichever operating system named it.

    Windows reports `scripts\\run.sh`, `find` reports `./scripts/run.sh`, and macOS hands back
    filenames in a decomposed Unicode form. All three must hash as `scripts/run.sh` in NFC.
    """
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return unicodedata.normalize("NFC", path)


def canonical_content_hash(digests: Mapping[str, str]) -> str:
    """Hash `{normalized path: sha256 hex}` with length-prefixed framing (ADR-0009).

    Raises ValueError when a digest is not sha256 hex. Push never hits that, because it
    computed the digests itself; sync does, and treats it as content it does not recognize.
    """
    outer = hashlib.sha256()
    # Sorted by the path's UTF-8 bytes, never by a locale: the order is part of the hash.
    for path_bytes, digest in sorted((path.encode("utf-8"), digest)
                                     for path, digest in digests.items()):
        if len(digest) != DIGEST_HEX_LENGTH:
            raise ValueError("A file digest must be 64 hexadecimal characters.")
        outer.update(len(path_bytes).to_bytes(_LENGTH_PREFIX_BYTES, "big"))
        outer.update(path_bytes)
        outer.update(bytes.fromhex(digest))
    return outer.hexdigest()
