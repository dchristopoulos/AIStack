# The cap on a single caller-supplied value rendered into a log line. Both name limits are 64,
# so this shows an over-length value being over-length without reproducing all of it.
LOGGED_VALUE_MAX_LENGTH = 80


def sanitized(text: str) -> str:
    """Escape every character that would be read as structure rather than as content.

    A newline in a log file starts a line, and a log line is how an operator reconstructs what
    happened; the same newline in a ToolError starts what an agent reads as a new turn. Values
    that reach either sink on the rejection path were chosen by the caller and have not been
    validated. Non-printables are escaped rather than dropped so the value stays diagnosable,
    and printable non-ASCII is left alone so a legitimate name is not mangled into hex.
    """
    return "".join(character if character.isprintable() else
                   character.encode("unicode_escape").decode("ascii")
                   for character in text)


def loggable(value: object) -> str:
    """Render one caller-supplied value for a log line: sanitized, and bounded.

    Length is capped here and not in `sanitized`, which also guards whole error messages that
    are legitimately long. An argument is not: nothing the caller sends is worth an unbounded
    log line, and this runs before any validation has agreed on a limit.
    """
    text = str(value)
    if len(text) <= LOGGED_VALUE_MAX_LENGTH:
        return sanitized(text)
    return (f"{sanitized(text[:LOGGED_VALUE_MAX_LENGTH])}"
            f"[+{len(text) - LOGGED_VALUE_MAX_LENGTH} more characters]")
