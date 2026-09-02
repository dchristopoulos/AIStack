from aistack.db.models.base import Base
from aistack.db.models.machine import Machine
from aistack.db.models.operating_system import OperatingSystem
from aistack.db.models.user import User

# Every model is imported here so that importing this package is enough to populate
# Base.metadata. create_schema() would otherwise create only the tables that happen to have
# been imported by whatever ran first.
__all__ = ["Base", "Machine", "OperatingSystem", "User"]
