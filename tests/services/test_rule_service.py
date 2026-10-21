"""Rules kept in the Library (ADR-0036), on both databases."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from aistack.commons.exceptions import Conflict, NotFound, ValidationError
from aistack.db.engine import build_session_factory
from aistack.db.models.project import Project
from aistack.db.models.rule import Rule, RuleRevision
from aistack.services import onboarding_service, operator_service, rule_service
from aistack.services.content_hash import text_hash

KEY = "github.com/acme/billing"
SECRET = "ghp_" + "a" * 36


@pytest.fixture(name="session_factory")
def session_factory_fixture(portable_engine):
    return build_session_factory(portable_engine)


def _join(session_factory, username):
    with session_factory.begin() as session:
        return onboarding_service.join(session, username, "laptop", "LINUX").user.user_id


def _project(session_factory, user_id, key=KEY):
    with session_factory.begin() as session:
        session.add(Project(user_id=user_id, key=key, name=key.rpartition("/")[2]))


@pytest.fixture(name="dimitris")
def dimitris_fixture(session_factory):
    return _join(session_factory, "dimitris")


def _call(session_factory, function, *arguments, **options):
    with session_factory.begin() as session:
        return function(session, *arguments, **options)


def test_a_rule_is_kept_with_its_first_revision_and_agents(session_factory, dimitris):
    saved = _call(session_factory, rule_service.create, dimitris, "house-style", "# Style\n",
                  agents=["codex", "claude_code"])

    assert (saved.saved, saved.revision, saved.credential_lines) == (True, 1, [])
    listed = _call(session_factory, rule_service.rules, dimitris)
    assert [(rule["name"], rule["project"], rule["agents"], rule["revision"], rule["pushed_by"])
            for rule in listed] == [("house-style", None, ["claude_code", "codex"], 1,
                                     "dimitris")]
    with session_factory.begin() as session:
        stored = session.scalar(select(RuleRevision))
        assert stored.content_hash == text_hash("# Style\n")


def test_an_edit_is_a_new_revision_and_the_old_one_is_kept(session_factory, dimitris):
    _call(session_factory, rule_service.create, dimitris, "house-style", "one\n")

    edited = _call(session_factory, rule_service.edit, dimitris, "house-style", "two\n")
    again = _call(session_factory, rule_service.edit, dimitris, "house-style", "two\n")

    assert (edited.revision, edited.unchanged) == (2, False)
    assert (again.revision, again.unchanged) == (2, True)
    with session_factory.begin() as session:
        assert session.scalars(select(RuleRevision.text).order_by(
            RuleRevision.revision)).all() == ["one\n", "two\n"]
    assert _call(session_factory, rule_service.text_of, dimitris, "house-style")["text"] == "two\n"


def test_a_credential_is_saved_only_once_confirmed(session_factory, dimitris):
    text = f"# Style\nuse {SECRET}\n"

    warned = _call(session_factory, rule_service.create, dimitris, "house-style", text)
    assert (warned.saved, warned.credential_lines) == (False, [2])
    assert _call(session_factory, rule_service.rules, dimitris) == []

    saved = _call(session_factory, rule_service.create, dimitris, "house-style", text,
                  confirmed=True)
    assert (saved.saved, saved.credential_lines, saved.revision) == (True, [2], 1)
    assert not _call(session_factory, rule_service.edit, dimitris, "house-style",
                     text + "more\n").saved


def test_a_rule_over_64_kib_is_refused(session_factory, dimitris):
    with pytest.raises(ValidationError, match="65537 bytes"):
        _call(session_factory, rule_service.create, dimitris, "big", "x" * (64 * 1024 + 1))


def test_a_name_is_unique_in_its_place(session_factory, dimitris):
    _project(session_factory, dimitris)
    _call(session_factory, rule_service.create, dimitris, "house-style", "a")
    # The same name for a project is a different rule.
    _call(session_factory, rule_service.create, dimitris, "house-style", "b", project=KEY)

    with pytest.raises(Conflict):
        _call(session_factory, rule_service.create, dimitris, "house-style", "c")
    with pytest.raises(Conflict):
        _call(session_factory, rule_service.create, dimitris, "house-style", "c", project=KEY)
    assert [rule["project"] for rule in _call(session_factory, rule_service.all_rules,
                                              dimitris)] == [None, KEY]
    assert [rule["name"] for rule in _call(session_factory, rule_service.rules, dimitris,
                                           KEY)] == ["house-style"]


def test_the_database_holds_a_name_unique_for_every_project(session_factory, dimitris):
    """The partial index, not only the service's check, on both databases."""
    _call(session_factory, rule_service.create, dimitris, "house-style", "a")
    with session_factory.begin() as session:
        team_id = session.scalar(select(Rule.team_id))

    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(Rule(team_id=team_id, name="house-style", pushed_by=dimitris))


def test_a_rename_keeps_the_history(session_factory, dimitris):
    _call(session_factory, rule_service.create, dimitris, "house-style", "a")
    _call(session_factory, rule_service.create, dimitris, "testing", "b")

    with pytest.raises(Conflict):
        _call(session_factory, rule_service.rename, dimitris, "house-style", "testing")
    assert _call(session_factory, rule_service.rename, dimitris, "house-style",
                 "style") == "style"

    assert _call(session_factory, rule_service.text_of, dimitris, "style")["revision"] == 1
    with pytest.raises(NotFound):
        _call(session_factory, rule_service.text_of, dimitris, "house-style")


def test_a_removed_rule_keeps_its_row_and_comes_back_by_name(session_factory, dimitris):
    _call(session_factory, rule_service.create, dimitris, "house-style", "a",
          agents=["claude_code"])
    _call(session_factory, rule_service.archive, dimitris, "house-style")

    assert _call(session_factory, rule_service.rules, dimitris) == []
    with pytest.raises(NotFound):
        _call(session_factory, rule_service.edit, dimitris, "house-style", "b")

    back = _call(session_factory, rule_service.create, dimitris, "house-style", "b",
                 agents=["codex"])
    assert back.revision == 2
    assert _call(session_factory, rule_service.rules, dimitris)[0]["agents"] == ["codex"]
    with session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(Rule)) == 1


def test_each_agent_has_one_file_for_every_project(session_factory, dimitris):
    _project(session_factory, dimitris)
    _call(session_factory, rule_service.create, dimitris, "mine", "a", agents=["claude_code"])
    _call(session_factory, rule_service.create, dimitris, "other", "b", agents=["codex"])

    with pytest.raises(Conflict, match="'mine' is already Claude Code's file"):
        _call(session_factory, rule_service.set_agents, dimitris, "other",
              ["codex", "claude_code"])
    # A project's rules each get a file of their own, so they share agents freely.
    _call(session_factory, rule_service.create, dimitris, "one", "a", project=KEY,
          agents=["claude_code", "codex"])
    _call(session_factory, rule_service.create, dimitris, "two", "a", project=KEY,
          agents=["claude_code", "codex"])
    # A removed rule frees its agent.
    _call(session_factory, rule_service.archive, dimitris, "mine")
    assert _call(session_factory, rule_service.set_agents, dimitris, "other",
                 ["claude_code", "codex"]) == ["claude_code", "codex"]


def test_another_persons_rule_reads_as_one_that_does_not_exist(session_factory, dimitris):
    maria = _join(session_factory, "maria")
    _project(session_factory, dimitris)
    _call(session_factory, rule_service.create, dimitris, "house-style", "a")
    _call(session_factory, rule_service.create, dimitris, "billing", "b", project=KEY)

    for name, project in (("house-style", None), ("billing", KEY)):
        for function, arguments in ((rule_service.edit, ("x",)),
                                    (rule_service.rename, ("x",)),
                                    (rule_service.set_agents, ([],)),
                                    (rule_service.archive, ()),
                                    (rule_service.text_of, ())):
            with pytest.raises(NotFound) as theirs:
                _call(session_factory, function, maria, name, *arguments, project=project)
            with pytest.raises(NotFound) as unknown:
                _call(session_factory, function, maria, "nothing", *arguments,
                      project=project.replace("billing", "nothing") if project else None)
            assert theirs.value.message == unknown.value.message.replace("nothing", name)

    assert _call(session_factory, rule_service.all_rules, maria) == []
    with pytest.raises(NotFound):
        _call(session_factory, rule_service.rules, maria, KEY)
    with pytest.raises(NotFound):
        _call(session_factory, rule_service.create, maria, "mine", "a", project=KEY)


def test_two_people_may_each_have_a_rule_of_one_name(session_factory, dimitris):
    maria = _join(session_factory, "maria")
    _call(session_factory, rule_service.create, dimitris, "house-style", "a",
          agents=["claude_code"])

    _call(session_factory, rule_service.create, maria, "house-style", "b",
          agents=["claude_code"])

    assert _call(session_factory, rule_service.text_of, maria, "house-style")["text"] == "b"
    assert _call(session_factory, rule_service.text_of, dimitris, "house-style")["text"] == "a"


def test_removing_a_project_takes_its_rules_with_it(session_factory, dimitris):
    _project(session_factory, dimitris)
    _call(session_factory, rule_service.create, dimitris, "billing", "b", project=KEY)
    with session_factory.begin() as session:
        session.delete(session.scalar(select(Project)))

    with session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(RuleRevision)) == 0


def test_forgetting_a_person_erases_their_rules(session_factory, dimitris):
    _project(session_factory, dimitris)
    _call(session_factory, rule_service.create, dimitris, "house-style", "a")
    _call(session_factory, rule_service.create, dimitris, "billing", "b", project=KEY)

    _call(session_factory, operator_service.forget, "dimitris")

    with session_factory.begin() as session:
        assert session.scalar(select(func.count()).select_from(Rule)) == 0
        assert session.scalar(select(func.count()).select_from(RuleRevision)) == 0
