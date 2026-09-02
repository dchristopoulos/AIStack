from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every AIStack table.

    Models import this rather than each declaring their own, so `Base.metadata` is the one
    thing `create_schema` has to be handed.
    """
