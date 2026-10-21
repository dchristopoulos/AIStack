import json
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from aistack.bootstrap import start_agent
from aistack.bootstrap.start_agent import RECIPES, StartRefused
from aistack.commons.exceptions import ValidationError


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(start_agent.shutil, "which", lambda name: f"/usr/bin/{name}")
    return home


def _skill(folder: Path, name: str, declared: str | None = None) -> None:
    (folder / name).mkdir(parents=True)
    (folder / name / "SKILL.md").write_text(
        f"---\nname: {declared or name}\ndescription: A skill.\n---\nBody\n", encoding="utf-8")


def _repository(path: Path, remote: str | None = "git@github.com:maria/shop.git") -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if remote:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote], check=True)
    return path.resolve()


def _prompt_input(shown) -> str:
    listing = "".join(f"- {name}: Does {name}. (file: r0/{name}/SKILL.md)\n" for name in shown)
    return json.dumps([{"type": "message", "content": [{"type": "input_text", "text":
        f"<skills_instructions>\n### Available skills\n{listing}</skills_instructions>"}]}])


def _fake_codex(available, version="codex-cli 0.163.0", ignores_flags=False):
    """Codex as far as the recipe sees it: a version, and the skills a set of flags leaves."""
    calls = []

    def run(command, **options):
        calls.append((command, options))
        if command[1] == "--version":
            return SimpleNamespace(returncode=0, stdout=version, stderr="")
        rules = next(part for part in command if part.startswith("--config=skills.config="))
        off = set(re.findall(r"name='([^']+)',enabled=false", rules))
        return SimpleNamespace(returncode=0, stderr="", stdout=_prompt_input(
            sorted(available if ignores_flags else set(available) - off)))
    return calls, run


def _fake_claude(version="2.1.241 (Claude Code)"):
    return lambda command, **_: SimpleNamespace(returncode=0, stdout=version, stderr="")


def _settings(command: list[str]) -> dict:
    return json.loads(command[1].removeprefix("--settings="))


def _started(recipe, folder, chosen, run):
    started, files = [], []

    def execute(command, where):
        # On Windows the settings are a file removed when the agent exits: read it while the
        # agent runs, and check after that it is gone.
        if os.name == "nt" and command[1].startswith("--settings="):
            files.append(Path(command[1].removeprefix("--settings=")))
            command = [command[0], "--settings=" + files[0].read_text(encoding="utf-8")]
        started.append((command, where))

    start_agent.start(recipe, folder, chosen, confirm=False, run=run, execute=execute)
    assert not any(file.exists() for file in files)
    return started[0]


# Skill names ---------------------------------------------------------------------------

def test_the_chosen_skills_are_checked_with_the_skill_name_rule_and_kept_once():
    assert start_agent.chosen_skills("tdd, code-review,tdd") == ("tdd", "code-review")
    for wrong in ("Code_Review", "../x", "a,,b", "", "synced"):
        with pytest.raises(ValidationError):
            start_agent.chosen_skills(wrong)


def test_an_unknown_agent_is_refused_by_name(capsys):
    with pytest.raises(SystemExit):
        start_agent.run(["--agent", "gemini", "--skills", "tdd"])
    assert "invalid choice: 'gemini'" in capsys.readouterr().err


# Claude Code ---------------------------------------------------------------------------

def test_claude_code_turns_off_every_other_skill_by_name_and_the_bundled_ones(home, tmp_path):
    project = _repository(tmp_path / "shop")
    _skill(home / ".claude" / "skills", "tdd")
    _skill(home / ".claude" / "skills", "wizard", declared="wizard-two")
    _skill(project / ".claude" / "skills", "deploy")
    _skill(project / "apps" / "web" / ".claude" / "skills", "nested")
    (home / ".claude" / "skills" / "synced").mkdir()

    command, folder = _started(RECIPES["claude-code"], project, ("tdd",), _fake_claude())

    assert folder == project
    assert command[0] == "/usr/bin/claude"
    assert len(command) == 2 and command[1].startswith("--settings=")
    assert _settings(command) == {
        "skillOverrides": {"deploy": "off", "nested": "off", "wizard": "off",
                           "wizard-two": "off"},
        "disableBundledSkills": True,
    }


def test_claude_code_turns_off_claude_ai_skills_from_the_release_that_reads_them(
        home, tmp_path):
    project = _repository(tmp_path / "shop")
    _skill(home / ".claude" / "skills", "tdd")

    command, _ = _started(RECIPES["claude-code"], project, ("tdd",),
                          _fake_claude("2.1.275 (Claude Code)"))

    assert _settings(command)["syncClaudeAiSkills"] is False


def test_a_skill_not_on_this_computer_is_refused_before_anything_starts(home, tmp_path):
    project = _repository(tmp_path / "shop")
    _skill(home / ".claude" / "skills", "tdd")

    with pytest.raises(StartRefused, match="research is not on this computer"):
        _started(RECIPES["claude-code"], project, ("tdd", "research"), _fake_claude())


@pytest.mark.parametrize("agent, output, found", [
    ("claude-code", "2.1.168 (Claude Code)", "Claude Code 2.1.168 is installed"),
    ("codex", "codex-cli 0.162.9", "Codex 0.162.9 is installed"),
])
def test_an_older_agent_is_named_with_the_version_found(agent, output, found):
    run = lambda command, **_: SimpleNamespace(returncode=0, stdout=output, stderr="")  # noqa: E731

    with pytest.raises(StartRefused, match=found):
        start_agent.installed(RECIPES[agent], run)


def test_a_missing_agent_says_which_command_was_not_found(monkeypatch):
    monkeypatch.setattr(start_agent.shutil, "which", lambda _: None)

    with pytest.raises(StartRefused, match="`codex` command was not found"):
        start_agent.installed(RECIPES["codex"], _fake_claude())


# Codex -----------------------------------------------------------------------------------

def test_codex_starts_with_the_flags_its_own_check_confirmed(home, tmp_path):
    project = _repository(tmp_path / "shop")
    _skill(home / ".agents" / "skills", "tdd")
    _skill(project / ".agents" / "skills", "deploy")
    calls, run = _fake_codex({"tdd", "deploy", "pdf:pdf"})

    command, folder = _started(RECIPES["codex"], project, ("tdd",), run)

    assert folder == project
    assert command == [
        "/usr/bin/codex", "--no-daemon", "--config=skills.bundled.enabled=false",
        "--config=skills.config=[{name='deploy',enabled=false},{name='pdf:pdf',enabled=false},"
        "{name='tdd',enabled=true}]",
    ]
    checks = [(each, options) for each, options in calls if each[1] == "debug"]
    # The plugin skill showed in the first check, so a second ran with it turned off too.
    assert len(checks) == 2
    assert checks[-1][0] == ["/usr/bin/codex", "debug", "prompt-input", *command[2:]]
    assert checks[-1][1]["cwd"] == project


def test_codex_that_ignores_the_flags_is_not_started(home, tmp_path):
    project = _repository(tmp_path / "shop")
    _skill(home / ".agents" / "skills", "tdd")
    _skill(home / ".agents" / "skills", "wizard")
    _, run = _fake_codex({"tdd", "wizard"}, ignores_flags=True)

    with pytest.raises(StartRefused, match="Codex still shows wizard"):
        _started(RECIPES["codex"], project, ("tdd",), run)


def test_codex_that_does_not_show_a_chosen_skill_is_not_started(home, tmp_path):
    project = _repository(tmp_path / "shop")
    _skill(home / ".agents" / "skills", "tdd")
    _, run = _fake_codex(set())

    with pytest.raises(StartRefused, match="Codex does not show tdd"):
        _started(RECIPES["codex"], project, ("tdd",), run)


def test_codex_output_that_is_not_json_stops_the_check(home, tmp_path):
    project = _repository(tmp_path / "shop")
    _skill(home / ".agents" / "skills", "tdd")

    def run(command, **_):
        return SimpleNamespace(returncode=0, stderr="",
                               stdout="codex-cli 0.163.0" if command[1] == "--version" else "?")

    with pytest.raises(StartRefused, match="did not print the JSON"):
        _started(RECIPES["codex"], project, ("tdd",), run)


def test_the_listing_is_read_as_codex_prints_it():
    rendered = json.loads(_prompt_input(["probe-one", "documents:documents"]))
    rendered[0]["content"][0]["text"] += "\n### How to use skills\n- Discovery: not a skill\n"

    assert start_agent.shown_skills(rendered) == {"probe-one", "documents:documents"}


# The project -----------------------------------------------------------------------------

def test_the_project_is_the_current_folders_repository(home, tmp_path):
    project = _repository(tmp_path / "shop")
    (project / "src").mkdir()

    assert start_agent.project_folder(None, project / "src", home) == project


def test_a_project_named_by_folder_or_by_its_key(home, tmp_path):
    project = _repository(tmp_path / "shop")

    assert start_agent.project_folder(str(project), tmp_path, home) == project
    assert start_agent.project_folder("github.com/maria/shop", project, home) == project


def test_a_project_this_computer_has_no_folder_of_is_refused(home, tmp_path, monkeypatch):
    project = _repository(tmp_path / "shop")
    monkeypatch.setenv("AISTACK_HOME", str(tmp_path / "no-library"))

    with pytest.raises(StartRefused, match="no folder of project 'github.com/maria/other'"):
        start_agent.project_folder("github.com/maria/other", project, home)
    with pytest.raises(ValidationError):
        start_agent.project_folder("Not A Key", project, home)


def test_a_folder_outside_a_repository_is_not_a_project(home, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    with pytest.raises(StartRefused, match="not in a project"):
        start_agent.project_folder(None, plain, home)
    with pytest.raises(StartRefused, match="not in a git repository"):
        start_agent.project_folder(str(plain), tmp_path, home)


# A new terminal --------------------------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="a shell script is the POSIX path")
@pytest.mark.parametrize("platform, opener", [
    ("darwin", ["open", "-a", "Terminal"]),
    ("linux", ["x-terminal-emulator", "-e"]),
])
def test_a_new_terminal_runs_the_same_command_quoted_for_the_shell(platform, opener, tmp_path,
                                                                   monkeypatch):
    monkeypatch.setattr(start_agent.sys, "platform", platform)
    folder = tmp_path / "it's a shop"
    folder.mkdir()
    command = ["/opt/aistack", "start", "--agent=codex", f"--project={folder}",
               "--skills=tdd"]
    opened = []

    start_agent.open_terminal(folder, command, popen=lambda argv, **_: opened.append(argv))

    assert opened[0][:-1] == opener
    script = Path(opened[0][-1]).read_text()
    lines = script.splitlines()
    assert lines[:2] == ["#!/bin/sh", 'rm -f "$0"']
    assert subprocess.run(["sh", "-c", f"printf '%s\\n' {lines[3]}"], capture_output=True,
                          text=True).stdout.splitlines() == command
    Path(opened[0][-1]).unlink()


@pytest.mark.skipif(os.name == "nt", reason="a shell script is the POSIX path")
def test_without_a_terminal_program_it_says_what_to_run(tmp_path, monkeypatch):
    monkeypatch.setattr(start_agent.sys, "platform", "linux")
    monkeypatch.setattr(start_agent.shutil, "which", lambda _: None)

    with pytest.raises(StartRefused, match="Run this in a terminal instead"):
        start_agent.open_terminal(tmp_path, ["/opt/aistack", "start"], popen=None)
