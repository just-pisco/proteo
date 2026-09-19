"""Filesystem side of per-display profiles: where a game keeps its settings,
and copying those files in and out of the profile store.

Scope roots carry a stable label (`pfx`, `config`, `share`) and every tracked
file is addressed as `<label>/<relative path>`. That keeps the manifest and the
stored copies independent of where the Steam library happens to live, so moving
a game between drives does not orphan its profiles.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..core import profiles
from ..core.config import Config


@dataclass(frozen=True)
class Root:
    label: str
    path: Path


def app_id(env: dict[str, str]) -> str | None:
    """Steam exports the app id to the game's own environment, which the
    launch-options wrapper inherits."""
    for var in ("SteamAppId", "STEAM_COMPAT_APP_ID", "SteamGameId"):
        value = (env.get(var) or "").strip()
        if value.isdigit() and value != "0":
            return value
    return None


def _normalize(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


def _same_game(directory: str, hints: set[str]) -> bool:
    """Does this XDG directory belong to the game we are launching?"""
    normalized = _normalize(directory)
    if not normalized:
        return False
    # substring matching only above a length where collisions stop being likely
    return any(normalized == h
               or (len(normalized) >= 4 and len(h) >= 4
                   and (normalized in h or h in normalized))
               for h in hints)


def roots(env: dict[str, str], cfg: Config,
          hints: tuple[str, ...] = ()) -> list[Root]:
    """Where to look for this game's configuration.

    A Proton game answers exactly: `STEAM_COMPAT_DATA_PATH` is its own prefix,
    a container that by construction holds this game's files and nothing else.
    If that prefix is declared but missing, the honest answer is "no scope" —
    falling back to the home directory would put unrelated application settings
    in range of a swap.

    A native game has no such container, so only the XDG subdirectories whose
    name matches the game are taken. Scanning `~/.config` wholesale would let a
    KDE settings file that happened to change during a session join the
    profile, and be restored over the live one at the next launch.
    """
    compat = (env.get("STEAM_COMPAT_DATA_PATH") or "").strip()
    if compat:
        user = Path(compat) / "pfx" / "drive_c" / "users" / "steamuser"
        return [Root("pfx", user)] if user.is_dir() else []

    names = {_normalize(h) for h in hints if h} - {""}
    if not names:
        return []
    home = Path(env.get("HOME", "~")).expanduser()
    found = []
    for rel in cfg.profile_native_roots:
        base = home / rel
        if not base.is_dir():
            continue
        try:
            children = sorted(base.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and _same_game(child.name, names):
                label = f"{rel.replace('/', '-')}-{child.name}"
                found.append(Root(label, child))
    return found


def name_hints(env: dict[str, str], command: list[str]) -> tuple[str, ...]:
    """Names a native game's config directory might plausibly carry: the Steam
    install folder, the executable, and the directory holding it."""
    hints = []
    install = (env.get("STEAM_COMPAT_INSTALL_PATH") or "").strip()
    if install:
        hints.append(os.path.basename(install.rstrip("/")))
    if command:
        executable = Path(command[0])
        hints.append(executable.stem)
        if executable.parent.name:
            hints.append(executable.parent.name)
    return tuple(h for h in hints if h)


def _skip_dir(name: str, cfg: Config) -> bool:
    lowered = name.lower()
    # pruning whole directories is what keeps a scan of a fat Proton prefix (or
    # of ~/.local/share, which holds the entire Steam library) affordable
    if any(word in lowered for word in cfg.profile_exclude):
        return True
    return lowered in ("steam", ".steam", "steamapps", "proton", "node_modules",
                       ".git", "shadercache", "windows", "winsxs")


def scan(scope: list[Root], cfg: Config) -> dict[str, tuple[int, int]]:
    """Fingerprint every plausible settings file as `key -> (size, mtime_ns)`.

    Only allow-listed extensions are stat'ed: the discovery pass runs on every
    single game launch, so it has to stay cheap enough to be invisible.
    """
    wanted = tuple(f".{e}" for e in cfg.profile_extensions)
    seen: dict[str, tuple[int, int]] = {}
    for root in scope:
        for dirpath, dirnames, filenames in os.walk(root.path, followlinks=False):
            dirnames[:] = [d for d in dirnames if not _skip_dir(d, cfg)]
            for filename in filenames:
                if not filename.lower().endswith(wanted):
                    continue
                full = Path(dirpath) / filename
                try:
                    st = full.stat()
                except OSError:
                    continue
                rel = full.relative_to(root.path).as_posix()
                seen[f"{root.label}/{rel}"] = (st.st_size, st.st_mtime_ns)
    return seen


def resolve(key: str, scope: list[Root]) -> Path | None:
    """Turn a `<label>/<relative path>` key back into an absolute path."""
    label, _, rel = key.partition("/")
    for root in scope:
        if root.label == label:
            return root.path / rel
    return None


def copy_out(keys: list[str], scope: list[Root], dest: Path) -> list[str]:
    """Copy the game's current files into `dest`. Returns the keys copied."""
    copied = []
    for key in keys:
        src = resolve(key, scope)
        if src is None or not src.is_file():
            continue
        target = dest / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied.append(key)
    return copied


def copy_in(keys: list[str], scope: list[Root], source: Path) -> list[str]:
    """Copy stored files back over the game's. Returns the keys restored."""
    restored = []
    for key in keys:
        src = source / key
        dest = resolve(key, scope)
        if dest is None or not src.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".proteo-tmp")
        shutil.copy2(src, tmp)
        tmp.replace(dest)  # atomic: a game reading mid-swap never sees a partial file
        restored.append(key)
    return restored


def digests_by_display_key(app: str, env: dict[str, str] | None = None
                           ) -> dict[str, dict[str, str]]:
    """For every stored file, its content digest under each display key —
    the evidence `profiles.discriminating` rules on."""
    keys_dir = profiles.game_dir(app, env) / "keys"
    if not keys_dir.is_dir():
        return {}
    digests: dict[str, dict[str, str]] = {}
    for key_dir in sorted(d for d in keys_dir.iterdir() if d.is_dir()):
        for rel in stored_keys(key_dir):
            try:
                data = (key_dir / rel).read_bytes()
            except OSError:
                continue
            digests.setdefault(rel, {})[key_dir.name] = \
                hashlib.sha256(data).hexdigest()
    return digests


def stored_keys(source: Path) -> list[str]:
    if not source.is_dir():
        return []
    return sorted(p.relative_to(source).as_posix()
                  for p in source.rglob("*") if p.is_file())


def prune_backups(app: str, keep: int, env: dict[str, str] | None = None) -> None:
    backups = profiles.game_dir(app, env) / "backups"
    if not backups.is_dir():
        return
    for old in sorted((d for d in backups.iterdir() if d.is_dir()),
                      reverse=True)[keep:]:
        shutil.rmtree(old, ignore_errors=True)
