"""Teams, groups, and a personal space per user (ADR-0015), as rules a user would state."""

import threading
from datetime import timedelta

import pytest
from sqlalchemy import delete, event, func, select

from aistack.commons.exceptions import Conflict, NotFound, ValidationError
from aistack.db.engine import build_session_factory
from aistack.db.models.skill import Skill
from aistack.db.models.invite import Invite
from aistack.db.models.machine import Machine
from aistack.db.models.team import GroupUnsubscribed, Team, TeamKind, TeamMember, TeamRole
from aistack.db.models.timestamps import as_utc, utc_now
from aistack.services import (
    dashboard_service,
    onboarding_service,
    operator_service,
    skill_service,
    sync_service,
    team_service,
)
from tests.archives import local_digests, skill_archive
from tests.teams import make_team


@pytest.fixture(name="session_factory")
def session_factory_fixture(portable_engine):
    return build_session_factory(portable_engine)


def _join(session_factory, username):
    with session_factory.begin() as session:
        return onboarding_service.join(session, username, "laptop", "LINUX")


@pytest.fixture(name="dimitris")
def dimitris_fixture(session_factory):
    return _join(session_factory, "dimitris")


@pytest.fixture(name="maria")
def maria_fixture(session_factory):
    return _join(session_factory, "maria")


@pytest.fixture(name="eve")
def eve_fixture(session_factory):
    """On the server, and in none of the others' teams."""
    return _join(session_factory, "eve")


@pytest.fixture(name="acme")
def acme_fixture(session_factory, dimitris, maria):
    """A team dimitris created and maria joined with its invite code."""
    with session_factory.begin() as session:
        make_team(session, "acme", dimitris.user.user_id, maria.user.user_id)
    return "acme"


def _do(session_factory, function, *args, **kwargs):
    with session_factory.begin() as session:
        return function(session, *args, **kwargs)


def _push(session_factory, joined, name="wizard", **archive):
    return _do(session_factory, skill_service.push, machine_id=joined.machine.machine_id,
               user_id=joined.user.user_id, name=name, origin=None,
               archive=skill_archive(name, **archive))


def _share(session_factory, joined, team, name="wizard", group=None):
    return _do(session_factory, skill_service.share, joined.user.user_id, name, team, group)


def _take(session_factory, joined, team, name="wizard"):
    return _do(session_factory, skill_service.get_skill, joined.machine.machine_id,
               joined.user.user_id, name, team)


def _listing(session_factory, joined) -> list[tuple]:
    return [(skill.team, skill.group, skill.name)
            for skill in _do(session_factory, skill_service.list_skills, joined.user.user_id)]


def _sync(session_factory, joined, local):
    return _do(session_factory, sync_service.sync, joined.machine.machine_id,
               joined.user.user_id, local)


def _same_sentence(first, name, second, other_name) -> bool:
    return str(first.value).replace(name, "X") == str(second.value).replace(other_name, "X")


# --- joining --------------------------------------------------------------------------------

def test_joining_puts_a_user_in_their_own_team_and_no_other(session_factory, dimitris, maria):
    with session_factory() as session:
        memberships = session.execute(
            select(Team.name, Team.kind, TeamMember.role)
            .join(TeamMember, TeamMember.team_id == Team.team_id)
            .where(TeamMember.user_id == maria.user.user_id).order_by(Team.name)).all()

    # No server-wide team any more (ADR-0019): a team is joined with its invite.
    assert memberships == [("maria", TeamKind.PERSONAL, TeamRole.ADMIN)]


def test_a_username_that_is_already_a_team_is_taken(session_factory, dimitris, maria, acme):
    """A personal team carries its user's name, so the two share one namespace."""
    with pytest.raises(Conflict, match="already taken, by a user or by a team") as as_a_team:
        _join(session_factory, "acme")
    with pytest.raises(Conflict) as as_a_user:
        _join(session_factory, "maria")

    # PH-16: a team's name is not explained as "you on a new computer" alone, and which of the
    # two holds a name is not said, as `create_team` does not say it.
    assert str(as_a_team.value).replace("acme", "X") == str(as_a_user.value).replace("maria", "X")


# --- my skills are mine ---------------------------------------------------------------------


def test_the_listing_narrows_to_a_team_or_to_words(session_factory, dimitris, maria, acme):
    """IMP-12: the listing had no filter, so a search read everything."""
    _push(session_factory, dimitris, "wizard", description="Casts spells.")
    _push(session_factory, dimitris, "release-notes", description="Builds release notes.")
    _share(session_factory, dimitris, acme, "release-notes")

    def names(**narrowed):
        return [(skill.team, skill.name) for skill in _do(
            session_factory, skill_service.list_skills, dimitris.user.user_id, **narrowed)]

    assert names(team="acme") == [("acme", "release-notes")]
    assert names(query="SPELL") == [(None, "wizard")]
    assert names(query="release", team="acme") == [("acme", "release-notes")]
    # Words are words: a % in them is matched as itself, not as a pattern.
    assert names(query="%") == []
    assert names(team="nowhere") == []

def test_a_pushed_skill_is_seen_by_nobody_else(session_factory, dimitris, maria):
    _push(session_factory, dimitris)

    assert _listing(session_factory, dimitris) == [(None, None, "wizard")]
    assert _listing(session_factory, maria) == []
    with pytest.raises(NotFound):
        _do(session_factory, skill_service.get_skill, maria.machine.machine_id,
            maria.user.user_id, "wizard")


def test_a_skill_on_disk_that_is_not_yet_mine_is_backed_up_not_asked_about(session_factory,
                                                                          dimitris):
    report = _sync(session_factory, dimitris, {"wizard": local_digests()})
    assert report.backup == ("wizard",) and report.ask == ()

    _push(session_factory, dimitris)

    after = _sync(session_factory, dimitris, {"wizard": local_digests()})
    assert after.backup == () and after.up_to_date == 1


def test_a_download_url_works_only_for_one_of_the_machines_users_own_skills(session_factory,
                                                                           dimitris, maria):
    _push(session_factory, dimitris)
    with session_factory() as session:
        version_id = skill_service.get_skill(session, dimitris.machine.machine_id,
                                             dimitris.user.user_id, "wizard").skill_version_id

    with pytest.raises(NotFound, match="no longer exists"):
        _do(session_factory, skill_service.archive_of, maria.machine.machine_id, version_id)


# --- sharing and taking ---------------------------------------------------------------------

def test_sharing_puts_a_copy_in_front_of_the_team_and_says_who_shared_it(session_factory,
                                                                        dimitris, maria, acme):
    _push(session_factory, dimitris)

    shared = _share(session_factory, dimitris, acme)

    assert (shared.team, shared.revision, shared.created, shared.possibly_unrelated) == (
        "acme", 1, True, False)
    assert _listing(session_factory, maria) == [("acme", None, "wizard")]
    listed = _do(session_factory, skill_service.list_skills, maria.user.user_id)[0]
    assert listed.pushed_by == "dimitris"


def test_taking_a_teams_skill_makes_it_your_own_and_installs_it(session_factory, dimitris,
                                                               maria, acme):
    _push(session_factory, dimitris, files={"notes.md": "by dimitris\n"})
    _share(session_factory, dimitris, acme)

    taken = _take(session_factory, maria, acme)

    assert (taken.revision, taken.pushed_by) == (1, "dimitris")
    assert _listing(session_factory, maria) == [(None, None, "wizard"),
                                                ("acme", None, "wizard")]
    local = {"wizard": local_digests(files={"notes.md": "by dimitris\n"})}
    assert _sync(session_factory, maria, local).up_to_date == 1


def test_a_skill_you_took_stays_yours_after_you_leave_the_team(session_factory, dimitris,
                                                              maria, acme):
    _push(session_factory, dimitris)
    _share(session_factory, dimitris, acme)
    _take(session_factory, maria, acme)

    _do(session_factory, team_service.leave_team, maria.user.user_id, acme)

    assert _listing(session_factory, maria) == [(None, None, "wizard")]
    report = _sync(session_factory, maria, {"wizard": local_digests()})
    assert report.up_to_date == 1 and report.ask == () and report.team_updates == ()
    # And an install link for it still works: it is her own skill.
    reinstalled = _do(session_factory, skill_service.get_skill, maria.machine.machine_id,
                      maria.user.user_id, "wizard")
    assert _do(session_factory, skill_service.archive_of, maria.machine.machine_id,
               reinstalled.skill_version_id)[0] == "wizard"


def test_a_teammates_change_is_offered_and_never_applied_unasked(session_factory, dimitris,
                                                                maria, acme):
    _push(session_factory, dimitris, files={"notes.md": "one\n"})
    _share(session_factory, dimitris, acme)
    _take(session_factory, maria, acme)
    _push(session_factory, dimitris, files={"notes.md": "two\n"})
    _share(session_factory, dimitris, acme)
    local = {"wizard": local_digests(files={"notes.md": "one\n"})}

    offered = _sync(session_factory, maria, local)

    assert offered.update == () and offered.install == () and offered.up_to_date == 1
    assert [(update.name, update.team, update.from_revision, update.to_revision,
             update.pushed_by) for update in offered.team_updates] == [
        ("wizard", "acme", 1, 2, "dimitris")]

    # Saying yes: take it, and then it is an ordinary update of her own skill.
    _take(session_factory, maria, acme)
    accepted = _sync(session_factory, maria, local)
    assert accepted.team_updates == ()
    assert [(update.from_revision, update.to_revision, update.pushed_by)
            for update in accepted.update] == [(1, 2, "dimitris")]


def test_the_one_who_shared_is_not_offered_their_own_change(session_factory, dimitris, acme):
    _push(session_factory, dimitris)
    _share(session_factory, dimitris, acme)

    assert _sync(session_factory, dimitris, {"wizard": local_digests()}).team_updates == ()


def test_any_member_may_change_a_teams_skill_and_it_says_who_did(session_factory, dimitris,
                                                                maria, acme):
    _push(session_factory, dimitris)
    _share(session_factory, dimitris, acme)
    _take(session_factory, maria, acme)
    _push(session_factory, maria, files={"notes.md": "improved by maria\n"})

    shared = _share(session_factory, maria, acme)

    assert (shared.revision, shared.previous_pushed_by, shared.possibly_unrelated) == (
        2, "dimitris", False)
    offered = _sync(session_factory, dimitris, {"wizard": local_digests()}).team_updates
    assert [(update.to_revision, update.pushed_by) for update in offered] == [(2, "maria")]


def test_sharing_over_a_teams_skill_you_never_took_is_flagged(session_factory, dimitris,
                                                             maria, acme):
    """Two people who each wrote a skill called wizard. The second share is told so."""
    _push(session_factory, dimitris, files={"x.md": "dimitris's\n"})
    _share(session_factory, dimitris, acme)
    _push(session_factory, maria, files={"x.md": "maria's unrelated one\n"})

    shared = _share(session_factory, maria, acme)

    assert (shared.revision, shared.possibly_unrelated, shared.previous_pushed_by) == (
        2, True, "dimitris")


def test_sharing_exactly_what_the_team_has_adds_nothing(session_factory, dimitris, acme):
    _push(session_factory, dimitris)
    _share(session_factory, dimitris, acme)

    again = _share(session_factory, dimitris, acme)

    assert (again.revision, again.unchanged) == (1, True)


# --- what someone outside a team is told ----------------------------------------------------

def _mine(session_factory, joined, name="wizard") -> tuple[int, str]:
    listed = {skill.name: skill for skill in _do(session_factory, skill_service.list_skills,
                                                 joined.user.user_id) if skill.team is None}
    return listed[name].revision, listed[name].pushed_by


def test_taking_a_namesake_you_never_took_is_refused_until_you_say_replace(session_factory,
                                                                          dimitris, maria,
                                                                          acme):
    """maria's own wizard is a different skill from the one dimitris shared as wizard."""
    _push(session_factory, maria, files={"x.md": "maria's own\n"})
    _push(session_factory, dimitris, files={"x.md": "dimitris's\n"})
    _share(session_factory, dimitris, acme)

    with pytest.raises(Conflict) as refused:
        _take(session_factory, maria, acme)

    assert ("your own 'wizard' (revision 1, last pushed by maria) that was not taken from team "
            "'acme'" in str(refused.value))
    assert "replaces yours on laptop at their next sync" in str(refused.value)
    assert _mine(session_factory, maria) == (1, "maria")

    taken = _do(session_factory, skill_service.get_skill, maria.machine.machine_id,
                maria.user.user_id, "wizard", acme, replace=True)

    assert (taken.revision, taken.pushed_by) == (2, "dimitris")
    assert _mine(session_factory, maria) == (2, "dimitris")


def test_taking_a_namesake_with_the_same_content_needs_no_replace(session_factory, dimitris,
                                                                 maria, acme):
    _push(session_factory, maria)
    _push(session_factory, dimitris)
    _share(session_factory, dimitris, acme)

    assert _take(session_factory, maria, acme).revision == 1


def test_an_update_over_your_own_changes_is_offered_as_one(session_factory, dimitris, maria,
                                                          acme):
    _push(session_factory, dimitris, files={"notes.md": "one\n"})
    _share(session_factory, dimitris, acme)
    _take(session_factory, maria, acme)
    _push(session_factory, maria, files={"notes.md": "maria's edit\n"})
    _push(session_factory, dimitris, files={"notes.md": "two\n"})
    _share(session_factory, dimitris, acme)

    local = {"wizard": local_digests(files={"notes.md": "maria's edit\n"})}
    offered = _sync(session_factory, maria, local).team_updates
    with session_factory() as session:
        source = next(skill["source"] for skill in dashboard_service.state(
            session, maria.user.user_id)["skills"] if skill["name"] == "wizard")

    assert [(update.from_revision, update.to_revision, update.own_changes)
            for update in offered] == [(1, 2, True)]
    assert (source["update_available"], source["own_changes"]) == (True, True)
    # Her copy follows acme, so accepting needs no replace.
    assert _take(session_factory, maria, acme).pushed_by == "dimitris"


def test_an_update_with_no_changes_of_yours_says_so(session_factory, dimitris, maria, acme):
    _push(session_factory, dimitris, files={"notes.md": "one\n"})
    _share(session_factory, dimitris, acme)
    _take(session_factory, maria, acme)
    _push(session_factory, dimitris, files={"notes.md": "two\n"})
    _share(session_factory, dimitris, acme)

    offered = _sync(session_factory, maria, {"wizard": local_digests(
        files={"notes.md": "one\n"})}).team_updates

    assert [update.own_changes for update in offered] == [False]


def test_sharing_an_edit_of_an_older_team_revision_names_the_one_it_replaced(session_factory,
                                                                            dimitris, maria,
                                                                            acme):
    _push(session_factory, dimitris, files={"notes.md": "rule A\n"})
    _share(session_factory, dimitris, acme)
    _take(session_factory, maria, acme)
    _push(session_factory, dimitris, files={"notes.md": "rule A\nrule B\n"})
    _share(session_factory, dimitris, acme)
    _push(session_factory, maria, files={"notes.md": "rule A\nrule C\n"})

    shared = _share(session_factory, maria, acme)

    assert (shared.revision, shared.overwrote_revision, shared.previous_pushed_by,
            shared.possibly_unrelated) == (3, 2, "dimitris", False)


def test_sharing_from_the_latest_team_revision_replaces_nothing_unseen(session_factory,
                                                                      dimitris, maria, acme):
    _push(session_factory, dimitris)
    _share(session_factory, dimitris, acme)
    _take(session_factory, maria, acme)
    _push(session_factory, maria, files={"notes.md": "maria's edit\n"})

    assert _share(session_factory, maria, acme).overwrote_revision is None


def test_a_skill_taken_from_one_team_and_shared_with_another_still_follows_the_first(
        session_factory, dimitris, maria, acme):
    with session_factory.begin() as session:
        make_team(session, "beta", maria.user.user_id)
    _push(session_factory, dimitris, files={"notes.md": "one\n"})
    _share(session_factory, dimitris, acme)
    _take(session_factory, maria, acme)

    shared = _share(session_factory, maria, "beta")
    assert (shared.created, shared.updates_from) == (True, "acme")
    _push(session_factory, maria, files={"notes.md": "one, for beta\n"})
    # Her second share into beta goes over what her first put there: nothing unrelated.
    again = _share(session_factory, maria, "beta")
    assert (again.revision, again.possibly_unrelated, again.updates_from) == (2, False, "acme")

    _push(session_factory, dimitris, files={"notes.md": "two\n"})
    _share(session_factory, dimitris, acme)
    offered = _sync(session_factory, maria, {"wizard": local_digests(
        files={"notes.md": "one, for beta\n"})}).team_updates

    assert [(update.team, update.to_revision, update.own_changes)
            for update in offered] == [("acme", 2, True)]


def test_a_team_you_are_not_in_reads_exactly_like_one_that_does_not_exist(session_factory,
                                                                         dimitris, eve, acme):
    _push(session_factory, dimitris)
    _share(session_factory, dimitris, acme)
    _push(session_factory, eve)

    with pytest.raises(NotFound) as hidden:
        _take(session_factory, eve, "acme")
    with pytest.raises(NotFound) as absent:
        _take(session_factory, eve, "nowhere")
    assert _same_sentence(hidden, "acme", absent, "nowhere")

    with pytest.raises(NotFound) as hidden:
        _share(session_factory, eve, "acme")
    with pytest.raises(NotFound) as absent:
        _share(session_factory, eve, "nowhere")
    assert _same_sentence(hidden, "acme", absent, "nowhere")

    for function, args in ((team_service.members, ()), (team_service.groups, ()),
                           (team_service.leave_team, ()),
                           (team_service.new_invite_code, ())):
        with pytest.raises(NotFound, match="not in a team named 'acme'"):
            _do(session_factory, function, eve.user.user_id, "acme", *args)
    assert _listing(session_factory, eve) == [(None, None, "wizard")]
    assert _do(session_factory, team_service.list_teams, eve.user.user_id) == []


def test_a_personal_team_cannot_be_reached_as_a_team(session_factory, dimitris, maria):
    """Naming someone's personal team gets the same answer as naming nothing."""
    _push(session_factory, dimitris)
    _push(session_factory, maria)

    for owner in ("dimitris", "maria"):
        with pytest.raises(NotFound, match="not in a team named"):
            _share(session_factory, maria, owner)
        with pytest.raises(NotFound):
            _take(session_factory, maria, owner)


# --- invite codes ---------------------------------------------------------------------------

def _members_of(session_factory, team) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(TeamMember).join(
            Team, Team.team_id == TeamMember.team_id).where(Team.name == team))


def _statuses(session_factory, joined, team) -> list[str]:
    return [invite.status for invite in
            _do(session_factory, team_service.invites, joined.user.user_id, team)]


def test_every_invite_admits_one_person_and_a_newer_one_cancels_nothing(session_factory,
                                                                        dimitris, eve, acme):
    frank = _join(session_factory, "frank")
    first = _do(session_factory, team_service.new_invite_code, dimitris.user.user_id, acme)
    second = _do(session_factory, team_service.new_invite_code, dimitris.user.user_id, acme)

    assert _do(session_factory, team_service.join_team, eve.user.user_id, first) == "acme"
    assert _do(session_factory, team_service.join_team, frank.user.user_id, second) == "acme"

    # Used once, it admits nobody else, and says so without repeating the code.
    late = _join(session_factory, "late")
    with pytest.raises(NotFound) as rejection:
        _do(session_factory, team_service.join_team, late.user.user_id, first)
    assert first not in str(rejection.value)
    assert _members_of(session_factory, "acme") == 4


def test_a_member_using_an_invite_again_leaves_it_for_someone_else(session_factory, dimitris,
                                                                   maria, eve, acme):
    code = _do(session_factory, team_service.new_invite_code, dimitris.user.user_id, acme)

    assert _do(session_factory, team_service.join_team, maria.user.user_id, code) == "acme"
    assert _do(session_factory, team_service.join_team, eve.user.user_id, code) == "acme"
    assert _members_of(session_factory, "acme") == 3


def test_the_invite_link_works_wherever_the_code_does(session_factory, dimitris, eve, acme):
    code = _do(session_factory, team_service.new_invite_code, dimitris.user.user_id, acme)
    link = f" https://aistack.example.com/invite/{code}/\n"

    assert _do(session_factory, team_service.join_team, eve.user.user_id, link) == "acme"


def test_a_cancelled_invite_admits_nobody(session_factory, dimitris, maria, eve, acme):
    _do(session_factory, team_service.set_member, dimitris.user.user_id, acme, "maria",
        can_invite=True)
    hers = _do(session_factory, team_service.new_invite_code, maria.user.user_id, acme)
    his = _do(session_factory, team_service.new_invite_code, dimitris.user.user_id, acme)
    ids = {invite.created_by: invite.invite_id for invite in
           _do(session_factory, team_service.invites, dimitris.user.user_id, acme)
           if invite.status == "PENDING"}

    # She may cancel her own and not his; an admin may cancel anyone's.
    with pytest.raises(NotFound):
        _do(session_factory, team_service.cancel_invite, maria.user.user_id, acme,
            ids["dimitris"])
    _do(session_factory, team_service.cancel_invite, dimitris.user.user_id, acme, ids["maria"])
    _do(session_factory, team_service.cancel_invite, dimitris.user.user_id, acme,
        ids["dimitris"])

    for code in (hers, his):
        with pytest.raises(NotFound, match="not a team invite code"):
            _do(session_factory, team_service.join_team, eve.user.user_id, code)


def test_an_invite_expires_after_seven_days(session_factory, dimitris, eve, acme):
    code = _do(session_factory, team_service.new_invite_code, dimitris.user.user_id, acme)
    with session_factory.begin() as session:
        # The fixture's invite, which maria used, is the other one.
        invite = session.scalar(select(Invite).where(Invite.used_on.is_(None)))
        assert as_utc(invite.expires_on) - as_utc(invite.created_on) == timedelta(days=7)
        invite.expires_on = utc_now() - timedelta(seconds=1)

    with pytest.raises(NotFound, match="not a team invite code"):
        _do(session_factory, team_service.join_team, eve.user.user_id, code)
    assert sorted(_statuses(session_factory, dimitris, acme)) == ["ACCEPTED", "EXPIRED"]


def test_two_people_using_one_invite_at_once_let_exactly_one_in(session_factory, portable_engine,
                                                                dimitris, acme):
    if portable_engine.dialect.name == "sqlite":
        pytest.skip("SQLite admits one writer at a time (ADR-0014), so the second never reads "
                    "the invite pending; this race exists on PostgreSQL")
    code = _do(session_factory, team_service.new_invite_code, dimitris.user.user_id, acme)
    people = [_join(session_factory, name) for name in ("ann", "bob")]
    both_read_it = threading.Barrier(2)
    outcomes = []

    def use(person):
        try:
            with session_factory.begin() as session:
                # Both have seen the invite pending before either marks it used.
                team_service.invited_to(session, code)
                both_read_it.wait(timeout=5)
                outcomes.append(team_service.join_team(session, person.user.user_id, code))
        except NotFound:
            outcomes.append("refused")

    threads = [threading.Thread(target=use, args=(person,)) for person in people]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["acme", "refused"]
    assert _members_of(session_factory, "acme") == 3


def test_an_admin_sees_every_invite_and_an_inviter_only_their_own(session_factory, dimitris,
                                                                  maria, eve, acme):
    _do(session_factory, team_service.set_member, dimitris.user.user_id, acme, "maria",
        can_invite=True)
    used = _do(session_factory, team_service.new_invite_code, dimitris.user.user_id, acme)
    _do(session_factory, team_service.new_invite_code, maria.user.user_id, acme)
    _do(session_factory, team_service.join_team, eve.user.user_id, used)

    everything = _do(session_factory, team_service.invites, dimitris.user.user_id, acme)
    hers = _do(session_factory, team_service.invites, maria.user.user_id, acme)

    # The fixture's invite, which maria used, is among them.
    assert sorted((invite.created_by, invite.status, invite.used_by)
                  for invite in everything) == [("dimitris", "ACCEPTED", "eve"),
                                                ("dimitris", "ACCEPTED", "maria"),
                                                ("maria", "PENDING", None)]
    assert [(invite.created_by, invite.status) for invite in hers] == [("maria", "PENDING")]
    assert used not in repr(everything)
    with pytest.raises(ValidationError, match="Only an admin"):
        _do(session_factory, team_service.invites, eve.user.user_id, acme)


@pytest.mark.parametrize("code", ["", "aistinv_", "aistinv_wrong", "not-a-code", None])
def test_a_code_that_is_not_one_is_refused_without_being_repeated(session_factory, eve, acme,
                                                                 code):
    with pytest.raises(NotFound, match="not a team invite code"):
        _do(session_factory, team_service.join_team, eve.user.user_id, code)


def test_only_an_admin_can_make_an_invite_code(session_factory, maria, acme):
    with pytest.raises(ValidationError, match="Only an admin"):
        _do(session_factory, team_service.new_invite_code, maria.user.user_id, acme)


def test_a_member_an_admin_lets_invite_can_make_an_invite_code_and_nothing_else(
        session_factory, dimitris, maria, eve, acme):
    _do(session_factory, team_service.set_member, dimitris.user.user_id, acme, "maria",
        can_invite=True)

    code = _do(session_factory, team_service.new_invite_code, maria.user.user_id, acme)

    assert _do(session_factory, team_service.join_team, eve.user.user_id, code) == acme
    with pytest.raises(ValidationError, match="Only an admin"):
        _do(session_factory, team_service.create_group, maria.user.user_id, acme, "design")
    with pytest.raises(ValidationError, match="Only an admin"):
        _do(session_factory, team_service.set_member, maria.user.user_id, acme, "eve",
            can_invite=True)


def test_a_member_who_may_no_longer_invite_cannot(session_factory, dimitris, maria, acme):
    _do(session_factory, team_service.set_member, dimitris.user.user_id, acme, "maria",
        can_invite=True)
    _do(session_factory, team_service.set_member, dimitris.user.user_id, acme, "maria",
        can_invite=False)

    with pytest.raises(ValidationError, match="Only an admin"):
        _do(session_factory, team_service.new_invite_code, maria.user.user_id, acme)


def _cancelled_is_unknown(session_factory, code):
    """Whoever holds the code now, its maker included, is told what a wrong code is told."""
    stranger = _join(session_factory, "stranger")
    with pytest.raises(NotFound, match="not a team invite code"):
        _do(session_factory, team_service.join_team, stranger.user.user_id, code)
    with pytest.raises(NotFound, match="not a team invite code"):
        _do(session_factory, onboarding_service.join, "newcomer", "box", "LINUX",
            team_invite=code)


def _let_maria_invite(session_factory, dimitris, acme) -> None:
    _do(session_factory, team_service.set_member, dimitris.user.user_id, acme, "maria",
        can_invite=True)


def test_a_removed_members_invites_admit_nobody_themselves_included(session_factory, dimitris,
                                                                    maria, acme):
    _let_maria_invite(session_factory, dimitris, acme)
    hers = _do(session_factory, team_service.new_invite_code, maria.user.user_id, acme)

    _do(session_factory, team_service.remove_member, dimitris.user.user_id, acme, "maria")

    with pytest.raises(NotFound, match="not a team invite code"):
        _do(session_factory, team_service.join_team, maria.user.user_id, hers)
    _cancelled_is_unknown(session_factory, hers)
    assert "CANCELLED" in _statuses(session_factory, dimitris, acme)


def test_a_member_who_left_leaves_no_working_invite(session_factory, dimitris, maria, acme):
    _let_maria_invite(session_factory, dimitris, acme)
    hers = _do(session_factory, team_service.new_invite_code, maria.user.user_id, acme)

    _do(session_factory, team_service.leave_team, maria.user.user_id, acme)

    _cancelled_is_unknown(session_factory, hers)


@pytest.mark.parametrize("change", [{"role": "MEMBER"}, {"can_invite": False}],
                         ids=["demoted", "no-longer-inviting"])
def test_invites_die_when_their_maker_may_no_longer_invite(session_factory, dimitris, maria,
                                                          acme, change):
    _do(session_factory, team_service.set_member, dimitris.user.user_id, acme, "maria",
        role="ADMIN" if "role" in change else None, can_invite=True if "can_invite" in change
        else None)
    hers = _do(session_factory, team_service.new_invite_code, maria.user.user_id, acme)

    _do(session_factory, team_service.set_member, dimitris.user.user_id, acme, "maria",
        **change)

    _cancelled_is_unknown(session_factory, hers)
    assert "CANCELLED" in _statuses(session_factory, dimitris, acme)


def test_an_admin_keeping_the_right_to_invite_keeps_their_invites(session_factory, dimitris,
                                                                  maria, eve, acme):
    _do(session_factory, team_service.set_member, dimitris.user.user_id, acme, "maria",
        role="ADMIN", can_invite=True)
    hers = _do(session_factory, team_service.new_invite_code, maria.user.user_id, acme)

    # Demoted, she may still invite, so what she made still works.
    _do(session_factory, team_service.set_member, dimitris.user.user_id, acme, "maria",
        role="MEMBER")

    assert _do(session_factory, team_service.join_team, eve.user.user_id, hers) == acme


def test_an_invite_from_someone_taken_off_the_server_admits_nobody(session_factory, dimitris,
                                                                   maria, acme):
    """OPERATING.md 'Someone left' deletes their machines and touches nothing in the team."""
    _let_maria_invite(session_factory, dimitris, acme)
    hers = _do(session_factory, team_service.new_invite_code, maria.user.user_id, acme)
    with session_factory.begin() as session:
        session.execute(delete(Machine).where(Machine.user_id == maria.user.user_id))

    _cancelled_is_unknown(session_factory, hers)


# --- admins and members ---------------------------------------------------------------------

@pytest.mark.parametrize(("action", "arguments"), [
    (team_service.remove_member, ("dimitris",)),
    (team_service.set_member, ("maria", "ADMIN")),
    (team_service.create_group, ("backend",)),
    (team_service.set_group, ("design", True)),
    (team_service.set_group_member, ("design", "maria", True)),
    (team_service.move_skill, ("wizard", "design")),
    (team_service.remove_skill, ("wizard",)),
])
def test_a_member_cannot_do_what_only_an_admin_may(session_factory, dimitris, maria, acme,
                                                  action, arguments):
    _do(session_factory, team_service.create_group, dimitris.user.user_id, acme, "design")
    _push(session_factory, dimitris)
    _share(session_factory, dimitris, acme)

    with pytest.raises(ValidationError, match="Only an admin"):
        _do(session_factory, action, maria.user.user_id, acme, *arguments)


def test_a_team_always_keeps_an_admin(session_factory, dimitris, maria, acme):
    for attempt in (lambda s: team_service.leave_team(s, dimitris.user.user_id, acme),
                    lambda s: team_service.set_member(s, dimitris.user.user_id, acme,
                                                      "dimitris", "MEMBER")):
        with pytest.raises(Conflict, match="no admin"):
            with session_factory.begin() as session:
                attempt(session)

    _do(session_factory, team_service.set_member, dimitris.user.user_id, acme, "maria", "ADMIN")
    assert _do(session_factory, team_service.leave_team, dimitris.user.user_id, acme) == "acme"


def test_removing_a_member_ends_what_they_see_and_keeps_what_they_took(session_factory,
                                                                      dimitris, maria, acme):
    _push(session_factory, dimitris)
    _share(session_factory, dimitris, acme)
    _take(session_factory, maria, acme)

    _do(session_factory, team_service.remove_member, dimitris.user.user_id, acme, "maria")

    assert _listing(session_factory, maria) == [(None, None, "wizard")]
    with pytest.raises(NotFound):
        _take(session_factory, maria, acme)


def test_an_admin_removing_a_teams_skill_leaves_the_copies_people_took(session_factory,
                                                                      dimitris, maria, acme):
    _push(session_factory, dimitris)
    _share(session_factory, dimitris, acme)
    _take(session_factory, maria, acme)

    _do(session_factory, team_service.remove_skill, dimitris.user.user_id, acme, "wizard")

    assert _listing(session_factory, maria) == [(None, None, "wizard")]
    assert _sync(session_factory, maria, {"wizard": local_digests()}).up_to_date == 1
    with session_factory() as session:
        assert session.scalars(select(Skill.source_skill_id)).all() == [None, None]


def test_the_last_member_leaving_deletes_the_team_and_frees_its_name(session_factory,
                                                                     dimitris):
    _do(session_factory, team_service.create_team, dimitris.user.user_id, "solo")
    _push(session_factory, dimitris)
    _share(session_factory, dimitris, "solo")
    code = _do(session_factory, team_service.new_invite_code, dimitris.user.user_id, "solo")

    assert _do(session_factory, team_service.leave_team, dimitris.user.user_id, "solo") == "solo"

    assert _do(session_factory, team_service.list_teams, dimitris.user.user_id) == []
    assert _listing(session_factory, dimitris) == [(None, None, "wizard")]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Invite)
                              .join(Team, Team.team_id == Invite.team_id)
                              .where(Team.name == "solo")) == 0
    with pytest.raises(NotFound, match="not a team invite code"):
        _do(session_factory, team_service.join_team, dimitris.user.user_id, code)
    assert _do(session_factory, team_service.create_team, dimitris.user.user_id,
               "solo") == "solo"


def test_the_only_member_cannot_demote_themselves_and_is_told_what_to_do(session_factory,
                                                                        dimitris):
    _do(session_factory, team_service.create_team, dimitris.user.user_id, "solo")

    with pytest.raises(Conflict, match="only member of team 'solo'. Leave it or delete it"):
        _do(session_factory, team_service.set_member, dimitris.user.user_id, "solo",
            "dimitris", "MEMBER")


def test_an_admin_deletes_a_team_and_members_keep_their_library_copies(session_factory,
                                                                       dimitris, maria, acme):
    _push(session_factory, dimitris)
    _share(session_factory, dimitris, acme)
    _take(session_factory, maria, acme)
    _do(session_factory, team_service.create_group, dimitris.user.user_id, acme, "design")

    with pytest.raises(ValidationError, match="Only an admin"):
        _do(session_factory, team_service.delete_team, maria.user.user_id, acme)
    assert _do(session_factory, team_service.delete_team, dimitris.user.user_id, acme) == acme

    for person in (dimitris, maria):
        assert _do(session_factory, team_service.list_teams, person.user.user_id) == []
        assert _listing(session_factory, person) == [(None, None, "wizard")]
    # Maria's copy is still hers on her computer, and nothing offers her a team update.
    assert _sync(session_factory, maria, {"wizard": local_digests()}).up_to_date == 1
    with session_factory() as session:
        assert session.scalars(select(Skill.source_skill_id)).all() == [None, None]
        assert session.scalar(select(func.count()).select_from(Team)
                              .where(Team.name == acme)) == 0


def test_an_admin_outside_a_private_group_cannot_move_or_remove_its_skills(session_factory,
                                                                           dimitris, maria,
                                                                           acme):
    _do(session_factory, team_service.set_member, dimitris.user.user_id, acme, "maria", "ADMIN")
    _do(session_factory, team_service.create_group, maria.user.user_id, acme, "vault",
        private=True)
    _push(session_factory, maria)
    _share(session_factory, maria, acme, group="vault")

    for action, arguments in ((team_service.move_skill, ("wizard", None)),
                              (team_service.remove_skill, ("wizard",))):
        with pytest.raises(NotFound) as hidden:
            _do(session_factory, action, dimitris.user.user_id, acme, *arguments)
        with pytest.raises(NotFound) as missing:
            _do(session_factory, action, dimitris.user.user_id, acme,
                *(("sorcerer",) + arguments[1:]))
        assert _same_sentence(hidden, "wizard", missing, "sorcerer")


def _offboard(session_factory, username, successors=None):
    return _do(session_factory, operator_service.take_out_of_teams, username, successors)


def test_the_operator_names_an_admin_for_a_team_whose_admins_are_gone(session_factory,
                                                                     dimitris, maria, acme):
    with session_factory.begin() as session:
        session.execute(delete(Machine).where(Machine.user_id == dimitris.user.user_id))

    _do(session_factory, operator_service.name_admin, acme, "maria")

    assert _do(session_factory, team_service.new_invite_code, maria.user.user_id, acme)


def test_taking_someone_off_the_server_hands_over_the_teams_they_ran(session_factory,
                                                                     dimitris, maria, eve,
                                                                     acme):
    _do(session_factory, team_service.create_team, dimitris.user.user_id, "solo")
    code = _do(session_factory, team_service.new_invite_code, dimitris.user.user_id, acme)

    # The only admin of acme: refused, and nothing changes, until someone takes it over.
    with pytest.raises(ValidationError, match="only admin of team 'acme'"):
        _offboard(session_factory, "dimitris")
    assert len(_do(session_factory, team_service.list_teams, dimitris.user.user_id)) == 2

    assert _offboard(session_factory, "dimitris", {"acme": "maria"}) == ["acme", "solo"]

    assert _do(session_factory, team_service.list_teams, dimitris.user.user_id) == []
    assert [(team.name, team.role, team.members) for team in
            _do(session_factory, team_service.list_teams, maria.user.user_id)] == [
        ("acme", TeamRole.ADMIN, 1)]
    with pytest.raises(NotFound, match="not a team invite code"):
        _do(session_factory, team_service.join_team, eve.user.user_id, code)
    # Their own team, which only they were in, is gone and its name free.
    assert _do(session_factory, team_service.create_team, eve.user.user_id, "solo") == "solo"


# --- groups, nested -------------------------------------------------------------------------

@pytest.fixture(name="groups")
def groups_fixture(session_factory, dimitris, maria, eve, acme):
    """acme: backend (open) > backend/aistack (private, maria in it) ; security (private).

    eve joins acme and is added to nothing. One skill sits in each group and one at the top.
    """
    admin = dimitris.user.user_id
    code = _do(session_factory, team_service.new_invite_code, admin, acme)
    _do(session_factory, team_service.join_team, eve.user.user_id, code)
    _do(session_factory, team_service.create_group, admin, acme, "backend")
    _do(session_factory, team_service.create_group, admin, acme, "aistack", "backend", True)
    _do(session_factory, team_service.create_group, admin, acme, "security", None, True)
    _do(session_factory, team_service.set_group_member, admin, acme, "backend/aistack",
        "maria", True)
    for name, group in (("top", None), ("sql-style", "backend"), ("api-notes", "backend/aistack"),
                        ("pentest", "security")):
        _push(session_factory, dimitris, name)
        _share(session_factory, dimitris, acme, name, group)
    return acme


def _team_view(session_factory, joined) -> list[tuple]:
    return [(group, name) for team, group, name in _listing(session_factory, joined)
            if team == "acme"]


def test_a_group_shows_its_skills_to_those_who_may_see_it(session_factory, dimitris, maria,
                                                         eve, groups):
    everything = [("backend", "sql-style"), ("backend/aistack", "api-notes"),
                  ("security", "pentest"), (None, "top")]

    assert sorted(_team_view(session_factory, dimitris), key=str) == sorted(everything, key=str)
    # In backend/aistack, so she sees it and the open group above it. Not security.
    assert sorted(_team_view(session_factory, maria), key=str) == sorted(
        [("backend", "sql-style"), ("backend/aistack", "api-notes"), (None, "top")], key=str)
    # Added to nothing: the open group and the team level only.
    assert sorted(_team_view(session_factory, eve), key=str) == sorted(
        [("backend", "sql-style"), (None, "top")], key=str)


def test_a_private_group_hides_everything_under_it(session_factory, dimitris, eve, groups):
    admin = dimitris.user.user_id
    _do(session_factory, team_service.create_group, admin, groups, "tools", "security")
    _push(session_factory, dimitris, "scanner")
    _share(session_factory, dimitris, groups, "scanner", "security/tools")

    assert ("security/tools", "scanner") not in _team_view(session_factory, eve)

    _do(session_factory, team_service.set_group_member, admin, groups, "security", "eve", True)
    assert ("security/tools", "scanner") in _team_view(session_factory, eve)


def test_a_skill_in_a_group_you_cannot_see_reads_like_one_that_does_not_exist(session_factory,
                                                                             eve, groups):
    with pytest.raises(NotFound) as hidden:
        _take(session_factory, eve, groups, "pentest")
    with pytest.raises(NotFound) as absent:
        _take(session_factory, eve, groups, "sorcerer")

    assert _same_sentence(hidden, "pentest", absent, "sorcerer")
    assert [group.path for group in _do(session_factory, team_service.groups,
                                        eve.user.user_id, groups)] == ["backend"]


def test_a_member_given_sight_of_every_group_reads_them_all_and_writes_to_none(
        session_factory, dimitris, eve, groups):
    _do(session_factory, team_service.set_member, dimitris.user.user_id, groups, "eve",
        sees_all_groups=True)

    assert ("security", "pentest") in _team_view(session_factory, eve)
    assert _take(session_factory, eve, groups, "pentest").name == "pentest"
    _push(session_factory, eve, "eves-own")
    with pytest.raises(NotFound, match="not in a group 'security'"):
        _share(session_factory, eve, groups, "eves-own", "security")


def test_sharing_into_a_group_takes_belonging_to_it_or_to_one_above_it(session_factory,
                                                                      dimitris, maria, eve,
                                                                      groups):
    _push(session_factory, maria, "marias")
    _push(session_factory, eve, "eves")

    assert _share(session_factory, maria, groups, "marias", "backend/aistack").group == (
        "backend/aistack")
    with pytest.raises(NotFound) as hidden:
        _share(session_factory, eve, groups, "eves", "backend/aistack")
    with pytest.raises(NotFound) as absent:
        _share(session_factory, eve, groups, "eves", "backend/nowhere")
    assert _same_sentence(hidden, "backend/aistack", absent, "backend/nowhere")
    # Open is readable by the team, not writable by it.
    with pytest.raises(NotFound):
        _share(session_factory, eve, groups, "eves", "backend")
    assert _share(session_factory, eve, groups, "eves").group is None


def _team_revision(session_factory, joined, name) -> tuple[int, str]:
    found = next(skill for skill in _do(session_factory, skill_service.list_skills,
                                        joined.user.user_id)
                 if skill.team == "acme" and skill.name == name)
    return found.revision, found.pushed_by


@pytest.mark.parametrize("sees_all", [False, True], ids=["open-group", "sees-all-groups"])
def test_sharing_over_a_groups_skill_takes_being_able_to_share_into_it(session_factory,
                                                                      dimitris, eve, groups,
                                                                      sees_all):
    """ADR-0029: seeing a group is reading and taking, not writing, by any path."""
    if sees_all:
        _do(session_factory, team_service.set_member, dimitris.user.user_id, groups, "eve",
            sees_all_groups=True)
    name, group = ("pentest", "security") if sees_all else ("sql-style", "backend")
    _push(session_factory, eve, name, files={"notes.md": "Eve's version."})

    with pytest.raises(Conflict) as refusal:
        _share(session_factory, eve, groups, name)

    assert str(refusal.value) == (
        f"'{name}' is in group '{group}' of team 'acme', which you can read but not share "
        "into. Ask a team admin to add you to it, or share yours under a different name.")
    assert _team_revision(session_factory, dimitris, name) == (1, "dimitris")


def test_a_group_member_still_shares_over_its_skill_without_naming_the_group(session_factory,
                                                                            maria, groups):
    _push(session_factory, maria, "api-notes", files={"notes.md": "Maria's version."})

    assert _share(session_factory, maria, groups, "api-notes").group == "backend/aistack"
    assert _team_revision(session_factory, maria, "api-notes") == (2, "maria")
    # Being in a group under 'backend' is not being in 'backend'.
    _push(session_factory, maria, "sql-style", files={"notes.md": "Maria's version."})
    with pytest.raises(Conflict, match="read but not share into"):
        _share(session_factory, maria, groups, "sql-style")


def test_the_member_list_shows_no_group_its_reader_cannot_see(session_factory, dimitris, eve,
                                                              groups):
    # Open, but under a private group: its path would name the private one.
    _do(session_factory, team_service.create_group, dimitris.user.user_id, groups, "tools",
        "security")

    def groups_of(viewer, username):
        return next(member.groups for member in
                    _do(session_factory, team_service.members, viewer.user.user_id, groups)
                    if member.username == username)

    assert groups_of(eve, "dimitris") == ("backend",)
    assert groups_of(dimitris, "dimitris") == (
        "backend", "backend/aistack", "security", "security/tools")


def _statements(session_factory, portable_engine, call) -> int:
    count = [0]

    def counted(*_):
        count[0] += 1

    event.listen(portable_engine, "before_cursor_execute", counted)
    try:
        with pytest.raises(NotFound) as refusal:
            _do(session_factory, call)
    finally:
        event.remove(portable_engine, "before_cursor_execute", counted)
    return count[0], str(refusal.value)


@pytest.mark.parametrize("action", ["subscribe", "share"])
def test_a_hidden_group_costs_the_same_work_as_a_missing_one(session_factory, portable_engine,
                                                             eve, groups, action):
    """The same sentence is not enough if a hidden group takes longer to answer."""
    _push(session_factory, eve, "eves")

    def asking_for(group):
        if action == "subscribe":
            return lambda session: team_service.set_subscribed(session, eve.user.user_id,
                                                               groups, group, False)
        return lambda session: skill_service.share(session, eve.user.user_id, "eves", groups,
                                                   group)

    hidden = _statements(session_factory, portable_engine, asking_for("security"))
    missing = _statements(session_factory, portable_engine, asking_for("nowhere"))

    assert hidden[0] == missing[0]
    assert hidden[1].replace("security", "X") == missing[1].replace("nowhere", "X")


def test_moving_a_skill_into_a_private_group_takes_it_out_of_others_sight(session_factory,
                                                                         dimitris, eve, groups):
    assert (None, "top") in _team_view(session_factory, eve)

    _do(session_factory, team_service.move_skill, dimitris.user.user_id, groups, "top",
        "security")

    assert ("security", "top") not in _team_view(session_factory, eve)
    assert (None, "top") not in _team_view(session_factory, eve)


def test_a_name_used_where_you_cannot_see_is_refused_without_being_overwritten(session_factory,
                                                                             eve, groups):
    _push(session_factory, eve, "pentest", files={"x.md": "eve's own\n"})

    with pytest.raises(Conflict, match="already uses the name 'pentest'"):
        _share(session_factory, eve, groups, "pentest")


def test_unsubscribing_from_a_group_stops_its_updates_and_those_under_it(session_factory,
                                                                        dimitris, maria,
                                                                        groups):
    for name in ("sql-style", "api-notes", "top"):
        _take(session_factory, maria, groups, name)
        _push(session_factory, dimitris, name, files={"notes.md": "changed\n"})
        _share(session_factory, dimitris, groups, name)
    local = {name: local_digests(name) for name in ("sql-style", "api-notes", "top")}

    def offered():
        by_sync = sorted(update.name for update in _sync(session_factory, maria,
                                                         local).team_updates)
        # IMP-02: the dashboard offers exactly what sync offers.
        by_page = sorted(skill["name"] for skill in _do(
            session_factory, dashboard_service.state, maria.user.user_id)["skills"]
            if skill["source"] and skill["source"]["update_available"])
        assert by_page == by_sync
        return by_sync

    assert offered() == ["api-notes", "sql-style", "top"]

    _do(session_factory, team_service.set_subscribed, maria.user.user_id, groups, "backend",
        False)
    assert offered() == ["top"]
    # It hides nothing: the skills are still listed and can still be taken.
    assert ("backend", "sql-style") in _team_view(session_factory, maria)

    _do(session_factory, team_service.set_subscribed, maria.user.user_id, groups, "backend",
        True)
    assert offered() == ["api-notes", "sql-style", "top"]


def test_leaving_a_team_takes_its_mutes_along(session_factory, dimitris, maria, groups):
    """DB-13: a member who came back silently missed the updates they once muted."""
    _do(session_factory, team_service.set_subscribed, maria.user.user_id, groups, "backend",
        False)
    _do(session_factory, team_service.leave_team, maria.user.user_id, groups)
    with session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(GroupUnsubscribed)
                              .where(GroupUnsubscribed.user_id == maria.user.user_id)) == 0

    code = _do(session_factory, team_service.new_invite_code, dimitris.user.user_id, groups)
    _do(session_factory, team_service.join_team, maria.user.user_id, code)

    backend = next(group for group in _do(session_factory, team_service.groups,
                                          maria.user.user_id, groups) if group.path == "backend")
    assert backend.subscribed is True


def test_groups_nest_as_deep_as_is_useful_and_no_deeper(session_factory, dimitris, acme):
    admin = dimitris.user.user_id
    path = None
    for _ in range(8):
        path = _do(session_factory, team_service.create_group, admin, acme, "sub", path)

    assert path == "/".join(["sub"] * 8)
    with pytest.raises(ValidationError, match="at most 8 deep"):
        _do(session_factory, team_service.create_group, admin, acme, "sub", path)
    with pytest.raises(Conflict, match="already has a group 'sub'"):
        _do(session_factory, team_service.create_group, admin, acme, "sub")


def _group_paths(session_factory, joined, team) -> list[str]:
    return [group.path for group in _do(session_factory, team_service.groups,
                                        joined.user.user_id, team)]


def test_renaming_a_group_takes_the_groups_under_it_along(session_factory, dimitris, maria,
                                                          groups):
    """PH-04: a mistyped group can be put right, and keeps its skills and members."""
    admin = dimitris.user.user_id

    assert _do(session_factory, team_service.rename_group, admin, groups, "backend",
               "server") == "server"

    assert _group_paths(session_factory, dimitris, groups) == [
        "security", "server", "server/aistack"]
    assert ("acme", "server/aistack", "api-notes") in _listing(session_factory, maria)
    assert ("acme", "server", "sql-style") in _listing(session_factory, maria)


def test_a_group_cannot_be_renamed_onto_a_taken_name(session_factory, dimitris, groups):
    admin = dimitris.user.user_id

    with pytest.raises(Conflict, match="already has a group 'security'"):
        _do(session_factory, team_service.rename_group, admin, groups, "backend", "security")
    with pytest.raises(ValidationError, match="lowercase letters"):
        _do(session_factory, team_service.rename_group, admin, groups, "backend", "a/b")

    assert _group_paths(session_factory, dimitris, groups) == [
        "backend", "backend/aistack", "security"]


def test_only_an_empty_group_is_deleted(session_factory, dimitris, groups):
    """Moving a private group's skills up would show them to people it kept them from."""
    admin = dimitris.user.user_id
    _do(session_factory, team_service.create_group, admin, groups, "typo")

    _do(session_factory, team_service.delete_group, admin, groups, "typo")

    with pytest.raises(Conflict, match="has groups inside it"):
        _do(session_factory, team_service.delete_group, admin, groups, "backend")
    with pytest.raises(Conflict, match="still has skills"):
        _do(session_factory, team_service.delete_group, admin, groups, "security")
    assert _group_paths(session_factory, dimitris, groups) == [
        "backend", "backend/aistack", "security"]


def test_only_an_admin_renames_or_deletes_a_group(session_factory, dimitris, maria,
                                                  groups):
    admin = dimitris.user.user_id
    _do(session_factory, team_service.create_group, admin, groups, "typo")

    for call, arguments in ((team_service.rename_group, ("typo", "other")),
                            (team_service.delete_group, ("typo",))):
        with pytest.raises(ValidationError, match="Only an admin"):
            _do(session_factory, call, maria.user.user_id, groups, *arguments)
    with pytest.raises(NotFound, match="no group 'missing'"):
        _do(session_factory, team_service.delete_group, admin, groups, "missing")

    assert "typo" in _group_paths(session_factory, dimitris, groups)


# --- removing from my skills ----------------------------------------------------------------

def test_removing_a_skill_from_my_skills_does_not_come_back_as_a_new_one(session_factory,
                                                                        dimitris):
    """The folder is still on the computer. Sync must ask about it, not back it up again."""
    _push(session_factory, dimitris)

    _do(session_factory, skill_service.remove_from_my_skills, dimitris.user.user_id, "wizard")

    assert _listing(session_factory, dimitris) == []
    report = _sync(session_factory, dimitris, {"wizard": local_digests()})
    assert report.backup == ()
    assert [(question.name, [option.choice.value for option in question.options])
            for question in report.ask] == [("wizard", ["enable", "remove"])]
    # Answering "enable" brings it back, as the option says it will.
    _do(session_factory, skill_service.get_skill, dimitris.machine.machine_id,
        dimitris.user.user_id, "wizard")
    assert _listing(session_factory, dimitris) == [(None, None, "wizard")]
    assert _sync(session_factory, dimitris, {"wizard": local_digests()}).up_to_date == 1


def test_answering_remove_for_a_removed_skill_is_just_deleting_the_folder(session_factory,
                                                                         dimitris):
    _push(session_factory, dimitris)
    _do(session_factory, skill_service.remove_from_my_skills, dimitris.user.user_id, "wizard")

    gone = _sync(session_factory, dimitris, {})

    assert gone.ask == () and gone.install == () and gone.backup == ()
