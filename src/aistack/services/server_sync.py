"""Execute the server's reconciliation report without deciding its questions (ADR-0035)."""

import asyncio
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from aistack.bundled import SYNC_SKILL_NAME, sync_skill_document
from aistack.commons.exceptions import AIStackError, ValidationError
from aistack.commons.text import sanitized
from aistack.db.models.harness import Harness
from aistack.services import local_skills
from aistack.services.server_connection import Connection, client
from aistack.services.skill_archive import read_archive
from aistack.services.skill_validation import validated_skill, validated_skill_name

SYNC_TIMEOUT = 150


def _git(top: Path, *arguments: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(top), *arguments],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if done.returncode:
        raise ValidationError("AIStack could not inspect this project's git state. Repair it before syncing its skills.")
    return done.stdout.strip()


def current_project(cwd: Path, home: Path) -> tuple[Path, dict] | None:
    try:
        top = Path(_git(cwd, "rev-parse", "--show-toplevel")).resolve()
        if top == home.resolve():
            return None
        remotes = _git(top, "remote").splitlines()
        remote = None
        if remotes:
            chosen = "origin" if "origin" in remotes else remotes[0]
            remote = _git(top, "config", "--get", f"remote.{chosen}.url")
            if "://" in remote:
                parts = urlsplit(remote)
                remote = urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[-1], query="", fragment=""))
        return top, {"path": str(top), "remote": remote}
    except (OSError, subprocess.SubprocessError, ValidationError, ValueError):
        return None


def _repository(top: Path, relative: str) -> set[str]:
    paths = []
    for flags in (("--cached",), ("--others", "--exclude-standard", "--directory")):
        paths.extend(_git(top, "ls-files", "-z", *flags, "--", relative).split("\0"))
    return {path[len(relative) + 1:].split("/")[0] for path in paths if path.startswith(relative + "/")}


def _project_destination(top: Path, folder: Path) -> None:
    if not folder.resolve().is_relative_to(top.resolve()):
        raise ValidationError("This project's skills folder leads outside the project. Nothing was installed there.")


def _ignore_install(top: Path, folder: Path, name: str) -> None:
    _project_destination(top, folder)
    relative = folder.relative_to(top).as_posix()
    if name in _repository(top, relative):
        raise ValidationError(f"The repository holds '{name}'. Nothing was installed over it.")
    exclude = Path(_git(top, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"))
    exclude.parent.mkdir(parents=True, exist_ok=True)
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    for entry in (f"/{relative}/{name}/", f"/{relative}/{local_skills.STAGING_FOLDER}/"):
        if entry not in text.splitlines():
            text = text.rstrip("\n") + "\n" + entry + "\n"
    exclude.write_text(text, encoding="utf-8")
    _git(top, "check-ignore", "-q", f"{relative}/{name}/")


async def sync_computer(connection: Connection, home: Path, cwd: Path) -> list[dict]:
    """Return reports with automatic results and all unresolved decisions intact."""
    async with asyncio.timeout(SYNC_TIMEOUT):
        async with client(connection) as mcp, httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
            async def call(tool, **arguments):
                result = await mcp.call_tool(tool, arguments)
                if result.is_error or not isinstance(result.structured_content, dict):
                    raise ValidationError("AIStack returned no usable sync result. Check the server and try again.")
                return result.structured_content

            tools = {tool.name: tool.inputSchema for tool in await mcp.list_tools()}
            project = current_project(cwd, home) if "here" in tools.get("sync", {}).get("properties", {}) else None
            reports = []
            harnesses = local_skills.folders_in_use(home)
            if os.environ.get("CODEX_HOME") and Path(os.environ["CODEX_HOME"]).is_dir() and "agents" not in harnesses:
                harnesses.append("agents")
            if not harnesses:
                raise ValidationError("No coding agent's skills folder was found. Connect Claude Code or Codex first.")
            for harness in harnesses:
                folder = local_skills.skills_folder(Harness(harness), home)
                arguments = {"harness": harness}
                if project:
                    arguments["here"] = project[1]
                report = await _folder(call, http, folder, arguments)
                reports.append(report)
            if project:
                managed = next((report.get("project") for report in reports if (report.get("project") or {}).get("managed")), None)
                if managed:
                    for harness in harnesses:
                        folder = local_skills.skills_folder(Harness(harness), project[0])
                        _project_destination(project[0], folder)
                        relative = folder.relative_to(project[0]).as_posix()
                        blocked = _repository(project[0], relative)
                        arguments = {"harness": harness, "here": project[1], "project": managed["key"], "repository": sorted(blocked)}
                        reports.append(await _folder(call, http, folder, arguments, project[0], blocked))
            return reports


async def _folder(call, http, folder, arguments, top=None, blocked=()):
    listing = local_skills.observed(folder, excluded=blocked)
    report = await call("sync", local=listing, **arguments)
    report.update(folder=str(folder), harness=arguments["harness"], completed=[], failures=[])
    for action in (*report["install"], *report["update"]):
        name = validated_skill_name(action["name"])
        try:
            if top:
                _ignore_install(top, folder, name)
            installed = await call("get_skill", name=name, **{key: arguments[key] for key in ("harness", "project") if key in arguments})
            response = await http.get(installed["download_url"])
            response.raise_for_status()
            # get_skill has recorded its revision already; never treat that as evidence
            # that a concurrent local edit is safe to replace.
            if local_skills.observed(folder, excluded=blocked).get(name) != listing.get(name):
                report["failures"].append(f"'{name}' changed during download. Keep the edits and choose restore, push or skip at the next sync.")
                continue
            if top:
                _ignore_install(top, folder, name)
            local_skills.install(folder, name, response.content, installed["content_hash"])
            report["completed"].append({"action": "installed" if action in report["install"] else "updated", "name": name, "revision": installed["revision"], "pushed_by": installed["pushed_by"]})
        except (OSError, httpx.HTTPError):
            report["failures"].append(f"Could not install '{name}'. Its files were kept; sync again to retry.")
        except AIStackError as error:
            report["failures"].append(error.message)
    for raw_name in report["backup"]:
        try:
            name = validated_skill_name(raw_name)
            if top and name in _repository(top, folder.relative_to(top).as_posix()):
                continue
            packed = local_skills.archive(folder, name)
            # Pure push validation, before requesting the upload ticket.
            validated_skill(name, read_archive(packed))
            issued = await call("push_skill", name=name, **{key: arguments[key] for key in ("harness", "project") if key in arguments})
            response = await http.put(issued["upload_url"], content=packed)
            response.raise_for_status()
            result = response.json()
            if "error" in result:
                raise ValidationError(result["error"])
            report["completed"].append({"action": "backed up", "name": name, "revision": result["revision"]})
        except (OSError, httpx.HTTPError, ValueError):
            report["failures"].append(f"Could not back up '{raw_name}'. Sync again to retry.")
        except AIStackError as error:
            report["failures"].append(error.message)
    if report.get("sync_skill_url") and top is None:
        # A person's Library copy suppresses this field on the server.
        document = sync_skill_document()
        target = folder / SYNC_SKILL_NAME
        if local_skills.observed(folder).get(SYNC_SKILL_NAME) == listing.get(SYNC_SKILL_NAME):
            target.mkdir(parents=True, exist_ok=True)
            local_skills.refresh(folder, SYNC_SKILL_NAME, document)
    return report


def output(reports: list[dict], hook: bool = False) -> str:
    lines = []
    for report in reports:
        if not hook:
            for done in report["completed"]:
                pusher = f", pushed by {done['pushed_by']}" if "pushed_by" in done else ""
                lines.append(f"{done['action'].capitalize()} {done['name']} revision {done['revision']}{pusher} ({report['folder']}).")
        attention = {key: report.get(key) for key in ("ask", "team_updates", "cannot_back_up", "from_other_computers", "left_to_repository") if report.get(key)}
        if report.get("first_sync"):
            attention["first_sync"] = True
        if attention:
            lines.append(f"AIStack decisions for {report['folder']} ({report['harness']}): " + json.dumps(attention, ensure_ascii=True))
            lines.append("Ask the person before acting. enable/restore: get_skill then install; push: push_skill then upload; remove: delete only the already-disabled local folder; skip: no action. Preserve overwrites_local and loses_local_edits warnings. Team updates require an explicit get_skill(name, team) answer. First sync: ask whether to use the same skills in both folders; project offers: ask before installing from other computers.")
        lines.extend(report["failures"])
    if not lines and not hook:
        lines.append("AIStack skills are up to date.")
    return "\n".join(sanitized(line) for line in lines)
