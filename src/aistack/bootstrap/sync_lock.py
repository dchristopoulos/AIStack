"""A bounded, process-wide sync lock for cooperating hooks on this computer."""

import contextlib
import os
from pathlib import Path

from aistack.commons.exceptions import Busy


@contextlib.contextmanager
def locked(home: Path):
    folder = home / ".aistack"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "sync.lock").open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Busy("Another AIStack sync is running on this computer. Try again when it finishes.") from None
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
