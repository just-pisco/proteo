import pytest

from proteo.core.config import Config, load_config


def test_defaults_without_files(tmp_path):
    cfg = load_config(paths=[tmp_path / "missing.toml"])
    assert cfg == Config()


def test_load_and_override(tmp_path):
    system = tmp_path / "system.toml"
    user = tmp_path / "user.toml"
    system.write_text('rescue_output = "HDMI-1"\nmax_fps = 144\n')
    user.write_text('max_fps = 165\nfuture_knob = "kept"\n')
    cfg = load_config(paths=[system, user])
    assert cfg.rescue_output == "HDMI-1"
    assert cfg.max_fps == 165                    # user file wins
    assert cfg.extra == {"future_knob": "kept"}  # unknown keys preserved, not fatal


def test_invalid_behavior_rejected(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text('physical_during_stream = "explode"\n')
    with pytest.raises(ValueError):
        load_config(paths=[bad])
