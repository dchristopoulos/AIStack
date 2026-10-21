"""Execute the server's reconciliation report without deciding its questions (ADR-0035)."""

import asyncio
import json
import os
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastmcp.exceptions import ToolError

from aistack.bundled import SYNC_SKILL_NAME, sync_skill_document
from aistack.commons.exceptions import AIStackError, ValidationError
from aistack.commons.text import sanitized
from aistack.db.models.coding_agent import CodingAgent
from aistack.db.models.harness import Harness
from aistack.services import (
    agent_files,
    hardware,
    local_skills,
    projects,
    repository_work,
    rule_files,
)
from aistack.services.rule_validation import validated_rule_name
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


# Where server-mode sync last reported each project it was told this computer manages, so
# `aistack start --project <key>` finds it offline. Display data, checked on disk before use.
REPORTED_PROJECTS = Path(".aistack") / "projects.json"


def _reported(home: Path) -> dict:
    try:
        value = json.loads((home / REPORTED_PROJECTS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def reported_project(home: Path, key: str) -> Path | None:
    path = _reported(home).get(key)
    return Path(path) if isinstance(path, str) and Path(path).is_absolute() else None


def remember_project(home: Path, key: str, top: Path | None) -> None:
    """Record the folder of a project the server manages here, or forget one it does not."""
    try:
        key = projects.validated_key(key)
    except ValidationError:
        return
    reported = _reported(home)
    if top is None:
        if reported.pop(key, None) is None:
            return
    else:
        reported[key] = str(top)
    path = home / REPORTED_PROJECTS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reported, indent=2) + "\n", encoding="utf-8")


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


async def sync_computer(connection: Connection, home: Path, cwd: Path,
                        rule_choices: dict[str, str] | None = None,
                        add_files: list[dict] | None = None) -> list[dict]:
    """Return reports with automatic results and all unresolved decisions intact.

    `rule_choices` carries the person's answers to rule questions, by the key the question
    was reported under; only an option the server offers is carried out. `add_files` is
    `aistack project add`: this computer starts managing the project `cwd` is in, whose
    Markdown files these are, and the server keeps the list (ADR-0036)."""
    async with asyncio.timeout(SYNC_TIMEOUT):
        async with client(connection) as mcp, httpx.AsyncClient(timeout=15, follow_redirects=False) as http:
            async def call(tool, **arguments):
                try:
                    result = await mcp.call_tool(tool, arguments)
                except ToolError as error:
                    # A server refusal fails one skill, as a local one does, not the whole sync.
                    raise AIStackError(str(error)) from None
                if result.is_error or not isinstance(result.structured_content, dict):
                    raise ValidationError("AIStack returned no usable sync result. Check the server and try again.")
                return result.structured_content

            tools = {tool.name: tool.inputSchema for tool in await mcp.list_tools()}
            properties = tools.get("sync", {}).get("properties", {})
            if not {"fingerprint", "identify"} <= properties.keys():
                raise ValidationError("Upgrade the AIStack server to support the copied-computer check before running program sync. The existing manual sync path remains available.")
            identity = await call("sync", local={}, identify=True)
            hardware_id = hardware.hardware_id()
            binding = None if hardware_id is None else hardware.fingerprint(uuid.UUID(identity["machine_id"]), hardware_id)
            # The check must succeed before observing or moving skill files.
            await call("sync", local={}, identify=True, fingerprint=binding)
            project = current_project(cwd, home) if "here" in tools.get("sync", {}).get("properties", {}) else None
            reports = []
            harnesses = local_skills.folders_in_use(home)
            if os.environ.get("CODEX_HOME") and Path(os.environ["CODEX_HOME"]).is_dir() and "agents" not in harnesses:
                harnesses.append("agents")
            if not harnesses:
                raise ValidationError("No coding agent's skills folder was found. Connect Claude Code or Codex first.")
            done_projects = None
            if add_files is not None:
                if project is None:
                    raise ValidationError(f"{cwd} is not in a git repository AIStack can add as a project.")
                if "project_files" not in properties:
                    raise ValidationError("Upgrade the AIStack server to add a project by its folder.")
                remote = project[1]["remote"]
                key = (projects.project_key(remote) if remote else None) or projects.local_project_key(
                    uuid.UUID(identity["machine_id"]), project[1]["path"])
                done_projects = await _project_folders(call, http, harnesses, project, key, binding, add_files)
            # Rules ride on the first folder's sync, from a server that takes them (ADR-0036).
            rules = None
            if "rules" in tools.get("sync", {}).get("properties", {}):
                rules = _observed_rules(home, project[0] if project else None)
            for harness in harnesses:
                folder = local_skills.skills_folder(Harness(harness), home)
                arguments = {"harness": harness, "fingerprint": binding}
                if project:
                    arguments["here"] = project[1]
                if rules is not None and harness == harnesses[0]:
                    arguments["rules"] = rules.observation
                report = await _folder(call, http, folder, arguments)
                if "rules" in arguments:
                    rules.entries = report.pop("rules", [])
                    rules.repository_files = report.pop("repository_files", [])
                    rules.ticked_files = report.pop("ticked_files", [])
                    rules.edits = report.pop("edits", [])
                    managed = (report.get("project") or {}).get("managed") is True
                    rules.top = project[0] if project and managed else None
                if hardware_id is None:
                    report["diagnostics"].append("No OS computer id could be read. Copied connections cannot be detected on this computer; older clients and full clones also remain outside this check.")
                reports.append(report)
            if project:
                managed = next((report.get("project") for report in reports if (report.get("project") or {}).get("managed")), None)
                named = managed or next((report.get("project") for report in reports if isinstance(report.get("project"), dict)), None)
                if named and isinstance(named.get("key"), str):
                    remember_project(home, named["key"], project[0] if managed else None)
                if done_projects is not None:
                    reports.extend(done_projects)
                elif managed:
                    reports.extend(await _project_folders(call, http, harnesses, project, managed["key"], binding))
            if rules is not None:
                done = await _apply_rules(http, rules, rule_choices or {})
                if rules.top is not None:
                    await repository_work.carry_out(http, rules.top, rules.ticked_files, rules.edits,
                                                    rule_choices or {}, done)
                if done["completed"] or done["failures"] or done["rule_questions"] or done.get("edit_questions"):
                    reports.append(done)
            return reports


async def _project_folders(call, http, harnesses: list[str], project: tuple[Path, dict], key: str,
                           binding, listing: list[dict] | None = None) -> list[dict]:
    """Sync each harness's skills folder in a project this computer manages, which is also
    what starts managing it. A listing from `aistack project add` rides on the first."""
    top, reports = project[0], []
    for harness in harnesses:
        folder = local_skills.skills_folder(Harness(harness), top)
        _project_destination(top, folder)
        relative = folder.relative_to(top).as_posix()
        blocked = _repository(top, relative)
        arguments = {"harness": harness, "fingerprint": binding, "here": project[1], "project": key, "repository": sorted(blocked)}
        if listing is not None and not reports:
            arguments["project_files"] = listing
        reports.append(await _folder(call, http, folder, arguments, top, blocked))
    return reports


class _Rules:
    """What sync read of the rule files here, and what the server answered about them."""

    def __init__(self, project_top: Path | None):
        self.observation: list[dict] = []
        # (place, agent, name) -> (path, content as read); name is None for every project.
        self.files: dict[tuple, tuple[Path, bytes | None]] = {}
        self.agents: list[CodingAgent] = []
        self.project_top = project_top
        self.tracked: set[str] | None = None
        self.override: bytes | None = None
        self.sections: dict[str, str] | None = None
        self.entries: list[dict] = []
        self.repository_files: list[dict] = []
        self.ticked_files: list[dict] = []
        self.edits: list[dict] = []
        # The project's top level once the server says this computer manages it.
        self.top: Path | None = None

    def observe(self, agent: CodingAgent, place: str, name: str | None, path: Path,
                content: bytes | None) -> None:
        self.files[(place, agent, name)] = (path, content)
        self.observation.append({"agent": agent.value, "place": place, "name": name,
                                 "digest": None if content is None else rule_files.digest(content)})


def _observed_rules(home: Path, top: Path | None) -> _Rules:
    rules = _Rules(top)
    for agent in agent_files.agents_writing_rules():
        path = rule_files.every_project_file(agent, home)
        if path is not None:
            rules.agents.append(agent)
            rules.observe(agent, "every_project", None, path, rule_files.read(path))
    if top is None:
        return rules
    try:
        rules.tracked = rule_files.tracked(top)
    except (ValidationError, OSError, subprocess.SubprocessError):
        return rules
    if CodingAgent.CLAUDE_CODE in rules.agents:
        for name, content in rule_files.claude_rules(top, rules.tracked).items():
            rules.observe(CodingAgent.CLAUDE_CODE, "project", name,
                          rule_files.claude_rule_path(top, name), content)
    if CodingAgent.CODEX in rules.agents:
        path = rule_files.override_path(top)
        rules.override = rule_files.read(path)
        if path.name not in rules.tracked and not path.is_symlink():
            rules.sections = rule_files.parsed_override(rules.override)
        for name, text in (rules.sections or {}).items():
            rules.observe(CodingAgent.CODEX, "project", name, path, text.encode("utf-8"))
    return rules


_ANSWERED = {"restore": "update", "push": "backup", "remove": "remove", "skip": "nothing"}


async def _apply_rules(http, rules: _Rules, choices: dict[str, str]) -> dict:
    """Carry out the server's action for each rule file, and every answer the person gave."""
    report = {"folder": "rules", "harness": "rules", "rules": True, "completed": [],
              "failures": [], "diagnostics": [], "rule_questions": []}
    top = rules.top
    sections: dict[str, str] = {}
    for entry in rules.entries:
        try:
            agent, place = CodingAgent(entry["agent"]), entry["place"]
            name = validated_rule_name(entry["name"])
            if place not in ("every_project", "project") or (place == "project" and top is None):
                raise ValueError(place)
        except (KeyError, ValueError, TypeError, AIStackError):
            report["failures"].append("AIStack returned a rule file it cannot place. Upgrade "
                                      "this program and sync again.")
            continue
        key = f"{place}:{agent.value}:{name}"
        codex_section = place == "project" and agent is CodingAgent.CODEX
        if codex_section:
            path = rule_files.override_path(top)
            observed = None if rules.sections is None or name not in rules.sections else (
                rules.sections[name].encode("utf-8"))
        elif place == "project":
            path = rule_files.claude_rule_path(top, name)
            observed = rules.files.get((place, agent, name), (path, None))[1]
        elif (place, agent, None) in rules.files:
            path, observed = rules.files[(place, agent, None)]
        else:
            report["failures"].append(f"AIStack returned a rule for {agent.value}, which this "
                                      "computer did not report. Sync again.")
            continue
        step = entry["action"]
        if step == "ask":
            offered = {option["choice"] for option in entry["options"]}
            choice = choices.get(key)
            if choice is None or choice not in offered:
                if choice is not None:
                    report["failures"].append(f"'{choice}' is not an answer to {key}; it offers "
                                              f"{', '.join(sorted(offered))}.")
                report["rule_questions"].append(_question(key, path, entry))
                if observed is not None and codex_section:
                    sections[name] = observed.decode("utf-8")
                continue
            step = _ANSWERED[choice]
        try:
            if step in ("install", "update"):
                response = await http.get(entry["download_url"])
                response.raise_for_status()
                text = response.content.decode("utf-8")
                if codex_section:
                    sections[name] = text
                    continue
                if place == "project":
                    _check_project_file(top, rules, path)
                    rule_files.exclude(top, path.relative_to(top).as_posix())
                if not rule_files.replace(path, text.encode("utf-8"), observed,
                                          follow_link=place == "every_project"):
                    report["failures"].append(f"{path} changed during sync. Its edits were kept; "
                                              "sync again to decide.")
                    continue
                report["completed"].append(f"Wrote rule {name} revision {entry['revision']}, "
                                           f"pushed by {entry['pushed_by']}, to {path}.")
            elif step == "backup":
                if codex_section:
                    sections[name] = observed.decode("utf-8")
                elif rule_files.read(path) != observed:
                    report["failures"].append(f"{path} changed during sync. Sync again to back it "
                                              "up.")
                    continue
                report["completed"].append(await _upload(http, entry["upload_url"], observed,
                                                          path, report["failures"]))
            elif step == "remove":
                if codex_section:
                    continue
                if not rule_files.remove(path, observed):
                    report["failures"].append(f"{path} changed during sync, so it was kept.")
                    continue
                report["completed"].append(f"Removed {path}.")
            elif codex_section and observed is not None:
                sections[name] = observed.decode("utf-8")
        except (OSError, httpx.HTTPError, UnicodeDecodeError):
            report["failures"].append(f"Could not sync rule {name} for {path}. Its file was kept; "
                                      "sync again to retry.")
        except AIStackError as error:
            report["failures"].append(error.message)
    report["completed"] = [line for line in report["completed"] if line]
    if top is not None:
        _write_project_settings(top, rules, sections, report)
    return report


def _check_project_file(top: Path, rules: _Rules, path: Path) -> None:
    relative = path.relative_to(top).as_posix()
    if rules.tracked is None or relative in rules.tracked:
        raise ValidationError(f"The repository holds {relative}, so AIStack did not write it.")
    if not rule_files.inside(top, path.parent) or path.is_symlink():
        raise ValidationError(f"{relative} leads outside the project, so AIStack did not write "
                              "it.")


async def _upload(http, url: str, content: bytes, path: Path, failures: list[str]) -> str | None:
    response = await http.put(url, content=content)
    try:
        result = response.json()
    except ValueError:
        response.raise_for_status()
        raise
    if "error" in result:
        failures.append(f"Did not back up {path}: {result['error']}")
        return None
    if not result.get("saved"):
        lines = ", ".join(str(line) for line in result.get("credential_lines", []))
        failures.append(f"Did not back up {path}: line {lines} looks like it holds a credential. "
                        "Remove it, or save the rule on the AIStack page to keep it as it is.")
        return None
    return f"Backed up {path} as rule {result['name']} revision {result['revision']}."


def _write_project_settings(top: Path, rules: _Rules, sections: dict[str, str],
                            report: dict) -> None:
    """Codex's override, and the files turned off for Claude Code, in a managed project."""
    turned: dict[str, bool] = {}
    for listed in rules.repository_files:
        try:
            turned[rule_files.validated_repository_path(listed.get("path"))] = (
                listed.get("turned_off") is True)
        except (AIStackError, AttributeError) as error:
            report["failures"].append(getattr(error, "message", "A repository file was not "
                                                                "understood."))
    try:
        if CodingAgent.CLAUDE_CODE in rules.agents and turned and rule_files.turn_off_for_claude(
                top, turned):
            report["completed"].append(f"Updated the files turned off for Claude Code in "
                                       f"{top / rule_files.SETTINGS_LOCAL}.")
        if CodingAgent.CODEX not in rules.agents or rules.tracked is None:
            return
        path = rule_files.override_path(top)
        off = turned.get("AGENTS.md", False)
        if not (sections or off or rules.sections is not None):
            return
        if path.name in rules.tracked or (rules.override is not None and rules.sections is None):
            report["failures"].append(f"{path} is not one AIStack made, so your Codex rules for "
                                      "this project were not written. Move it away and sync again.")
            return
        text = rule_files.override_text("" if off else rule_files.repository_text(top),
                                        sorted(sections.items()))
        if text.encode("utf-8") == rules.override:
            return
        if not rule_files.inside(top, path.parent):
            raise ValidationError(f"{path} leads outside the project, so it was not written.")
        rule_files.exclude(top, path.name)
        if rule_files.replace(path, text.encode("utf-8"), rules.override):
            report["completed"].append(f"Wrote {path} for Codex.")
        else:
            report["failures"].append(f"{path} changed during sync. Sync again to rewrite it.")
    except OSError:
        report["failures"].append("Could not write this project's rule settings. Sync again to "
                                  "retry.")
    except AIStackError as error:
        report["failures"].append(error.message)


def _question(key: str, path: Path, entry: dict) -> dict:
    """A rule question as the person's agent reads it: never with a transfer URL, which is a
    credential."""
    return {"key": key, "file": str(path)} | {
        field: entry.get(field) for field in ("local", "desired", "revision", "edited_from",
                                              "pushed_by", "options", "removed_from_library")}


async def _folder(call, http, folder, arguments, top=None, blocked=()):
    listing = local_skills.observed(folder, excluded=blocked)
    report = await call("sync", local=listing, **arguments)
    report.update(folder=str(folder), harness=arguments["harness"], project_folder=arguments.get("project"), completed=[], failures=[], diagnostics=[])
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
    offers: dict[tuple, dict] = {}
    for report in reports:
        if report.get("rules"):
            if not hook:
                lines.extend(report["completed"])
            if report["rule_questions"]:
                lines.append("AIStack rule decisions: " + json.dumps(report["rule_questions"], ensure_ascii=True))
                lines.append("Ask the person before acting, naming the file. To carry out an answer, run aistack sync --rule-choice <key>=<choice>: restore writes the Library's text over the file, push keeps the file's text in the Library, remove deletes the file (or its part of AGENTS.override.md), skip changes nothing. Preserve overwrites_local and loses_local_edits warnings; edited_from below revision means the rule was also edited on the page.")
            if report.get("edit_questions"):
                lines.append("AIStack edits from the page waiting: " + json.dumps(report["edit_questions"], ensure_ascii=True))
                lines.append("Each file changed here since the edit was made on the page. Ask the person, naming the file. To carry out an answer, run aistack sync --rule-choice <key>=<choice>: write replaces the file's text here with the edit, cancel drops the edit and keeps the file.")
            lines.extend(report["failures"])
            continue
        if not hook:
            for done in report["completed"]:
                pusher = f", pushed by {done['pushed_by']}" if "pushed_by" in done else ""
                lines.append(f"{done['action'].capitalize()} {done['name']} revision {done['revision']}{pusher} ({report['folder']}).")
        attention = {key: report.get(key) for key in ("ask", "cannot_back_up", "from_other_computers", "left_to_repository") if report.get(key)}
        # One offer per skill, however many folders list it: the skill is one in the Library.
        for offer in report.get("team_updates") or ():
            key = (offer["name"], offer["team"], offer["to_revision"])
            place = {"folder": report["folder"], "harness": report["harness"]} | ({"project": report["project_folder"]} if report.get("project_folder") else {})
            offers.setdefault(key, offer | {"folders": []})["folders"].append(place)
        if report.get("first_sync"):
            attention["first_sync"] = True
        if attention:
            lines.append(f"AIStack decisions for {report['folder']} ({report['harness']}): " + json.dumps(attention, ensure_ascii=True))
            lines.append("Ask the person before acting. enable/restore: get_skill then install; push: push_skill then upload; remove: delete only the already-disabled local folder; skip: no action. Preserve overwrites_local and loses_local_edits warnings. First sync: ask whether to use the same skills in both folders; project offers: ask before installing from other computers.")
        lines.extend(report["failures"])
        if not hook:
            lines.extend(report.get("diagnostics", []))
    if offers:
        lines.append("AIStack team updates: " + json.dumps(list(offers.values()), ensure_ascii=True))
        lines.append("Ask once per skill, even when several folders list it, naming pushed_by and any own_changes or different_skill warning. On yes: get_skill(name, team) once, with the harness and any project of its first folder, then run aistack sync again to install it in every folder listed.")
    if not lines and not hook:
        lines.append("AIStack skills are up to date.")
    return "\n".join(sanitized(line) for line in lines)
