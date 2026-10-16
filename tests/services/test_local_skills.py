"""Writing skill folders in local mode: an install is a whole revision or nothing."""

import threading

from aistack.services import local_skills
from aistack.services.skill_archive import read_archive
from aistack.services.skill_validation import validated_skill
from tests.archives import skill_archive


def _revision(text: str) -> tuple[bytes, str]:
    packed = skill_archive("wizard", files={"notes.md": text, "more.md": text})
    return packed, validated_skill("wizard", read_archive(packed)).content_hash


def test_two_installs_of_one_skill_at_once_leave_one_whole_revision(tmp_path, monkeypatch):
    """Two sessions installing one skill at once used to share a staging folder: the second
    discarded the first's copy, and the first then moved what was there into place."""
    first, second = _revision("first\n"), _revision("second\n")
    second_done = threading.Event()
    swap_in = local_skills._swap_in

    def first_waits_for_the_second(staged, destination, staging):
        if threading.current_thread().name == "first":
            assert second_done.wait(5)
        swap_in(staged, destination, staging)

    monkeypatch.setattr(local_skills, "_swap_in", first_waits_for_the_second)
    failures = []

    def install(packed_and_hash, done=None):
        try:
            local_skills.install(tmp_path, "wizard", *packed_and_hash)
        except Exception as error:
            failures.append(error)
        finally:
            if done is not None:
                done.set()

    racing = threading.Thread(target=install, args=(first,), name="first")
    racing.start()
    install(second, second_done)
    racing.join(10)

    assert failures == []
    folder = tmp_path / "wizard"
    assert (folder / "notes.md").read_text() == (folder / "more.md").read_text() == "first\n"
    # Nothing is left half-written beside it.
    assert list((tmp_path / local_skills.STAGING_FOLDER).iterdir()) == []
