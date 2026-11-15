"""The one place a test polls a real process or server."""

from __future__ import annotations

import time
from collections.abc import Callable


def wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float,
    interval: float = 0.05,
    what: str = "condition",
) -> None:
    """Return once `predicate()` is true. Fail with a message naming `what` after `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {what}")
        time.sleep(interval)
