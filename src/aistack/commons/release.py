"""Which AIStack this is, in words a person can find again: a version on PyPI or an image tag.

Every build between two releases carries the same package version, so an image built from a
commit on main also names that commit: `0.1.0+g1a2b3c4` is the image tagged `sha-1a2b3c4`.
The database records this name (ADR-0024), and a refusal repeats it.
"""

import os
from importlib import metadata

PACKAGE = "aistack-mcp"

# What local mode says when its Library needs a newer release. serve_local starts that update
# at once (self_update), unless the person turned updates off.
UPDATE_AND_RESTART = ("AIStack updates itself to read it: restart your coding agent in a "
                      "minute. If this message comes back, run `uv tool upgrade aistack-mcp` "
                      "in a terminal, then restart your coding agent.")


def release() -> str:
    try:
        version = metadata.version(PACKAGE)
    except metadata.PackageNotFoundError:
        return "from a source checkout"
    # Set by the image build from the commit; empty in a release's image and on PyPI.
    commit = os.environ.get("AISTACK_BUILD_COMMIT", "").strip()
    return f"{version}+g{commit[:7]}" if commit else version
