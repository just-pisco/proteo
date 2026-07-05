"""Configuration loading. Nothing hard-coded: physical output, limits and
behavior all come from TOML, with safe defaults when no file exists.

Search order (later wins): /etc/proteo/config.toml, then
$XDG_CONFIG_HOME/proteo/config.toml (default ~/.config/proteo/config.toml).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    # name of the physical output `proteo rescue` re-enables when no snapshot exists
    rescue_output: str = "DP-2"
    rescue_mode: str = ""            # e.g. "5120x1440@240"; empty = leave current mode
    # what happens to physical outputs while streaming
    physical_during_stream: str = "disable"   # "disable" | "keep"
    # clamps applied to client-requested modes
    max_width: int = 4095            # DTD-encodable ceiling
    max_height: int = 2304
    min_width: int = 640
    min_height: int = 480
    default_width: int = 1920
    default_height: int = 1080
    default_fps: int = 60
    max_fps: int = 240
    min_fps: int = 24
    # HDR stays off until Phase 4; opt-in only
    hdr_enabled: bool = False
    virtual_name: str = "Proteo VD"  # monitor name embedded in the EDID
    # systemd user unit of the streaming host the guard watches
    host_unit: str = "app-dev.lizardbyte.app.Sunshine.service"
    guard_poll_seconds: int = 1
    guard_debounce: int = 2          # consecutive bad polls before restoring
    extra: dict = field(default_factory=dict, compare=False)


def default_config_paths(env: dict[str, str] | None = None) -> list[Path]:
    env = env if env is not None else dict(os.environ)
    xdg = env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME", "/root"), ".config")
    return [Path("/etc/proteo/config.toml"), Path(xdg) / "proteo" / "config.toml"]


def load_config(paths: list[Path] | None = None,
                env: dict[str, str] | None = None) -> Config:
    merged: dict = {}
    for p in (paths if paths is not None else default_config_paths(env)):
        try:
            with open(p, "rb") as f:
                merged.update(tomllib.load(f))
        except FileNotFoundError:
            continue
    known = {k: merged.pop(k) for k in list(merged)
             if k in Config.__dataclass_fields__ and k != "extra"}
    cfg = Config(**known, extra=merged)
    if cfg.physical_during_stream not in ("disable", "keep"):
        raise ValueError(
            f"physical_during_stream must be 'disable' or 'keep', "
            f"got {cfg.physical_during_stream!r}")
    return cfg
