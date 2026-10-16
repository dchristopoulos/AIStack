"""Counts of what the server did, for the operator's `/metrics` (STD-19).

In memory, as the throttle is: a server is one process, and a restart starts the counts again,
which a Prometheus counter is allowed to do.
"""

import threading
from collections import Counter

from aistack.commons.release import release

_counts: Counter[tuple[str, str, str]] = Counter()
# Counted from the event loop and from worker threads alike.
_lock = threading.Lock()

_FAMILIES = {
    "tool": ("aistack_tool_calls_total", "MCP tool calls, by tool and outcome."),
    "route": ("aistack_route_requests_total", "HTTP requests to AIStack's own routes, by "
                                              "route and outcome."),
}


def count(kind: str, name: str, outcome: str) -> None:
    """One call of tool or route `name`: `ok`, `refused` (a sentence for the caller), or
    `error` (a fault here)."""
    with _lock:
        _counts[kind, name, outcome] += 1


def exposition() -> str:
    """Every count, in the Prometheus text format."""
    with _lock:
        counts = sorted(_counts.items())
    lines = ["# HELP aistack_info The AIStack release this server runs.",
             "# TYPE aistack_info gauge", f'aistack_info{{version="{release()}"}} 1']
    for kind, (family, help_text) in _FAMILIES.items():
        lines += [f"# HELP {family} {help_text}", f"# TYPE {family} counter"]
        lines += [f'{family}{{{kind}="{name}",outcome="{outcome}"}} {value}'
                  for (counted, name, outcome), value in counts if counted == kind]
    return "\n".join(lines) + "\n"
