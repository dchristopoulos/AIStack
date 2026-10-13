import hashlib
import unicodedata
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from aistack.bundled import SYNC_SKILL_NAME, sync_skill_document
from aistack.commons.exceptions import ValidationError
from aistack.db.engine import build_session_factory
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill_version import SkillVersion
from aistack.services import onboarding_service, skill_service, sync_service
from aistack.services.reconciliation import Choice, Desired, Observed
from aistack.services.sync_service import Install, Update
from tests.archives import local_digests, skill_archive
from tests.teams import enable, share_with_everyone


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


@pytest.fixture(name="desktop")
def desktop_fixture(session_factory, dimitris):
    """Dimitris's second computer. A machine with no decision about one of its own user's
    skills is the only way to be undecided: nobody else's skill is ever compared."""
    with session_factory.begin() as session:
        added = onboarding_service.add_machine(session, dimitris.user.user_id, "desktop",
                                               "LINUX")
    return SimpleNamespace(user=dimitris.user, machine=added.machine)


def _push(session_factory, joined, name="wizard", **archive):
    with session_factory.begin() as session:
        pushed = skill_service.push(session, machine_id=joined.machine.machine_id,
                                    user_id=joined.user.user_id, name=name, origin=None,
                                    archive=skill_archive(name, **archive))
        share_with_everyone(session, joined.user.user_id, name)
        return pushed


def _enable(session_factory, joined, name="wizard"):
    with session_factory.begin() as session:
        enable(session, joined.machine.machine_id, name)


def _disable(session_factory, joined, name="wizard"):
    with session_factory.begin() as session:
        skill_service.disable_skill(session, joined.machine.machine_id,
                                    joined.user.user_id, name)


def _sync(session_factory, joined, local):
    with session_factory.begin() as session:
        return sync_service.sync(session, joined.machine.machine_id, joined.user.user_id,
                                 local)


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
        session_factory, dimitris, desktop):
    _push(session_factory, dimitris, files={"notes.md": "one\n"})
    _enable(session_factory, desktop)
    _push(session_factory, dimitris, files={"notes.md": "two\n"})
    _push(session_factory, desktop, files={"notes.md": "three\n"})
    _enable(session_factory, dimitris)

    report = _sync(session_factory, dimitris,
                   {"wizard": local_digests(files={"notes.md": "one\n"})})

    assert report.install == ()
    assert report.update == (Update("wizard", from_revision=1, to_revision=3,
                                    pushed_by="dimitris"),)


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

    assert report == sync_service.SyncReport(install=(), update=(), ask=(), backup=(), team_updates=(),
                                             up_to_date=0, refresh_sync_skill=True)


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


def test_sync_changes_no_desired_state(session_factory, dimitris, desktop):
    _push(session_factory, dimitris, files={"notes.md": "one\n"})
    with session_factory() as session:
        before = session.execute(select(MachineSkill.machine_id, MachineSkill.enabled)).all()
        revisions = session.scalar(select(func.count()).select_from(SkillVersion))

    _sync(session_factory, dimitris, {})
    _sync(session_factory, desktop, {"wizard": local_digests(files={"notes.md": "one\n"})})

    with session_factory() as session:
        assert session.execute(select(MachineSkill.machine_id,
                                      MachineSkill.enabled)).all() == before
        assert session.scalar(select(func.count()).select_from(SkillVersion)) == revisions


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


# --- the questions --------------------------------------------------------------------------

def _only_question(report):
    assert report.install == () and report.update == ()
    assert len(report.ask) == 1
    return report.ask[0]


def _choices(question) -> list[Choice]:
    return [option.choice for option in question.options]


def _flags(question) -> dict[Choice, tuple[bool, bool]]:
    return {option.choice: (option.overwrites_local, option.loses_local_edits)
            for option in question.options}


EDITED = {"wizard": local_digests(files={"notes.md": "my local edit\n"})}


def test_an_edited_enabled_skill_is_a_question_with_restore_push_and_skip(session_factory,
                                                                        dimitris, maria):
    _push(session_factory, maria)
    _enable(session_factory, dimitris)

    question = _only_question(_sync(session_factory, dimitris, EDITED))

    assert (question.name, question.desired, question.local) == (
        "wizard", Desired.ENABLED, Observed.UNKNOWN)
    assert question.local_revision is None
    assert question.latest_revision == 1
    assert question.pushed_by == "maria"
    assert _flags(question) == {
        Choice.RESTORE: (True, True),
        Choice.PUSH: (False, False),
        Choice.SKIP: (False, False),
    }


def test_skipping_means_being_asked_again(session_factory, dimitris):
    """Skip is not a state the server stores. The same input gives the same question."""
    _push(session_factory, dimitris)

    first = _sync(session_factory, dimitris, EDITED)
    second = _sync(session_factory, dimitris, EDITED)

    assert first == second
    assert len(second.ask) == 1


def test_a_disabled_skill_back_on_disk_is_asked_about_by_what_is_on_disk(session_factory,
                                                                       dimitris):
    _push(session_factory, dimitris, files={"notes.md": "one\n"})
    _push(session_factory, dimitris, files={"notes.md": "two\n"})
    _disable(session_factory, dimitris)

    current = _only_question(_sync(session_factory, dimitris,
                                   {"wizard": local_digests(files={"notes.md": "two\n"})}))
    stale = _only_question(_sync(session_factory, dimitris,
                                 {"wizard": local_digests(files={"notes.md": "one\n"})}))
    unknown = _only_question(_sync(session_factory, dimitris, EDITED))

    assert current.desired is stale.desired is unknown.desired is Desired.DISABLED
    assert (current.local, current.local_revision) == (Observed.CURRENT, 2)
    assert (stale.local, stale.local_revision) == (Observed.STALE, 1)
    assert (unknown.local, unknown.local_revision) == (Observed.UNKNOWN, None)

    # Re-enable with no rewrite, or finish the removal.
    assert _flags(current) == {Choice.ENABLE: (False, False), Choice.REMOVE: (False, False)}
    # Re-enabling replaces the files, and says so. Nothing is lost: revision 1 is in the vault.
    assert _flags(stale) == {Choice.ENABLE: (True, False), Choice.REMOVE: (False, False)}
    # Only here can an answer destroy work, and both ways of doing so are flagged.
    assert _flags(unknown) == {
        Choice.PUSH: (False, False),
        Choice.ENABLE: (True, True),
        Choice.REMOVE: (False, True),
        Choice.SKIP: (False, False),
    }


def test_a_vault_skill_on_disk_with_no_decision_is_asked_about_by_what_is_on_disk(
        session_factory, dimitris, desktop):
    """The desktop has the folder, the skill is one of his own, and that machine never chose it."""
    _push(session_factory, dimitris, files={"notes.md": "one\n"})
    _push(session_factory, dimitris, files={"notes.md": "two\n"})

    current = _only_question(_sync(session_factory, desktop,
                                   {"wizard": local_digests(files={"notes.md": "two\n"})}))
    stale = _only_question(_sync(session_factory, desktop,
                                 {"wizard": local_digests(files={"notes.md": "one\n"})}))
    unknown = _only_question(_sync(session_factory, desktop, EDITED))

    assert current.desired is stale.desired is unknown.desired is Desired.UNDECIDED
    assert _flags(current) == {Choice.ENABLE: (False, False), Choice.SKIP: (False, False)}
    assert _flags(stale) == {Choice.ENABLE: (True, False), Choice.SKIP: (False, False)}
    assert _flags(unknown) == {
        Choice.PUSH: (False, False),
        Choice.ENABLE: (True, True),
        Choice.SKIP: (False, False),
    }


def test_disabled_and_undecided_are_reported_as_different_things(session_factory, dimitris,
                                                               desktop):
    """One row with enabled = false, one machine with no row. Same disk, different question."""
    _push(session_factory, dimitris)
    _disable(session_factory, dimitris)
    local = {"wizard": local_digests()}

    disabled = _only_question(_sync(session_factory, dimitris, local))
    undecided = _only_question(_sync(session_factory, desktop, local))

    assert disabled.desired is Desired.DISABLED
    assert undecided.desired is Desired.UNDECIDED
    assert Choice.REMOVE in _choices(disabled)
    assert Choice.REMOVE not in _choices(undecided)


def test_only_unknown_content_is_ever_offered_a_choice_that_loses_edits(session_factory,
                                                                      dimitris, desktop):
    _push(session_factory, dimitris, "current")
    _push(session_factory, dimitris, "stale", files={"notes.md": "one\n"})
    _push(session_factory, dimitris, "stale", files={"notes.md": "two\n"})
    _push(session_factory, dimitris, "edited")

    report = _sync(session_factory, desktop, {
        "current": local_digests("current"),
        "stale": local_digests("stale", files={"notes.md": "one\n"}),
        "edited": local_digests("edited", files={"x.md": "mine\n"}),
    })

    assert [question.name for question in report.ask] == ["current", "edited", "stale"]
    for question in report.ask:
        loses = any(option.loses_local_edits for option in question.options)
        assert loses == (question.local is Observed.UNKNOWN)


# --- the states that are never reported -----------------------------------------------------

def test_the_three_absent_states_produce_no_report_at_all(session_factory, dimitris, maria):
    """Absent + disabled, absent + no decision, absent + not in the vault."""
    _push(session_factory, dimitris, "disabled-here")
    _disable(session_factory, dimitris, "disabled-here")
    _push(session_factory, maria, "never-chosen")

    report = _sync(session_factory, dimitris, {})

    assert report == sync_service.SyncReport(install=(), update=(), ask=(), backup=(), team_updates=(),
                                             up_to_date=0, refresh_sync_skill=True)


# --- backup ---------------------------------------------------------------------------------

def test_a_local_skill_the_vault_has_never_seen_is_an_orphan(session_factory, dimitris):
    _push(session_factory, dimitris)

    report = _sync(session_factory, dimitris, {
        "wizard": local_digests(),
        "my-private-skill": local_digests("my-private-skill"),
        "another-one": local_digests("another-one"),
    })

    assert report.backup == ("another-one", "my-private-skill")
    assert report.ask == ()
    assert report.up_to_date == 1


def test_the_skill_setup_installed_is_not_an_orphan(session_factory, dimitris):
    """Setup writes it from the server, so a fresh vault never holds it. Offering to push the
    skill that does the syncing, on every sync, is noise."""
    report = _sync(session_factory, dimitris, {
        SYNC_SKILL_NAME: local_digests(SYNC_SKILL_NAME),
        "my-private-skill": local_digests("my-private-skill"),
    })

    assert report.backup == ("my-private-skill",)
    assert report.ask == ()


def test_the_sync_skill_is_reconciled_like_any_other_once_the_vault_holds_it(session_factory,
                                                                           dimitris):
    _push(session_factory, dimitris, SYNC_SKILL_NAME)

    current = _sync(session_factory, dimitris, {SYNC_SKILL_NAME: local_digests(SYNC_SKILL_NAME)})
    edited = _sync(session_factory, dimitris, {
        SYNC_SKILL_NAME: local_digests(SYNC_SKILL_NAME, files={"notes.md": "my local edit\n"}),
    })

    assert current.up_to_date == 1
    assert _only_question(edited).name == SYNC_SKILL_NAME


def _bundled_digests() -> dict[str, str]:
    return {"SKILL.md": hashlib.sha256(sync_skill_document().encode("utf-8")).hexdigest()}


def test_a_sync_skill_that_matches_the_servers_needs_no_refresh(session_factory, dimitris):
    report = _sync(session_factory, dimitris, {SYNC_SKILL_NAME: _bundled_digests()})

    assert report.refresh_sync_skill is False


def test_a_sync_skill_from_an_older_server_is_refreshed(session_factory, dimitris):
    """Setup fetched it once. Without this, an upgraded server talks to old instructions."""
    report = _sync(session_factory, dimitris, {SYNC_SKILL_NAME: local_digests(SYNC_SKILL_NAME)})

    assert report.refresh_sync_skill is True
    assert report.backup == () and report.ask == ()


def test_a_machine_without_the_sync_skill_is_offered_it(session_factory, dimitris):
    """add_machine connects a second computer without running setup, so it has no copy."""
    assert _sync(session_factory, dimitris, {}).refresh_sync_skill is True


def test_a_sync_skill_the_vault_holds_is_the_vaults_to_manage(session_factory, dimitris):
    _push(session_factory, dimitris, SYNC_SKILL_NAME)

    report = _sync(session_factory, dimitris, {SYNC_SKILL_NAME: local_digests(SYNC_SKILL_NAME)})

    assert report.refresh_sync_skill is False
    assert report.up_to_date == 1


def test_an_orphan_is_reported_and_never_pushed(session_factory, dimitris):
    """A fresh machine may hold dozens of third-party skills. Sync imports none of them."""
    local = {f"third-party-{number}": local_digests(f"third-party-{number}")
             for number in range(30)}

    report = _sync(session_factory, dimitris, local)

    assert len(report.backup) == 30
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(SkillVersion)) == 0
        assert session.scalar(select(func.count()).select_from(MachineSkill)) == 0


def test_a_folder_name_the_vault_could_never_hold_is_still_just_an_orphan(session_factory,
                                                                        dimitris):
    report = _sync(session_factory, dimitris, {"My Skill (copy)": local_digests()})

    assert report.backup == ("My Skill (copy)",)


def test_a_renamed_local_folder_is_one_install_plus_one_orphan(session_factory, dimitris):
    """The documented quirk: the vault knows names, not that a folder used to be called one."""
    _push(session_factory, dimitris)

    report = _sync(session_factory, dimitris, {"wizard-renamed": local_digests()})

    assert report.install == (Install("wizard", 1, "dimitris"),)
    assert report.backup == ("wizard-renamed",)
    assert report.ask == ()


# --- the two invariants ---------------------------------------------------------------------

def test_no_sync_outcome_changes_desired_state_or_the_vault(session_factory, dimitris, desktop):
    """Every state at once, twice. Sync reads; only get, push, and disable write."""
    _push(session_factory, dimitris, "enabled-edited")
    _push(session_factory, dimitris, "disabled-present")
    _disable(session_factory, dimitris, "disabled-present")
    _push(session_factory, desktop, "undecided-present")
    local = {
        "enabled-edited": local_digests("enabled-edited", files={"x.md": "mine\n"}),
        "disabled-present": local_digests("disabled-present"),
        "undecided-present": local_digests("undecided-present"),
        "orphan": local_digests("orphan"),
    }

    def snapshot():
        with session_factory() as session:
            return (
                sorted(session.execute(select(MachineSkill.machine_id, MachineSkill.skill_id,
                                              MachineSkill.enabled)).all()),
                session.scalar(select(func.count()).select_from(SkillVersion)),
            )

    before = snapshot()
    report = _sync(session_factory, dimitris, local)
    _sync(session_factory, dimitris, local)

    assert [question.name for question in report.ask] == [
        "disabled-present", "enabled-edited", "undecided-present"]
    assert report.backup == ("orphan",)
    assert snapshot() == before
