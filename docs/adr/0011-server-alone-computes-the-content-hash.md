# The server alone computes the canonical content hash

Status: accepted (amends ADR-0009: the framing is unchanged, the second implementation is removed)

`sync` receives, for every local skill, a map of relative path to the sha256 of that file's bytes. The server normalizes the paths and feeds them through the length-prefixed framing of ADR-0009 to get the canonical `content_hash`. The agent never computes that hash.

Why: ADR-0009 chose length-prefixed framing so that two implementations could agree byte for byte. The second implementation was never specified, and it has no good home. A model cannot compute sha256, so it needs a script; Python is not installed on a stock Windows machine, and a script per shell is three implementations of an 8-byte big-endian length prefix that must never drift. What every supported machine already has is a way to digest one file: `shasum -a 256`, `sha256sum`, or `Get-FileHash`. Sending those digests moves the framing to the one place that already implements it, and the agreement problem ADR-0009 solved carefully stops existing.

The cost is a larger `sync` argument: one path and one 64-character digest per file instead of one digest per skill. The reference corpus is 25 skills and 75 files, about 7,000 characters, and it is a copy of command output rather than generated content. A mistyped digest fails safe: the skill is reported as locally modified and the user is asked, which is the same answer sync gives for any content it does not recognize (ADR-0006).

Upload needs no agent-side digest at all. The server digests the bytes it received over the transfer URL (ADR-0010).

Rejected: a hashing script shipped by `setup-aistack` (three runtimes to keep in step, for a value the server can derive); sending file contents to `sync` (the bytes through the model, which ADR-0010 exists to avoid).
