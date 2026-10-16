"""Local mode's setup text, which `aistack setup` prints because there is no server."""

from aistack.bundled import local_setup_instructions


def test_local_setup_on_a_connected_computer_follows_a_moved_library():
    """AUTO-05: a computer still on the old place is told so, and set up again with the new
    one, instead of stopping at "already connected"."""
    text = local_setup_instructions()
    step_one = text[text.index("## 1."):text.index("## 2.")]

    assert "**A command, and the user named another place**" in step_one
    assert "with `check`" in step_one
    assert "claude mcp remove aistack --scope user" in step_one
    assert "**An address.**" in step_one
