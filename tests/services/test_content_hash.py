import unicodedata

import pytest

from aistack.services.content_hash import (
    canonical_content_hash,
    file_digest,
    normalized_path,
)

# The fixture the push ticket asks for: a unicode filename, a nested path, and CRLF content.
FIXTURE = {
    "SKILL.md": b"---\nname: fixture\ndescription: A fixture.\n---\r\nBody with CRLF.\r\n",
    "références/naïve.md": "café\n".encode("utf-8"),
    "scripts/run.sh": b"#!/bin/sh\r\necho hi\r\n",
}

# Derived without this module, with perl, shasum, and xxd, so the assertion is not the
# implementation agreeing with itself. For each file in byte order of its path:
#
#   perl -e 'print pack("Q>", length($ARGV[0])), $ARGV[0]' "$path"   # 8-byte length, path
#   shasum -a 256 "$file" | cut -d' ' -f1 | xxd -r -p                # raw 32-byte digest
#
# and the concatenation of all three piped into `shasum -a 256`.
EXPECTED_HASH = "46def75068debc93803ee57d1e057bd6489cb9270d5b1711425c45ae193bf26b"


def _hashed(files: dict[str, bytes]) -> str:
    return canonical_content_hash({normalized_path(path): file_digest(content)
                                   for path, content in files.items()})


def test_the_fixture_hashes_to_the_independently_derived_constant():
    assert _hashed(FIXTURE) == EXPECTED_HASH


def test_the_hash_does_not_depend_on_the_order_files_arrive_in():
    assert _hashed(dict(reversed(FIXTURE.items()))) == EXPECTED_HASH


def test_windows_separators_and_a_leading_dot_slash_hash_the_same():
    """What `Get-FileHash` and `find .` report for the same three files."""
    reported = {
        ".\\SKILL.md": FIXTURE["SKILL.md"],
        "./références/naïve.md": FIXTURE["références/naïve.md"],
        "scripts\\run.sh": FIXTURE["scripts/run.sh"],
    }

    assert _hashed(reported) == EXPECTED_HASH


def test_a_decomposed_filename_hashes_the_same_as_a_composed_one():
    """macOS returns filenames in NFD; the same file pushed from Linux arrives in NFC."""
    decomposed = unicodedata.normalize("NFD", "références/naïve.md")
    assert decomposed != "références/naïve.md"

    files = {**FIXTURE, decomposed: FIXTURE["références/naïve.md"]}
    del files["références/naïve.md"]

    assert _hashed(files) == EXPECTED_HASH


def test_content_is_hashed_exactly_as_it_is():
    """No newline translation: the same text with LF endings is different content."""
    unix_endings = {**FIXTURE, "scripts/run.sh": b"#!/bin/sh\necho hi\n"}

    assert _hashed(unix_endings) != EXPECTED_HASH


def test_a_renamed_file_changes_the_hash():
    renamed = {**FIXTURE, "scripts/start.sh": FIXTURE["scripts/run.sh"]}
    del renamed["scripts/run.sh"]

    assert _hashed(renamed) != EXPECTED_HASH


def test_the_framing_keeps_a_path_from_running_into_the_next_field():
    """Without a length prefix, moving a character between two paths would hash the same."""
    digest = file_digest(b"same")

    assert (canonical_content_hash({"ab": digest, "c": digest})
            != canonical_content_hash({"a": digest, "bc": digest}))


def test_paths_sort_by_bytes_not_by_locale():
    """'Z' sorts before 'a' in bytes and after it in most locales. Either order must agree."""
    digests = {"Z.md": file_digest(b"z"), "a.md": file_digest(b"a")}

    assert (canonical_content_hash(digests)
            == canonical_content_hash(dict(reversed(digests.items()))))


@pytest.mark.parametrize("digest", ["", "abc", "g" * 64, "a" * 63, "a" * 65])
def test_a_digest_that_is_not_sha256_hex_is_refused(digest):
    with pytest.raises(ValueError):
        canonical_content_hash({"SKILL.md": digest})
