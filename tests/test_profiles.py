from proteo.core.config import Config
from proteo.core.profiles import (
    Manifest, changed_paths, classify, discriminating, display_key, game_dir,
    is_config_candidate, manifest_load, manifest_save, manifest_path, store_dir,
)

CFG = Config()


def output(name, width, height, enabled=True, priority=1, rotation=1):
    return {"name": name, "enabled": enabled, "priority": priority,
            "rotation": rotation, "currentModeId": "m",
            "modes": [{"id": "m", "name": f"{width}x{height}@60",
                       "size": {"width": width, "height": height}}]}


# --------------------------------------------------------------------------
# display key
# --------------------------------------------------------------------------

def test_key_from_primary_output():
    snap = {"outputs": [output("DP-2", 5120, 1440)]}
    assert display_key(snap) == "5120x1440"


def test_key_ignores_disabled_and_follows_priority():
    # during a stream the physical output is disabled and the virtual one is
    # primary: the key must describe what the game will actually see
    snap = {"outputs": [output("DP-2", 5120, 1440, enabled=False, priority=1),
                        output("DVI-I-1", 1920, 1080, priority=2)]}
    assert display_key(snap) == "1920x1080"

    snap = {"outputs": [output("DP-2", 5120, 1440, priority=2),
                        output("DVI-I-1", 1920, 1080, priority=1)]}
    assert display_key(snap) == "1920x1080"


def test_key_swaps_axes_when_rotated():
    snap = {"outputs": [output("DP-2", 1920, 1080, rotation=2)]}
    assert display_key(snap) == "1080x1920"


def test_key_falls_back_when_nothing_is_on():
    assert display_key({"outputs": []}) == "unknown"
    assert display_key({}, fallback="none") == "none"
    assert display_key({"outputs": [{"name": "DP-2", "enabled": True}]}) == "unknown"


# --------------------------------------------------------------------------
# candidate classification — the save-data guard rail
# --------------------------------------------------------------------------

def test_real_rdr2_paths():
    settings = ("pfx/Documents/Rockstar Games/Red Dead Redemption 2/"
                "Settings/system.xml")
    savegame = ("pfx/Documents/Rockstar Games/Red Dead Redemption 2/"
                "Profiles/a1b2/SGTA0001.xml")
    assert is_config_candidate(settings, 4774, CFG)
    # excluded by the "profile" word: swapping this would trade save games
    assert not is_config_candidate(savegame, 4774, CFG)


def test_extension_size_and_word_filters():
    assert is_config_candidate("pfx/AppData/Local/Game/settings.ini", 900, CFG)
    assert not is_config_candidate("pfx/AppData/Local/Game/data.pak", 900, CFG)
    assert not is_config_candidate("pfx/Game/huge.xml", CFG.profile_max_bytes + 1, CFG)
    for word in ("save", "cache", "crash", "backup"):
        assert not is_config_candidate(f"pfx/{word}/settings.xml", 10, CFG)


def test_filters_are_case_insensitive():
    assert not is_config_candidate("pfx/SaveGames/opts.ini", 10, CFG)
    assert is_config_candidate("pfx/Game/SETTINGS.XML", 10, CFG)


def test_classify_splits_and_sorts():
    tracked, ignored = classify(
        {"pfx/b.ini": 10, "pfx/a.xml": 10, "pfx/save/c.xml": 10, "pfx/d.pak": 10},
        CFG)
    assert tracked == ["pfx/a.xml", "pfx/b.ini"]
    assert ignored == ["pfx/d.pak", "pfx/save/c.xml"]


def test_exclusions_are_configurable():
    cfg = Config(profile_exclude=(), profile_extensions=("xml",))
    assert is_config_candidate("pfx/save/anything.xml", 10, cfg)
    assert not is_config_candidate("pfx/settings.ini", 10, cfg)


# --------------------------------------------------------------------------
# change detection
# --------------------------------------------------------------------------

def test_changed_paths_reports_new_and_touched():
    before = {"a": (10, 1), "b": (10, 1)}
    after = {"a": (10, 1), "b": (12, 2), "c": (7, 3)}
    assert changed_paths(before, after) == {"b": 12, "c": 7}


def test_changed_paths_ignores_deletions():
    # a file the game removed cannot be captured, and must not look like a change
    assert changed_paths({"a": (10, 1)}, {}) == {}


def test_changed_paths_notices_same_size_rewrite():
    assert changed_paths({"a": (10, 1)}, {"a": (10, 2)}) == {"a": 10}


# --------------------------------------------------------------------------
# manifest
# --------------------------------------------------------------------------

def test_manifest_roundtrip(tmp_path):
    m = Manifest(app_id="1174180", name="Red Dead Redemption 2",
                 roots=["pfx"], files=["pfx/a.xml"], candidates=["pfx/c.xml"],
                 ignored=["pfx/b.pak"])
    p = tmp_path / "manifest.json"
    manifest_save(m, p)
    assert manifest_load(p) == m


def test_manifest_load_missing_and_corrupt(tmp_path):
    assert manifest_load(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert manifest_load(bad) is None


def test_learn_only_observes_never_swaps():
    m = Manifest(app_id="1")
    m.learn(["pfx/a.xml"], ["pfx/c.pak"])
    # seeing a file change is not enough to start swapping it
    assert m.files == []
    assert m.candidates == ["pfx/a.xml"]
    assert m.ignored == ["pfx/c.pak"]


def test_learn_is_cumulative_and_never_demotes():
    m = Manifest(app_id="1", files=["pfx/a.xml"])
    m.learn(["pfx/a.xml", "pfx/b.xml"], ["pfx/c.pak"])
    # an already-swapped file does not fall back to merely observed
    assert m.files == ["pfx/a.xml"]
    assert m.candidates == ["pfx/b.xml"]
    m.learn([], ["pfx/b.xml"])
    assert m.candidates == ["pfx/b.xml"]
    assert m.ignored == ["pfx/c.pak"]


def test_promote_moves_out_of_both_watch_lists():
    m = Manifest(app_id="1", candidates=["pfx/a.xml"], ignored=["pfx/b.ini"])
    assert m.promote({"pfx/a.xml", "pfx/b.ini"}) == ["pfx/a.xml", "pfx/b.ini"]
    assert m.files == ["pfx/a.xml", "pfx/b.ini"]
    assert m.candidates == [] and m.ignored == []
    # promoting again reports nothing new
    assert m.promote({"pfx/a.xml"}) == []


def test_watched_is_the_union_of_swapped_and_observed():
    m = Manifest(app_id="1", files=["pfx/b.xml"], candidates=["pfx/a.xml"])
    assert m.watched == ["pfx/a.xml", "pfx/b.xml"]


# --------------------------------------------------------------------------
# promotion evidence
# --------------------------------------------------------------------------

def test_only_files_differing_between_displays_are_promoted():
    digests = {
        # the settings file: genuinely different on each screen
        "pfx/system.xml": {"5120x1440": "aaa", "1920x1080": "bbb"},
        # a launcher component manifest: rewritten every launch, same content
        "pfx/manifest.json": {"5120x1440": "ccc", "1920x1080": "ccc"},
    }
    assert discriminating(digests) == {"pfx/system.xml"}


def test_a_single_display_is_never_enough_evidence():
    assert discriminating({"pfx/system.xml": {"5120x1440": "aaa"}}) == set()
    assert discriminating({}) == set()


# --------------------------------------------------------------------------
# store layout
# --------------------------------------------------------------------------

def test_store_follows_xdg_data_home():
    env = {"XDG_DATA_HOME": "/data", "HOME": "/home/pisco"}
    assert store_dir(env).as_posix() == "/data/proteo/profiles"
    assert game_dir("1174180", env).as_posix() == "/data/proteo/profiles/1174180"
    assert manifest_path("1174180", env).name == "manifest.json"


def test_store_defaults_under_home():
    env = {"HOME": "/home/pisco"}
    assert store_dir(env).as_posix() == "/home/pisco/.local/share/proteo/profiles"
