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


# --- structure: what tarfile must never be handed -------------------------------------------

def _tar_bytes(members) -> bytes:
    """The uncompressed tar of `raw_archive(members)`, for editing block by block."""
    return gzip.decompress(raw_archive(members))


def _pax_member(records: bytes, member_type: bytes = tarfile.XHDTYPE) -> tuple:
    header = tarfile.TarInfo(name="PaxHeader")
    header.type = member_type
    header.size = len(records)
    return header.tobuf(format=tarfile.USTAR_FORMAT), records


def _with_leading_header(header_block: bytes, data: bytes, then: list) -> bytes:
    """A gzipped tar that opens with one hand-built header member, then ordinary files."""
    padding = b"\0" * (-len(data) % 512)
    return gzip.compress(header_block + data + padding + _tar_bytes(then))


def test_a_small_upload_cannot_make_tarfile_build_a_huge_header(tmp_path):
    """Six kilobytes of gzip that tarfile would turn into 56 MiB of pax records."""
    import tracemalloc

    block, records = _pax_member(b"6 a=b\n" * 698_333)
    bomb = _with_leading_header(block, records, [("SKILL.md", b"x")])
    assert len(bomb) < 16 * 1024

    tracemalloc.start()
    try:
        with pytest.raises(ValidationError):
            read_archive(bomb)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # Decompressing it costs what it weighs; parsing it is what must not happen.
    assert peak < 16 * 1024 * 1024


@pytest.mark.parametrize("member_type", [tarfile.XHDTYPE, tarfile.XGLTYPE])
def test_an_extended_header_larger_than_any_filename_needs_is_rejected(member_type):
    block, records = _pax_member(b"30 comment=" + b"x" * 18 + b"\n" * 1 + b"6 a=b\n" * 3000,
                                 member_type)

    with pytest.raises(ValidationError, match="extended header far larger"):
        read_archive(_with_leading_header(block, records, [("SKILL.md", b"x")]))


@pytest.mark.parametrize("record", [
    b"11 size=99\n",
    b"26 GNU.sparse.map=0,1,2,3\n",
    b"22 GNU.sparse.major=1\n",
    b"28 GNU.sparse.realsize=abc\n",
])
@pytest.mark.parametrize("member_type", [tarfile.XHDTYPE, tarfile.XGLTYPE])
def test_a_header_that_redefines_where_data_ends_is_rejected(record, member_type):
    """`size` and the sparse keys make tarfile read a different archive than was inspected.

    The malformed sparse values used to reach tarfile, which raises ValueError for them, and
    the upload answered 500.
    """
    block, records = _pax_member(record, member_type)

    with pytest.raises(ValidationError, match="tar extension"):
        read_archive(_with_leading_header(block, records, [("SKILL.md", b"x")]))


def test_an_ordinary_extended_header_is_still_accepted():
    """A long or non-ASCII path is exactly what tar writes a pax header for."""
    long_name = "références/" + "naïve-" * 20 + "notes.md"

    read = read_archive(raw_archive([("SKILL.md", b"x"), (long_name, b"y")]))

    assert [file.path for file in read] == ["SKILL.md", long_name]


def test_an_oversized_gnu_long_name_is_rejected():
    header = tarfile.TarInfo(name="././@LongLink")
    header.type = tarfile.GNUTYPE_LONGNAME
    header.size = 8 * 1024
    block = header.tobuf(format=tarfile.GNU_FORMAT)

    with pytest.raises(ValidationError, match="extended header far larger"):
        read_archive(_with_leading_header(block, b"n" * header.size, [("SKILL.md", b"x")]))


def test_a_damaged_header_rejects_the_archive_instead_of_truncating_it():
    """tarfile stops quietly at a bad block, and half a skill would be stored as a whole one."""
    tar = bytearray(_tar_bytes([("SKILL.md", b"x"), ("notes.md", b"y")]))
    second_header = tar.index(b"notes.md")
    tar[second_header + 200] ^= 0xFF

    with pytest.raises(ValidationError, match="not a readable tar archive"):
        read_archive(gzip.compress(bytes(tar)))


def test_a_garbage_block_between_members_is_rejected():
    tar = _tar_bytes([("SKILL.md", b"x"), ("notes.md", b"y")])
    second_header = tar.index(b"notes.md")
    damaged = tar[:second_header] + b"\xa5" * 512 + tar[second_header:]

    with pytest.raises(ValidationError, match="not a readable tar archive"):
        read_archive(gzip.compress(damaged))


def test_data_after_the_end_of_archive_marker_is_rejected():
    tar = _tar_bytes([("SKILL.md", b"x")])

    with pytest.raises(ValidationError, match="not a readable tar archive"):
        read_archive(gzip.compress(tar + b"hidden after the end"))


def test_a_member_that_claims_more_data_than_the_archive_holds_is_rejected():
    tar = _tar_bytes([("SKILL.md", b"x" * 4000)])

    with pytest.raises(ValidationError, match="not a readable tar archive"):
        read_archive(gzip.compress(tar[:1024]))


def test_no_damaged_archive_ever_raises_anything_but_a_rejection():
    """Flip one byte anywhere, three hundred times. The answer is always a sentence."""
    import random

    tar = _tar_bytes([("SKILL.md", b"---\nname: x\n---\n"), ("scripts/run.sh", b"echo hi\n"),
                      ("références/" + "n" * 120 + ".md", b"y")])
    random.seed(20261013)

    for _ in range(300):
        damaged = bytearray(tar)
        damaged[random.randrange(len(damaged))] ^= 1 << random.randrange(8)
        try:
            read_archive(gzip.compress(bytes(damaged)))
        except ValidationError:
            pass
