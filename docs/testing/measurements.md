# Test measurements, October 2026

What the suite covered, what it cost, and which mutants on the trust boundaries it let through. Measured on 2026-10-17 at 1166ca3, macOS, Python 3.14.6, with the locked dependencies, on SQLite, without the browser tests (`--ignore=tests/ui`). The rules these numbers feed are in [strategy.md](strategy.md).

## Coverage

`coverage run --branch --source=src/aistack -m pytest --ignore=tests/ui`: 1435 passed, 23 skipped (the PostgreSQL half), 90% of statements and branches over 6440 statements. 77 of 117 files are fully covered.

Coverage is read here only for lines no test reaches (rule 2). The low numbers are mostly code that runs in a subprocess, which coverage does not follow without `COVERAGE_PROCESS_START`: `bootstrap/__main__.py` (25%), `services/library_move.py` (38%), `bootstrap/hardware.py` (42%). Those are reached by the CLI tests, just not measured.

Unreached lines on the trust-boundary modules:

| Module | Missed | What is never run |
|---|---|---|
| services/local_skills.py | 9 lines, 91% | Refusing a local skill over `MAX_FILE_COUNT` files or with a file over `MAX_FILE_BYTES` (115, 118, 124); the install retry after a rename race and the `Busy` it ends in (173 to 186); a stale staged `SKILL.md` in `refresh` (216). |
| services/library_log.py | 11 lines, 95% | Replay refusals for a log event naming a revision or a computer that is not valid (177, 449, 472, 511, 520); a removal of an unknown computer (335). |
| services/skill_archive.py | 4 lines, 97% | Malformed pax records: a non-numeric or non-positive length (198 to 204). |
| services/sync_service.py | 4 lines, 98% | `repository` that is not a list of short strings, or too long (303, 306); the `IntegrityError` path when two syncs record the same harness at once (395). |
| services/skill_validation.py | 4 lines, 98% | `origin` that is not text (123); `MAX_FILE_COUNT` in `refusal_from_listing` (176); frontmatter that `json.dumps` refuses (375). |
| mcp/auth/failure_limiter.py | 4 lines, 94% | Evicting the oldest key past `MAX_TRACKED_KEYS` (70); a window that empties a key (81 to 84). |
| mcp/routes/request_body.py | 1 line | An upload that stalls past its read timeout (32). |
| services/transfer_ticket.py | 1 line | A ticket claim that is not text (254). |

## The thirty slowest tests

`--durations=30`, same run (coverage adds roughly 10% to each):

| Seconds | Test |
|---|---|
| 7.6 | mcp/test_library_github.py::test_terminal_commands_find_the_library_the_agent_was_set_up_with |
| 6.1 | mcp/test_library_github.py::test_check_says_where_the_library_lives_or_what_is_wrong |
| 5.8 | mcp/test_library_github.py::test_a_computer_whose_clock_runs_ahead_does_not_win_over_a_newer_edit |
| 5.5 | mcp/test_library_github.py::test_computers_that_edited_one_skill_offline_agree_once_back |
| 5.2 | mcp/test_library_github.py::test_moving_a_library_to_github_keeps_its_history_placements_and_removals |
| 5.2 | db/test_engine.py::test_sqlite_waits_for_a_busy_writer_before_failing_with_a_sentence |
| 5.2 | mcp/test_reads_while_writing_over_http.py::test_a_write_that_waits_too_long_says_to_try_again[sqlite] |
| 4.9 | db/test_backup.py::test_the_commands_need_only_the_database_address |
| 4.9 | mcp/test_library_github.py::test_moving_here_from_github_keeps_the_library |
| 4.5 | mcp/test_library_github.py::test_a_github_library_exports_and_moves_by_copy_and_sync |
| 3.8 | bootstrap/test_agent_config.py::test_connect_checks_the_library_installs_the_skill_and_connects_codex |
| 3.8 | mcp/test_local_mode.py::test_export_writes_the_library_as_skill_folders[sqlite] |
| 3.5 | mcp/test_library_github.py::test_a_move_never_lands_in_a_repository_holding_another_library |
| 3.0 | mcp/test_library_github.py::test_a_skill_backed_up_on_one_computer_installs_on_another |
| 2.8 | mcp/test_library_github.py::test_the_agent_and_the_page_say_when_github_could_not_be_reached |
| 2.4 | mcp/test_library_github.py::test_changes_made_offline_go_out_with_the_next_push |
| 2.3 | mcp/test_library_github.py::test_a_library_its_log_cannot_rebuild_is_not_moved |
| 2.1 | mcp/test_local_mode.py::test_the_command_serves_over_stdio |
| 2.1 | bootstrap/test_agent_config.py::test_connect_after_a_move_follows_the_library_and_not_the_old_connection |
| 2.0 | db/test_backup.py::test_a_server_stopped_like_docker_stop_leaves_one_file_with_everything |
| 1.9 | mcp/test_library_github.py::test_a_log_from_a_newer_release_is_explained_through_the_agent |
| 1.8 | mcp/test_library_github.py::test_a_file_cannot_speak_for_another_computer |
| 1.8 | db/test_backup.py::test_postgresql_is_pointed_at_its_own_tools |
| 1.7 | mcp/test_local_mode.py::test_the_command_prints_local_setup_and_its_skill[sync-skill] |
| 1.7 | bootstrap/test_admin_cli.py::test_the_command_runs_as_aistack_admin[sqlite] |
| 1.7 | mcp/test_local_mode.py::test_sync_skill_writes_itself_into_a_skills_folder_as_utf8 |
| 1.7 | mcp/test_local_mode.py::test_the_command_prints_local_setup_and_its_skill[setup] |
| 1.6 | mcp/test_library_github.py::test_export_with_no_library_anywhere_creates_none |
| 1.6 | bootstrap/test_agent_config.py::test_the_hook_reminds_when_it_cannot_tell_and_never_fails_a_session |
| 1.6 | bootstrap/test_agent_config.py::test_connect_refuses_to_name_a_program_that_is_not_installed |

Total wall time is about 4 minutes 20 seconds; these thirty are about 100 seconds of it. Sixteen of them are `test_library_github.py`, which drives real `git` against local bare repositories, and most of the rest start `aistack` as a subprocess (about 1.6 seconds each, mostly interpreter and import time). The two 5-second tests wait out SQLite's 5-second busy timeout on purpose; they could shorten the timeout in the test engine instead of waiting the production one.

## Mutants on the trust boundaries

### How it was run

mutmut 3.8.0 runs on Python 3.14 on macOS. Two things had to be found first:

- Forked test processes crash on macOS when anything asks the system for proxy settings (`urllib.request.getproxies` reaches `_scproxy`, which is not fork-safe; httpx does this when a client is made). mutmut reports those mutants as "segfault": 1002 of 3273 in the first run. Running with `no_proxy='*'` keeps the lookup in the environment, and every one of them then ran normally.
- mutmut copies only `src/` and `tests/` into `mutants/`, and the documentation tests read `docs/` and the root files, so the stats run fails until those are listed in `also_copy`.

mutmut is not a project dependency; it was installed into a scratch copy of the repository with the locked versions. The configuration used, for the next measurement:

```toml
[tool.mutmut]
source_paths = ["src/"]
only_mutate = [
    "src/aistack/services/skill_archive.py",
    "src/aistack/services/skill_validation.py",
    "src/aistack/services/content_hash.py",
    "src/aistack/services/reconciliation.py",
    "src/aistack/services/sync_service.py",
    "src/aistack/services/visibility.py",
    "src/aistack/services/library_log.py",
    "src/aistack/services/local_skills.py",
    "src/aistack/mcp/auth/*",
    "src/aistack/mcp/routes/transfer.py",
    "src/aistack/mcp/routes/request_body.py",
]
also_copy = [".agents", ".claude", ".github", "AGENTS.md", "CHANGELOG.md", "CLAUDE.md", "CONTEXT.md",
             "Dockerfile", "README.md", "SECURITY.md", "compose.yaml", "compose.test.yaml", "docs", "scripts"]
pytest_add_cli_args_test_selection = ["tests", "--ignore=tests/ui"]
pytest_add_cli_args = ["-p", "no:cacheprovider", "-x", "-q"]
```

Run with `no_proxy='*' mutmut run --max-children 8`: about 35 minutes for 3273 mutants on an M-series laptop.

mutmut mutates only code inside functions, so `services/reconciliation.py`, whose policy is the module-level `_POLICY` table, produced no mutants. It was swept by hand instead: each of the 12 rows had its step replaced by every other step, and each option in an `ASK` row was dropped and had each of its two flags flipped, 90 mutants in all, each run against the reconciliation, sync, project-sync and MCP tests. All 90 were caught.

### Results

| Module | Mutants | Caught | Timed out | Survived, message text only | Survived, logic |
|---|---|---|---|---|---|
| mcp/auth (six files) | 303 | 249 | 0 | 26 | 28 |
| mcp/routes/request_body | 27 | 19 | 0 | 5 | 3 |
| mcp/routes/transfer | 52 | 47 | 0 | 2 | 3 |
| services/content_hash | 38 | 32 | 0 | 4 | 2 |
| services/library_log | 951 | 799 | 1 | 60 | 91 |
| services/local_skills | 197 | 143 | 0 | 26 | 28 |
| services/skill_archive | 273 | 181 | 4 | 43 | 45 |
| services/skill_validation | 444 | 314 | 0 | 85 | 45 |
| services/sync_service | 689 | 601 | 0 | 18 | 70 |
| services/visibility | 299 | 264 | 0 | 9 | 26 |
| services/reconciliation (by hand) | 90 | 90 | 0 | 0 | 0 |

A timeout counts as caught. "Message text only" means the mutant changes nothing but the wording or case of a string: those are left alone, because rule 1 says error text is UX, and tests pin what a sentence must contain, not every character. The 341 logic survivors are listed in [survivors-2026-10.txt](survivors-2026-10.txt), less one covered since.

### Equivalent mutants

Groups that change nothing observable, and need no test:

- An explicit `join(X, a == b)` condition replaced by nothing or `None`: SQLAlchemy infers the same condition from the single foreign key (visibility, sync_service).
- `.limit(1)` changed to `.limit(2)` or `None` under `session.scalar`, which takes the first row anyway; `"utf-8"` to `"UTF-8"`; `to_bytes(n, "big")` to `to_bytes(n)`, whose default is big-endian since Python 3.11.
- Changes to the `Elapsed: ...ms` arithmetic or to whole log messages in `verify_token` and `_log_reconciled`: the log line is not a contract (log safety is pinned by the `sanitized` and secret tests, which still pass).

### Survivors that are missing tests

The rest, grouped by what a missing test would have to show. A survivor is a candidate for a new test, not a list of current vulnerabilities; the test work that followed in October 2026 took them in this order, trust boundaries first.

Authorization and visibility:

1. **A download URL keeps working after its machine's token is rotated.** `_load_download` passing `token_prefix=None` survives (transfer, ADR-0027): the service-level check exists, but no test calls the download route with a ticket minted before a rotation.
2. **`team_skill` without `Team.name == team` survives**: no test has the same skill name in two of the caller's teams, so `get_skill(name, team)` could return the other team's copy.
3. **`my_project` without `Project.key == key` survives**: no test gives one person two projects and asks for the second.
4. **`required_my_skill(removed_too=True)` by default survives**: no test asks for a removed skill through a path that must not see it.
5. **`shows_membership` with `not in access.member` survives**: who belongs to a private group is shown wrongly with no test noticing.
6. **`memberships` without `known(Team.kind)` survives**: no test stores a team kind from a newer release and lists teams (ADR-0031).
7. **`sync_service._here` without the machine filter, and `_machine_harness` without `machine_id`, survive**: a project or harness recorded on another of the person's computers is taken as this one's.
8. **`_team_updates` without `Skill.archived.is_(False)` or without `Skill.name.in_(enabled_here)` survives**: offers for a removed skill, or for one not enabled on this computer, are never tested to be absent. `_removed` without its name filter survives too.

Push validation and archives:

9. **`_inspect_structure` with `offset =` instead of `offset +=`, or the size rounding negated, survives**: the walk from one header to the next is never shown to matter: no test puts a refused record (a link, a device, an oversized pax or long-name header) behind a member that a wrong offset would skip.
10. **Every boundary mutant in `_reject_layout_records` survives** (`find` to `rfind`, the start position dropped, `position = length`): no test pax header holds more than one record, and none has a zero or negative length.
11. **Size limits checked with `>` survive as `>=`** in `read_archive` (archive and total bytes), `_gunzipped`, `_inspect_structure` (long names, pax header), `skill_validation._validated_version`, `refusal_from_listing`, `sync_service._repository_names` and `_local_hashes`, `request_body.bounded_body`, and `local_skills.archive`: no test sends exactly the limit. `_gunzipped` also survives dropping its `max_length`, which is the decompression-bomb guard.
12. **`_measured` (frontmatter node budget and depth) survives most changes**: no test sits at the depth or node limit, so the YAML amplification guard is only known to refuse far-over inputs.
13. **`build_archive` survives changing the gzip `mtime`, the tar format, the sort key and the executable mode**: nothing pins that two builds of the same files are byte-identical, which local mode's export and hashing assume.

Local mode files:

14. **`local_skills.install` survives every `chmod` change, and `archive` survives `& 0o111` becoming `| 0o111`**: no test checks that an executable script installs executable and a plain file does not.
15. **`local_skills.remove` returning `True` for a skill that is not there, and `is_symlink() and exists()`, survive**; `observed` survives two of its three filters; `_swap_in`'s retry and `Busy` are never reached (also uncovered above).

Library log:

16. **Replay of project events is untested**: 36 survivors in `_apply_to_project`. Project event kinds are still in `_REPLAY_ONLY` (ADR-0026), and no test replays one.
17. **`append` survives storing its events as unpublished, and `<=` becoming `<`** on the ordering check; `catch_up` survives returning `True`; `Event.to_json` survives dropping `sort_keys` and `separators`, so nothing pins the canonical line format other computers read.
18. **`removed`, `pushed` and `apply` survive leaving fields out of the event** (name, os, origin, harness): replay tests compare skills, not the computers or the origin they carry.
19. **`_free_name` and `_remove_machine` survive dropping their `user_id` filter, and `_free_name` survives `while name not in taken`**: no test replays two computers with one name.

Auth and limits:

20. **`FailureLimiter` survives evicting the newest key instead of the oldest, `>` becoming `>=`, and every change to `retry_after`**: the eviction order and the `Retry-After` value are not checked.
21. **`verify_token` survives passing `None` as the failure kind, and `client_id=str(None)`**: nothing reads either.

## Other findings

- Two gaps found earlier were closed later in October: installs now flush files before the rename, and the real-GitHub contract test runs weekly outside the merge gate.

## Test speed follow-up, 2026-10-19

The two SQLite contention checks now set a 50 ms timeout on their test connections.
The connection-policy test still checks the five-second default. The printed sync skill
is checked in process; its file-writing command still runs as a real subprocess.

On macOS with Python 3.14.8, the five affected checks took 13.93 seconds before and
2.23 seconds after. Run the same group with:

```sh
poetry run pytest -q --durations=5 \
  tests/db/test_engine.py::test_sqlite_waits_for_a_busy_writer_before_failing_with_a_sentence \
  tests/mcp/test_reads_while_writing_over_http.py::test_a_write_that_waits_too_long_says_to_try_again \
  tests/mcp/test_local_mode.py::test_the_command_prints_local_setup_and_its_skill \
  tests/mcp/test_local_mode.py::test_sync_skill_writes_itself_into_a_skills_folder_as_utf8
```

Both contention checks still fail when the conversion to `Busy` is removed. The
in-process command check fails when its print is removed. No tests were deleted.
The slow Git-backed Library journeys keep separate repositories. Starting a computer
writes an event, even when the test's later calls only read.
