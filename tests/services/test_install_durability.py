"""An install persists its staged revision before making it visible."""

import os
import stat
import sys
from pathlib import Path

import pytest

from aistack.services import local_skills
from aistack.services.skill_archive import read_archive
from aistack.services.skill_validation import validated_skill
from tests.archives import skill_archive


def _revision(body):
    packed = skill_archive(
        files={"docs/nested/notes.md": body, "run.sh": "echo hi\n"},
        executable=frozenset({"run.sh"}),
    )
    return packed, validated_skill("wizard", read_archive(packed)).content_hash


def test_files_and_directories_are_flushed_before_the_install_is_replaced(tmp_path, monkeypatch):
    flushed_files = set()
    flushed_directories = []
    fsync = os.fsync
    open_file = Path.open
    handles = {}
    swap_in = local_skills._swap_in
    flush_directory = local_skills._flush_directory

    def opened(path, *args, **kwargs):
        stream = open_file(path, *args, **kwargs)
        if args == ("wb",):
            handles[stream.fileno()] = path
        return stream

    def flushed(descriptor):
        details = os.fstat(descriptor)
        if stat.S_ISREG(details.st_mode):
            # Without stream.flush(), these small writes would still be in Python's buffer.
            assert details.st_size > 0
            path = handles[descriptor]
            relative = path.relative_to(tmp_path / local_skills.STAGING_FOLDER)
            relative = Path(*relative.parts[1:])
            if os.name != "nt":
                assert stat.S_IMODE(details.st_mode) == (0o755 if relative.name == "run.sh" else 0o644)
            flushed_files.add(relative.as_posix())
        else:
            flushed_directories.append(details.st_ino)
        fsync(descriptor)

    def directory_flushed(folder):
        flush_directory(folder)
        if os.name != "nt":
            assert folder.stat().st_ino in flushed_directories

    def replacing(staged, destination, staging):
        assert flushed_files == {"SKILL.md", "run.sh", "docs/nested/notes.md"}
        if os.name != "nt":
            assert flushed_directories == [
                (staged / "docs/nested").stat().st_ino,
                (staged / "docs").stat().st_ino,
                staged.stat().st_ino,
                staging.stat().st_ino,
            ]
        swap_in(staged, destination, staging)

    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(os, "fsync", flushed)
    monkeypatch.setattr(local_skills, "_flush_directory", directory_flushed)
    monkeypatch.setattr(local_skills, "_swap_in", replacing)

    local_skills.install(tmp_path, "wizard", *_revision("new\n"))

    assert (tmp_path / "wizard/docs/nested/notes.md").read_bytes() == b"new\n"
    if os.name != "nt":
        assert flushed_directories[-1] == tmp_path.stat().st_ino


@pytest.mark.parametrize("failure", ["file", "directory"])
def test_a_failed_flush_before_replacement_keeps_the_installed_revision(
        tmp_path, monkeypatch, failure):
    if failure == "directory" and sys.platform == "win32":
        pytest.skip("Windows cannot open a directory with os.open.")
    local_skills.install(tmp_path, "wizard", *_revision("old\n"))
    fsync = os.fsync

    def failed(descriptor):
        directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
        if directory == (failure == "directory"):
            raise OSError("disk refused the flush")
        fsync(descriptor)

    monkeypatch.setattr(os, "fsync", failed)
    with pytest.raises(OSError, match="disk refused the flush"):
        local_skills.install(tmp_path, "wizard", *_revision("new\n"))

    assert (tmp_path / "wizard/docs/nested/notes.md").read_bytes() == b"old\n"
    assert list((tmp_path / local_skills.STAGING_FOLDER).iterdir()) == []


@pytest.mark.skipif(sys.platform == "win32", reason="Windows cannot open a directory with os.open.")
def test_a_directory_descriptor_is_closed_when_its_flush_fails(tmp_path, monkeypatch):
    descriptors = []

    def failed(descriptor):
        descriptors.append(descriptor)
        raise OSError("disk refused the flush")

    monkeypatch.setattr(os, "fsync", failed)
    with pytest.raises(OSError, match="disk refused"):
        local_skills._flush_directory(tmp_path)

    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
