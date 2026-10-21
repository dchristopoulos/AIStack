import plistlib
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace

import pytest

from aistack.bootstrap import computer_link, start_agent
from aistack.bootstrap.computer_link import LinkRefused
from aistack.bootstrap.start_agent import StartRefused
from aistack.services import server_sync

KEY = "github.com/maria/shop"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("AISTACK_HOME", str(tmp_path / "no-library"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return home


def _repository(path: Path, remote: str | None = "git@github.com:maria/shop.git") -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if remote:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote], check=True)
    return path.resolve()


@pytest.fixture
def shop(home, tmp_path):
    project = _repository(tmp_path / "shop")
    server_sync.remember_project(home, KEY, project)
    return project


# The links accepted ----------------------------------------------------------------------

def test_a_start_link_runs_start_in_the_folder_this_computer_reported(home, shop):
    command = computer_link.link_command(
        "aistack://start?agent=claude-code&project=github.com%2Fmaria%2Fshop&skills=tdd%2Ccode-review",
        home)

    assert command == ["start", "--agent=claude-code", f"--project={shop}",
                       "--skills=tdd,code-review"]


def test_a_sync_link_runs_sync_and_a_project_add_link_names_an_existing_folder(home, tmp_path):
    assert computer_link.link_command("aistack://sync", home) == ["sync"]
    assert computer_link.link_command(f"aistack://project-add?folder={tmp_path}", home) == [
        "project", "add", "--", str(tmp_path.resolve())]


# Every rejection ---------------------------------------------------------------------------

@pytest.mark.parametrize("link", [
    "https://start?agent=codex",
    "aistack:start",
    "aistack://run?command=rm",
    "aistack://Start?agent=codex&project=a/b&skills=tdd",
    "aistack://start/extra?agent=codex&project=a/b&skills=tdd",
    "aistack://start?agent=codex&project=a/b&skills=tdd#more",
    "aistack://start:80?agent=codex&project=a/b&skills=tdd",
    "aistack://me@start?agent=codex&project=a/b&skills=tdd",
    "aistack://start?agent=codex&project=a/b",
    "aistack://start?agent=codex&project=a/b&skills=tdd&prompt=hi",
    "aistack://start?agent=codex&agent=claude-code&skills=tdd",
    "aistack://start?agent=codex&project=a/b&skills=tdd&skills=x",
    "aistack://start?agent=codex;project=a/b;skills=tdd",
    "aistack://sync?now=1",
    "aistack://project-add",
    "aistack://start?agent=codex&project=a/b&skills=tdd\n",
    "aistack://start?agent=codex&project=a%2Fb%0A&skills=tdd",
    "aistack://start?agent=codex&project=a/b&skills=" + "a" * 5000,
    "aistack://start?agent=codex&project=a/b&skills=" + "a" * 2000,
    "aistack://sync\u202e",
])
def test_a_link_of_any_other_shape_is_refused(link, home):
    with pytest.raises(LinkRefused):
        computer_link.link_command(link, home)


@pytest.mark.parametrize("query, refusal", [
    ("agent=bash&project=github.com/maria/shop&skills=tdd", "AIStack starts"),
    ("agent=--help&project=github.com/maria/shop&skills=tdd", "AIStack starts"),
    ("agent=codex&project=github.com/maria/shop&skills=../etc", "skill name"),
    ("agent=codex&project=github.com/maria/shop&skills=tdd;rm%20-rf", "skill name"),
    ("agent=codex&project=github.com/maria/shop&skills=", "at least one"),
    ("agent=codex&project=/etc&skills=tdd", "not a project key"),
    ("agent=codex&project=Not%20A%20Key&skills=tdd", "not a project key"),
    ("agent=codex&project=github.com/maria/other&skills=tdd", "not a project this computer"),
])
def test_every_start_parameter_is_checked(query, refusal, home, shop):
    with pytest.raises(LinkRefused, match=refusal):
        computer_link.link_command(f"aistack://start?{query}", home)


@pytest.mark.parametrize("folder", ["relative/path", "/no/such/folder", "-rf"])
def test_project_add_takes_only_an_existing_absolute_folder(folder, home):
    with pytest.raises(LinkRefused, match="not a folder"):
        computer_link.link_command(f"aistack://project-add?folder={folder}", home)


def test_a_project_whose_recorded_folder_now_holds_another_repository_is_not_managed(home,
                                                                                    tmp_path):
    other = _repository(tmp_path / "other", "git@github.com:maria/other.git")
    server_sync.remember_project(home, KEY, other)

    with pytest.raises(LinkRefused, match="not a project this computer manages"):
        computer_link.link_command(
            f"aistack://start?agent=codex&project={KEY}&skills=tdd", home)


# The command ---------------------------------------------------------------------------------

def test_the_handler_opens_a_terminal_with_the_link_after_a_double_dash(home, monkeypatch):
    opened = []
    monkeypatch.setattr(start_agent, "open_terminal", lambda *call: opened.append(call))
    monkeypatch.setattr(computer_link.agent_config, "installed_program",
                        lambda: Path("/opt/aistack"))

    computer_link.run(["--new-terminal", "--", "aistack://sync"])

    assert opened == [(home, [str(Path("/opt/aistack")), "open", "--", "aistack://sync"])]
    with pytest.raises(SystemExit, match="did not act"):
        computer_link.run(["--new-terminal", "--", "--help"])


def test_a_start_link_hands_the_checked_arguments_to_start(home, shop, monkeypatch):
    started = []
    monkeypatch.setattr(start_agent, "run", started.append)

    computer_link.run([f"aistack://start?agent=codex&project={KEY}&skills=tdd"])

    assert started == [["--agent=codex", f"--project={shop}", "--skills=tdd"]]


def test_a_project_add_link_runs_project_add_on_the_folder(home, tmp_path, monkeypatch):
    from aistack.bootstrap import project_add

    added = []
    monkeypatch.setattr(project_add, "run", added.append)

    computer_link.run([f"aistack://project-add?folder={tmp_path}"])

    assert added == [["add", "--", str(tmp_path.resolve())]]


# Where a project is ------------------------------------------------------------------------

def test_start_finds_a_managed_project_by_the_folder_sync_reported(home, shop, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    assert start_agent.project_folder(KEY, elsewhere, home) == shop


def test_sync_forgets_a_project_the_server_no_longer_manages(home, shop):
    server_sync.remember_project(home, KEY, None)

    assert server_sync.reported_project(home, KEY) is None
    server_sync.remember_project(home, "Not A Key", shop)
    assert not (home / ".aistack" / "projects.json").read_text().count("Not A Key")


def test_with_no_known_folder_start_asks_for_one(home, tmp_path):
    project = _repository(tmp_path / "shop")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    assert start_agent.project_folder(KEY, elsewhere, home, ask=lambda _: str(project)) == project
    other = _repository(tmp_path / "other", "git@github.com:maria/other.git")
    with pytest.raises(StartRefused, match="not a folder of project"):
        start_agent.project_folder(KEY, elsewhere, home, ask=lambda _: str(other))


# Registration ------------------------------------------------------------------------------

# The macOS and Linux handlers, tested on any system: a POSIX path wherever the test runs.
PROGRAM = PurePosixPath("/Users/maria/.local/bin/aistack")


def _recording(answer=""):
    calls = []

    def run(command, **_):
        calls.append(command)
        if command[0] == "osacompile":
            # What osacompile leaves: an applet whose Info.plist names no URL type.
            calls.append(Path(command[3]).read_text())
            info = Path(command[2]) / "Contents" / "Info.plist"
            info.parent.mkdir(parents=True)
            info.write_bytes(plistlib.dumps({"CFBundleExecutable": "applet"}))
        return SimpleNamespace(returncode=0, stdout=answer, stderr="")
    return calls, run


def test_macos_registers_an_applet_with_the_url_type_with_launch_services(home):
    calls, run = _recording()

    assert computer_link.register(PROGRAM, home, "darwin", run) == computer_link.REGISTERED
    assert computer_link.register(PROGRAM, home, "darwin", run) == computer_link.REGISTERED

    app = home / "Applications" / "AIStack Link.app"
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleURLTypes"] == [{"CFBundleURLName": "AIStack computer link",
                                         "CFBundleURLSchemes": ["aistack"]}]
    assert info["LSUIElement"] is True
    assert calls[1] == ('on open location link\n\tdo shell script quoted form of '
                        f'"{PROGRAM}" & " open --new-terminal -- " & quoted form of link\n'
                        'end open location\n')
    assert calls[2] == ["codesign", "--force", "--sign", "-", str(app.with_name(
        ".aistack-link-staging.app"))]
    assert calls[3] == [computer_link.LSREGISTER, "-f", str(app)]
    assert sorted(path.name for path in app.parent.iterdir()) == ["AIStack Link.app"]
    assert computer_link.registered(PROGRAM, home, "darwin", run)
    assert not computer_link.registered(PurePosixPath("/elsewhere/aistack"), home, "darwin", run)


def test_windows_registers_the_current_users_class_with_the_link_after_a_double_dash(home):
    values = {}
    registry = SimpleNamespace(set=lambda key, name, value: values.__setitem__((key, name), value),
                               get=lambda key, name: values.get((key, name)))
    program = PureWindowsPath(r"C:\Users\maria\.local\bin\aistack.exe")

    assert computer_link.register(program, home, "win32", registry=registry) == \
        computer_link.REGISTERED

    assert values == {
        (r"Software\Classes\aistack", ""): "URL:AIStack computer link",
        (r"Software\Classes\aistack", "URL Protocol"): "",
        (r"Software\Classes\aistack\shell\open\command", ""):
            rf'"{program}" open -- "%1"',
    }
    assert computer_link.registered(program, home, "win32", registry=registry)


def test_linux_writes_a_desktop_handler_and_makes_it_the_default(home):
    calls, run = _recording(answer="aistack-link.desktop\n")

    assert computer_link.register(PROGRAM, home, "linux", run) == computer_link.REGISTERED

    entry = home / ".local" / "share" / "applications" / "aistack-link.desktop"
    assert f'Exec="{PROGRAM}" open --new-terminal -- %u\n' in entry.read_text()
    assert "MimeType=x-scheme-handler/aistack;\n" in entry.read_text()
    assert calls == [["xdg-mime", "default", "aistack-link.desktop", "x-scheme-handler/aistack"]]
    assert computer_link.registered(PROGRAM, home, "linux", run)
    assert not computer_link.registered(PROGRAM, home, "linux", _recording("firefox.desktop")[1])


@pytest.mark.parametrize("program", ['/opt/a"b/aistack', "/opt/$HOME/aistack", "/opt/a%1/aistack",
                                     "/opt/a\\b/aistack", "relative/aistack"])
@pytest.mark.parametrize("system", ["darwin", "linux"])
def test_a_program_path_a_handler_would_misread_is_not_registered(program, system, home):
    calls, run = _recording()

    assert "not registered" in computer_link.register(PurePosixPath(program), home, system, run)
    assert calls == []


def test_a_failed_registration_says_so_and_does_not_stop_setup(home):
    # The conftest's run refuses, as a computer without xdg-mime would.
    assert "not registered" in computer_link.register(PROGRAM, home, "linux")
    assert not computer_link.registered(PROGRAM, home, "linux")
