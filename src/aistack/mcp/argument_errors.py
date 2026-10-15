"""A tool call whose arguments do not fit, described without repeating them (SEC-03).

FastMCP answers such a call with pydantic's error, which quotes every input it rejected, and
logs the same text. For `join_team` an input is a team's invite code under whatever name or
shape the agent gave it. The answer and the log line here say which fields failed and how,
and what the tool takes.
"""

from pydantic import ValidationError as PydanticValidationError
from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp import types

from aistack.commons.text import sanitized


class ArgumentErrors(Middleware):
    async def on_call_tool(self, context: MiddlewareContext[types.CallToolRequestParams],
                           call_next: CallNext[types.CallToolRequestParams, ToolResult],
                           ) -> ToolResult:
        try:
            return await call_next(context)
        except ValidationError as error:
            name = context.message.name
            cause = error.__cause__
            problems = argument_problems(
                cause.errors(include_url=False) if isinstance(cause, PydanticValidationError)
                else None)
            takes = await _parameters(context, name)
            raise ToolError(sanitized(
                f"{name} was called with arguments it does not take ({problems}). "
                f"It takes: {takes}. Send each as a plain value, under exactly that name."
            )) from None


async def _parameters(context: MiddlewareContext, name: str) -> str:
    try:
        tool = await context.fastmcp_context.fastmcp.get_tool(name)
        return ", ".join(tool.parameters.get("properties", {})) or "no arguments"
    except Exception:
        return "the parameters its description lists"


def argument_problems(detail: object) -> str:
    """Pydantic's errors as field and kind only, such as `code: missing`; never an input.

    A field name is the caller's too, and an agent could use the code itself as one, so only
    a short identifier that is not one of AIStack's credentials is shown.
    """
    if not isinstance(detail, list):
        return "not described"
    return ", ".join(
        f"{'.'.join(_field_part(part) for part in error.get('loc', ()))}: "
        f"{_field_part(error.get('type'))}"
        for error in detail if isinstance(error, dict))


def _field_part(part: object) -> str:
    if isinstance(part, int):
        return str(part)
    if (isinstance(part, str) and part.isidentifier() and len(part) <= 40
            and not part.startswith("aist")):
        return part
    return "?"
