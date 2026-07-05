from proteo.core.config import Config
from proteo.core.layout import (find_new_output, mode_setting, rescue_commands,
                                restore_commands, stream_layout_commands)


def snap(*outs):
    return {"outputs": list(outs)}


def dp2(enabled=True, priority=1):
    return {
        "id": 1, "name": "DP-2", "connected": True, "enabled": enabled,
        "priority": priority, "currentModeId": "3",
        "modes": [{"id": "3", "name": "5120x1440@240",
                   "size": {"width": 5120, "height": 1440}, "refreshRate": 240.0}],
        "pos": {"x": 0, "y": 0},
    }


def virt(name="DVI-I-1"):
    return {
        "id": 2, "name": name, "connected": True, "enabled": True,
        "priority": 2, "currentModeId": "51",
        "modes": [{"id": "51", "name": "1920x1080@60",
                   "size": {"width": 1920, "height": 1080}, "refreshRate": 59.93}],
        "pos": {"x": 4096, "y": 0},
    }


def test_find_new_output():
    assert find_new_output(snap(dp2()), snap(dp2(), virt())) == "DVI-I-1"
    assert find_new_output(snap(dp2()), snap(dp2())) is None


def test_mode_setting_prefers_name():
    assert mode_setting(dp2()) == "5120x1440@240"
    nameless = dp2()
    del nameless["modes"][0]["name"]
    assert mode_setting(nameless) == "3"


def test_stream_layout_disable_physical():
    cmds = stream_layout_commands(snap(dp2()), "DVI-I-1", Config())
    assert cmds == ["output.DVI-I-1.enable", "output.DVI-I-1.priority.1",
                    "output.DP-2.disable"]


def test_stream_layout_keep_physical():
    cfg = Config(physical_during_stream="keep")
    cmds = stream_layout_commands(snap(dp2()), "DVI-I-1", cfg)
    assert "output.DP-2.disable" not in cmds
    assert "output.DVI-I-1.priority.1" in cmds


def test_stream_layout_skips_already_disabled_physical():
    cmds = stream_layout_commands(snap(dp2(enabled=False)), "DVI-I-1", Config())
    assert "output.DP-2.disable" not in cmds


def test_restore_reapplies_snapshot():
    saved = snap(dp2())
    current = snap(dp2(enabled=False), virt())
    cmds = restore_commands(saved, current)
    assert cmds == ["output.DP-2.enable", "output.DP-2.mode.5120x1440@240",
                    "output.DP-2.position.0,0", "output.DP-2.priority.1"]


def test_restore_ignores_gone_outputs():
    saved = snap(dp2(), virt("HDMI-9"))
    cmds = restore_commands(saved, snap(dp2()))
    assert not any("HDMI-9" in c for c in cmds)


def test_restore_redisables_outputs_saved_disabled():
    saved = snap(dp2(), {**virt("HDMI-2"), "enabled": False})
    cmds = restore_commands(saved, snap(dp2(), virt("HDMI-2")))
    assert "output.HDMI-2.disable" in cmds


def test_rescue_commands():
    cfg = Config(rescue_output="DP-2", rescue_mode="5120x1440@240")
    assert rescue_commands(cfg) == ["output.DP-2.enable",
                                    "output.DP-2.mode.5120x1440@240",
                                    "output.DP-2.priority.1"]
    assert "mode" not in " ".join(rescue_commands(Config(rescue_mode="")))
