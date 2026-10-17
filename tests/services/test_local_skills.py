"""Writing skill folders in local mode: an install is a whole revision or nothing."""

import threading

import pytest

from aistack.commons.exceptions import ValidationError
from aistack.services import local_skills
from aistack.services.skill_archive import MAX_FILE_BYTES, MAX_FILE_COUNT, read_archive
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


# --- every limit at exactly the limit (T3) --------------------------------------------------

def _folder(tmp_path, files: dict[str, bytes]):
    for path, content in files.items():
        (tmp_path / "wizard" / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "wizard" / path).write_bytes(content)


@pytest.mark.parametrize(("files", "expected"), [
    ({f"file-{number}.md": b"x" for number in range(MAX_FILE_COUNT)}, None),
    ({f"file-{number}.md": b"x" for number in range(MAX_FILE_COUNT + 1)},
     "holds more than 100 files"),
    ({"big.md": b"a" * MAX_FILE_BYTES}, None),
    ({"big.md": b"a" * (MAX_FILE_BYTES + 1)}, "the limit per file is 262144"),
], ids=["count-at-limit", "count-past-limit", "size-at-limit", "size-past-limit"])
def test_a_folder_at_its_limits_is_packed_and_past_them_refused(tmp_path, files, expected):
    _folder(tmp_path, files)

    if expected is None:
        assert len(read_archive(local_skills.archive(tmp_path, "wizard"))) == len(files)
    else:
        with pytest.raises(ValidationError, match=expected):
            local_skills.archive(tmp_path, "wizard")


def test_noise_the_operating_system_made_is_skipped_and_the_rest_still_packed(tmp_path):
    """os.walk lists a folder's own files before its subfolders, so the noise comes first."""
    _folder(tmp_path, {".DS_Store": b"noise", "SKILL.md": b"x", "docs/notes.md": b"y"})

    packed = read_archive(local_skills.archive(tmp_path, "wizard"))

    assert sorted(file.path for file in packed) == ["SKILL.md", "docs/notes.md"]
