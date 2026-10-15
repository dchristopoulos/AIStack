import logging
import re

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
    # Only lines about the code are searched, and only for the length as a
    # whole number: unrelated startup lines carry timings and ports.
    about_the_code = [
        record.getMessage() for record in caplog.records
        if re.search(r"invite|length|characters", record.getMessage(), re.IGNORECASE)]
    length = re.compile(rf"\b{len(INVITE_CODE)}\b")
    assert not any(length.search(message) for message in about_the_code)


def test_a_placeholder_invite_code_stops_assembly_before_a_database_is_touched(sqlite_url):
    with pytest.raises(ValueError):
        application_context.build_application_context(
            Settings(database_url=sqlite_url, aistack_invite_code=SecretStr("change-me")))

    with pytest.raises(RuntimeError, match="has not been built"):
        application_context.get_session_factory()


def test_using_the_context_before_assembly_says_what_to_do(sqlite_url):
    with pytest.raises(RuntimeError, match="build_application_context"):
        application_context.get_session_factory()



def test_the_dashboard_names_the_librarys_provider_but_never_its_password():
    from aistack.bootstrap.context.application_context import _described

    described = _described("postgresql://maria:s3cret@ep-cool-1.eu-central-1.aws.neon.tech/aistack")

    assert described == {"kind": "postgresql", "provider": "Neon",
                         "host": "ep-cool-1.eu-central-1.aws.neon.tech"}
    assert _described("sqlite:////home/maria/.aistack/aistack.db") == {"kind": "this_computer"}


@pytest.mark.parametrize(("system", "hardware", "expected"), [
    ("Darwin", "      Model Name: MacBook Pro\n      Chip: Apple M4 Pro\n", "MacBook Pro M4 Pro"),
    # An Intel Mac reports a processor, not a chip: the model alone.
    ("Darwin", "      Model Name: iMac\n      Processor Name: 6-Core Intel Core i5\n", "iMac"),
    ("Windows", "", "Windows PC"),
])
def test_a_new_computer_is_named_as_its_owner_would_name_it(monkeypatch, system, hardware,
                                                             expected):
    import subprocess

    monkeypatch.setattr(application_context.platform, "system", lambda: system)
    monkeypatch.setattr(application_context.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=hardware))

    assert application_context._computer_name() == expected
