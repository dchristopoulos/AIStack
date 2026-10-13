"""Builders for the gzipped tars the tests upload.

`skill_archive` goes through the production writer, for the uploads that should be accepted.
`raw_archive` writes members directly, for the ones a hostile or careless client would send.
"""

import gzip
import hashlib
import io
import tarfile

from aistack.services.skill_archive import build_archive

SKILL_MD = "---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\nDo the thing.\n"


def skill_document(name: str = "wizard", description: str = "Walks a human through steps.",
                   extra_frontmatter: str = "") -> str:
    document = SKILL_MD.format(name=name, description=description)
    return document.replace("\n---\n\n", f"\n{extra_frontmatter}---\n\n", 1)


def skill_archive(name: str = "wizard", files: dict[str, str | bytes] | None = None,
                  executable: frozenset[str] = frozenset(), **document) -> bytes:
    """A well-formed archive of one skill: SKILL.md plus `files`."""
    contents: dict[str, str | bytes] = {"SKILL.md": skill_document(name, **document)}
    contents.update(files or {})
    return build_archive(
        (path, content.encode("utf-8") if isinstance(content, str) else content,
         path in executable)
        for path, content in contents.items()
    )


def raw_archive(members: list[tarfile.TarInfo | tuple[str, bytes]]) -> bytes:
    """An archive of exactly these members, with no checks at all."""
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for member in members:
                if isinstance(member, tarfile.TarInfo):
                    archive.addfile(member)
                    continue
                path, content = member
                info = tarfile.TarInfo(name=path)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def special_member(name: str, member_type: bytes, linkname: str = "") -> tarfile.TarInfo:
    info = tarfile.TarInfo(name=name)
    info.type = member_type
    info.linkname = linkname
    return info


def local_digests(name: str = "wizard", files: dict[str, str | bytes] | None = None,
                  **document) -> dict[str, str]:
    """What a machine holding that skill would send to sync: {path: sha256} of each file."""
    contents: dict[str, str | bytes] = {"SKILL.md": skill_document(name, **document)}
    contents.update(files or {})
    return {
        path: hashlib.sha256(
            content.encode("utf-8") if isinstance(content, str) else content).hexdigest()
        for path, content in contents.items()
    }
