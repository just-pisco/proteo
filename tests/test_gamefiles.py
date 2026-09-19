"""The adapters are normally left out of the test suite, but this one only
touches a temporary directory — and it is the code that writes over a game's
own files, so it earns coverage.
"""

from pathlib import Path

from proteo.adapters.gamefiles import (
    Root, app_id, copy_in, copy_out, name_hints, prune_backups, resolve, roots,
    scan, stored_keys,
)
from proteo.core.config import Config

CFG = Config()


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# --------------------------------------------------------------------------
# app id and scope discovery
# --------------------------------------------------------------------------

def test_app_id_from_steam_variables():
    assert app_id({"SteamAppId": "1174180"}) == "1174180"
    assert app_id({"STEAM_COMPAT_APP_ID": "292030"}) == "292030"
    assert app_id({}) is None
    assert app_id({"SteamAppId": "0"}) is None          # Steam's "no app" value
    assert app_id({"SteamAppId": "not-a-number"}) is None


def test_roots_prefers_the_proton_prefix(tmp_path):
    user = tmp_path / "compat" / "pfx" / "drive_c" / "users" / "steamuser"
    user.mkdir(parents=True)
    found = roots({"STEAM_COMPAT_DATA_PATH": str(tmp_path / "compat"),
                   "HOME": str(tmp_path)}, CFG)
    assert [r.label for r in found] == ["pfx"]
    assert found[0].path == user


def test_roots_refuses_to_guess_when_the_prefix_is_missing(tmp_path):
    # a declared-but-absent prefix must NOT fall back to the home directory:
    # unrelated application settings would come into swapping range
    (tmp_path / ".config").mkdir()
    assert roots({"STEAM_COMPAT_DATA_PATH": str(tmp_path / "gone"),
                  "HOME": str(tmp_path)}, CFG, ("anything",)) == []


def test_native_roots_are_limited_to_directories_matching_the_game(tmp_path):
    (tmp_path / ".config" / "wesnoth").mkdir(parents=True)
    (tmp_path / ".config" / "kdeglobals.d").mkdir()
    (tmp_path / ".local" / "share" / "wesnoth").mkdir(parents=True)
    found = roots({"HOME": str(tmp_path)}, CFG, ("Wesnoth",))
    assert [r.label for r in found] == [".config-wesnoth", ".local-share-wesnoth"]


def test_native_roots_empty_without_hints(tmp_path):
    (tmp_path / ".config" / "wesnoth").mkdir(parents=True)
    assert roots({"HOME": str(tmp_path)}, CFG) == []


def test_native_roots_ignore_short_accidental_matches(tmp_path):
    (tmp_path / ".config" / "kde").mkdir(parents=True)
    # "kde" is under the 4-character substring floor, so it only matches itself
    assert roots({"HOME": str(tmp_path)}, CFG, ("kdenlive",)) == []


def test_name_hints_from_install_path_and_command():
    hints = name_hints({"STEAM_COMPAT_INSTALL_PATH": "/games/Wesnoth/"},
                       ["/games/Wesnoth/bin/wesnoth.sh", "-w"])
    assert hints == ("Wesnoth", "wesnoth", "bin")
    assert name_hints({}, []) == ()


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------

def test_scan_finds_config_files_and_prunes_noise(tmp_path):
    write(tmp_path / "Settings" / "system.xml", "<x/>")
    write(tmp_path / "game.ini", "[a]")
    write(tmp_path / "data.pak", "binary")                 # wrong extension
    write(tmp_path / "Profiles" / "SGTA0001.xml", "save")  # pruned directory
    write(tmp_path / "cache" / "shader.xml", "noise")      # pruned directory

    seen = scan([Root("pfx", tmp_path)], CFG)
    assert set(seen) == {"pfx/Settings/system.xml", "pfx/game.ini"}


def test_scan_records_size_and_mtime(tmp_path):
    target = write(tmp_path / "a.xml", "12345")
    seen = scan([Root("pfx", tmp_path)], CFG)
    size, mtime = seen["pfx/a.xml"]
    assert size == 5
    assert mtime == target.stat().st_mtime_ns


def test_scan_spans_several_roots(tmp_path):
    write(tmp_path / "one" / "a.xml", "1")
    write(tmp_path / "two" / "b.ini", "2")
    seen = scan([Root("one", tmp_path / "one"), Root("two", tmp_path / "two")], CFG)
    assert set(seen) == {"one/a.xml", "two/b.ini"}


# --------------------------------------------------------------------------
# resolving and copying
# --------------------------------------------------------------------------

def test_resolve_maps_keys_back_to_paths(tmp_path):
    scope = [Root("pfx", tmp_path / "prefix")]
    assert resolve("pfx/Settings/system.xml", scope) == \
        tmp_path / "prefix" / "Settings" / "system.xml"
    assert resolve("other/a.xml", scope) is None


def test_copy_out_then_copy_in_round_trips(tmp_path):
    scope = [Root("pfx", tmp_path / "game")]
    original = write(tmp_path / "game" / "Settings" / "system.xml", "<desk/>")
    store = tmp_path / "store"

    assert copy_out(["pfx/Settings/system.xml"], scope, store) == \
        ["pfx/Settings/system.xml"]
    assert stored_keys(store) == ["pfx/Settings/system.xml"]

    original.write_text("<tv/>")          # the game rewrote it for the TV
    assert copy_in(["pfx/Settings/system.xml"], scope, store) == \
        ["pfx/Settings/system.xml"]
    assert original.read_text() == "<desk/>"


def test_copy_skips_missing_files_without_failing(tmp_path):
    scope = [Root("pfx", tmp_path / "game")]
    (tmp_path / "game").mkdir()
    assert copy_out(["pfx/absent.xml"], scope, tmp_path / "store") == []
    assert copy_in(["pfx/absent.xml"], scope, tmp_path / "store") == []


def test_copy_in_leaves_no_temporary_file_behind(tmp_path):
    scope = [Root("pfx", tmp_path / "game")]
    write(tmp_path / "game" / "a.xml", "old")
    write(tmp_path / "store" / "pfx" / "a.xml", "new")
    copy_in(["pfx/a.xml"], scope, tmp_path / "store")
    assert sorted(p.name for p in (tmp_path / "game").iterdir()) == ["a.xml"]


def test_stored_keys_on_empty_store(tmp_path):
    assert stored_keys(tmp_path / "nothing") == []


# --------------------------------------------------------------------------
# backup retention
# --------------------------------------------------------------------------

def test_prune_backups_keeps_the_newest(tmp_path):
    env = {"XDG_DATA_HOME": str(tmp_path)}
    backups = tmp_path / "proteo" / "profiles" / "1174180" / "backups"
    for stamp in ("20260101-000000", "20260102-000000", "20260103-000000"):
        (backups / stamp).mkdir(parents=True)
    prune_backups("1174180", 2, env)
    assert sorted(d.name for d in backups.iterdir()) == \
        ["20260102-000000", "20260103-000000"]


def test_prune_backups_without_a_store_is_a_noop(tmp_path):
    prune_backups("1174180", 2, {"XDG_DATA_HOME": str(tmp_path)})
