from aistack.db.models.base import Base
from aistack.db.models.harness import Harness
from aistack.db.models.machine import Machine
from aistack.db.models.machine_harness import MachineHarness
from aistack.db.models.machine_skill import MachineSkill
from aistack.db.models.operating_system import OperatingSystem
from aistack.db.models.skill import Skill
from aistack.db.models.skill_file import SkillFile
from aistack.db.models.skill_version import SkillVersion
from aistack.db.models.team import (
    GroupMember,
    GroupUnsubscribed,
    Team,
    TeamGroup,
    TeamKind,
    TeamMember,
    TeamRole,
)
from aistack.db.models.user import User

# Every model is imported here so that importing this package is enough to populate
# Base.metadata. The check that models and migrations agree would otherwise see only the tables
# that happen to have been imported by whatever ran first.
__all__ = [
    "Base",
    "GroupMember",
    "GroupUnsubscribed",
    "Harness",
    "Machine",
    "MachineHarness",
    "MachineSkill",
    "OperatingSystem",
    "Skill",
    "SkillFile",
    "SkillVersion",
    "Team",
    "TeamGroup",
    "TeamKind",
    "TeamMember",
    "TeamRole",
    "User",
]
