"""kscreen-doctor adapter: the only place that talks to KWin output management."""

from __future__ import annotations

import json
import subprocess
import time

from ..core import layout

KSCREEN = "kscreen-doctor"


class KScreenError(RuntimeError):
    pass


def snapshot() -> dict:
    res = subprocess.run([KSCREEN, "-j"], capture_output=True, text=True)
    if res.returncode != 0:
        raise KScreenError(f"kscreen-doctor -j failed: {res.stderr.strip()}")
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError as e:
        raise KScreenError(f"kscreen-doctor -j returned invalid JSON: {e}") from e


def apply(settings: list[str], verbose: bool = False) -> None:
    if not settings:
        return
    if verbose:
        print(f"[kscreen] {' '.join(settings)}")
    res = subprocess.run([KSCREEN, *settings], capture_output=True, text=True)
    if res.returncode != 0:
        raise KScreenError(
            f"kscreen-doctor {' '.join(settings)} failed: "
            f"{(res.stderr or res.stdout).strip()}")


def wait_for_new_output(before: dict, timeout: float = 10.0,
                        interval: float = 0.25) -> str | None:
    """Poll until an output not present in `before` appears; returns its name."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        name = layout.find_new_output(before, snapshot())
        if name:
            return name
        time.sleep(interval)
    return None


def wait_for_output_gone(name: str, timeout: float = 10.0,
                         interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if name not in layout.connected_names(snapshot()):
            return True
        time.sleep(interval)
    return False


def enabled_names(snap: dict) -> set[str]:
    return {o["name"] for o in layout.outputs(snap) if o.get("enabled")}
