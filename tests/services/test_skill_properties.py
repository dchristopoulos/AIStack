"""Generated files and paths keep the same meaning across archives and operating systems."""

import io
import os
import tarfile
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from hypothesis import example, given
from hypothesis import strategies as st

from aistack.commons.exceptions import ValidationError
from aistack.commons.text import loggable
from aistack.services.content_hash import canonical_content_hash, file_digest, normalized_path
from aistack.services.local_skills import install
from aistack.services.reconciliation import Choice, Desired, Observed, Step, reconcile
from aistack.services.skill_archive import build_archive, read_archive
from aistack.services.skill_validation import _validated_path, validated_skill
from tests.archives import skill_document

_NAMES = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=15)
_FILES = st.dictionaries(_NAMES, st.text(alphabet="abc XYZ\n", max_size=80), min_size=1, max_size=6)


def _skill(files):
    return validated_skill("wizard", read_archive(build_archive(files)))


@given(files=_FILES, data=st.data())
def test_file_order_and_archive_layout_do_not_change_the_content_hash(files, data):
    entries = [("SKILL.md", skill_document().encode(), False)]
    entries += [(f"docs/file-{name}.txt", body.encode(), False) for name, body in files.items()]
    expected = _skill(entries)
    order = data.draw(st.permutations(entries))
    assert canonical_content_hash({path: file_digest(content)
                                   for path, content, _ in order}) == expected.content_hash
    layout = data.draw(st.sampled_from([tarfile.USTAR_FORMAT, tarfile.PAX_FORMAT, tarfile.GNU_FORMAT]))
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=layout) as archive:
        directory = tarfile.TarInfo("./docs")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        for path, content, _ in order:
            member = tarfile.TarInfo(f"./{path}")
            member.size = len(content)
            member.mtime = data.draw(st.integers(min_value=0, max_value=2**31))
            archive.addfile(member, io.BytesIO(content))
    assert validated_skill("wizard", read_archive(buffer.getvalue())).content_hash == (
        expected.content_hash)


@given(files=_FILES)
def test_one_changed_byte_or_filename_changes_the_hash(files):
    entries = [("SKILL.md", skill_document().encode(), False)]
    entries += [(f"docs/file-{name}.txt", ("a" + body).encode(), False) for name, body in files.items()]
    original = _skill(entries).content_hash
    path, content, mode = entries[-1]
    assert _skill([*entries[:-1], (path, b"b" + content[1:], mode)]).content_hash != original
    assert _skill([*entries[:-1], (path.replace("docs/", "copy/", 1), content, mode)]).content_hash != original


@given(body=st.text(alphabet="abc XYZ\n", max_size=80), executable=st.booleans())
def test_modes_round_trip_without_changing_the_hash(body, executable):
    entries = [("SKILL.md", skill_document().encode(), False), ("run.sh", body.encode(), executable)]
    packed = build_archive(entries)
    archived = read_archive(packed)
    assert next(file.executable for file in archived if file.path == "run.sh") is executable
    checked = validated_skill("wizard", archived)
    assert checked.content_hash == _skill([(path, content, not mode)
                                          for path, content, mode in entries]).content_hash
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        install(folder, "wizard", packed, checked.content_hash)
        target = folder / "wizard/run.sh"
        assert target.read_bytes() == body.encode()
        if os.name != "nt":
            assert bool(target.stat().st_mode & 0o111) is executable


@given(raw=st.one_of(
    st.text(max_size=300),
    st.lists(st.one_of(_NAMES, st.sampled_from(["..", ".", "", "C:", "nul", ".git", "a\n"])),
             min_size=1, max_size=10).map("/".join),
    st.lists(_NAMES, min_size=1, max_size=8).map("/".join),
))
@example(raw="../escape.txt")
@example(raw="/outside/file.txt")
@example(raw="D:/outside/file.txt")
@example(raw="")
def test_a_path_is_inside_the_skill_on_both_systems_or_its_refusal_names_it(raw):
    try:
        path = _validated_path(raw)
    except ValidationError as error:
        assert loggable(normalized_path(raw)) in str(error)
        assert str(error).isprintable()
        return
    for root in (PurePosixPath("/skills/wizard"), PureWindowsPath("C:/skills/wizard")):
        joined = root / path
        assert joined.is_relative_to(root)
        assert ".." not in joined.parts
        assert joined != root


@given(desired=st.sampled_from(Desired), observed=st.sampled_from(Observed))
def test_every_sync_state_has_a_verdict_and_local_edits_require_a_choice(desired, observed):
    verdict = reconcile(desired, observed)
    assert verdict.step in Step
    if observed is Observed.UNKNOWN:
        assert verdict.step is Step.ASK
        for option in verdict.options:
            if option.choice in (Choice.ENABLE, Choice.RESTORE, Choice.REMOVE):
                assert option.loses_local_edits
    if verdict.step in (Step.INSTALL, Step.UPDATE):
        assert desired is Desired.ENABLED
        assert observed in (Observed.ABSENT, Observed.STALE)
