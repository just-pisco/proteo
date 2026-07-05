from proteo.core.config import Config
from proteo.core.model import request_from_env

CFG = Config()


def test_parses_sunshine_env():
    req = request_from_env({
        "SUNSHINE_CLIENT_WIDTH": "3120",
        "SUNSHINE_CLIENT_HEIGHT": "1440",
        "SUNSHINE_CLIENT_FPS": "120",
        "SUNSHINE_CLIENT_HDR": "true",
    }, CFG)
    assert (req.width, req.height, req.fps) == (3120, 1440, 120)
    assert req.hdr is False  # HDR stays off until enabled in config
    assert req.mode_str == "3120x1440@120"


def test_defaults_on_missing_or_garbage():
    req = request_from_env({}, CFG)
    assert (req.width, req.height, req.fps) == (1920, 1080, 60)
    req = request_from_env({"SUNSHINE_CLIENT_WIDTH": "banana",
                            "SUNSHINE_CLIENT_FPS": ""}, CFG)
    assert (req.width, req.fps) == (1920, 60)


def test_clamps_and_evens():
    req = request_from_env({"SUNSHINE_CLIENT_WIDTH": "9999",
                            "SUNSHINE_CLIENT_HEIGHT": "99",
                            "SUNSHINE_CLIENT_FPS": "500"}, CFG)
    assert req.width == CFG.max_width - CFG.max_width % 2
    assert req.height == CFG.min_height
    assert req.fps == CFG.max_fps
    req = request_from_env({"SUNSHINE_CLIENT_WIDTH": "1081"}, CFG)
    assert req.width % 2 == 0


def test_hdr_opt_in_via_config():
    cfg = Config(hdr_enabled=True)
    on = request_from_env({"SUNSHINE_CLIENT_HDR": "true"}, cfg)
    off = request_from_env({"SUNSHINE_CLIENT_HDR": "false"}, cfg)
    assert on.hdr is True and off.hdr is False
