"""This computer's hardware id, which a home folder copied onto another computer does not carry.

Read only to tell a restored home folder from the computer it came from; it is never stored,
logged, or sent anywhere as it is, only as a hash salted with the machine id.
"""

import platform
import re
import subprocess
from pathlib import Path

# Linux and the BSDs: written once by the system at install, kept in /etc.
_MACHINE_ID_FILES = (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id"))


def hardware_id() -> str | None:
    """The id the operating system keeps for this computer, or None where none can be read
    (a container without one, say): then a restored home folder cannot be told apart."""
    try:
        system = platform.system()
        if system == "Darwin":
            return _macos()
        if system == "Windows":
            return _windows()
        return _linux()
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _macos() -> str | None:
    shown = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                           capture_output=True, text=True, timeout=10,
                           stdin=subprocess.DEVNULL).stdout
    found = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', shown)
    return found.group(1) if found else None


def _windows() -> str | None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                        0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        return str(winreg.QueryValueEx(key, "MachineGuid")[0]) or None


def _linux() -> str | None:
    for path in _MACHINE_ID_FILES:
        try:
            text = path.read_text().strip()
        except FileNotFoundError:
            continue
        if text:
            return text
    return None
