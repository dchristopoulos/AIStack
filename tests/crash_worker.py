"""Subprocess operations with test-only blocking hooks at selected write boundaries."""

import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

from aistack.bootstrap.configuration.settings.settings_config import LocalSettings
from aistack.bootstrap.context import application_context
from aistack.db.engine import build_engine, build_session_factory
from aistack.mcp.tools import local
from aistack.services import local_skills, skill_service
from aistack.services.library_repo import LibraryRepo
from aistack.services.skill_archive import read_archive
from aistack.services.skill_validation import validated_skill


def hold(boundary):
    if os.environ["AISTACK_TEST_CRASH_AT"] == boundary:
        print(f"ready:{os.getpid()}", flush=True)
        # The parent keeps stdin open and kills us instead of releasing the operation.
        sys.stdin.read(1)


def install(configuration):
    folder = Path(configuration["folder"])
    rename = Path.rename
    swap_in = local_skills._swap_in

    def renamed(path, target):
        result = rename(path, target)
        if path == folder / "wizard":
            hold("old-moved")
        elif Path(target) == folder / "wizard":
            hold("new-moved")
        return result

    def staged(*args):
        hold("staged")
        return swap_in(*args)

    with patch.object(Path, "rename", renamed), patch.object(local_skills, "_swap_in", staged):
        local_skills.install(
            folder,
            "wizard",
            Path(configuration["archive"]).read_bytes(),
            configuration["content_hash"],
        )


def transaction(configuration):
    engine = build_engine(configuration["database_url"])
    uploaded = validated_skill("wizard", read_archive(Path(configuration["archive"]).read_bytes()))
    with build_session_factory(engine).begin() as session:
        skill_service.store(
            session,
            uuid.UUID(configuration["machine_id"]),
            uuid.UUID(configuration["user_id"]),
            uploaded,
            None,
        )
        session.flush()
        hold("before-commit")


def library(configuration):
    home = Path(configuration["home"])
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(home)
    application_context.build_local_context(LocalSettings(
        aistack_home=home / ".aistack",
        aistack_library_repo=configuration["repository"],
        aistack_username="maria",
        aistack_auto_update=False,
    ))
    publish = LibraryRepo.publish

    def before_push(repo, events):
        hold("before-push")
        return publish(repo, events)

    with patch.object(LibraryRepo, "publish", before_push):
        local._push_one("wizard", None, "claude_code")
        application_context.library_after_write()


if __name__ == "__main__":
    operation, source = sys.argv[1:]
    {"install": install, "transaction": transaction, "library": library}[operation](
        json.loads(Path(source).read_text(encoding="utf-8")))
