"""The latest revision of a chosen set of skills, read without touching anyone else's.

Every skill's latest revision is one GROUP BY away, but over the whole server that is every
revision of every skill, and on SQLite it runs holding the write lock. So each caller names
the skills it is about to return, and only their revisions are read: `skill_id IN (...)`
walks `uq_skill_version_skill_revision`, and a file count walks `uq_skill_file_version_path`.
"""

from typing import Any

from sqlalchemy import ColumnElement, Select, func, select

from aistack.db.models.skill_file import SkillFile
from aistack.db.models.skill_version import SkillVersion


def latest(skill_ids: Select[Any]) -> Any:
    """The latest revision of each skill `skill_ids` selects, as a subquery of SkillVersion's
    columns: skill_id, skill_version_id, revision, content_hash, pushed_by, created_on."""
    top = (
        select(SkillVersion.skill_id, func.max(SkillVersion.revision).label("revision"))
        .where(SkillVersion.skill_id.in_(skill_ids))
        .group_by(SkillVersion.skill_id).subquery()
    )
    return (
        select(SkillVersion.skill_id, SkillVersion.skill_version_id, SkillVersion.revision,
               SkillVersion.content_hash, SkillVersion.pushed_by, SkillVersion.created_on)
        .join(top, (top.c.skill_id == SkillVersion.skill_id)
              & (top.c.revision == SkillVersion.revision))
        .subquery()
    )


def file_count(skill_version_id: ColumnElement[Any]) -> Any:
    """How many files one revision has, counted for that revision alone."""
    return (select(func.count()).select_from(SkillFile)
            .where(SkillFile.skill_version_id == skill_version_id)
            .scalar_subquery())
