"""`aistack github` against a stand-in for the GitHub CLI: sign in once, then the private
repository is found or created, and nothing else is asked of the person."""

import sys
import textwrap

import pytest

from aistack.bootstrap import github_setup

pytestmark = pytest.mark.skipif(sys.platform == "win32",
                                reason="The stand-in gh is a script Windows cannot run.")

FAKE_GH = textwrap.dedent('''\
    #!{python}
    import pathlib, sys
    state = pathlib.Path({state!r})
    with open(state / "calls", "a") as calls:
        calls.write(" ".join(sys.argv[1:]) + "\\n")
    command = sys.argv[1:3]
    if sys.argv[1] == "--version":
        print("gh version 2.98.0")
    elif command == ["auth", "status"]:
        sys.exit(0 if (state / "signed_in").exists() else 1)
    elif command == ["auth", "login"]:
        print("! First copy your one-time code: AB12-CD34", flush=True)
    elif command == ["api", "user"]:
        print("maria")
    elif command == ["repo", "view"]:
        if not (state / "repo").exists():
            sys.exit(1)
        print((state / "repo").read_text())
    elif command == ["repo", "create"]:
        (state / "repo").write_text("true")
    ''')


@pytest.fixture(name="gh")
def gh_fixture(tmp_path, monkeypatch):
    state = tmp_path / "gh-state"
    state.mkdir()
    script = tmp_path / "gh"
    script.write_text(FAKE_GH.format(python=sys.executable, state=str(state)))
    script.chmod(0o755)
    monkeypatch.setattr(github_setup, "gh_command", lambda: str(script))
    monkeypatch.setattr(github_setup.webbrowser, "open", lambda url: None)
    monkeypatch.setattr(github_setup, "_WAIT_FOR_APPROVAL_SECONDS", 0.2)
    monkeypatch.setattr(github_setup, "_POLL_SECONDS", 0.05)
    return state


def test_a_first_run_shows_the_code_and_a_second_creates_the_private_repository(
        gh, tmp_path, capsys):
    home = tmp_path / ".aistack"

    assert github_setup.connect(home) == github_setup.WAITING
    assert "enter the code AB12-CD34" in capsys.readouterr().out

    # The person approves in the browser; the next run finds them signed in.
    (gh / "signed_in").touch()
    assert github_setup.connect(home) == github_setup.SIGNED_IN
    out = capsys.readouterr().out
    assert "AISTACK_LIBRARY_REPO=maria/aistack-library" in out
    assert "repo create maria/aistack-library --private" in (gh / "calls").read_text()


def test_a_second_computer_finds_the_repository_and_creates_nothing(gh, tmp_path, capsys):
    (gh / "signed_in").touch()
    (gh / "repo").write_text("true")

    assert github_setup.connect(tmp_path / ".aistack") == github_setup.SIGNED_IN
    assert "AISTACK_LIBRARY_REPO=maria/aistack-library" in capsys.readouterr().out
    assert "repo create" not in (gh / "calls").read_text()


def test_a_public_repository_of_that_name_is_never_used(gh, tmp_path, capsys):
    (gh / "signed_in").touch()
    (gh / "repo").write_text("false")

    assert github_setup.connect(tmp_path / ".aistack") == github_setup.FAILED
    out = capsys.readouterr().out
    assert "is public" in out and "AISTACK_LIBRARY_REPO=" not in out


def test_without_the_github_cli_it_says_how_to_install_it(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(github_setup, "gh_command", lambda: str(tmp_path / "no-gh"))

    assert github_setup.connect(tmp_path / ".aistack") == github_setup.FAILED
    assert "brew install gh" in capsys.readouterr().out
