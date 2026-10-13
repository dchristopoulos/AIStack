"""Reading and writing the gzipped tar a skill travels in (ADR-0010).

Reading is a trust boundary: the bytes come from a client, and an archive is a format built to
describe things a skill must never contain. Nothing here touches the filesystem.
"""

import gzip
import io
import tarfile
import zlib
from collections.abc import Iterable
from dataclasses import dataclass

from aistack.commons.exceptions import ValidationError
from aistack.commons.text import loggable

# Sized against the reference corpus (largest skill 19 KB) with two orders of magnitude spare.
MAX_ARCHIVE_BYTES = 1024 * 1024
MAX_FILE_COUNT = 100
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 1024 * 1024

# Headers, padding, and pax records on top of the file bytes themselves. Generous, and still
# a hard ceiling on what one megabyte of gzip may expand to.
_MAX_TAR_BYTES = 4 * MAX_TOTAL_BYTES

# auto-detect off: 16 + MAX_WBITS means "a gzip stream, and nothing else".
_GZIP_WBITS = 16 + zlib.MAX_WBITS

_EXECUTABLE_BITS = 0o111


@dataclass(frozen=True)
class ArchivedFile:
    """One regular file as the archive named it. The path is not yet validated."""

    path: str
    content: bytes
    executable: bool


def read_archive(body: bytes) -> list[ArchivedFile]:
    """Return the regular files in a gzipped tar, or reject the whole archive."""
    if len(body) > MAX_ARCHIVE_BYTES:
        raise ValidationError(
            f"The upload is {len(body)} bytes and the limit is {MAX_ARCHIVE_BYTES}. A skill "
            "is instructions and a few supporting files; leave out anything that is not."
        )

    files: list[ArchivedFile] = []
    total_bytes = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(_gunzipped(body)), mode="r:") as archive:
            for member in archive:
                if member.isdir() or is_filesystem_noise(member.name):
                    continue
                # REGTYPE and AREGTYPE only. isfile() would also admit sparse files, and
                # everything else is a link, a device, or a FIFO.
                if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE):
                    raise ValidationError(
                        f"'{loggable(member.name)}' is not a regular file (it is a link, "
                        "device, or other special entry). A skill may contain only files "
                        "and folders; replace a link with a copy of what it points to."
                    )
                if len(files) == MAX_FILE_COUNT:
                    raise ValidationError(
                        f"The archive holds more than {MAX_FILE_COUNT} files. If a .git or "
                        "node_modules folder is inside the skill, leave it out."
                    )
                if member.size > MAX_FILE_BYTES:
                    raise ValidationError(
                        f"'{loggable(member.name)}' is {member.size} bytes and the limit "
                        f"per file is {MAX_FILE_BYTES}."
                    )
                total_bytes += member.size
                if total_bytes > MAX_TOTAL_BYTES:
                    raise ValidationError(
                        f"The files total more than {MAX_TOTAL_BYTES} bytes uncompressed, "
                        "which is the limit for one skill."
                    )
                files.append(ArchivedFile(
                    path=member.name,
                    content=archive.extractfile(member).read(),
                    executable=bool(member.mode & _EXECUTABLE_BITS),
                ))
    except tarfile.TarError as error:
        raise ValidationError(
            "The upload is not a readable tar archive. Create it with "
            "'tar -czf <file> -C <skill folder> .' and send that file unchanged."
        ) from error

    if not files:
        raise ValidationError("The archive contains no files. Archive the skill's own folder, "
                              "the one that holds SKILL.md.")
    return files


def build_archive(files: Iterable[tuple[str, bytes, bool]], modified_at: int = 0) -> bytes:
    """Pack `(path, content, executable)` into a gzipped tar that any `tar` can extract.

    Deterministic: same files and same `modified_at` (seconds since the epoch) give the same
    bytes. Every file carries that one timestamp, and no owner, because nothing about the
    server's clock or its user belongs on the machine that installs the skill.
    """
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=modified_at) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for path, content, executable in sorted(files, key=lambda file: file[0].encode()):
                member = tarfile.TarInfo(name=path)
                member.size = len(content)
                member.mode = 0o755 if executable else 0o644
                member.mtime = modified_at
                archive.addfile(member, io.BytesIO(content))
    return buffer.getvalue()


def _gunzipped(body: bytes) -> bytes:
    """Decompress with a ceiling, so a small upload cannot become a large allocation.

    tarfile's own gzip mode has no such ceiling, and it reads a pax header into memory at
    whatever size the header claims — one megabyte of gzip can claim a gigabyte.
    """
    output = bytearray()
    remaining = body
    try:
        # A gzip file may be several streams back to back; tar itself writes one.
        while remaining:
            stream = zlib.decompressobj(wbits=_GZIP_WBITS)
            output += stream.decompress(remaining, _MAX_TAR_BYTES + 1 - len(output))
            if len(output) > _MAX_TAR_BYTES:
                raise ValidationError(
                    f"The archive expands to more than {_MAX_TAR_BYTES} bytes, far beyond "
                    f"the {MAX_TOTAL_BYTES} a skill's files may total."
                )
            if not stream.eof:
                raise ValidationError("The upload ends in the middle of its gzip data. Send "
                                      "the whole archive file.")
            remaining = stream.unused_data
    except zlib.error as error:
        raise ValidationError(
            "The upload is not gzip data. Create it with 'tar -czf <file> -C <skill folder> .' "
            "and send it with 'curl --data-binary @<file>', which sends the bytes unchanged."
        ) from error
    return bytes(output)


def is_filesystem_noise(name: str) -> bool:
    """Entries the operating system made, not the skill's author.

    macOS `tar` synthesizes `._name` AppleDouble entries for extended attributes; they never
    existed on disk. `.DS_Store` did, and is Finder's, not the skill's.
    """
    basename = name.rsplit("/", 1)[-1]
    return basename == ".DS_Store" or basename.startswith("._")
