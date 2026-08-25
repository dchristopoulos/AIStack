# Length-prefixed canonical content hash, not JSON

Status: accepted (reverses the JSON canonicalization recorded in `docs/DESIGN.md` §4 Versions before it was implemented)

The canonical `content_hash` is computed by feeding a single sha256 an unambiguous length-prefixed byte stream. Paths are normalized and validated, files are sorted by the unsigned UTF-8 bytes of the normalized path, and each file's exact bytes are digested. Then, for every file in order, the outer sha256 consumes:

1. the path's byte length as an unsigned 8-byte big-endian integer;
2. the path's UTF-8 bytes;
3. the raw 32-byte content digest.

`content_hash` is the lowercase hex of the outer digest. The full procedure, including path normalization rules, lives in `docs/DESIGN.md` §4 Versions.

Why: agent and server compute this independently and must agree byte for byte. JSON makes that agreement depend on two serializers matching each other, and conforming serializers legitimately differ in escaping and representation even when configured the same way. The earlier argument for JSON was that both sides already have a library, but the thing that must match is the bytes, not the data structure, and length prefixing makes the bytes unambiguous with no library at all: no field can be misread as part of the next one, and no separator needs escaping.

Pre-implementation decision. No `SKILL_VERSION` row exists yet, so nothing migrates.

The executable bit stays excluded from the hash for the reason already recorded in §4 Versions: Windows filesystems cannot carry it, so hashing it would give every Windows machine a permanent phantom conflict.

Rejected: ad-hoc JSON canonicalization (the agreement problem above); a canonical-JSON dependency such as JCS (a dependency on both sides of the wire, and every future harness adapter, to serialize two fields).
