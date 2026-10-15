import re
from pathlib import Path

BUNDLED = Path(__file__).parents[2] / "src" / "aistack" / "bundled"
TEXTS = {path.relative_to(BUNDLED).as_posix(): path.read_text(encoding="utf-8")
         for path in BUNDLED.rglob("*.md")}


def test_every_claude_mcp_add_names_the_server_before_its_options():
    """`-e` and `--header` take every value after them, so a name after one is read as one
    more value and `claude mcp add` fails with nothing added."""
    lines = [(path, line) for path, text in TEXTS.items()
             for line in text.splitlines() if "claude mcp add" in line]
    assert lines
    for path, line in lines:
        command = line[line.index("claude mcp add"):].split()
        options = [index for index, word in enumerate(command)
                   if word in {"-e", "--env", "-H", "--header"}]
        assert "aistack" in command, (path, line)
        assert not options or command.index("aistack") < options[0], (path, line)


def test_nothing_bundled_runs_mcp_get_which_prints_the_credential():
    """`claude mcp get aistack` prints the machine token or the database password in full.
    It may only be named to say never to run it."""
    warning = "Never run `claude mcp get aistack` or `codex mcp get aistack`"
    for path, text in TEXTS.items():
        assert len(re.findall(r"mcp get aistack", text)) == 2 * text.count(warning), path


def test_both_sync_skills_keep_the_codex_approvals_current():
    approvals = [f'tools.{tool}.approval_mode' for tool in
                 ("sync", "list_skills", "get_skill", "push_skill")]
    server = TEXTS["skills/sync-aistack/SKILL.md"]
    assert all(approval in server for approval in approvals)
    assert "connect codex" in TEXTS["local/sync-aistack/SKILL.md"]
