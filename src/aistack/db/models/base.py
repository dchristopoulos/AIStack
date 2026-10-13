from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every AIStack table.

    Models import this rather than each declaring their own, so `Base.metadata` is the one
    description of the schema the migrations are checked against.
    """
