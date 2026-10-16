# Security pass: archives, paths, installs and self-update

Step 43 of [PLAN.md](PLAN.md), 2026-10-17. The audit gave this area a light pass only. This one read `skill_archive.py`, `skill_validation.py`, `content_hash.py`, `local_skills.py`, the transfer routes, both sync skills' shell steps and `self_update.py`, and tried crafted inputs against them. Every case below is a test in the suite, named where it lives.

## Fixed

**Two installs of one skill at once could put a partial folder in place** (local mode). Every install staged into the same `.aistack-staging/<name>`. A second install of the same skill, from another agent session started at the same moment, discarded the first one's copy while it was being written, and the first then moved whatever was there into the skills folder, or failed. Each install now stages into a folder of its own and swaps it in by renames; a concurrent install that lands between the two renames is moved out in turn, and after five such losses the call says to try again. `tests/services/test_local_skills.py` pauses one install at the swap while another runs whole; with the shared staging folder it fails, with the fix the folder holds one whole revision and nothing is left beside it.

**A file named like a Windows short name could stand for another file of the skill.** NTFS gives a long name an alias such as `SCRIPT~1.SH`. A skill carrying both `script-for-review.sh` and `SCRIPT~1.SH` installs the second over the first on Windows only, so what a teammate reviewed (step 39's diff) is not what runs there. A path segment with a `~` and a digit before its first dot is now refused at push. Names that merely contain a `~` (`backup~.md`, `v1.0~beta.md`) are still accepted.

## Checked and holding

| Tried | What happens | Test |
|---|---|---|
| A right-to-left override in a name (`report‮gnp.sh`, read as `report.sh.png`) | Refused: not printable | `test_a_path_some_machine_could_not_hold_is_rejected` |
| A zero-width joiner hiding `.git` (`.g‍it/hooks/pre-commit`), which old HFS+ volumes fold to `.git` | Refused: not printable | same |
| `SKILL.md` and `skill.md`, `café.md` in NFC and NFD, the dotless `ı` against `i` | Refused as one file on a case-insensitive filesystem | `test_two_paths_a_case_insensitive_filesystem_would_merge_are_rejected` and neighbours |
| A pax global header whose `path` renames every member after it | Refused: they become one file | `test_a_global_pax_header_that_renames_every_member_is_refused` |
| A pax `path` record of `../outside.md`, `/etc/passwd`, `docs/../../x.md` | Refused: tarfile applies the record, and the name it produces is the one validated | `test_a_pax_path_that_leaves_the_skill_is_refused` |
| A pax `size` or `GNU.sparse` record, an oversized pax or long-name header, a pax header claiming gigabytes | Refused on the raw blocks before tarfile parses anything | existing tests in `test_skill_archive.py` |
| Links, devices, FIFOs, contiguous files | Refused: only regular files | existing |
| A skill named like the staging folder (`.aistack-staging`), `synced`, or a Windows device | Refused: a skill name is `[a-z0-9]+(-[a-z0-9]+)*`, and `synced` and device names are named exceptions | existing in `test_skill_validation.py` |
| A file inside a skill named `.aistack-staging/x` | Accepted, and harmless: it sits inside the skill's own folder | |
| A sync listing that holds a nested `.git` | Left out of the hash, as push leaves it out | step 40, `test_a_skill_folder_that_is_a_git_clone_is_current` |

**Content hashing.** `content_hash.py` frames each path and digest with a length prefix and sorts by bytes, so no two different file sets share a framing; push and sync both pass paths through `normalized_path` (NFC, `/`-separated) first, so a Windows and a macOS listing of the same files hash alike. Push and sync both call it and nothing else frames a hash.

**Local installs** re-validate and re-hash a stored archive before writing a byte (`local_skills.install`), so a tampered row in a shared database or a GitHub Library cannot install anything push would have refused or anything other than what was pushed.

## Self-update

`self_update.check_and_upgrade` runs only when the program is a uv tool install (`uv-receipt.toml` beside its interpreter), at most once a day, in a background thread, and only for a newer release of the same minor version. It reads the newest version from `https://pypi.org/pypi/aistack-mcp/json` with certificate checking on, then runs `uv tool upgrade aistack-mcp`, found on `PATH` or in uv's usual install folders, with a five-minute limit; a failure is logged and changes nothing. It runs nothing else and nothing from the Library or a server.

One gap, recorded and not fixed: the version check asks pypi.org, while `uv tool upgrade` installs whatever the index uv is configured with calls newest. On a computer whose uv points at a private mirror, a mirror holding a newer minor than pypi.org would be installed without the minor-version guard. Closing it means installing the exact version checked (`uv tool install aistack-mcp==<version>`), which also pins the receipt, so the manual `uv tool upgrade` the warning suggests stops moving; that trade is the owner's to make.

## Residual

- **Server mode's install steps share a stage folder too.** get_skill's description stages at `<skills>/.aistack-staging/<name>`, so two agent sessions installing one skill at the same moment can collide as local mode did. The agent runs those steps, so the fix is a sentence in the description (stage at a name of its own) rather than code; it waits for room in the description and for step 40d, which replaces these steps with a download per sync.
- **The NTFS short-name rule over-refuses** a few real names (`notes~2.md`). The sentence says what to rename.
