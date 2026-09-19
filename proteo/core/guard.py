"""Pure decision logic for the guard daemon.

The guard exists for one reason: a proteo session left orphaned (host
crashed, hold process died, machine about to sleep) means the user may be
staring at a black physical screen with no way to interact. Every decision
here errs on the side of restoring the physical displays.

Pure and testable: observations in, decisions out. The daemon in cli.py
supplies observations and executes decisions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    session: bool       # session state file exists
    hold_active: bool   # proteo-hold.service is active
    host_active: bool   # Sunshine/Apollo service is active


def decide(obs: Observation) -> str | None:
    """Returns a human-readable reason to restore, or None to do nothing."""
    if not obs.session:
        return None
    if not obs.hold_active:
        return "virtual display holder died while a session was active"
    if not obs.host_active:
        return "streaming host is no longer running; its undo never fired"
    return None


class Debouncer:
    """Require N consecutive positive observations before acting: `proteo do`
    legitimately restarts the hold unit during a reshape, and a single poll
    landing inside that window must not trigger a restore."""

    def __init__(self, threshold: int):
        if threshold < 1:
            raise ValueError("threshold must be >= 1")
        self.threshold = threshold
        self._streak = 0

    def update(self, positive: bool) -> bool:
        self._streak = self._streak + 1 if positive else 0
        return self._streak >= self.threshold


class SteamQuietWatcher:
    """Fires once each time Steam has been closed for `delay` seconds.

    Launch options live in a file Steam keeps in memory and rewrites on exit,
    so they can only be edited while it is closed — and not immediately, since
    that exit write lands a moment after the process disappears. Waiting out a
    delay and then firing exactly once per Steam session keeps the guard from
    rewriting the file in a loop.
    """

    def __init__(self, delay: float):
        if delay < 0:
            raise ValueError("delay must be >= 0")
        self.delay = delay
        self._closed_at: float | None = None
        self._fired = False

    def update(self, steam_running: bool, now: float) -> bool:
        if steam_running:
            # a fresh Steam session re-arms us: it may have installed new games
            self._closed_at = None
            self._fired = False
            return False
        if self._closed_at is None:
            self._closed_at = now
        if self._fired or now - self._closed_at < self.delay:
            return False
        self._fired = True
        return True
