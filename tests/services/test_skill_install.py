import io
import tarfile
import time
import uuid

import pytest
from sqlalchemy import select

from aistack.commons.exceptions import InvalidTicket, NotFound, ValidationError
from aistack.db.engine import build_session_factory
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.timestamps import as_utc
from aistack.services import onboarding_service, skill_service
from aistack.services.content_hash import file_digest
from tests.archives import skill_archive, skill_document


@pytest.fixture(name="session_factory")
def session_factory_fixture(portable_engine):
    return build_session_factory(portable_engine)


@pytest.fixture(name="dimitris")
def dimitris_fixture(session_factory):
    with session_factory.begin() as session:
        return onboarding_service.join(session, "dimitris", "macbook", "MACOS")


@pytest.fixture(name="desktop")
def desktop_fixture(session_factory, dimitris):
    """A second machine for the same user."""
    with session_factory.begin() as session:
        return onboarding_service.add_machine(session, dimitris.user.user_id, "desktop",
                                              "WINDOWS").machine


@pytest.fixture(name="maria")
def maria_fixture(session_factory):
    with session_factory.begin() as session:
        return onboarding_service.join(session, "maria", "laptop", "LINUX")


def _push(session_factory, joined, name="wizard", **archive):
    with session_factory.begin() as session:
        return skill_service.push(session, machine_id=joined.machine.machine_id,
                                  user_id=joined.user.user_id, name=name, origin=None,
                                  archive=skill_archive(name, **archive))


def _get(session_factory, machine_id, name="wizard"):
    with session_factory.begin() as session:
        return skill_service.get_skill(session, machine_id, name)


def _disable(session_factory, machine_id, name="wizard"):
    with session_factory.begin() as session:
        return skill_service.disable_skill(session, machine_id, name)


def _decisions(session_factory) -> dict[uuid.UUID, bool]:
    with session_factory() as session:
        return dict(session.execute(select(MachineSkill.machine_id, MachineSkill.enabled)).all())


def _extracted(archive: bytes) -> dict[str, tuple[bytes, bool]]:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        return {member.name: (tar.extractfile(member).read(), bool(member.mode & 0o111))
                for member in tar}


# --- list_skills ----------------------------------------------------------------------------

def test_an_empty_vault_lists_nothing(session_factory):
    with session_factory() as session:
        assert skill_service.list_skills(session) == []


def test_the_listing_is_names_and_descriptions_sorted_by_name(session_factory, dimitris, maria):
    _push(session_factory, dimitris, "wizard")
    _push(session_factory, maria, "code-review", description="Reviews a diff.")
    _push(session_factory, dimitris, "tdd", description="Red, green, refactor.")

    with session_factory() as session:
        listing = skill_service.list_skills(session)

    assert [(skill.name, skill.description) for skill in listing] == [
        ("code-review", "Reviews a diff."),
        ("tdd", "Red, green, refactor."),
        ("wizard", "Walks a human through steps."),
    ]


def test_the_listing_shows_the_latest_description(session_factory, dimitris):
    _push(session_factory, dimitris, description="First draft.")
    _push(session_factory, dimitris, description="Second draft.")

    with session_factory() as session:
        assert skill_service.list_skills(session)[0].description == "Second draft."


# --- get_skill ------------------------------------------------------------------------------

def test_get_skill_describes_the_latest_revision_without_carrying_its_bytes(session_factory,
                                                                           dimitris, maria):
    _push(session_factory, dimitris, files={"notes.md": "one\n"})
    document = skill_document(extra_frontmatter="version: 2.0\n")
    pushed = _push(session_factory, maria, files={"SKILL.md": document, "run.sh": "echo hi\n"},
                   executable=frozenset({"run.sh"}))

    skill = _get(session_factory, dimitris.machine.machine_id)

    assert skill.name == "wizard"
    assert skill.revision == 2
    assert skill.version == "2.0"
    assert skill.pushed_by == "maria"
    assert skill.content_hash == pushed.content_hash
    assert [(file.path, file.sha256, file.executable) for file in skill.files] == [
        ("SKILL.md", file_digest(document.encode()), False),
        ("run.sh", file_digest(b"echo hi\n"), True),
    ]
    assert not hasattr(skill.files[0], "content")


def test_a_skill_without_a_frontmatter_version_reports_none(session_factory, dimitris):
    _push(session_factory, dimitris)

    assert _get(session_factory, dimitris.machine.machine_id).version is None


def test_get_skill_enables_the_skill_for_the_calling_machine_only(session_factory, dimitris,
                                                                 desktop, maria):
    """Enablement is per machine, even between two machines of one user."""
    _push(session_factory, maria)

    _get(session_factory, desktop.machine_id)

    assert _decisions(session_factory) == {maria.machine.machine_id: True,
                                           desktop.machine_id: True}


def test_calling_get_skill_twice_keeps_one_row(session_factory, dimitris):
    _push(session_factory, dimitris)

    _get(session_factory, dimitris.machine.machine_id)
    _get(session_factory, dimitris.machine.machine_id)

    assert _decisions(session_factory) == {dimitris.machine.machine_id: True}


def test_get_skill_re_enables_an_explicitly_disabled_skill(session_factory, dimitris):
    _push(session_factory, dimitris)
    _disable(session_factory, dimitris.machine.machine_id)

    _get(session_factory, dimitris.machine.machine_id)

    assert _decisions(session_factory) == {dimitris.machine.machine_id: True}


def test_get_skill_on_an_unknown_name_says_where_to_look(session_factory, dimitris):
    with pytest.raises(NotFound) as rejection:
        _get(session_factory, dimitris.machine.machine_id, "sorcerer")

    assert "no skill named 'sorcerer'" in str(rejection.value)
    assert "list_skills" in str(rejection.value)
    assert _decisions(session_factory) == {}


@pytest.mark.parametrize("name", ["Wizard", "../wizard", "wizard\nFORGED", ""])
def test_a_malformed_name_is_a_format_error_not_a_lookup(session_factory, dimitris, name):
    with pytest.raises(ValidationError) as rejection:
        _get(session_factory, dimitris.machine.machine_id, name)

    assert "\n" not in str(rejection.value)


# --- disable_skill --------------------------------------------------------------------------

def test_disable_keeps_the_row_and_flips_it(session_factory, dimitris):
    """`enabled = False` is an explicit decision; a missing row is none. Sync tells them apart."""
    _push(session_factory, dimitris)

    assert _disable(session_factory, dimitris.machine.machine_id) == "wizard"

    assert _decisions(session_factory) == {dimitris.machine.machine_id: False}


def test_disabling_twice_is_not_an_error(session_factory, dimitris):
    _push(session_factory, dimitris)

    _disable(session_factory, dimitris.machine.machine_id)
    _disable(session_factory, dimitris.machine.machine_id)

    assert _decisions(session_factory) == {dimitris.machine.machine_id: False}


def test_disable_on_one_machine_leaves_the_users_other_machine_alone(session_factory, dimitris,
                                                                   desktop):
    _push(session_factory, dimitris)
    _get(session_factory, desktop.machine_id)

    _disable(session_factory, desktop.machine_id)

    assert _decisions(session_factory) == {dimitris.machine.machine_id: True,
                                           desktop.machine_id: False}


def test_disabling_a_skill_this_machine_never_enabled_is_refused(session_factory, dimitris,
                                                               maria):
    _push(session_factory, maria)

    with pytest.raises(NotFound) as rejection:
        _disable(session_factory, dimitris.machine.machine_id)

    assert "was never enabled on this machine" in str(rejection.value)
    # No row is still no decision: the refusal must not create one.
    assert _decisions(session_factory) == {maria.machine.machine_id: True}


def test_disabling_an_unknown_skill_is_refused(session_factory, dimitris):
    with pytest.raises(NotFound, match="no skill named 'sorcerer'"):
        _disable(session_factory, dimitris.machine.machine_id, "sorcerer")


# --- archive_of -----------------------------------------------------------------------------

def test_the_archive_reproduces_the_pushed_files_byte_for_byte(session_factory, dimitris):
    files = {
        "scripts/run.sh": "#!/bin/sh\r\necho hi\r\n",
        "références/naïve.md": "café\n",
        "with-bom.md": "\ufeffhello\n",
    }
    _push(session_factory, dimitris, files=files, executable=frozenset({"scripts/run.sh"}))
    skill = _get(session_factory, dimitris.machine.machine_id)

    with session_factory() as session:
        name, archive = skill_service.archive_of(session, dimitris.machine.machine_id,
                                                 skill.skill_version_id)

    assert name == "wizard"
    extracted = _extracted(archive)
    assert extracted == {
        "SKILL.md": (skill_document().encode(), False),
        "scripts/run.sh": (files["scripts/run.sh"].encode(), True),
        "références/naïve.md": (files["références/naïve.md"].encode(), False),
        "with-bom.md": (files["with-bom.md"].encode(), False),
    }
    # What the tool described is what the archive holds.
    assert {file.path: file.sha256 for file in skill.files} == {
        path: file_digest(content) for path, (content, _) in extracted.items()}


def test_the_archive_is_of_the_revision_asked_for_not_the_latest(session_factory, dimitris):
    """A push landing after the URL was issued must not change what the URL serves."""
    _push(session_factory, dimitris, files={"notes.md": "one\n"})
    described = _get(session_factory, dimitris.machine.machine_id)
    _push(session_factory, dimitris, files={"notes.md": "two\n"})

    with session_factory() as session:
        _, archive = skill_service.archive_of(session, dimitris.machine.machine_id,
                                              described.skill_version_id)

    assert _extracted(archive)["notes.md"][0] == b"one\n"


def test_a_revoked_machine_cannot_download(session_factory, dimitris):
    _push(session_factory, dimitris)
    skill = _get(session_factory, dimitris.machine.machine_id)
    with session_factory.begin() as session:
        session.delete(session.merge(dimitris.machine))

    with session_factory() as session:
        with pytest.raises(InvalidTicket, match="no longer registered"):
            skill_service.archive_of(session, dimitris.machine.machine_id,
                                     skill.skill_version_id)


def test_a_revision_that_does_not_exist_is_not_found(session_factory, dimitris):
    with session_factory() as session:
        with pytest.raises(NotFound, match="no longer exists"):
            skill_service.archive_of(session, dimitris.machine.machine_id, uuid.uuid4())


def test_installed_files_are_dated_by_when_the_revision_was_pushed(session_factory, dimitris):
    """Not 1970, and the same on SQLite (naive timestamps) and Postgres (aware ones)."""
    _push(session_factory, dimitris)
    skill = _get(session_factory, dimitris.machine.machine_id)
    with session_factory() as session:
        pushed_on = session.scalar(select(SkillVersion.created_on))
        _, archive = skill_service.archive_of(session, dimitris.machine.machine_id,
                                              skill.skill_version_id)

    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        modified = {member.mtime for member in tar}

    assert modified == {int(as_utc(pushed_on).timestamp())}
    assert abs(modified.pop() - time.time()) < 60


def test_the_same_revision_always_downloads_as_the_same_bytes(session_factory, dimitris):
    _push(session_factory, dimitris, files={"b.md": "b\n", "a.md": "a\n"})
    skill = _get(session_factory, dimitris.machine.machine_id)

    with session_factory() as session:
        first = skill_service.archive_of(session, dimitris.machine.machine_id,
                                         skill.skill_version_id)
        second = skill_service.archive_of(session, dimitris.machine.machine_id,
                                          skill.skill_version_id)

    assert first == second
