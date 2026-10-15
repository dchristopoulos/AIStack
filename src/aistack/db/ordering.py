"""Text order that is the same on every database (ADR-0002).

SQLite orders text by its bytes. PostgreSQL orders it by the database's collation, which on
managed services and the official image is a locale that ignores punctuation and case at
first, so `j-smith`, `j.smith` and `j_smith` would come back in another order.
"""

from sqlalchemy import ColumnElement
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


class bytewise(FunctionElement):  # noqa: N801 - read as a function in an order_by
    """`expression`, ordered by its bytes: `.order_by(bytewise(Team.name))`."""

    inherit_cache = True

    def __init__(self, expression: ColumnElement):
        super().__init__(expression)
        self.type = expression.type


@compiles(bytewise)
def _as_it_is(element: bytewise, compiler, **kw) -> str:
    # SQLite's default collation, BINARY, already compares bytes.
    return compiler.process(element.clauses, **kw)


@compiles(bytewise, "postgresql")
def _collated(element: bytewise, compiler, **kw) -> str:
    return f'{compiler.process(element.clauses, **kw)} COLLATE "C"'
