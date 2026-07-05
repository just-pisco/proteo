"""Lifecycle of the EVDI hold process, run as a transient systemd user unit.

A unit (rather than a detached fork) buys us: independence from the caller's
cgroup (Sunshine restarts don't silently kill the connector), `systemctl
--user stop` as teardown, journald logging, and a DBus-watchable object for
the Phase-2 guard daemon.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

UNIT = "proteo-hold.service"


class ProcError(RuntimeError):
    pass


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def start_hold(edid_path: Path) -> int:
    """Start the hold unit; returns its MainPID."""
    pkg_parent = str(Path(__file__).resolve().parents[2])
    res = _run(["systemd-run", "--user", "--unit", UNIT, "--collect", "--quiet",
                f"--setenv=PYTHONPATH={pkg_parent}",
                sys.executable, "-m", "proteo", "_hold", "--edid", str(edid_path)])
    if res.returncode != 0:
        raise ProcError(f"systemd-run failed: {(res.stderr or res.stdout).strip()}")
    return hold_pid()


def hold_active() -> bool:
    return _run(["systemctl", "--user", "is-active", "--quiet", UNIT]).returncode == 0


def hold_pid() -> int:
    res = _run(["systemctl", "--user", "show", "-p", "MainPID", "--value", UNIT])
    try:
        return int(res.stdout.strip())
    except ValueError:
        return 0


def stop_hold() -> None:
    """Stop the hold unit (SIGTERM → clean evdi_disconnect). Idempotent."""
    res = _run(["systemctl", "--user", "stop", UNIT])
    if res.returncode != 0 and "not loaded" not in (res.stderr or ""):
        # a failed unit still needs clearing so the name is reusable
        _run(["systemctl", "--user", "reset-failed", UNIT])
