"""A project is its owner's alone, and reaching for somebody else's reads as reaching for none
(ADR-0026)."""

import pytest

from aistack.commons.exceptions import NotFound
from aistack.db.engine import build_session_factory
from aistack.db.models.project import Project
from aistack.services import onboarding_service, visibility

KEY = "github.com/acme/billing"


@pytest.fixture(name="session_factory")
def session_factory_fixture(portable_engine):
    return build_session_factory(portable_engine)


def _join(session_factory, username):
    with session_factory.begin() as session:
        return onboarding_service.join(session, username, "laptop", "LINUX").user.user_id


def test_a_project_is_found_by_its_owner(session_factory):
    dimitris = _join(session_factory, "dimitris")
    with session_factory.begin() as session:
        session.add(Project(user_id=dimitris, key=KEY, name="billing"))

    with session_factory.begin() as session:
        assert visibility.required_my_project(session, dimitris, KEY).name == "billing"


def test_another_users_project_answers_like_one_that_does_not_exist(session_factory):
    dimitris = _join(session_factory, "dimitris")
    maria = _join(session_factory, "maria")
    with session_factory.begin() as session:
        session.add(Project(user_id=dimitris, key=KEY, name="billing"))

    with session_factory.begin() as session:
        assert visibility.my_project(session, maria, KEY) is None
        with pytest.raises(NotFound) as theirs:
            visibility.required_my_project(session, maria, KEY)
        with pytest.raises(NotFound) as unknown:
            visibility.required_my_project(session, maria, "github.com/acme/nothing")

    assert theirs.value.message == unknown.value.message.replace("nothing", "billing")
