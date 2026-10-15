# Changelog

One section per release, written when the release is cut, in the form of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/) below 1.0: a new patch release works beside the one before it, and a new minor (0.1 to 0.2) is one that older releases stop working with. Each minor's section opens with **Upgrade notes** that say what to do first.

The image tag `0.1` follows the releases of 0.1, and the package on PyPI is `aistack-mcp`. The tag pipeline publishes a release only when this file has a section for it, and uses that section as the GitHub Release's notes.

## 0.1.0 (2026-10-15)

The first release on PyPI and the first version-tagged image.

### Upgrade notes

- A server running an image from before this release upgrades in place at startup. Take a backup first (docs/OPERATING.md, Backups).
- Local mode installs with `uv tool install aistack-mcp` and updates itself within 0.1.

### Added

- Skills synced between a person's computers through their own Library, on a server, in a local SQLite file, in a GitHub repository, or in a PostgreSQL database.
- Teams and groups to share skills with, where a teammate's change is an offer to take, never an overwrite.
- The web dashboard, on a server and on `127.0.0.1` in local mode.
