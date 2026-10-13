import unicodedata

import pytest
from sqlalchemy import func, select

from aistack.commons.exceptions import ValidationError
from aistack.db.engine import build_session_factory
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill_version import SkillVersion
from aistack.services import onboarding_service, skill_service, sync_service
from aistack.services.sync_service import Install, Update
from tests.archives import local_digests, skill_archive


@pytest.fixture(name="session_factory")
def session_factory_fixture(portable_engine):
    return build_session_factory(portable_engine)


@pytest.fixture(name="dimitris")
def dimitris_fixture(session_factory):
    with session_factory.begin() as session:
        return onboarding_service.join(session, "dimitris", "macbook", "MACOS")


@pytest.fixture(name="maria")
def maria_fixture(session_factory):
    with session_factory.begin() as session:
        return onboarding_service.join(session, "maria", "laptop", "LINUX")


def _push(session_factory, joined, name="wizard", **archive):
    with session_factory.begin() as session:
        return skill_service.push(session, machine_id=joined.machine.machine_id,
                                  user_id=joined.user.user_id, name=name, origin=None,
                                  archive=skill_archive(name, **archive))


def _enable(session_factory, joined, name="wizard"):
    with session_factory.begin() as session:
        skill_service.get_skill(session, joined.machine.machine_id, name)


def _disable(session_factory, joined, name="wizard"):
    with session_factory.begin() as session:
        skill_service.disable_skill(session, joined.machine.machine_id, name)


def _sync(session_factory, joined, local):
    with session_factory.begin() as session:
        return sync_service.sync(session, joined.machine.machine_id, local)


# --- the silent rows ------------------------------------------------------------------------

def test_a_fresh_machine_installs_everything_enabled_for_it(session_factory, dimitris, maria):
    _push(session_factory, dimitris, "wizard")
    _push(session_factory, dimitris, "code-review")
    _enable(session_factory, maria, "wizard")
    _enable(session_factory, maria, "code-review")

    report = _sync(session_factory, maria, {})

    assert report.install == (Install("code-review", 1, "dimitris"),
                              Install("wizard", 1, "dimitris"))
    assert report.update == ()
    assert report.up_to_date == 0


def test_an_older_unmodified_copy_is_updated_naming_both_revisions_and_the_pusher(
        session_factory, dimitris, maria):
    _push(session_factory, dimitris, files={"notes.md": "one\n"})
    _enable(session_factory, maria)
    _push(session_factory, dimitris, files={"notes.md": "two\n"})
    _push(session_factory, maria, files={"notes.md": "three\n"})
    _enable(session_factory, dimitris)

    report = _sync(session_factory, dimitris,
                   {"wizard": local_digests(files={"notes.md": "one\n"})})

    assert report.install == ()
    assert report.update == (Update("wizard", from_revision=1, to_revision=3,
                                    pushed_by="maria"),)


def test_a_copy_matching_the_latest_revision_appears_nowhere(session_factory, dimitris):
    _push(session_factory, dimitris, files={"notes.md": "one\n"})

    report = _sync(session_factory, dimitris,
                   {"wizard": local_digests(files={"notes.md": "one\n"})})

    assert report.install == () and report.update == ()
    assert report.up_to_date == 1


def test_the_three_silent_rows_together(session_factory, dimitris):
    _push(session_factory, dimitris, "absent")
    _push(session_factory, dimitris, "stale", files={"notes.md": "one\n"})
    _push(session_factory, dimitris, "stale", files={"notes.md": "two\n"})
    _push(session_factory, dimitris, "current")

    report = _sync(session_factory, dimitris, {
        "stale": local_digests("stale", files={"notes.md": "one\n"}),
        "current": local_digests("current"),
    })

    assert [entry.name for entry in report.install] == ["absent"]
    assert [entry.name for entry in report.update] == ["stale"]
    assert report.up_to_date == 1


# --- hashing --------------------------------------------------------------------------------

def test_digests_of_a_pushed_fixture_are_recognized_as_current(session_factory, dimitris):
    """A unicode filename and CRLF content, the way three different shells would report them."""
    files = {"références/naïve.md": "café\r\n", "scripts/run.sh": "#!/bin/sh\r\necho hi\r\n"}
    _push(session_factory, dimitris, files=files)
    digests = local_digests(files=files)

    as_find_reports = {f"./{path}": digest for path, digest in digests.items()}
    as_powershell_reports = {path.replace("/", "\\"): digest.upper()
                             for path, digest in digests.items()}
    as_macos_reports = {unicodedata.normalize("NFD", path): digest
                        for path, digest in digests.items()}

    for reported in (digests, as_find_reports, as_powershell_reports, as_macos_reports):
        assert _sync(session_factory, dimitris, {"wizard": reported}).up_to_date == 1


def test_sync_and_push_agree_because_they_share_one_hash_function(session_factory, dimitris):
    pushed = _push(session_factory, dimitris, files={"a/b.md": "x\n", "c.md": "y\n"})

    with session_factory() as session:
        stored = session.scalar(select(SkillVersion.content_hash))
    assert stored == pushed.content_hash
    assert sync_service._canonical_hash(
        local_digests(files={"a/b.md": "x\n", "c.md": "y\n"})) == stored


def test_finder_and_appledouble_files_do_not_make_a_skill_look_modified(session_factory,
                                                                      dimitris):
    _push(session_factory, dimitris)
    local = {**local_digests(), ".DS_Store": "a" * 64, "._SKILL.md": "b" * 64}

    assert _sync(session_factory, dimitris, {"wizard": local}).up_to_date == 1


def test_matching_the_latest_revision_wins_over_matching_an_older_one(session_factory,
                                                                     dimitris):
    """A → B → A: the local copy equals revisions 1 and 3. It is current, not stale."""
    _push(session_factory, dimitris, files={"notes.md": "A\n"})
    _push(session_factory, dimitris, files={"notes.md": "B\n"})
    _push(session_factory, dimitris, files={"notes.md": "A\n"})

    report = _sync(session_factory, dimitris,
                   {"wizard": local_digests(files={"notes.md": "A\n"})})

    assert report.update == ()
    assert report.up_to_date == 1


def test_a_stale_copy_matching_two_older_revisions_reports_the_newer_of_them(session_factory,
                                                                           dimitris):
    """A → B → A → C: the local A is revision 3's content, so that is what it updates from."""
    for content in ("A\n", "B\n", "A\n", "C\n"):
        _push(session_factory, dimitris, files={"notes.md": content})

    report = _sync(session_factory, dimitris,
                   {"wizard": local_digests(files={"notes.md": "A\n"})})

    assert report.update == (Update("wizard", from_revision=3, to_revision=4,
                                    pushed_by="dimitris"),)


@pytest.mark.parametrize("digest", ["", "not-a-digest", "g" * 64, "a" * 63])
def test_a_malformed_digest_is_content_the_vault_does_not_recognize(session_factory, dimitris,
                                                                  digest):
    """Never an error and never an action: an unrecognized copy is left exactly as it is."""
    _push(session_factory, dimitris)

    report = _sync(session_factory, dimitris, {"wizard": {"SKILL.md": digest}})

    assert report.install == () and report.update == ()
    assert report.up_to_date == 0


def test_two_spellings_of_one_path_are_not_trusted(session_factory, dimitris):
    _push(session_factory, dimitris)
    digest = local_digests()["SKILL.md"]

    report = _sync(session_factory, dimitris,
                   {"wizard": {"SKILL.md": digest, "./SKILL.md": "c" * 64}})

    assert report.up_to_date == 0


# --- scope ----------------------------------------------------------------------------------

def test_a_locally_modified_enabled_skill_is_neither_installed_nor_updated(session_factory,
                                                                         dimitris):
    _push(session_factory, dimitris)

    report = _sync(session_factory, dimitris,
                   {"wizard": local_digests(files={"notes.md": "my local edit\n"})})

    assert report.install == () and report.update == ()


def test_a_local_skill_not_enabled_here_is_left_alone(session_factory, dimitris, maria):
    """In the vault, on disk, older revision, but this machine never chose it."""
    _push(session_factory, dimitris, files={"notes.md": "one\n"})
    _push(session_factory, dimitris, files={"notes.md": "two\n"})

    report = _sync(session_factory, maria,
                   {"wizard": local_digests(files={"notes.md": "one\n"})})

    assert report.install == () and report.update == ()


def test_an_explicitly_disabled_skill_is_not_reinstalled(session_factory, dimitris):
    _push(session_factory, dimitris)
    _disable(session_factory, dimitris)

    report = _sync(session_factory, dimitris, {})

    assert report.install == ()


def test_sync_is_not_discovery(session_factory, dimitris, maria):
    """A vault skill with no local presence and no decision here appears nowhere."""
    _push(session_factory, dimitris, "wizard")
    _push(session_factory, dimitris, "code-review")

    report = _sync(session_factory, maria, {})

    assert report == sync_service.SyncReport(install=(), update=(), up_to_date=0)


def test_sync_is_scoped_to_the_calling_machine(session_factory, dimitris, maria):
    _push(session_factory, dimitris, "wizard")
    _push(session_factory, maria, "code-review")

    assert [entry.name for entry in _sync(session_factory, dimitris, {}).install] == ["wizard"]
    assert [entry.name for entry in _sync(session_factory, maria, {}).install] == [
        "code-review"]


def test_a_local_skill_the_vault_has_never_seen_is_not_acted_on(session_factory, dimitris):
    report = _sync(session_factory, dimitris, {"my-private-skill": local_digests()})

    assert report.install == () and report.update == ()


@pytest.mark.parametrize("folder", ["synced", ".aistack-staging", ".trash", ".git"])
def test_reserved_and_hidden_folders_are_ignored_even_if_sent(session_factory, dimitris,
                                                            folder):
    """`synced` belongs to Claude Code's own claude.ai sync; dot-folders are never skills."""
    _push(session_factory, dimitris)

    report = _sync(session_factory, dimitris,
                   {folder: local_digests(), "wizard": local_digests()})

    assert report.up_to_date == 1


def test_sync_changes_no_desired_state(session_factory, dimitris, maria):
    _push(session_factory, dimitris, files={"notes.md": "one\n"})
    with session_factory() as session:
        before = session.execute(select(MachineSkill.machine_id, MachineSkill.enabled)).all()

    _sync(session_factory, dimitris, {})
    _sync(session_factory, maria, {"wizard": local_digests(files={"notes.md": "one\n"})})

    with session_factory() as session:
        assert session.execute(select(MachineSkill.machine_id,
                                      MachineSkill.enabled)).all() == before
        assert session.scalar(select(func.count()).select_from(SkillVersion)) == 1


# --- limits ---------------------------------------------------------------------------------

def test_too_many_local_skills_is_rejected(session_factory, dimitris):
    local = {f"skill-{number}": {} for number in range(sync_service.MAX_LOCAL_SKILLS + 1)}

    with pytest.raises(ValidationError, match="skill folders, and the limit is 1000"):
        _sync(session_factory, dimitris, local)


def test_too_many_local_files_is_rejected(session_factory, dimitris):
    local = {"huge": {f"file-{number}": "a" * 64
                      for number in range(sync_service.MAX_LOCAL_FILES + 1)}}

    with pytest.raises(ValidationError, match="files, and the limit is 20000"):
        _sync(session_factory, dimitris, local)
