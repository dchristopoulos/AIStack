import gzip
import io
import tarfile
import time

import pytest

from aistack.commons.exceptions import ValidationError
from aistack.services.skill_archive import (
    MAX_ARCHIVE_BYTES,
    MAX_FILE_BYTES,
    MAX_FILE_COUNT,
    ArchivedFile,
    build_archive,
    read_archive,
)
from tests.archives import raw_archive, special_member


def test_an_archive_round_trips_paths_bytes_and_the_executable_bit():
    files = [
        ("SKILL.md", b"---\nname: wizard\n---\r\nbody\r\n", False),
        ("scripts/run.sh", b"#!/bin/sh\necho hi\n", True),
        ("références/naïve.md", "café\n".encode("utf-8"), False),
    ]

    read = read_archive(build_archive(files))

    assert sorted(read, key=lambda file: file.path) == sorted(
        (ArchivedFile(path, content, executable) for path, content, executable in files),
        key=lambda file: file.path)


def test_building_is_deterministic():
    files = [("b.md", b"b", False), ("a.md", b"a", True)]

    assert build_archive(files) == build_archive(reversed(files))


def test_a_built_archive_is_one_any_tar_can_extract(tmp_path):
    archive = build_archive([("SKILL.md", b"x", False), ("bin/tool", b"y", True)])

    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        tar.extractall(tmp_path, filter="data")

    assert (tmp_path / "SKILL.md").read_bytes() == b"x"
    assert (tmp_path / "bin" / "tool").stat().st_mode & 0o111
    assert not (tmp_path / "SKILL.md").stat().st_mode & 0o111


def test_directories_and_a_leading_dot_slash_are_what_tar_dash_c_produces():
    directory = tarfile.TarInfo(name="./scripts")
    directory.type = tarfile.DIRTYPE

    read = read_archive(raw_archive([directory, ("./SKILL.md", b"x"),
                                     ("./scripts/run.sh", b"y")]))

    assert [file.path for file in read] == ["./SKILL.md", "./scripts/run.sh"]


@pytest.mark.parametrize("noise", [".DS_Store", "._SKILL.md", "scripts/._run.sh",
                                   "scripts/.DS_Store"])
def test_entries_the_operating_system_made_are_skipped(noise):
    read = read_archive(raw_archive([("SKILL.md", b"x"), (noise, b"\x00\x05\x16\x07")]))

    assert [file.path for file in read] == ["SKILL.md"]


@pytest.mark.parametrize(("member_type", "linkname"), [
    (tarfile.SYMTYPE, "/Users/someone/.ssh/id_rsa"),
    (tarfile.SYMTYPE, "../../etc/passwd"),
    (tarfile.LNKTYPE, "SKILL.md"),
    (tarfile.CHRTYPE, ""),
    (tarfile.BLKTYPE, ""),
    (tarfile.FIFOTYPE, ""),
    (tarfile.GNUTYPE_SPARSE, ""),
], ids=["symlink-absolute", "symlink-relative", "hardlink", "char-device", "block-device",
        "fifo", "sparse"])
def test_anything_that_is_not_a_file_or_a_folder_rejects_the_whole_push(member_type, linkname):
    archive = raw_archive([("SKILL.md", b"x"), special_member("secret", member_type, linkname)])

    with pytest.raises(ValidationError) as rejection:
        read_archive(archive)

    assert "'secret' is not a regular file" in str(rejection.value)


def test_one_file_more_than_the_limit_is_rejected():
    archive = raw_archive([(f"file-{number}.md", b"x") for number in range(MAX_FILE_COUNT + 1)])

    with pytest.raises(ValidationError, match=f"more than {MAX_FILE_COUNT} files"):
        read_archive(archive)


def test_exactly_the_file_limit_is_accepted():
    archive = raw_archive([(f"file-{number}.md", b"x") for number in range(MAX_FILE_COUNT)])

    assert len(read_archive(archive)) == MAX_FILE_COUNT


def test_a_file_over_the_per_file_limit_is_rejected_naming_it():
    archive = raw_archive([("SKILL.md", b"x"), ("big.md", b"a" * (MAX_FILE_BYTES + 1))])

    with pytest.raises(ValidationError) as rejection:
        read_archive(archive)

    assert "'big.md'" in str(rejection.value)
    assert str(MAX_FILE_BYTES) in str(rejection.value)


def test_files_that_fit_one_by_one_but_not_together_are_rejected():
    archive = raw_archive([(f"part-{number}.md", b"a" * MAX_FILE_BYTES) for number in range(5)])

    with pytest.raises(ValidationError, match="total more than"):
        read_archive(archive)


def test_an_upload_over_the_compressed_limit_is_rejected_before_it_is_opened():
    with pytest.raises(ValidationError, match=f"limit is {MAX_ARCHIVE_BYTES}"):
        read_archive(b"\x1f\x8b" + b"\x00" * MAX_ARCHIVE_BYTES)


def test_a_decompression_bomb_stops_at_the_ceiling_not_at_the_end():
    """Half a gigabyte of zeros is under 600 KB of gzip, comfortably inside the upload limit."""
    bomb = gzip.compress(b"\x00" * (512 * 1024 * 1024), compresslevel=9)
    assert len(bomb) < MAX_ARCHIVE_BYTES

    started_at = time.perf_counter()
    with pytest.raises(ValidationError, match="expands to more than"):
        read_archive(bomb)

    # Decompressing all of it takes seconds and half a gigabyte; stopping early takes neither.
    assert time.perf_counter() - started_at < 1


def test_a_pax_header_claiming_a_huge_size_cannot_allocate_it():
    """tarfile reads an extended header into memory at whatever size the header says."""
    header = tarfile.TarInfo(name="PaxHeader")
    header.type = tarfile.XHDTYPE
    header.size = 300 * 1024 * 1024
    block = header.tobuf(format=tarfile.PAX_FORMAT)
    bomb = gzip.compress(block + b"\x00" * header.size, compresslevel=9)
    assert len(bomb) < MAX_ARCHIVE_BYTES

    with pytest.raises(ValidationError):
        read_archive(bomb)


@pytest.mark.parametrize(("body", "expected"), [
    (b"", "not a readable tar archive"),
    (b"just some text, not an archive", "not gzip data"),
    (gzip.compress(b"gzip, but there is no tar inside"), "not a readable tar archive"),
    (raw_archive([("SKILL.md", b"x" * 5000)])[:-20], "ends in the middle"),
], ids=["empty", "not-gzip", "not-tar", "truncated"])
def test_a_body_that_is_not_a_gzipped_tar_says_how_to_make_one(body, expected):
    with pytest.raises(ValidationError) as rejection:
        read_archive(body)

    assert expected in str(rejection.value)


def test_an_archive_holding_only_folders_and_noise_is_rejected():
    directory = tarfile.TarInfo(name="scripts")
    directory.type = tarfile.DIRTYPE

    with pytest.raises(ValidationError, match="contains no files"):
        read_archive(raw_archive([directory, (".DS_Store", b"\x00")]))


def test_a_hostile_member_name_is_escaped_in_the_rejection():
    archive = raw_archive([special_member("evil\nFORGED LINE\x1b[2J", tarfile.SYMTYPE, "x")])

    with pytest.raises(ValidationError) as rejection:
        read_archive(archive)

    assert "\n" not in str(rejection.value)
    assert "\x1b" not in str(rejection.value)
