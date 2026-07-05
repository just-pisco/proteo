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
