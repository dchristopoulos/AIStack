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


# The cap on one rendered failure in the log. A traceback fits; a traceback through three
# thousand recursive frames does not, and one request should not buy a megabyte of log.
LOGGED_FAILURE_MAX_LENGTH = 8000


def bounded_failure(text: str) -> str:
    """Sanitize a failure for one log line, keeping its start and its end.

    The end of a traceback names the exception and the start names the entry point; the
    frames in between are the part that repeats.
    """
    text = sanitized(text)
    if len(text) <= LOGGED_FAILURE_MAX_LENGTH:
        return text
    half = LOGGED_FAILURE_MAX_LENGTH // 2
    return f"{text[:half]}[+{len(text) - 2 * half} more characters]{text[-half:]}"


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
