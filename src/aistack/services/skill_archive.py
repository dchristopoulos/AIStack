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

# Headers, padding, and pax records on top of the file bytes themselves. A hundred files
# with an extended header each add well under 300 KiB, so twice the content limit is ample,
# and it is the hard ceiling on what one megabyte of gzip may expand to.
_MAX_TAR_BYTES = 2 * MAX_TOTAL_BYTES

_BLOCK_BYTES = 512
_END_OF_ARCHIVE = bytes(_BLOCK_BYTES)

# Members that describe the next member instead of being one: pax extended and global
# headers, and GNU long names and long link names. tarfile parses them itself, in full,
# before a caller sees anything.
_PAX_HEADER_TYPES = (tarfile.XHDTYPE, tarfile.XGLTYPE)
_LONG_NAME_TYPES = (tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK)
# A path is at most 255 characters and macOS adds a few extended attributes per file.
_MAX_PAX_HEADER_BYTES = 16 * 1024
_MAX_LONG_NAME_BYTES = 4 * 1024
# Records that change where tarfile believes a member's data ends. A skill has no use for
# either, and each would let the archive tarfile reads differ from the one inspected here.
_LAYOUT_PAX_KEYS = ("size", "GNU.sparse")

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
    tar = _gunzipped(body)
    _inspect_structure(tar)
    try:
        with tarfile.open(fileobj=io.BytesIO(tar), mode="r:") as archive:
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
    except ValidationError:
        raise
    except Exception as error:
        # Deliberately broad. tarfile raises TarError for most damage, and ValueError,
        # IndexError, or EOFError for the rest (a malformed sparse map, a short read). Every
        # one of them means the same thing to the caller, and none is a server fault.
        raise _unreadable() from error

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


def _inspect_structure(tar: bytes) -> None:
    """Walk the tar's header blocks and refuse anything tarfile would be unsafe to parse.

    tarfile reads a pax header into memory at whatever size it claims and then splits it into
    records, so a few kilobytes of gzip become tens of megabytes of dictionaries. It also
    stops silently at the first damaged header, which would store half a skill. Both are
    checked here, on the raw blocks, before tarfile is handed a byte.
    """
    offset = 0
    while offset < len(tar):
        header = tar[offset:offset + _BLOCK_BYTES]
        if header == _END_OF_ARCHIVE:
            if tar[offset:].strip(b"\0"):
                raise _unreadable()
            return
        if len(header) < _BLOCK_BYTES or not _checksum_matches(header):
            raise _unreadable()

        member_type = header[156:157]
        size = _octal(header[124:136])
        data = tar[offset + _BLOCK_BYTES:offset + _BLOCK_BYTES + size]
        if len(data) < size:
            raise _unreadable()

        if member_type in _PAX_HEADER_TYPES:
            if size > _MAX_PAX_HEADER_BYTES:
                raise _oversized_header()
            _reject_layout_records(data)
        elif member_type in _LONG_NAME_TYPES and size > _MAX_LONG_NAME_BYTES:
            raise _oversized_header()

        offset += _BLOCK_BYTES + -(-size // _BLOCK_BYTES) * _BLOCK_BYTES


def _checksum_matches(header: bytes) -> bool:
    """A tar header's checksum is the sum of its bytes with the checksum field as spaces."""
    expected = _octal(header[148:156])
    return expected == sum(header[:148]) + 8 * ord(" ") + sum(header[156:])


def _octal(field: bytes) -> int:
    """A numeric header field. Anything but plain octal is refused, base-256 sizes included."""
    digits = field.strip(b" \0")
    if not digits:
        return 0
    try:
        return int(digits, 8)
    except ValueError:
        raise _unreadable() from None


def _reject_layout_records(pax_header: bytes) -> None:
    """Refuse a pax header that redefines a member's size or declares it sparse.

    Records are `<length> <key>=<value>\\n`, where the length counts the whole record.
    """
    position = 0
    while position < len(pax_header):
        length_end = pax_header.find(b" ", position)
        key_end = pax_header.find(b"=", length_end)
        if length_end < 0 or key_end < 0:
            raise _unreadable()
        try:
            length = int(pax_header[position:length_end])
        except ValueError:
            raise _unreadable() from None
        if length <= 0:
            raise _unreadable()

        key = pax_header[length_end + 1:key_end].decode("utf-8", errors="replace")
        if key.startswith(_LAYOUT_PAX_KEYS):
            raise ValidationError(
                f"The archive uses a tar extension ('{loggable(key)}') that a skill has no "
                "need for. Create it with plain 'tar -czf <file> -C <skill folder> .'."
            )
        position += length


def _unreadable() -> ValidationError:
    return ValidationError(
        "The upload is not a readable tar archive. Create it with "
        "'tar -czf <file> -C <skill folder> .' and send that file unchanged."
    )


def _oversized_header() -> ValidationError:
    return ValidationError(
        "The archive carries an extended header far larger than any file name needs. Create "
        "it with plain 'tar -czf <file> -C <skill folder> .'."
    )


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
