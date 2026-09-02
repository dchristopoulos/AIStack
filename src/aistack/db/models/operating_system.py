from enum import StrEnum


class OperatingSystem(StrEnum):
    """The operating systems a machine may report.

    Required at join: MACHINE.os is NOT NULL and MCP gives the server no way to observe the
    client's platform, so the agent has to state it.
    """

    MACOS = "MACOS"
    WINDOWS = "WINDOWS"
    LINUX = "LINUX"
