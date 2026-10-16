from aistack.commons.exceptions import ValidationError
from aistack.commons.text import (
    LOGGED_FAILURE_MAX_LENGTH,
    LOGGED_VALUE_MAX_LENGTH,
    bounded_failure,
    loggable,
    sanitized,
)


def test_a_newline_cannot_forge_a_log_line():
    forged = "x\n2026-01-01 00:00:00 INFO [aistack] Join completed. Admin: 'True'."

    rendered = loggable(forged)

    assert "\n" not in rendered
    assert "\\n" in rendered


def test_control_characters_are_escaped_not_dropped():
    # Escaped, so an operator can still see what was sent. Dropping them hides the attempt.
    assert loggable("a\tb\rc\x1b[2J") == "a\\tb\\rc\\x1b[2J"


def test_a_legitimate_non_ascii_name_survives_intact():
    assert loggable("Δημήτρης") == "Δημήτρης"


def test_an_unbounded_value_is_capped_and_says_how_much_was_dropped():
    rendered = loggable("A" * 100_000)

    assert rendered.startswith("A" * LOGGED_VALUE_MAX_LENGTH)
    assert rendered.endswith(f"[+{100_000 - LOGGED_VALUE_MAX_LENGTH} more characters]")
    assert len(rendered) < 200


def test_sanitized_does_not_truncate():
    """Whole error messages go through sanitized(), and ours are legitimately long."""
    long_message = "word " * 200

    assert sanitized(long_message) == long_message


def test_a_domain_exception_cannot_carry_a_forged_line():
    """The guard is on the base class, so no service can reintroduce this by forgetting."""
    error = ValidationError("username is blank. Received: 'x\nINFO nice try'.")

    assert "\n" not in error.message
    assert "\n" not in str(error)
    assert "\\nINFO nice try" in error.message


def test_a_short_failure_is_logged_whole_and_escaped():
    assert bounded_failure("boom\nsecond line") == "boom\\nsecond line"


def test_a_huge_failure_keeps_its_start_and_its_end():
    """Three thousand recursive frames must not buy a megabyte of log."""
    traceback = "Traceback (most recent call last):\n" + "  frame\n" * 100_000 + "RecursionError"

    rendered = bounded_failure(traceback)

    assert len(rendered) < LOGGED_FAILURE_MAX_LENGTH + 100
    assert rendered.startswith("Traceback (most recent call last):")
    assert rendered.endswith("RecursionError")
    assert "more characters]" in rendered
    assert "\n" not in rendered
