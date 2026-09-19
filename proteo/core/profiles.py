"""Per-display game settings profiles: pure planning, no filesystem writes.

Why this exists: proteo hands the game a virtual display at the client's
resolution, so a game launched from the TV rewrites its own configuration
(resolution, refresh rate, often the quality preset that came with the
auto-detect) — and that rewrite is still there when you sit back at the desk.
Profiles keep one copy of a game's config files per display shape and swap the
right one in at launch.

Two decisions shape everything here:

- **Keyed on display geometry, not on the streaming mechanism.** A key like
  `5120x1440` covers Sunshine+proteo, Steam Remote Play and simply plugging in
  another monitor, with no special case per transport. proteo never has to ask
  "am I streaming?" — it asks "what shape is the screen?".
- **Which files belong to a profile is learned, not declared.** The wrapper
  fingerprints the game's config scope before and after a session; whatever
  changed and looks like configuration joins the profile. The alternative — a
  hand-written path per game — ages badly and is exactly the chore this feature
  is supposed to remove.

The classifier below is deliberately timid. Swapping a save game between
profiles would destroy progress, which is far worse than failing to track a
settings file, so anything that smells like save data is excluded by path and
only known configuration extensions are admitted. Files rejected this way are
still recorded, as `ignored`, so `proteo profiles show` can surface them and a
human can promote one on purpose.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from .config import Config

# kscreen rotation values that swap the logical width/height
_ROTATIONS_SWAPPING_AXES = (2, 8)  # 2 = left (90°), 8 = right (270°)

MANIFEST_VERSION = 1


# --------------------------------------------------------------------------
# display key
# --------------------------------------------------------------------------

def display_key(snapshot: dict, fallback: str = "unknown") -> str:
    """Stable name for the current screen shape, e.g. `5120x1440`.

    The primary output wins (priority 1, as KWin ranks them); its *mode* size is
    used rather than the logical size, because the logical size also moves with
    the fractional scale factor and the game does not care about that.
    """
    primary = _primary_output(snapshot)
    if primary is None:
        return fallback
    mode = _current_mode(primary)
    size = (mode or {}).get("size") or primary.get("size")
    if not size:
        return fallback
    width, height = size.get("width"), size.get("height")
    if not width or not height:
        return fallback
    if primary.get("rotation") in _ROTATIONS_SWAPPING_AXES:
        width, height = height, width
    return f"{width}x{height}"


def _primary_output(snapshot: dict) -> dict | None:
    enabled = [o for o in snapshot.get("outputs", []) if o.get("enabled")]
    if not enabled:
        return None
    # priority 1 is primary; unset priority sorts last, never ahead of a real one
    return min(enabled, key=lambda o: o.get("priority") or 1_000_000)


def _current_mode(output: dict) -> dict | None:
    cur = output.get("currentModeId")
    for m in output.get("modes", []):
        if m.get("id") == cur:
            return m
    return None


# --------------------------------------------------------------------------
# candidate classification
# --------------------------------------------------------------------------

def is_config_candidate(rel_path: str, size: int, cfg: Config) -> bool:
    """Is this file safe to treat as swappable game configuration?

    `rel_path` is relative to the scan root and always uses forward slashes, so
    the exclusion words match the same way on every scope.
    """
    p = PurePosixPath(rel_path)
    if p.suffix.lower().lstrip(".") not in cfg.profile_extensions:
        return False
    if size > cfg.profile_max_bytes:
        return False
    lowered = rel_path.lower()
    return not any(word in lowered for word in cfg.profile_exclude)


def classify(rel_paths: dict[str, int], cfg: Config) -> tuple[list[str], list[str]]:
    """Split `{rel_path: size}` into (tracked, ignored), both sorted."""
    tracked, ignored = [], []
    for rel, size in rel_paths.items():
        (tracked if is_config_candidate(rel, size, cfg) else ignored).append(rel)
    return sorted(tracked), sorted(ignored)


# --------------------------------------------------------------------------
# fingerprints
# --------------------------------------------------------------------------

def changed_paths(before: dict[str, tuple[int, int]],
                  after: dict[str, tuple[int, int]]) -> dict[str, int]:
    """Paths that appeared or whose `(size, mtime_ns)` moved, with their size.

    Size+mtime rather than a content hash: the scan runs on every game launch
    and a prefix can hold tens of thousands of files. A file rewritten with
    identical content costs one redundant copy into the profile, which is
    harmless; the reverse mistake — missing a real change — is not.
    """
    changed = {}
    for rel, stamp in after.items():
        if before.get(rel) != stamp:
            changed[rel] = stamp[0]
    return changed


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------

@dataclass
class Manifest:
    """What proteo has learned about one game, persisted next to its profiles."""
    app_id: str
    name: str = ""
    roots: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)      # promoted: swapped
    candidates: list[str] = field(default_factory=list)  # watched, not yet swapped
    ignored: list[str] = field(default_factory=list)    # never configuration
    version: int = MANIFEST_VERSION
    extra: dict = field(default_factory=dict)

    def learn(self, observed: list[str], ignored: list[str]) -> None:
        """Record what changed this session. Nothing is swapped on this basis
        alone — `promote` decides that."""
        self.candidates = sorted((set(self.candidates) | set(observed))
                                 - set(self.files))
        self.ignored = sorted((set(self.ignored) | set(ignored))
                              - set(self.files) - set(self.candidates))

    def promote(self, keys: set[str]) -> list[str]:
        """Move files into the swapped set. Returns the newly promoted ones."""
        new = sorted(keys - set(self.files))
        self.files = sorted(set(self.files) | keys)
        self.candidates = sorted(set(self.candidates) - set(self.files))
        self.ignored = sorted(set(self.ignored) - set(self.files))
        return new

    @property
    def watched(self) -> list[str]:
        """Everything worth storing a per-display copy of."""
        return sorted(set(self.files) | set(self.candidates))


def discriminating(digests: dict[str, dict[str, str]]) -> set[str]:
    """Which files actually depend on the display shape?

    `digests` maps a file to `{display key: content digest}`. A file earns a
    swap only once two display shapes have been seen to hold *different*
    content for it. Everything a game rewrites identically on every launch —
    launcher component manifests, update metadata, timestamps that happen to
    live in a config file — never qualifies, so proteo cannot make it regress
    by restoring an older copy.

    The cost is that the first session on a new screen only observes; swapping
    starts from the second. That is the right trade: a wrong swap is silent and
    damaging, a late swap is merely one round of settings to redo.
    """
    return {path for path, per_key in digests.items() if len(set(per_key.values())) > 1}


def manifest_load(path: Path) -> Manifest | None:
    try:
        raw = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    known = {k: raw[k] for k in Manifest.__dataclass_fields__ if k in raw}
    try:
        return Manifest(**known)
    except TypeError:
        return None


def manifest_save(manifest: Manifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(manifest), indent=1))
    tmp.replace(path)  # atomic: a crash mid-write must not lose the manifest


# --------------------------------------------------------------------------
# store layout
# --------------------------------------------------------------------------

def store_dir(env: dict[str, str] | None = None) -> Path:
    """Profiles live under XDG_DATA_HOME, not XDG_RUNTIME_DIR: unlike session
    state, they are the whole point and must survive reboots."""
    env = env if env is not None else dict(os.environ)
    base = env.get("XDG_DATA_HOME") or os.path.join(env.get("HOME", "/root"),
                                                    ".local", "share")
    return Path(base) / "proteo" / "profiles"


def game_dir(app_id: str, env: dict[str, str] | None = None) -> Path:
    return store_dir(env) / app_id


def manifest_path(app_id: str, env: dict[str, str] | None = None) -> Path:
    return game_dir(app_id, env) / "manifest.json"


def key_dir(app_id: str, key: str, env: dict[str, str] | None = None) -> Path:
    return game_dir(app_id, env) / "keys" / key


def backup_dir(app_id: str, stamp: str, env: dict[str, str] | None = None) -> Path:
    return game_dir(app_id, env) / "backups" / stamp
