"""A stored value set that a release reads safely when a newer release widened it (ADR-0031).

A harness, an operating system, a team's kind and a member's role are each stored as VARCHAR
plus a CHECK naming the allowed values. A newer release may add a value while computers on
this release keep running on the same database (ADR-0024). SQLAlchemy's Enum raises on a
value it does not know, so one such row would fail every query that reads it. This one reads
it as None, and the services list only `known()` rows.
"""

from sqlalchemy import ColumnElement, Enum
from sqlalchemy.orm import InstrumentedAttribute


class ValueSet(Enum):
    """An Enum whose unknown stored values read as None instead of raising."""

    cache_ok = True

    def result_processor(self, dialect, coltype):
        # `enums` holds the stored spelling of each member, in member order.
        members = dict(zip(self.enums, self.enum_class, strict=True))

        def process(value):
            return None if value is None else members.get(value)

        return process


def known(column: InstrumentedAttribute) -> ColumnElement[bool]:
    """Only rows whose value this release knows: `.where(known(Machine.os))`."""
    return column.in_(list(column.type.enum_class))
