"""Kill a worker only after it reports reaching the requested write boundary."""

import json
import os
import queue
import signal
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def kill_at(tmp_path, operation, boundary, **configuration):
    configuration_file = tmp_path / "crash.json"
    configuration_file.write_text(json.dumps(configuration), encoding="utf-8")
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(ROOT / "src"), str(ROOT))),
        "AISTACK_TEST_CRASH_AT": boundary,
    }
    with (tmp_path / "worker.log").open("w+b") as log:
        worker = subprocess.Popen(
            [sys.executable, "-m", "tests.crash_worker", operation, str(configuration_file)],
            cwd=ROOT,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
        )
        ready = queue.Queue()
        reader = threading.Thread(target=lambda: ready.put(worker.stdout.readline()), daemon=True)
        reader.start()
        try:
            try:
                message = ready.get(timeout=30)
            except queue.Empty:
                message = "worker did not reach its boundary"
            if message != "ready\n":
                log.seek(0)
                raise AssertionError(f"{message}: {log.read().decode(errors='replace')}")
            _kill(worker)
            worker.wait(timeout=10)
            if sys.platform != "win32":
                assert worker.returncode == -signal.SIGKILL
            else:
                assert worker.returncode != 0  # TerminateProcess is Windows' hard kill.
        finally:
            if worker.poll() is None:
                _kill(worker)
                worker.wait(timeout=10)
            reader.join(timeout=5)
            worker.stdin.close()
            worker.stdout.close()


def _kill(worker):
    if sys.platform == "win32":
        # A Windows virtualenv's python.exe launches the interpreter as a child process.
        subprocess.run(
            ["taskkill", "/PID", str(worker.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=True,
        )
    else:
        worker.kill()
