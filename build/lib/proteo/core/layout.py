"""Pure planning over kscreen-doctor JSON snapshots.

Everything here is data-in/data-out: snapshots are the parsed output of
`kscreen-doctor -j`, plans are lists of kscreen-doctor setting strings.
No subprocess, no DBus — the adapters execute what this module decides.
"""

from __future__ import annotations

from .config import Config


def outputs(snapshot: dict) -> list[dict]:
    return snapshot.get("outputs", [])


def connected_names(snapshot: dict) -> set[str]:
    return {o["name"] for o in outputs(snapshot) if o.get("connected", True)}


def find_output(snapshot: dict, name: str) -> dict | None:
    for o in outputs(snapshot):
        if o["name"] == name:
            return o
    return None


def find_new_output(before: dict, after: dict) -> str | None:
    """Name of the output present in `after` but not in `before` (the virtual
    connector that appeared when the EVDI client connected)."""
    new = connected_names(after) - connected_names(before)
    if len(new) > 1:
        raise RuntimeError(f"multiple new outputs appeared at once: {sorted(new)}")
    return next(iter(new), None)


def current_mode(output: dict) -> dict | None:
    cur = output.get("currentModeId")
    for m in output.get("modes", []):
        if m.get("id") == cur:
            return m
    return None


def mode_setting(output: dict) -> str | None:
    """kscreen-doctor mode selector for the output's current mode. Prefer the
    mode name (stable across reboots); fall back to the mode id."""
    m = current_mode(output)
    if m is None:
        return None
    return m.get("name") or m.get("id")


def stream_layout_commands(before: dict, virtual_name: str, cfg: Config) -> list[str]:
    """Settings that make the virtual output the stream target once it exists."""
    cmds = [f"output.{virtual_name}.enable",
            f"output.{virtual_name}.priority.1"]
    if cfg.physical_during_stream == "disable":
        for o in outputs(before):
            if o.get("enabled") and o["name"] != virtual_name:
                cmds.append(f"output.{o['name']}.disable")
    return cmds


def restore_commands(saved: dict, current: dict) -> list[str]:
    """Settings that bring every still-present physical output back to its
    snapshotted state: enabled, mode, position, priority."""
    present = connected_names(current)
    cmds: list[str] = []
    for o in outputs(saved):
        name = o["name"]
        if name not in present:
            continue
        if not o.get("enabled"):
            cmds.append(f"output.{name}.disable")
            continue
        cmds.append(f"output.{name}.enable")
        mode = mode_setting(o)
        if mode:
            cmds.append(f"output.{name}.mode.{mode}")
        pos = o.get("pos")
        if pos is not None:
            cmds.append(f"output.{name}.position.{pos['x']},{pos['y']}")
        prio = o.get("priority")
        if prio:
            cmds.append(f"output.{name}.priority.{prio}")
    return cmds


def rescue_commands(cfg: Config) -> list[str]:
    """Last-resort restore when no snapshot exists: re-enable the configured
    physical output, optionally at the configured mode."""
    cmds = [f"output.{cfg.rescue_output}.enable",
            f"output.{cfg.rescue_output}.priority.1"]
    if cfg.rescue_mode:
        cmds.insert(1, f"output.{cfg.rescue_output}.mode.{cfg.rescue_mode}")
    return cmds
