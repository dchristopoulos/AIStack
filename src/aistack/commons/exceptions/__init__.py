class AIStackError(Exception):
    """Base for every rejection AIStack raises deliberately.

    The message is agent-facing UX: it says what to fix and what was received, never which
    class was raised. Anything not derived from this is a server fault, and the MCP layer
    masks it rather than describing it to the caller.
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ValidationError(AIStackError):
    """A tool argument the caller can correct: wrong shape, wrong length, wrong value."""


class Conflict(AIStackError):
    """The argument is well-formed but collides with state that already exists."""
