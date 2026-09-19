"""Steam's on-disk configuration: where the libraries are, which games are
installed, and the per-game launch options in `localconfig.vdf`.

Everything here refuses to act while Steam is running. Steam holds the whole of
`localconfig.vdf` in memory and rewrites it on exit, so an edit made underneath
a live client is silently reverted a few minutes later — worse than not editing
at all, because it looks like it worked.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from ..core import steamvdf

# Steam's install directories, in the order they are worth trying
_STEAM_ROOTS = (".steam/debian-installation", ".steam/steam", ".local/share/Steam",
                ".var/app/com.valvesoftware.Steam/.local/share/Steam")

# leaf path to a user's launch options inside localconfig.vdf
_APPS_PATH = ("UserLocalConfigStore", "Software", "Valve", "Steam", "apps")


class SteamError(RuntimeError):
    pass


def steam_root(env: dict[str, str] | None = None) -> Path | None:
    env = env if env is not None else dict(os.environ)
    home = Path(env.get("HOME", "~")).expanduser()
    for rel in _STEAM_ROOTS:
        candidate = home / rel
        if (candidate / "steamapps").is_dir():
            return candidate
    return None


def is_running() -> bool:
    """Is a Steam client up? Checked by walking /proc rather than by pgrep, so
    the guard does not fork a process every poll."""
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
        except OSError:
            continue
        if comm in ("steam", "steamwebhelper"):
            return True
    return False


def library_paths(root: Path) -> list[Path]:
    """Every Steam library folder, including the ones on other drives."""
    libraries = [root / "steamapps"]
    manifest = root / "steamapps" / "libraryfolders.vdf"
    try:
        tree = steamvdf.loads(manifest.read_text(encoding="utf-8",
                                                 errors="surrogateescape"))
    except (OSError, steamvdf.VdfError):
        return libraries
    folders = steamvdf.find(tree, "libraryfolders")
    if not isinstance(folders, list):
        return libraries
    for _, entry in folders:
        path = steamvdf.find(entry, "path") if isinstance(entry, list) else None
        if isinstance(path, str):
            candidate = Path(path) / "steamapps"
            if candidate.is_dir() and candidate not in libraries:
                libraries.append(candidate)
    return libraries


def installed_app_ids(root: Path) -> list[str]:
    """App ids with an install manifest, minus Steam's own internal entries."""
    found = set()
    for library in library_paths(root):
        for manifest in library.glob("appmanifest_*.acf"):
            app = manifest.stem.removeprefix("appmanifest_")
            # 228980 is Steamworks Common Redistributables, never launched
            if app.isdigit() and app != "228980":
                found.add(app)
    return sorted(found, key=int)


def user_config_paths(root: Path) -> list[Path]:
    """`localconfig.vdf` for every Steam account used on this machine."""
    userdata = root / "userdata"
    if not userdata.is_dir():
        return []
    return sorted(p for p in userdata.glob("*/config/localconfig.vdf")
                  if p.is_file())


def backup(path: Path, keep: int = 5) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.proteo-{stamp}")
    shutil.copy2(path, target)
    old = sorted(path.parent.glob(f"{path.name}.proteo-*"), reverse=True)[keep:]
    for stale in old:
        stale.unlink(missing_ok=True)
    return target


def apply_launch_options(config: Path, app_ids: list[str], remove: bool = False,
                         wrapper: str = steamvdf.WRAPPER) -> list[str]:
    """Set (or clear) proteo's wrapper for `app_ids` in one localconfig.vdf.

    Only apps that already have an entry are touched, and only the
    `LaunchOptions` leaf within them: everything else in the file is written
    back exactly as it was parsed. Returns the app ids actually changed.
    """
    text = config.read_text(encoding="utf-8", errors="surrogateescape")
    tree = steamvdf.loads(text)
    apps = steamvdf.find(tree, *_APPS_PATH)
    if not isinstance(apps, list):
        raise SteamError(f"{config}: no apps section — unexpected layout")

    wanted = set(app_ids)
    changed = []
    for app, entry in apps:
        if app not in wanted or not isinstance(entry, list):
            continue
        current = steamvdf.find(entry, "LaunchOptions")
        current = current if isinstance(current, str) else ""
        updated = (steamvdf.without_wrapper(current, wrapper) if remove
                   else steamvdf.with_wrapper(current, wrapper))
        if updated != current:
            # an unhooked game keeps an empty LaunchOptions rather than losing
            # the key: that is exactly what Steam writes when you clear the
            # field in its own UI, and proteo never deletes keys from a file
            # it does not own
            steamvdf.set_value(entry, "LaunchOptions", updated)
            changed.append(app)

    if changed:
        backup(config)
        tmp = config.with_name(config.name + ".proteo-tmp")
        tmp.write_text(steamvdf.dumps(tree) + "\n", encoding="utf-8",
                       errors="surrogateescape")
        tmp.replace(config)
    return changed


def missing_app_ids(config: Path, app_ids: list[str],
                    wrapper: str = steamvdf.WRAPPER) -> list[str]:
    """Which of `app_ids` do not carry the wrapper yet — a read-only check, so
    the guard can stay quiet when there is nothing to do."""
    try:
        tree = steamvdf.loads(config.read_text(encoding="utf-8",
                                               errors="surrogateescape"))
    except (OSError, steamvdf.VdfError):
        return []
    apps = steamvdf.find(tree, *_APPS_PATH)
    if not isinstance(apps, list):
        return []
    wanted = set(app_ids)
    missing = []
    for app, entry in apps:
        if app in wanted and isinstance(entry, list):
            current = steamvdf.find(entry, "LaunchOptions")
            if wrapper not in (current if isinstance(current, str) else ""):
                missing.append(app)
    return missing
