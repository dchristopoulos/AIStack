"""Hard process exits leave complete revisions and committed Library events."""

import subprocess

import pytest
from sqlalchemy import select

from aistack.bootstrap.configuration.settings.settings_config import LocalSettings
from aistack.bootstrap.context import application_context
from aistack.db.engine import build_engine, build_session_factory
from aistack.db.models import Base
from aistack.db.models.skill_version import SkillVersion
from aistack.db.schema import migrate_schema
from aistack.services import (
    library_log,
    local_skills,
    onboarding_service,
    skill_service,
    sync_service,
)
from aistack.services.library_repo import LibraryRepo
from aistack.services.skill_archive import read_archive
from aistack.services.skill_validation import validated_skill
from tests.archives import skill_archive
from tests.crash_process import kill_at


def _revision(body):
    packed = skill_archive(files={"docs/notes.md": body, "more.md": body})
    return packed, validated_skill("wizard", read_archive(packed))


def _contents(folder):
    if not folder.exists():
        return None
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in folder.rglob("*") if path.is_file()}


def _files(packed):
    return {file.path: file.content for file in read_archive(packed)}


def _snapshot(session):
    return {table.name: sorted(session.execute(table.select()).all(), key=repr)
            for table in Base.metadata.sorted_tables}


@pytest.mark.parametrize("boundary", ["staged", "old-moved", "new-moved"])
def test_a_killed_install_leaves_a_whole_revision_and_the_next_sync_settles_it(
        portable_engine, tmp_path, boundary):
    factory = build_session_factory(portable_engine)
    old_archive, old = _revision("old\n")
    new_archive, new = _revision("new\n")
    with factory.begin() as session:
        joined = onboarding_service.join(session, "maria", "laptop", "LINUX")
        for revision in (old, new):
            skill_service.store(
                session,
                joined.machine.machine_id,
                joined.user.user_id,
                revision,
                None,
            )
    folder = tmp_path / "skills"
    local_skills.install(folder, "wizard", old_archive, old.content_hash)
    archive = tmp_path / "new.tar.gz"
    archive.write_bytes(new_archive)

    kill_at(
        tmp_path,
        "install",
        boundary,
        folder=str(folder),
        archive=str(archive),
        content_hash=new.content_hash,
    )

    expected = {"staged": _files(old_archive), "old-moved": None, "new-moved": _files(new_archive)}
    assert _contents(folder / "wizard") == expected[boundary]
    with factory.begin() as session:
        report = sync_service.sync(
            session,
            joined.machine.machine_id,
            joined.user.user_id,
            local_skills.observed(folder),
        )
        assert report.ask == () and report.backup == ()
        assert len(report.update) == (boundary == "staged")
        assert len(report.install) == (boundary == "old-moved")
        assert report.up_to_date == (boundary == "new-moved")
        install = skill_service.get_skill(
            session,
            joined.machine.machine_id,
            joined.user.user_id,
            "wizard",
        )
        name, packed = skill_service.archive_of(
            session,
            joined.machine.machine_id,
            install.skill_version_id,
        )
    local_skills.install(folder, name, packed, install.content_hash)

    assert _contents(folder / "wizard") == _files(new_archive)
    with factory.begin() as session:
        settled = sync_service.sync(
            session,
            joined.machine.machine_id,
            joined.user.user_id,
            local_skills.observed(folder),
        )
    assert settled.up_to_date == 1
    assert settled.install == settled.update == settled.ask == ()


def test_a_server_write_killed_before_commit_keeps_the_previous_revision(
        portable_engine, tmp_path):
    factory = build_session_factory(portable_engine)
    _, old = _revision("old\n")
    packed, new = _revision("new\n")
    with factory.begin() as session:
        joined = onboarding_service.join(session, "maria", "laptop", "LINUX")
        skill_service.store(session, joined.machine.machine_id, joined.user.user_id, old, None)
    with factory.begin() as session:
        before = _snapshot(session)
    archive = tmp_path / "new.tar.gz"
    archive.write_bytes(packed)

    kill_at(
        tmp_path,
        "transaction",
        "before-commit",
        database_url=portable_engine.url.render_as_string(hide_password=False),
        archive=str(archive),
        machine_id=str(joined.machine.machine_id),
        user_id=str(joined.user.user_id),
    )

    with factory.begin() as session:
        assert _snapshot(session) == before
        [version] = session.scalars(select(SkillVersion)).all()
        assert version.revision == 1 and version.content_hash == old.content_hash
        _, archived = skill_service.archive_of(
            session,
            joined.machine.machine_id,
            version.skill_version_id,
        )
        assert _files(archived) == {file.path: file.content.encode("utf-8") for file in old.files}
        retried = skill_service.store(
            session,
            joined.machine.machine_id,
            joined.user.user_id,
            new,
            None,
        )
        assert retried.revision == 2


def test_a_local_write_killed_before_its_git_push_is_published_after_restart(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(remote)], check=True)
    home = tmp_path / "home"
    folder = home / ".claude/skills/wizard"
    folder.mkdir(parents=True)
    original = b"---\nname: wizard\ndescription: A saved skill.\n---\n\nSaved before the crash.\n"
    (folder / "SKILL.md").write_bytes(original)

    kill_at(tmp_path, "library", "before-push", home=str(home), repository=str(remote))

    settings = LocalSettings(
        aistack_home=home / ".aistack",
        aistack_library_repo=str(remote),
        aistack_username="maria",
        aistack_auto_update=False,
    )
    import ctypes
    import sys
    from pathlib import Path
    dll = ctypes.CDLL(str(Path(sys.base_prefix) / "DLLs/sqlite3.dll"))
    callback_type = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p)
    callback = callback_type(lambda _, code, text: print("SQLite native log", code, text.decode()))
    print("Log configured", dll.sqlite3_config(16, callback, None))
    engine = build_engine(settings.library_url())
    try:
        with build_session_factory(engine).begin() as session:
            pending = library_log.unpublished(session)
            assert len(pending) == 1 and pending[0].kind == library_log.SKILL_PUSHED
            [version] = session.scalars(select(SkillVersion)).all()
            assert version.revision == 1
    finally:
        engine.dispose()

    before = LibraryRepo(tmp_path / "before", str(remote))
    before.pull()
    assert not [event for event in before.events() if event.kind == library_log.SKILL_PUSHED]
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    try:
        application_context.build_local_context(settings)
        assert application_context.library_after_write() is True
        with application_context.get_session_factory().begin() as session:
            assert library_log.unpublished(session) == []
        before.pull()
        [event] = [event for event in before.events() if event.kind == library_log.SKILL_PUSHED]
        assert event.event_id == pending[0].event_id

        # A fresh copy on another computer must rebuild the same stored files.
        rebuilt = build_engine(f"sqlite:///{(tmp_path / 'rebuilt.db').as_posix()}")
        try:
            migrate_schema(rebuilt)
            with build_session_factory(rebuilt).begin() as session:
                library_log.rebuild(session, before.events())
                machine_id = event.machine_id
                [version] = session.scalars(select(SkillVersion)).all()
                _, packed = skill_service.archive_of(session, machine_id, version.skill_version_id)
                assert _files(packed) == {"SKILL.md": original}
        finally:
            rebuilt.dispose()
    finally:
        application_context.dispose_application_context()
