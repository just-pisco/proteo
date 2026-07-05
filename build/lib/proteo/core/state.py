"""Session state persisted to disk, so that a separate `proteo undo`
invocation — or a post-crash recovery — knows exactly what to tear down
and what to restore.

Lives under $XDG_RUNTIME_DIR (tmpfs): vanishes on reboot, which is correct
because the display configuration resets on reboot anyway.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class SessionState:
    virtual_output: str
    helper_pid: int
    edid_path: str
    request: dict            # width/height/fps/hdr as saved
    snapshot: dict           # kscreen-doctor -j taken before the session began
    version: int = 1
    extra: dict = field(default_factory=dict)


def runtime_dir(env: dict[str, str] | None = None) -> Path:
    env = env if env is not None else dict(os.environ)
    base = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / "proteo"


def state_path(env: dict[str, str] | None = None) -> Path:
    return runtime_dir(env) / "session.json"


def save(state: SessionState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(state), indent=1))
    tmp.replace(path)  # atomic: undo never sees a half-written state


def load(path: Path) -> SessionState | None:
    try:
        raw = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    known = {k: raw[k] for k in SessionState.__dataclass_fields__ if k in raw}
    try:
        return SessionState(**known)
    except TypeError:
        return None


def clear(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
