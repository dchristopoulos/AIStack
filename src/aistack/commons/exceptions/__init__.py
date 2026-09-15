from aistack.commons.text import sanitized


class AIStackError(Exception):
    """Base for every rejection AIStack raises deliberately.

    The message is agent-facing UX: it says what to fix and what was received, never which
    class was raised. Anything not derived from this is a server fault, and the MCP layer
    masks it rather than describing it to the caller.

    The message is sanitized here rather than at each raise site. "What was received" means a
    service interpolates a value the caller chose into a string that then reaches two sinks
    that both treat newlines as structure: the server log, where a newline forges a line, and
    the agent's context, where it forges a turn. Guarding the base class is the one place every
    rejection already routes through, so a later service cannot reintroduce this by forgetting.
    """

    def __init__(self, message: str):
        message = sanitized(message)
        super().__init__(message)
        self.message = message


class ValidationError(AIStackError):
    """A tool argument the caller can correct: wrong shape, wrong length, wrong value."""


class Conflict(AIStackError):
    """The argument is well-formed but collides with state that already exists."""
