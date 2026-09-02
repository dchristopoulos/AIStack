import logging

import pytest
from pydantic import SecretStr

from aistack.bootstrap.configuration.settings.settings_config import Settings
from aistack.bootstrap.context import application_context
from tests.conftest import INVITE_CODE


@pytest.fixture(autouse=True)
def disposed_context():
    yield
    application_context.dispose_application_context()


def test_startup_confirms_an_invite_code_without_revealing_anything_about_it(sqlite_url, caplog):
    with caplog.at_level(logging.DEBUG):
        application_context.build_application_context(
            Settings(database_url=sqlite_url, aistack_invite_code=INVITE_CODE))

    assert "Invite code: 'configured'." in caplog.text
    assert INVITE_CODE not in caplog.text
    # Not even its length: that is the one hint that narrows a brute force.
    assert str(len(INVITE_CODE)) not in caplog.text


def test_a_placeholder_invite_code_stops_assembly_before_a_database_is_touched(sqlite_url):
    with pytest.raises(ValueError):
        application_context.build_application_context(
            Settings(database_url=sqlite_url, aistack_invite_code=SecretStr("change-me")))

    with pytest.raises(RuntimeError, match="has not been built"):
        application_context.get_session_factory()


def test_using_the_context_before_assembly_says_what_to_do(sqlite_url):
    with pytest.raises(RuntimeError, match="build_application_context"):
        application_context.get_session_factory()
