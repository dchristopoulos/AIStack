"""Every change a person can make leaves one INFO line naming it, its team and its user
(STD-10). The log is the only record there is, and a click on the dashboard wrote nothing."""

import inspect
import logging
from types import SimpleNamespace

import pytest

from aistack.db.engine import build_session_factory
from aistack.services import (
    dashboard_service,
    onboarding_service,
    skill_service,
    team_service,
)
from tests.archives import skill_archive
from tests.teams import make_team

# Each change: how to make it in the world below, the line it writes, who makes it, and the
# team the line names (None for one that is about no team).
CHANGES = {
    "create_team": (lambda s, w: team_service.create_team(s, w.d, "newteam"),
                    "Team created", "d", "newteam"),
    "new_invite": (lambda s, w: team_service.new_invite(s, w.d, "acme"),
                   "Team invite made", "d", "acme"),
    "join_team": (lambda s, w: team_service.join_team(
        s, w.e, team_service.new_invite_code(s, w.d, "acme")), "Team joined", "e", "acme"),
    "cancel_invite": (lambda s, w: team_service.cancel_invite(
        s, w.d, "acme", str(team_service.new_invite(s, w.d, "acme")[1])),
        "Team invite cancelled", "d", "acme"),
    "set_subscribed": (lambda s, w: team_service.set_subscribed(s, w.m, "acme", "backend",
                                                                False),
                       "Group unsubscribed", "m", "acme"),
    "leave_team": (lambda s, w: team_service.leave_team(s, w.m, "acme"), "Team left", "m",
                   "acme"),
    "delete_team": (lambda s, w: team_service.delete_team(s, w.d, "acme"), "Team deleted", "d",
                    "acme"),
    "remove_member": (lambda s, w: team_service.remove_member(s, w.d, "acme", "maria"),
                      "Team member removed", "d", "acme"),
    "set_member": (lambda s, w: team_service.set_member(s, w.d, "acme", "maria",
                                                        can_invite=True),
                   "Team member changed", "d", "acme"),
    "create_group": (lambda s, w: team_service.create_group(s, w.d, "acme", "frontend"),
                     "Group created", "d", "acme"),
    "set_group": (lambda s, w: team_service.set_group(s, w.d, "acme", "backend", True),
                  "Group privacy set", "d", "acme"),
    "rename_group": (lambda s, w: team_service.rename_group(s, w.d, "acme", "backend", "server"),
                     "Group renamed", "d", "acme"),
    "delete_group": (lambda s, w: team_service.delete_group(s, w.d, "acme", "empty"),
                     "Group deleted", "d", "acme"),
    "set_group_member": (lambda s, w: team_service.set_group_member(s, w.d, "acme", "backend",
                                                                    "maria", True),
                         "Group member added", "d", "acme"),
    "move_skill": (lambda s, w: team_service.move_skill(s, w.d, "acme", "notes", "backend"),
                   "Team skill moved", "d", "acme"),
    "remove_skill": (lambda s, w: team_service.remove_skill(s, w.d, "acme", "notes"),
                     "Team skill removed", "d", "acme"),
    "take_from_team": (lambda s, w: skill_service.take_from_team(s, w.m, "notes", "acme"),
                       "Skill taken from a team", "m", "acme"),
    "share": (lambda s, w: skill_service.share(s, w.d, "wizard", "acme"), "Skill shared", "d",
              "acme"),
    "restore_revision": (lambda s, w: skill_service.restore_revision(s, w.d, "wizard", 1),
                         "Revision restored", "d", None),
    "remove_from_my_skills": (lambda s, w: skill_service.remove_from_my_skills(s, w.d,
                                                                               "wizard"),
                              "Skill removed from the Library", "d", None),
    "bring_back": (lambda s, w: (skill_service.remove_from_my_skills(s, w.d, "wizard"),
                                 skill_service.bring_back(s, w.d, "wizard")),
                   "Skill brought back to the Library", "d", None),
}
# Dashboard changes made outside those two services.
ALSO = {
    "set_on_machine": (lambda s, w: dashboard_service.set_on_machine(
        s, w.d, "wizard", str(w.laptop), False), "Skill taken off on the dashboard", "d", None),
    "set_full_name": (lambda s, w: onboarding_service.set_full_name(s, w.d, "Dimitris"),
                      "Full name set", "d", None),
}
# Logged where they are called from, with what only the caller knows: the transfer route and
# local mode's push tool for a push, the tools for an install or a disable, and every caller
# of set_enabled. Or called through another change in this table.
LOGGED_BY_CALLERS = {"push", "store", "get_skill", "disable_skill", "set_enabled",
                     "new_invite_code", "admit", "lock"}
READERS = {"invited_to", "is_open_invite", "invited_team", "invites", "list_teams", "overview",
           "members", "groups", "list_skills", "changed_since_taken", "replaced_since_taken",
           "archive_of", "export_library"}


@pytest.fixture(name="world")
def world_fixture(portable_engine):
    factory = build_session_factory(portable_engine)
    with factory.begin() as session:
        dimitris = onboarding_service.join(session, "dimitris", "laptop", "LINUX")
        maria = onboarding_service.join(session, "maria", "laptop", "LINUX")
        eve = onboarding_service.join(session, "eve", "laptop", "LINUX")
        d = dimitris.user.user_id
        make_team(session, "acme", d, maria.user.user_id)
        team_service.create_group(session, d, "acme", "backend")
        team_service.create_group(session, d, "acme", "empty")
        for name, notes in (("wizard", "one\n"), ("wizard", "two\n"), ("notes", "x\n")):
            skill_service.push(session, dimitris.machine.machine_id, d, name, None,
                               skill_archive(name, files={"notes.md": notes}))
        skill_service.share(session, d, "notes", "acme")
    return SimpleNamespace(factory=factory, d=d, m=maria.user.user_id, e=eve.user.user_id,
                           laptop=dimitris.machine.machine_id)


def test_every_change_in_the_services_is_in_the_table():
    public = {name for module in (team_service, skill_service)
              for name, function in vars(module).items()
              if inspect.isfunction(function) and function.__module__ == module.__name__
              and not name.startswith("_")}

    assert public == set(CHANGES) | LOGGED_BY_CALLERS | READERS


@pytest.mark.parametrize("change", sorted({**CHANGES, **ALSO}))
def test_a_change_writes_one_line_naming_it_its_team_and_its_user(world, caplog, change):
    make, line, actor, team = {**CHANGES, **ALSO}[change]
    user = getattr(world, actor)
    caplog.set_level(logging.INFO, logger="aistack.services")

    with world.factory.begin() as session:
        make(session, world)

    written = [record.getMessage() for record in caplog.records
               if record.name.startswith("aistack.services") and record.levelno == logging.INFO
               and record.getMessage().startswith(line)]
    assert len(written) == 1, (change, [record.getMessage() for record in caplog.records])
    assert str(user) in written[0]
    if team is not None:
        assert f"'{team}'" in written[0]
