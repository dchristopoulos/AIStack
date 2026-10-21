"""What `aistack sync` does with a managed project's own files (ADR-0036, ADR-0038).

Three things, each only after the person asked for it on the page:
- a ticked file's text is uploaded when its hash changed, so the page shows what is here;
- an edit made on the page for this computer is written into the working copy, only while
  the file still has the text the edit started from, and otherwise the person is asked;
- an edit committed on the page is shared: a commit holding only that file, made on a
  temporary index from the branch's upstream commit, is pushed to a new branch, and a pull
  request is opened with `gh` when it is signed in. The person's working tree, index, and
  branches are never touched, and nothing is committed to the branch they are on.

git and gh run without a shell, with every value an argument of its own. Their output is
never echoed: a push's error can carry a remote's credentials.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import httpx

from aistack.commons.exceptions import AIStackError, ValidationError
from aistack.db.models.rule import RULE_TEXT_MAX_BYTES
from aistack.services import agent_files, projects, rule_files
from aistack.services.project_file_service import validated_path

EDIT_CHOICES = ("write", "cancel")
_REGULAR_FILE_MODES = ("100644", "100755")
_GIT_TIMEOUT = 30
_NETWORK_TIMEOUT = 120


class ShareFailed(AIStackError):
    """Why an edit was not shared; the edit stays committed on the page for the next sync."""


async def carry_out(http, top: Path, ticked: list[dict], edits: list[dict],
                    choices: dict[str, str], report: dict) -> None:
    """Write and share the edits waiting for this computer, then upload the ticked files
    that changed, adding what happened to the rules `report`."""
    report.setdefault("edit_questions", [])
    try:
        tracked = _tracked(top)
    except (OSError, subprocess.SubprocessError, ShareFailed):
        report["failures"].append(f"AIStack could not read the git state of {top}, so its "
                                  "files were not synced.")
        return
    for edit in edits:
        try:
            relative, target = _tracked_file(top, edit.get("path"), tracked)
            if edit.get("note") is None:
                await _write(http, top, relative, target, edit, choices, report)
            else:
                await _share(http, top, relative, edit, report)
        except (OSError, httpx.HTTPError, UnicodeDecodeError, subprocess.SubprocessError,
                KeyError, TypeError, ValueError):
            report["failures"].append(f"Could not carry out the edit of "
                                      f"{edit.get('path')!s:.200} from the page. Sync again to "
                                      "retry.")
        except AIStackError as error:
            report["failures"].append(error.message)
    for file in ticked:
        try:
            relative, target = _tracked_file(top, file.get("path"), tracked)
            content = rule_files.read(target)
            if content is None or rule_files.digest(content) == file.get("content_hash"):
                continue
            if len(content) > RULE_TEXT_MAX_BYTES:
                report["failures"].append(f"{relative} is larger than 64 KiB, so the page does "
                                          "not show its current text.")
                continue
            content.decode("utf-8")
            response = await http.put(file["upload_url"], content=content)
            result = response.json()
            if "error" in result:
                report["failures"].append(f"Did not send {relative} to the page: "
                                          f"{result['error']}")
            elif not result.get("saved"):
                lines = ", ".join(str(line) for line in result.get("credential_lines", []))
                report["failures"].append(f"Did not send {relative} to the page: line {lines} "
                                          "looks like it holds a credential.")
            else:
                report["completed"].append(f"Sent the current text of {relative} to the page.")
        except UnicodeDecodeError:
            report["failures"].append(f"{file.get('path')!s:.200} is not UTF-8 text, so the "
                                      "page does not show it.")
        except (OSError, httpx.HTTPError, KeyError, TypeError, ValueError):
            report["failures"].append(f"Could not send {file.get('path')!s:.200} to the page. "
                                      "Sync again to retry.")
        except AIStackError as error:
            report["failures"].append(error.message)


def markdown_files(top: Path) -> list[dict]:
    """What `aistack project add` sends: every agent's file the table knows and every other
    Markdown file git tracks, by path and size, never their text. A file missing from the
    working tree, or a link, is left out."""
    tracked = sorted(_tracked(top))
    agents = agent_files.all_readers(tracked)
    listed = []
    for relative in tracked:
        if relative not in agents and not relative.endswith(".md"):
            continue
        try:
            validated_path(relative)
        except ValidationError:
            continue
        target = top.joinpath(*relative.split("/"))
        if target.is_symlink() or not target.is_file():
            continue
        listed.append({"path": relative, "size": target.stat().st_size})
    return listed


def _tracked(top: Path) -> set[str]:
    return {path for path in _git(top, "ls-files", "-z").decode("utf-8").split("\0") if path}


def _tracked_file(top: Path, path: object, tracked: set[str]) -> tuple[str, Path]:
    """A file git tracks in this project, which the server named. Nothing else in a
    repository is ever read or written here."""
    relative = validated_path(path)
    if relative not in tracked:
        raise ValidationError(f"git does not track {relative} in {top}, so AIStack left it "
                              "alone.")
    target = top.joinpath(*relative.split("/"))
    if target.is_symlink() or not rule_files.inside(top, target.parent):
        raise ValidationError(f"{relative} leads outside the project, so AIStack left it "
                              "alone.")
    return relative, target


async def _edit_text(http, edit: dict) -> bytes:
    response = await http.get(edit["url"])
    if response.status_code != 200:
        raise ValidationError(_refusal(response, "The edit could not be fetched."))
    content = response.content
    if rule_files.digest(content) != edit["content_hash"]:
        raise ValidationError("The edit arrived changed, so it was not used. Sync again.")
    return content


async def _report(http, edit: dict, outcome: str, address: str | None = None) -> None:
    response = await http.post(edit["url"], json={"outcome": outcome,
                                                  "pull_request_url": address})
    if response.status_code != 200:
        raise ValidationError(_refusal(response, "The page was not told what became of the "
                                                 "edit."))


def _refusal(response, fallback: str) -> str:
    try:
        return str(response.json()["error"])
    except (ValueError, KeyError, TypeError):
        return fallback


async def _write(http, top: Path, relative: str, target: Path, edit: dict,
                 choices: dict[str, str], report: dict) -> None:
    key = f"repository:{relative}"
    observed = rule_files.read(target)
    here = None if observed is None else rule_files.digest(observed)
    choice = choices.get(key)
    if here == edit["content_hash"]:
        await _report(http, edit, "written")
        return
    if choice == "cancel":
        await _report(http, edit, "cancelled")
        report["completed"].append(f"Cancelled the edit of {relative} from the page; "
                                   f"{target} is as it was.")
        return
    if here != edit["base_hash"] and choice != "write":
        if choice is not None:
            report["failures"].append(f"'{choice}' is not an answer to {key}; it offers "
                                      f"{', '.join(EDIT_CHOICES)}.")
        report["edit_questions"].append({"key": key, "file": str(target),
                                         "options": list(EDIT_CHOICES)})
        return
    content = await _edit_text(http, edit)
    if not rule_files.replace(target, content, observed):
        report["failures"].append(f"{target} changed during sync, so the edit from the page "
                                  "was not written. Sync again.")
        return
    await _report(http, edit, "written")
    report["completed"].append(f"Wrote the edit of {relative} from the page into {target}. "
                               "Commit… on the page shares it as a pull request.")


async def _share(http, top: Path, relative: str, edit: dict, report: dict) -> None:
    content = await _edit_text(http, edit)
    branch = branch_name(relative, edit["content_hash"])
    address, opened = share(top, relative, content, edit["note"], branch)
    await _report(http, edit, "shared", address)
    if opened:
        report["completed"].append(f"Shared the edit of {relative} as pull request {address}.")
    elif address:
        report["completed"].append(f"Pushed the edit of {relative} to branch {branch}. Open "
                                   f"the pull request at {address}")
    else:
        report["completed"].append(f"Pushed the edit of {relative} to branch {branch}. Open a "
                                   "pull request from it where the repository is kept.")


def branch_name(relative: str, content_hash: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", relative.lower()).strip("-")[:40].strip("-") or "file"
    return f"aistack/{slug}-{content_hash[:8]}"


def share(top: Path, relative: str, content: bytes, note: str,
          branch: str) -> tuple[str | None, bool]:
    """Commit `content` as `relative` on a new branch and push it, then open a pull request.
    Returns the pull request's address, or the address that opens one, and whether `gh`
    opened it.

    The commit's parent is the commit the person's branch tracks upstream, or the one they
    are on when it tracks none, so only this file differs from where the pull request goes.
    It is built on a temporary index: the working tree, the index and every local branch
    stay as they were.
    """
    current = _git(top, "symbolic-ref", "-q", "--short", "HEAD", check=False).decode().strip()
    remote = base = None
    if current:
        remote = _config(top, f"branch.{current}.remote")
        merge = _config(top, f"branch.{current}.merge")
        base = merge.removeprefix("refs/heads/") if merge else None
    remotes = _git(top, "remote").decode().split()
    if remote not in remotes:
        remote, base = ("origin" if "origin" in remotes else (remotes[0] if remotes else None),
                        None)
    if remote is None:
        raise ShareFailed(f"{top} has no remote to push a branch to, so the edit of {relative} "
                          "was not shared.")
    if branch in (current, base):
        raise ShareFailed(f"The branch {branch} is the one you are on, so nothing was pushed.")
    upstream = _git(top, "rev-parse", "-q", "--verify", "@{upstream}^{commit}",
                    check=False).decode().strip()
    parent = upstream if base and upstream else _git(top, "rev-parse", "--verify",
                                                      "HEAD^{commit}").decode().strip()

    listed = _git(top, "ls-tree", "-z", parent, "--", relative).decode().split("\0")[0]
    mode = listed.split(" ", 1)[0] if listed else "100644"
    if mode not in _REGULAR_FILE_MODES:
        raise ShareFailed(f"{relative} is not a plain file in git, so it was not shared.")
    with tempfile.TemporaryDirectory(prefix="aistack-share-") as folder:
        # A temporary index: the person's own index is never read or written.
        index = {"GIT_INDEX_FILE": str(Path(folder) / "index")}
        blob = _git(top, "hash-object", "-w", "--stdin", f"--path={relative}",
                    input=content).decode().strip()
        _git(top, "read-tree", parent, env=index)
        _git(top, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{relative}", env=index)
        tree = _git(top, "write-tree", env=index).decode().strip()
    changed = _git(top, "diff-tree", "-r", "-z", "--name-only", "--no-commit-id", parent,
                   tree).decode().split("\0")
    if [path for path in changed if path] != [relative]:
        raise ShareFailed(f"The edit of {relative} is what the branch already holds, so there "
                          "was nothing to share.")
    subject, _, body = note.strip().partition("\n")
    message = subject.strip() + ("\n\n" + body.strip() if body.strip() else "") + "\n"
    commit = _git(top, "commit-tree", tree, "-p", parent, "-F", "-",
                  input=message.encode("utf-8")).decode().strip()
    # A new branch on the remote and nothing else: no local ref moves, and never a force.
    _git(top, "push", "--quiet", remote, f"{commit}:refs/heads/{branch}",
         timeout=_NETWORK_TIMEOUT, failure="The branch could not be pushed. Check that you "
                                           "can push to this repository, then sync again.")
    opened = _gh_pull_request(top, branch, base, subject.strip(), body.strip())
    if opened:
        return opened, True
    url = _config(top, f"remote.{remote}.url")
    key = None
    try:
        key = projects.project_key(url) if url else None
    except ValidationError:
        pass
    if key and key.startswith("github.com/"):
        return f"https://{key}/pull/new/{branch}", False
    return (f"https://{key}" if key else None), False


def _gh_pull_request(top: Path, branch: str, base: str | None, title: str,
                     body: str) -> str | None:
    gh = shutil.which("gh")
    if gh is None:
        return None
    environment = os.environ | {"GH_PROMPT_DISABLED": "1", "NO_COLOR": "1"}
    try:
        if subprocess.run([gh, "auth", "status"], cwd=top, capture_output=True,
                          env=environment, timeout=_GIT_TIMEOUT).returncode:
            return None
        arguments = [gh, "pr", "create", "--head", branch, "--title", title,
                     "--body", body or title]
        if base:
            arguments += ["--base", base]
        done = subprocess.run(arguments, cwd=top, capture_output=True, text=True,
                              env=environment, timeout=_NETWORK_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.findall(r"https://\S+", done.stdout) if done.returncode == 0 else []
    return found[-1] if found else None


def _config(top: Path, name: str) -> str | None:
    value = _git(top, "config", "--get", name, check=False).decode().strip()
    return value or None


def _git(top: Path, *arguments: str, env: dict | None = None, input: bytes | None = None,
         timeout: int = _GIT_TIMEOUT, check: bool = True,
         failure: str | None = None) -> bytes:
    done = subprocess.run(
        ["git", "-C", str(top), *arguments],
        capture_output=True,
        input=input,
        env=os.environ | {"GIT_TERMINAL_PROMPT": "0"} | (env or {}),
        timeout=timeout,
    )
    if check and done.returncode:
        raise ShareFailed(failure or f"git could not {arguments[0]} in {top}, so the edit was "
                                     "not shared. If git asks for your name and email, set "
                                     "them, then sync again.")
    return done.stdout
