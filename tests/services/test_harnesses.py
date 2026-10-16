"""A skill is placed per computer and harness, and each folder is synced on its own (ADR-0018)."""

import hashlib
from typing import get_args

import pytest
from sqlalchemy import select

from aistack.bundled import SYNC_SKILL_NAME, sync_skill_document
from aistack.commons.exceptions import NotFound, ValidationError
from aistack.db.engine import build_session_factory
from aistack.db.models.harness import Harness
from aistack.db.models.machine_harness import MachineHarness
from aistack.db.models.machine_skill import MachineSkill
from aistack.services import dashboard_service, onboarding_service, skill_service, sync_service
from aistack.services.harnesses import HARNESSES, HarnessKey
from aistack.services.sync_service import Install
from tests.archives import local_digests, skill_archive

AGENTS = "agents"
CLAUDE_CODE = "claude_code"


@pytest.fixture(name="session_factory")
def session_factory_fixture(portable_engine):
    return build_session_factory(portable_engine)


@pytest.fixture(name="dimitris")
def dimitris_fixture(session_factory):
    with session_factory.begin() as session:
        return onboarding_service.join(session, "dimitris", "macbook", "MACOS")


def _ids(joined):
    return joined.machine.machine_id, joined.user.user_id


def _push(session_factory, joined, name="wizard", harness=None, **archive):
    with session_factory.begin() as session:
        return skill_service.push(session, *_ids(joined), name=name, origin=None,
                                  archive=skill_archive(name, **archive), harness=harness)


def _get(session_factory, joined, name="wizard", harness=None):
    with session_factory.begin() as session:
        return skill_service.get_skill(session, *_ids(joined), name, harness=harness)


def _disable(session_factory, joined, name="wizard", harness=None):
    with session_factory.begin() as session:
        return skill_service.disable_skill(session, *_ids(joined), name, harness=harness)


def _sync(session_factory, joined, local, harness=None):
    with session_factory.begin() as session:
        return sync_service.sync(session, *_ids(joined), local, harness)


def _decisions(session_factory):
    with session_factory() as session:
        return sorted(session.execute(select(MachineSkill.harness, MachineSkill.enabled)).all())


# --- an unknown harness ---------------------------------------------------------------------

REFUSED = "harness must be one of claude_code, agents. Received: 'codex'."


@pytest.mark.parametrize("call", [
    lambda factory, joined: _push(factory, joined, harness="codex"),
    lambda factory, joined: _get(factory, joined, harness="codex"),
    lambda factory, joined: _disable(factory, joined, harness="codex"),
    lambda factory, joined: _sync(factory, joined, {}, harness="codex"),
], ids=["push", "get_skill", "disable_skill", "sync"])
def test_an_unknown_harness_is_refused_naming_what_was_received_and_what_is_allowed(
        session_factory, dimitris, call):
    _push(session_factory, dimitris)
    before = _decisions(session_factory)

    with pytest.raises(ValidationError) as rejection:
        call(session_factory, dimitris)

    assert str(rejection.value) == REFUSED
    assert _decisions(session_factory) == before


def test_the_dashboard_refuses_an_unknown_harness_the_same_way(session_factory, dimitris):
    _push(session_factory, dimitris)

    with pytest.raises(ValidationError) as rejection:
        with session_factory.begin() as session:
            dashboard_service.set_on_machine(session, dimitris.user.user_id, "wizard",
                                             str(dimitris.machine.machine_id), True, "codex")

    assert str(rejection.value) == REFUSED


def test_a_harness_that_is_not_text_is_refused_without_a_crash(session_factory, dimitris):
    with pytest.raises(ValidationError, match="harness must be one of"):
        _sync(session_factory, dimitris, {}, harness=["agents"])


def test_the_tool_schema_offers_exactly_the_stored_harnesses():
    assert get_args(HarnessKey) == tuple(Harness) == tuple(HARNESSES)


# --- the default is the old behaviour -------------------------------------------------------

def test_naming_no_harness_means_claude_code(session_factory, dimitris):
    _push(session_factory, dimitris)

    assert _decisions(session_factory) == [(Harness.CLAUDE_CODE, True)]
    _sync(session_factory, dimitris, {})
    assert _sync(session_factory, dimitris, {}) == _sync(session_factory, dimitris, {},
                                                         CLAUDE_CODE)


# --- each folder is its own decision --------------------------------------------------------

def test_a_push_from_one_harness_places_the_skill_there_only(session_factory, dimitris):
    _push(session_factory, dimitris, harness=AGENTS)

    assert _decisions(session_factory) == [(Harness.AGENTS, True)]
    assert _sync(session_factory, dimitris, {}, AGENTS).install == (
        Install("wizard", 1, "dimitris"),)
    # Never decided in Claude Code, and absent there: nothing to say.
    nothing = _sync(session_factory, dimitris, {})
    assert (nothing.install, nothing.ask, nothing.backup) == ((), (), ())


def test_a_decision_in_one_harness_never_reaches_the_other(session_factory, dimitris):
    _push(session_factory, dimitris)
    _get(session_factory, dimitris, harness=AGENTS)
    _disable(session_factory, dimitris, harness=AGENTS)
    on_disk = {"wizard": local_digests()}

    claude_code = _sync(session_factory, dimitris, on_disk)
    agents = _sync(session_factory, dimitris, on_disk, AGENTS)

    assert claude_code.up_to_date == 1 and claude_code.ask == ()
    assert [(question.name, question.desired.value) for question in agents.ask] == [
        ("wizard", "disabled")]


def test_a_skill_only_one_harness_decided_about_is_undecided_in_the_other(session_factory,
                                                                         dimitris):
    _push(session_factory, dimitris)

    report = _sync(session_factory, dimitris, {"wizard": local_digests()}, AGENTS)

    assert [(question.desired.value, question.local.value) for question in report.ask] == [
        ("undecided", "current")]
    assert report.backup == ()


def test_disabling_in_a_harness_that_never_had_it_is_refused(session_factory, dimitris):
    _push(session_factory, dimitris)

    with pytest.raises(NotFound, match="never enabled on this machine in harness 'agents'"):
        _disable(session_factory, dimitris, harness=AGENTS)

    assert _decisions(session_factory) == [(Harness.CLAUDE_CODE, True)]


def test_removing_from_the_library_turns_it_off_in_every_harness(session_factory, dimitris):
    _push(session_factory, dimitris)
    _get(session_factory, dimitris, harness=AGENTS)

    with session_factory.begin() as session:
        skill_service.remove_from_my_skills(session, dimitris.user.user_id, "wizard")

    assert _decisions(session_factory) == [(Harness.AGENTS, False),
                                           (Harness.CLAUDE_CODE, False)]


# --- where to install -----------------------------------------------------------------------

@pytest.mark.parametrize(("os", "harness", "folder"), [
    ("MACOS", None, "~/.claude/skills"),
    ("LINUX", AGENTS, "~/.agents/skills"),
    ("WINDOWS", CLAUDE_CODE, "$HOME\\.claude\\skills"),
    ("WINDOWS", AGENTS, "$HOME\\.agents\\skills"),
])
def test_get_skill_says_which_folder_to_install_into(session_factory, os, harness, folder):
    with session_factory.begin() as session:
        joined = onboarding_service.join(session, "dimitris", "box", os)
    _push(session_factory, joined)

    assert _get(session_factory, joined, harness=harness).folder == folder


# --- which harnesses a machine has ----------------------------------------------------------

def test_sync_records_the_harness_and_when_it_last_synced(session_factory, dimitris):
    def synced():
        with session_factory() as session:
            return dict(session.execute(select(MachineHarness.harness,
                                               MachineHarness.last_synced_on)).all())

    assert synced() == {}

    _sync(session_factory, dimitris, {}, AGENTS)
    first = synced()
    _sync(session_factory, dimitris, {}, AGENTS)
    _sync(session_factory, dimitris, {})
    second = synced()

    assert set(first) == {Harness.AGENTS}
    assert set(second) == {Harness.AGENTS, Harness.CLAUDE_CODE}
    assert second[Harness.AGENTS] > first[Harness.AGENTS]


def test_a_folders_first_sync_on_a_machine_is_reported_once(session_factory, dimitris):
    """It is when the agent offers to put the other folder's skills here too (ADR-0021)."""
    assert _sync(session_factory, dimitris, {}).first_sync is True
    assert _sync(session_factory, dimitris, {}).first_sync is False
    assert _sync(session_factory, dimitris, {}, AGENTS).first_sync is True
    assert _sync(session_factory, dimitris, {}, AGENTS).first_sync is False


def test_the_sync_skill_goes_into_the_agents_folder_only_where_setup_put_it(session_factory,
                                                                         dimitris):
    """There it would tell an agent with no connection to AIStack to sync (ADR-0021)."""
    assert _sync(session_factory, dimitris, {}).refresh_sync_skill is True
    assert _sync(session_factory, dimitris, {}, AGENTS).refresh_sync_skill is False
    stale = {SYNC_SKILL_NAME: local_digests(SYNC_SKILL_NAME)}
    assert _sync(session_factory, dimitris, stale, AGENTS).refresh_sync_skill is True


def test_a_computer_whose_claude_code_never_synced_gets_the_sync_skill_in_the_agents_folder(
        session_factory, dimitris):
    """PH-06: a computer added with add_machine and only Codex there. Codex is the agent
    connected to AIStack, and nothing else would ever put the sync skill in its folder."""
    assert _sync(session_factory, dimitris, {}, AGENTS).refresh_sync_skill is True
    current = {SYNC_SKILL_NAME: {"SKILL.md": hashlib.sha256(
        sync_skill_document().encode("utf-8")).hexdigest()}}
    assert _sync(session_factory, dimitris, current, AGENTS).refresh_sync_skill is False


def _state(session_factory, joined):
    with session_factory() as session:
        return dashboard_service.state(session, joined.user.user_id)


def test_a_computer_that_never_synced_shows_no_folder(session_factory, dimitris):
    """UX-07: shown with Claude Code, a computer added for Codex invited placements in a
    folder no agent there syncs."""
    assert _state(session_factory, dimitris)["machines"][0]["harnesses"] == []


def test_a_computer_shows_the_harnesses_that_synced_or_hold_a_decision(session_factory,
                                                                      dimitris):
    _sync(session_factory, dimitris, {}, AGENTS)
    assert _state(session_factory, dimitris)["machines"][0]["harnesses"] == [AGENTS]

    _push(session_factory, dimitris)
    state = _state(session_factory, dimitris)

    assert state["machines"][0]["harnesses"] == [CLAUDE_CODE, AGENTS]
    assert state["skills"][0]["placements"] == [
        {"machine": str(dimitris.machine.machine_id), "harness": CLAUDE_CODE, "revision": 1,
         "project": None}]


def test_the_dashboard_places_a_skill_in_one_harness(session_factory, dimitris):
    _push(session_factory, dimitris)
    machine = str(dimitris.machine.machine_id)

    with session_factory.begin() as session:
        dashboard_service.set_on_machine(session, dimitris.user.user_id, "wizard", machine,
                                         True, AGENTS)
        dashboard_service.set_on_machine(session, dimitris.user.user_id, "wizard", machine,
                                         False)

    assert _state(session_factory, dimitris)["skills"][0]["placements"] == [
        {"machine": machine, "harness": AGENTS, "revision": None, "project": None}]
