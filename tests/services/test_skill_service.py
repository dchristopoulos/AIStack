import uuid

import pytest
from sqlalchemy import func, select

from aistack.commons.exceptions import Conflict, InvalidTicket, ValidationError
from aistack.db.engine import build_session_factory
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.skill import Skill
from aistack.db.models.skill_file import SkillFile
from aistack.db.models.skill_version import SkillVersion
from aistack.services import onboarding_service, skill_service
from tests.archives import skill_archive, skill_document

ORIGIN = "https://github.com/mattpocock/skills"


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


def _push(session_factory, joined, archive=None, name="wizard", origin=None):
    with session_factory.begin() as session:
        return skill_service.push(
            session,
            machine_id=joined.machine.machine_id,
            user_id=joined.user.user_id,
            name=name,
            origin=origin,
            archive=skill_archive(name) if archive is None else archive,
        )


def _count(session_factory, model) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(model))


def _files_of(session_factory, revision: int, name: str = "wizard") -> dict[str, tuple]:
    with session_factory() as session:
        rows = session.execute(
            select(SkillFile.path, SkillFile.content, SkillFile.sha256, SkillFile.executable)
            .join(SkillVersion, SkillVersion.skill_version_id == SkillFile.skill_version_id)
            .join(Skill, Skill.skill_id == SkillVersion.skill_id)
            .where(Skill.name == name, SkillVersion.revision == revision)
        ).all()
    return {path: (content, sha256, executable) for path, content, sha256, executable in rows}


def test_the_first_push_stores_revision_one_with_its_files_and_provenance(session_factory,
                                                                         dimitris):
    script = "#!/bin/sh\r\necho hi\r\n"
    archive = skill_archive(files={"scripts/run.sh": script, "REFERENCE.md": "Notes.\n"},
                            executable=frozenset({"scripts/run.sh"}))

    pushed = _push(session_factory, dimitris, archive, origin=ORIGIN)

    assert pushed.name == "wizard"
    assert pushed.revision == 1
    assert pushed.created is True
    assert pushed.unchanged is False
    assert pushed.file_count == 3
    assert pushed.previous_pushed_by is None
    assert pushed.stored_origin == ORIGIN
    with session_factory() as session:
        skill = session.scalar(select(Skill))
        version = session.scalar(select(SkillVersion))
    assert skill.name == "wizard"
    assert skill.description == "Walks a human through steps."
    assert skill.origin == ORIGIN
    assert skill.pushed_by == dimitris.user.user_id
    assert version.revision == 1
    assert version.pushed_by == dimitris.user.user_id
    assert version.content_hash == pushed.content_hash
    assert version.frontmatter_json == {"name": "wizard",
                                        "description": "Walks a human through steps."}

    files = _files_of(session_factory, revision=1)
    assert set(files) == {"SKILL.md", "REFERENCE.md", "scripts/run.sh"}
    assert files["scripts/run.sh"][0] == script
    assert files["scripts/run.sh"][2] is True
    assert files["SKILL.md"][0] == skill_document()
    assert files["SKILL.md"][2] is False


def test_a_second_push_adds_revision_two_and_leaves_revision_one_untouched(session_factory,
                                                                          dimitris, maria):
    _push(session_factory, dimitris, skill_archive(files={"notes.md": "first\n"}))
    before = _files_of(session_factory, revision=1)

    pushed = _push(session_factory, dimitris, skill_archive(
        files={"notes.md": "second\n"}, description="Now does more."))

    assert pushed.revision == 2
    assert pushed.created is False
    assert pushed.unchanged is False
    assert pushed.previous_pushed_by == "dimitris"
    # Versions are immutable: a push adds rows and changes none.
    assert _files_of(session_factory, revision=1) == before
    assert _files_of(session_factory, revision=2)["notes.md"][0] == "second\n"

    with session_factory() as session:
        skill = session.scalar(select(Skill))
        revisions = session.execute(
            select(SkillVersion.revision, SkillVersion.pushed_by)
            .order_by(SkillVersion.revision)).all()
    # The skill row keeps who first pushed it and follows the latest description.
    assert skill.pushed_by == dimitris.user.user_id
    assert skill.description == "Now does more."
    assert revisions == [(1, dimitris.user.user_id), (2, dimitris.user.user_id)]


def test_identical_content_creates_no_revision_and_says_so(session_factory, dimitris, maria):
    _push(session_factory, dimitris)

    again = _push(session_factory, dimitris)

    assert again.unchanged is True
    assert again.created is False
    assert again.revision == 1
    assert again.previous_pushed_by == "dimitris"
    assert _count(session_factory, SkillVersion) == 1
    assert _count(session_factory, SkillFile) == 1


def test_flipping_only_the_executable_bit_is_not_a_new_revision(session_factory, dimitris):
    """The bit is stored but not hashed (Windows cannot carry it), so the vault sees no change."""
    _push(session_factory, dimitris, skill_archive(files={"run.sh": "echo hi\n"}))

    again = _push(session_factory, dimitris, skill_archive(
        files={"run.sh": "echo hi\n"}, executable=frozenset({"run.sh"})))

    assert again.unchanged is True
    assert _files_of(session_factory, revision=1)["run.sh"][2] is False


def test_content_that_returns_to_an_earlier_state_is_still_a_new_revision(session_factory,
                                                                         dimitris):
    """A → B → A: only a match with the *latest* revision means nothing to do."""
    first = skill_archive(files={"notes.md": "A\n"})
    _push(session_factory, dimitris, first)
    _push(session_factory, dimitris, skill_archive(files={"notes.md": "B\n"}))

    back = _push(session_factory, dimitris, first)

    assert back.revision == 3
    assert back.unchanged is False


def test_a_push_enables_the_skill_for_the_pushing_machine_only(session_factory, dimitris,
                                                             maria):
    _push(session_factory, dimitris)

    with session_factory() as session:
        decisions = session.execute(select(MachineSkill.machine_id, MachineSkill.enabled)).all()
    assert decisions == [(dimitris.machine.machine_id, True)]


def test_pushing_twice_keeps_one_decision_row(session_factory, dimitris):
    _push(session_factory, dimitris, skill_archive(files={"notes.md": "one\n"}))
    _push(session_factory, dimitris, skill_archive(files={"notes.md": "two\n"}))

    assert _count(session_factory, MachineSkill) == 1


def test_a_push_re_enables_a_skill_the_machine_had_disabled(session_factory, dimitris):
    _push(session_factory, dimitris)
    with session_factory.begin() as session:
        session.scalar(select(MachineSkill)).enabled = False

    _push(session_factory, dimitris)

    with session_factory() as session:
        assert session.scalar(select(MachineSkill.enabled)) is True
    assert _count(session_factory, MachineSkill) == 1


def test_an_unchanged_push_still_enables_the_skill_for_a_new_machine(session_factory, dimitris,
                                                                   maria):
    _push(session_factory, dimitris)

    _push(session_factory, maria)

    assert _count(session_factory, MachineSkill) == 2


def test_the_origin_is_recorded_once_and_never_overwritten(session_factory, dimitris, maria):
    _push(session_factory, dimitris, origin=ORIGIN)

    pushed = _push(session_factory, dimitris, skill_archive(files={"x.md": "x\n"}),
                   origin="https://example.com/some-other-wizard")

    assert pushed.stored_origin == ORIGIN
    with session_factory() as session:
        assert session.scalar(select(Skill.origin)) == ORIGIN


def test_a_later_push_does_not_fill_in_an_origin_the_first_one_left_out(session_factory,
                                                                       dimitris, maria):
    _push(session_factory, dimitris, origin=None)

    pushed = _push(session_factory, dimitris, skill_archive(files={"x.md": "x\n"}), origin=ORIGIN)

    assert pushed.stored_origin is None


# --- whose skill a push lands in ------------------------------------------------------------

def test_two_people_pushing_the_same_name_each_get_their_own_skill(session_factory, dimitris,
                                                                  maria):
    """A push lands in the pusher's own skills. Nobody's push can land on anybody else's."""
    first = _push(session_factory, dimitris, skill_archive(files={"x.md": "dimitris\n"}))
    second = _push(session_factory, maria, skill_archive(files={"x.md": "maria\n"}))

    assert (first.revision, first.created) == (1, True)
    assert (second.revision, second.created, second.previous_pushed_by) == (1, True, None)
    with session_factory() as session:
        assert len(session.scalars(select(Skill)).all()) == 2


def test_the_frontmatter_is_stored_parsed_and_skill_md_is_stored_verbatim(session_factory,
                                                                         dimitris):
    document = skill_document(
        extra_frontmatter="version: 1.10\nallowed-tools: Bash(git *)\nmetadata:\n  team: x\n")

    _push(session_factory, dimitris, skill_archive(files={"SKILL.md": document}))

    with session_factory() as session:
        version = session.scalar(select(SkillVersion))
    assert version.version == "1.10"
    assert version.frontmatter_json == {
        "name": "wizard",
        "description": "Walks a human through steps.",
        "version": "1.10",
        "allowed-tools": "Bash(git *)",
        "metadata": {"team": "x"},
    }
    assert _files_of(session_factory, revision=1)["SKILL.md"][0] == document


def test_a_rejected_upload_leaves_no_row_behind(session_factory, dimitris):
    with pytest.raises(ValidationError):
        _push(session_factory, dimitris, skill_archive(files={"logo.png": b"\x89PNG\x00"}))

    for model in (Skill, SkillVersion, SkillFile, MachineSkill):
        assert _count(session_factory, model) == 0


def test_a_rejected_revision_leaves_the_existing_skill_as_it_was(session_factory, dimitris):
    _push(session_factory, dimitris)

    with pytest.raises(ValidationError):
        _push(session_factory, dimitris, skill_archive(description="d" * 1025))

    assert _count(session_factory, SkillVersion) == 1
    with session_factory() as session:
        assert session.scalar(select(Skill.description)) == "Walks a human through steps."


def test_the_archive_must_be_the_skill_the_ticket_named(session_factory, dimitris):
    with pytest.raises(ValidationError, match="but the push is for 'wizard'"):
        _push(session_factory, dimitris, skill_archive("sorcerer"), name="wizard")


def test_a_machine_revoked_after_the_url_was_issued_cannot_push(session_factory, dimitris):
    with session_factory.begin() as session:
        session.delete(session.merge(dimitris.machine))

    with pytest.raises(InvalidTicket, match="no longer registered"):
        _push(session_factory, dimitris)

    assert _count(session_factory, Skill) == 0


def test_a_ticket_naming_a_machine_under_the_wrong_user_is_refused(session_factory, dimitris,
                                                                 maria):
    """Cannot happen with a signed ticket; the service does not rely on that."""
    with session_factory.begin() as session:
        with pytest.raises(InvalidTicket):
            skill_service.push(session, machine_id=dimitris.machine.machine_id,
                               user_id=maria.user.user_id, name="wizard", origin=None,
                               archive=skill_archive())


def test_an_unknown_machine_is_refused(session_factory, dimitris):
    with session_factory.begin() as session:
        with pytest.raises(InvalidTicket):
            skill_service.push(session, machine_id=uuid.uuid4(), user_id=dimitris.user.user_id,
                               name="wizard", origin=None, archive=skill_archive())


def test_two_skills_keep_separate_revision_counters(session_factory, dimitris):
    _push(session_factory, dimitris, name="wizard")
    _push(session_factory, dimitris, skill_archive("wizard", files={"x.md": "x\n"}))

    other = _push(session_factory, dimitris, name="code-review")

    assert other.revision == 1
    assert other.created is True


def test_a_push_that_keeps_losing_the_revision_race_gives_up_cleanly(session_factory, dimitris,
                                                                    monkeypatch):
    """Three losses in a row. The real race needs Postgres; the give-up path does not."""
    _push(session_factory, dimitris, skill_archive(files={"notes.md": "one\n"}))
    _push(session_factory, dimitris, skill_archive(files={"notes.md": "two\n"}))
    with session_factory() as session:
        revision_one = session.scalar(select(SkillVersion).where(SkillVersion.revision == 1))

    # Every read reports revision 1 as the latest, so every attempt claims the taken number 2.
    monkeypatch.setattr(skill_service, "_latest_version", lambda session, skill_id: revision_one)

    with pytest.raises(Conflict) as rejection:
        _push(session_factory, dimitris, skill_archive(files={"notes.md": "three\n"}))

    assert "push it again" in str(rejection.value)
    assert _count(session_factory, SkillVersion) == 2
    assert _count(session_factory, SkillFile) == 4
