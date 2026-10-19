"""Writing skill folders in local mode: an install is a whole revision or nothing."""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from aistack.commons.exceptions import Busy, ValidationError
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


# --- modes, a missing skill, links, what sync is shown ---------------------------------------

posix_modes = pytest.mark.skipif(sys.platform == "win32", reason="Windows has no execute bit.")


@posix_modes
def test_an_install_writes_scripts_executable_and_everything_else_not(tmp_path):
    # "Assets" sorts before SKILL.md, so the first file written needs two new folders.
    packed = skill_archive("wizard", files={"Assets/run.sh": "echo hi\n", "notes.md": "x\n"},
                           executable=frozenset({"Assets/run.sh"}))
    content_hash = validated_skill("wizard", read_archive(packed)).content_hash

    local_skills.install(tmp_path, "wizard", packed, content_hash)

    folder = tmp_path / "wizard"
    assert (folder / "Assets/run.sh").stat().st_mode & 0o777 == 0o755
    assert (folder / "notes.md").stat().st_mode & 0o777 == 0o644


@posix_modes
@pytest.mark.parametrize(("mode", "executable"), [
    (0o644, False),
    (0o744, True),
    (0o645, True),
], ids=["plain", "owner-only", "others-only"])
def test_a_packed_file_is_executable_when_anyone_may_run_it(tmp_path, mode, executable):
    _folder(tmp_path, {"run.sh": b"echo hi\n"})
    (tmp_path / "wizard/run.sh").chmod(mode)

    [packed] = read_archive(local_skills.archive(tmp_path, "wizard"))

    assert packed.executable is executable


def test_a_link_to_a_folder_inside_a_skill_is_refused_by_push_and_left_out_of_sync(tmp_path):
    _folder(tmp_path, {"SKILL.md": b"x"})
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere/secret.md").write_bytes(b"s")
    (tmp_path / "wizard/docs").symlink_to(tmp_path / "elsewhere", target_is_directory=True)

    with pytest.raises(ValidationError, match="'docs' in 'wizard' is a link"):
        local_skills.archive(tmp_path, "wizard")
    assert local_skills.observed(tmp_path)["wizard"] == {
        "SKILL.md": local_skills._digest(tmp_path / "wizard/SKILL.md"),
    }


def test_sync_is_shown_skill_folders_only(tmp_path):
    _folder(tmp_path, {"SKILL.md": b"x", ".DS_Store": b"noise"})
    for hidden in (local_skills.STAGING_FOLDER, ".hidden", "synced"):
        (tmp_path / hidden / "inside").mkdir(parents=True)
        (tmp_path / hidden / "inside/SKILL.md").write_bytes(b"x")
    (tmp_path / "README.md").write_bytes(b"not a skill")

    assert {name: list(files) for name, files in local_skills.observed(tmp_path).items()} == {
        "wizard": ["SKILL.md"],
    }


def test_removing_a_skill_that_is_not_there_says_so_and_touches_nothing(tmp_path):
    assert local_skills.remove(tmp_path, "wizard") is False
    assert list(tmp_path.iterdir()) == []


def test_removing_a_linked_skill_takes_the_link_and_never_what_it_points_to(tmp_path):
    (tmp_path / "checkout").mkdir()
    (tmp_path / "checkout/SKILL.md").write_bytes(b"x")
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "wizard").symlink_to(tmp_path / "checkout", target_is_directory=True)
    (skills / "gone").symlink_to(tmp_path / "nowhere", target_is_directory=True)

    assert local_skills.remove(skills, "wizard") is True
    assert local_skills.remove(skills, "gone") is True

    assert (tmp_path / "checkout/SKILL.md").read_bytes() == b"x"
    assert not (skills / "wizard").is_symlink() and not (skills / "gone").is_symlink()
    assert list((skills / local_skills.STAGING_FOLDER).iterdir()) == []


def test_removing_a_skill_folder_takes_all_of_it(tmp_path):
    _folder(tmp_path, {"SKILL.md": b"x", "docs/notes.md": b"y"})

    assert local_skills.remove(tmp_path, "wizard") is True

    assert sorted(path.name for path in tmp_path.iterdir()) == [local_skills.STAGING_FOLDER]
    assert list((tmp_path / local_skills.STAGING_FOLDER).iterdir()) == []


def test_a_refresh_left_half_done_is_finished_by_the_next(tmp_path):
    _folder(tmp_path, {"SKILL.md": b"old", "SKILL.md.aistack-new": b"stale"})

    local_skills.refresh(tmp_path, "wizard", "new")

    assert sorted(path.name for path in (tmp_path / "wizard").iterdir()) == ["SKILL.md"]
    assert (tmp_path / "wizard/SKILL.md").read_bytes() == b"new"

@pytest.mark.parametrize("collisions", [1, 5],
                         ids=["retry-succeeds", "retry-exhausted"])
def test_an_install_racing_between_renames_retries_or_says_to_try_again(
        tmp_path, monkeypatch, collisions):
    local_skills.install(tmp_path, "wizard", *_revision("old\n"))
    rendezvous = threading.Barrier(2)
    rename = Path.rename
    attempts = []
    main_thread = threading.get_ident()

    def contender_between_renames(path, target):
        if (threading.get_ident() != main_thread
                and path.parent == tmp_path / local_skills.STAGING_FOLDER
                and not path.name.endswith(".replaced")):
            attempts.append(path)
            if len(attempts) <= collisions:
                # The previous folder has moved out, but this revision has not moved in.
                assert not (tmp_path / "wizard").exists()
                rendezvous.wait(timeout=10)
                rendezvous.wait(timeout=10)
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", contender_between_renames)
    with ThreadPoolExecutor(max_workers=1) as pool:
        losing = pool.submit(local_skills.install, tmp_path, "wizard", *_revision("loser\n"))
        try:
            for index in range(collisions):
                rendezvous.wait(timeout=10)
                local_skills.install(tmp_path, "wizard", *_revision(f"winner {index}\n"))
                rendezvous.wait(timeout=10)
            if collisions == 5:
                with pytest.raises(Busy, match="Another session kept installing 'wizard'.*Try again"):
                    losing.result(timeout=10)
                expected = f"winner {collisions - 1}\n"
                assert len(attempts) == 5
            else:
                losing.result(timeout=10)
                expected = "loser\n"
                assert len(attempts) == collisions + 1
        finally:
            rendezvous.abort()

    folder = tmp_path / "wizard"
    assert (folder / "notes.md").read_text() == (folder / "more.md").read_text() == expected
    assert sorted(path.name for path in folder.iterdir()) == ["SKILL.md", "more.md", "notes.md"]
    assert list((tmp_path / local_skills.STAGING_FOLDER).iterdir()) == []
