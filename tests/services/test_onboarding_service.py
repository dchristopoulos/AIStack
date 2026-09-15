import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from aistack.commons.exceptions import Conflict, ValidationError
from aistack.db.engine import build_session_factory
from aistack.db.models.machine import Machine
from aistack.db.models.operating_system import OperatingSystem
from aistack.db.models.user import User
from aistack.services import onboarding_service
from aistack.services.token_service import TOKEN_PREFIX, hash_token


@pytest.fixture(name="session_factory")
def session_factory_fixture(portable_engine):
    return build_session_factory(portable_engine)


def _join(session_factory, username="dimitris", machine_name="macbook", os="MACOS"):
    with session_factory.begin() as session:
        return onboarding_service.join(session, username, machine_name, os)


def test_join_creates_the_user_and_their_first_machine(session_factory: sessionmaker[Session]):
    joined = _join(session_factory, username="dimitris", machine_name="macbook", os="MACOS")

    assert joined.user.username == "dimitris"
    assert joined.machine.name == "macbook"
    assert joined.machine.os is OperatingSystem.MACOS
    assert joined.token.startswith(TOKEN_PREFIX)
    assert joined.token not in repr(joined)

    with session_factory() as session:
        machine = session.scalar(select(Machine))
        assert machine.user_id == joined.user.user_id
        # Only the hash is stored; the plaintext exists nowhere in the database.
        assert machine.token_hash == hash_token(joined.token)
        assert joined.token not in str(machine.__dict__)


def test_the_first_user_to_join_becomes_the_admin(session_factory: sessionmaker[Session]):
    first = _join(session_factory, username="first", machine_name="one")
    second = _join(session_factory, username="second", machine_name="two")

    assert first.user.is_admin is True
    assert second.user.is_admin is False

    with session_factory() as session:
        admins = session.scalars(select(User.username).where(User.is_admin.is_(True))).all()
        assert admins == ["first"]


def test_duplicate_username_is_rejected(session_factory: sessionmaker[Session]):
    _join(session_factory, username="dimitris", machine_name="macbook")

    with pytest.raises(Conflict) as rejection:
        _join(session_factory, username="dimitris", machine_name="desktop")

    assert "dimitris" in str(rejection.value)
    assert "add the machine" in str(rejection.value)


def test_the_same_machine_name_is_free_for_a_different_user(session_factory: sessionmaker[Session]):
    _join(session_factory, username="first", machine_name="macbook")

    second = _join(session_factory, username="second", machine_name="macbook")

    assert second.machine.name == "macbook"


@pytest.mark.parametrize("os", ["", "mac", "SOLARIS", "MACOS;", None, "macos", "  Windows  "])
def test_an_unsupported_os_is_rejected_naming_what_arrived(session_factory, os):
    with pytest.raises(ValidationError) as rejection:
        _join(session_factory, os=os)

    assert "MACOS, WINDOWS, LINUX" in str(rejection.value)
    assert str(os) in str(rejection.value)


@pytest.mark.parametrize("os", ["MACOS", "WINDOWS", "LINUX"])
def test_the_exact_supported_os_is_stored(session_factory, os):
    joined = _join(session_factory, os=os)

    assert joined.machine.os.value == os


@pytest.mark.parametrize("field", ["username", "machine_name"])
def test_nul_in_a_name_is_rejected_before_any_write(session_factory, field):
    with pytest.raises(ValidationError, match="NUL") as rejection:
        _join(session_factory, **{field: "x\x00y"})
    assert "\\x00" in str(rejection.value)
    with session_factory() as session:
        assert session.scalars(select(User)).all() == []
        assert session.scalars(select(Machine)).all() == []


@pytest.mark.parametrize("field", ["username", "machine_name"])
@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_a_blank_name_is_rejected(session_factory, field, value):
    with pytest.raises(ValidationError) as rejection:
        _join(session_factory, **{field: value})

    assert f"{field} is blank" in str(rejection.value)


@pytest.mark.parametrize("field", ["username", "machine_name"])
def test_an_over_length_name_is_rejected_saying_the_limit_and_what_arrived(session_factory, field):
    with pytest.raises(ValidationError) as rejection:
        _join(session_factory, **{field: "n" * 65})

    assert "65 characters long" in str(rejection.value)
    assert "limit is 64" in str(rejection.value)


@pytest.mark.parametrize("field", ["username", "machine_name"])
def test_names_are_stored_trimmed(session_factory, field):
    joined = _join(session_factory, **{field: "  spaced  "})

    assert (joined.user.username if field == "username" else joined.machine.name) == "spaced"
