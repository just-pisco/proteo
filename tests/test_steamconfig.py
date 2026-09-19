"""Filesystem-only adapter, and the one that writes into Steam's own config —
so it gets tested, on synthetic files under tmp_path.
"""

import pytest

from proteo.adapters.steamconfig import (
    SteamError, apply_launch_options, installed_app_ids, library_paths,
    missing_app_ids, user_config_paths,
)

WRAPPER = "proteo profile -- %command%"


def localconfig(apps: str) -> str:
    return ('"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n'
            '\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n\t\t\t\t{\n'
            f"{apps}"
            "\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}")


def app_block(app_id: str, *leaves: str) -> str:
    body = "".join(f"\t\t\t\t\t\t{leaf}\n" for leaf in leaves)
    return f'\t\t\t\t\t"{app_id}"\n\t\t\t\t\t{{\n{body}\t\t\t\t\t}}\n'


def write_config(tmp_path, apps: str):
    path = tmp_path / "localconfig.vdf"
    path.write_text(localconfig(apps))
    return path


# --------------------------------------------------------------------------
# writing launch options
# --------------------------------------------------------------------------

def test_hooks_only_the_requested_apps(tmp_path):
    config = write_config(tmp_path, app_block("111", '"LaunchOptions"\t\t""')
                          + app_block("222", '"LaunchOptions"\t\t""'))
    assert apply_launch_options(config, ["111"]) == ["111"]
    text = config.read_text()
    assert text.count(WRAPPER) == 1
    assert '"222"' in text  # untouched, still present


def test_environment_assignments_survive(tmp_path):
    original = 'WINEDLLOVERRIDES=\\"DWrite.dll=n,b\\" %command%'
    config = write_config(tmp_path,
                          app_block("111", f'"LaunchOptions"\t\t"{original}"'))
    apply_launch_options(config, ["111"])
    assert 'WINEDLLOVERRIDES=\\"DWrite.dll=n,b\\" proteo profile -- %command%' \
        in config.read_text()


def test_adds_the_key_when_a_game_has_none(tmp_path):
    config = write_config(tmp_path, app_block("111", '"LastPlayed"\t\t"1"'))
    assert apply_launch_options(config, ["111"]) == ["111"]
    text = config.read_text()
    assert WRAPPER in text
    assert '"LastPlayed"\t\t"1"' in text


def test_is_idempotent_and_makes_no_backup_when_nothing_changes(tmp_path):
    config = write_config(tmp_path, app_block("111", '"LaunchOptions"\t\t""'))
    apply_launch_options(config, ["111"])
    backups = len(list(tmp_path.glob("*.proteo-*")))
    assert apply_launch_options(config, ["111"]) == []
    assert len(list(tmp_path.glob("*.proteo-*"))) == backups


def test_a_backup_is_taken_before_writing(tmp_path):
    config = write_config(tmp_path, app_block("111", '"LaunchOptions"\t\t""'))
    before = config.read_text()
    apply_launch_options(config, ["111"])
    backups = list(tmp_path.glob("localconfig.vdf.proteo-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == before


def test_unknown_app_ids_are_ignored(tmp_path):
    config = write_config(tmp_path, app_block("111", '"LaunchOptions"\t\t""'))
    assert apply_launch_options(config, ["999"]) == []


def test_removal_leaves_the_key_empty(tmp_path):
    config = write_config(tmp_path, app_block("111", '"LaunchOptions"\t\t""'))
    apply_launch_options(config, ["111"])
    assert apply_launch_options(config, ["111"], remove=True) == ["111"]
    assert WRAPPER not in config.read_text()
    assert '"LaunchOptions"\t\t""' in config.read_text()


def test_an_unexpected_layout_is_refused_not_guessed(tmp_path):
    path = tmp_path / "localconfig.vdf"
    path.write_text('"Something"\n{\n\t"else"\t\t"1"\n}')
    with pytest.raises(SteamError):
        apply_launch_options(path, ["111"])


# --------------------------------------------------------------------------
# read-only checks
# --------------------------------------------------------------------------

def test_missing_app_ids_reports_only_unhooked_games(tmp_path):
    config = write_config(tmp_path,
                          app_block("111", f'"LaunchOptions"\t\t"{WRAPPER}"')
                          + app_block("222", '"LaunchOptions"\t\t""'))
    assert missing_app_ids(config, ["111", "222"]) == ["222"]


def test_missing_app_ids_survives_an_unreadable_file(tmp_path):
    assert missing_app_ids(tmp_path / "absent.vdf", ["111"]) == []
    broken = tmp_path / "broken.vdf"
    broken.write_text('"unbalanced" {')
    assert missing_app_ids(broken, ["111"]) == []


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def test_library_paths_include_other_drives(tmp_path):
    root = tmp_path / "steam"
    (root / "steamapps").mkdir(parents=True)
    other = tmp_path / "elsewhere" / "SteamLibrary" / "steamapps"
    other.mkdir(parents=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t'
        f'"{tmp_path / "elsewhere" / "SteamLibrary"}"\n\t}}\n}}')
    assert library_paths(root) == [root / "steamapps", other]


def test_library_paths_without_a_manifest(tmp_path):
    root = tmp_path / "steam"
    (root / "steamapps").mkdir(parents=True)
    assert library_paths(root) == [root / "steamapps"]


def test_installed_app_ids_skips_the_redistributables(tmp_path):
    root = tmp_path / "steam"
    apps = root / "steamapps"
    apps.mkdir(parents=True)
    for app in ("1174180", "228980", "703080"):
        (apps / f"appmanifest_{app}.acf").write_text("{}")
    assert installed_app_ids(root) == ["703080", "1174180"]


def test_user_config_paths_covers_every_account(tmp_path):
    root = tmp_path / "steam"
    (root / "steamapps").mkdir(parents=True)
    for user in ("111", "222"):
        cfg = root / "userdata" / user / "config"
        cfg.mkdir(parents=True)
        (cfg / "localconfig.vdf").write_text("{}")
    assert len(user_config_paths(root)) == 2
    assert user_config_paths(tmp_path / "nothing") == []
