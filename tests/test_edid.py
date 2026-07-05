import shutil
import subprocess

import pytest

from proteo.core.edid import cvt_rb_timings, make_edid, max_fitting_fps


def checksum_ok(blob: bytes) -> bool:
    return sum(blob[0:128]) % 256 == 0


def test_blob_shape_and_checksum():
    e = make_edid(1920, 1080, 60)
    assert len(e) == 128
    assert e[0:8] == b"\x00\xff\xff\xff\xff\xff\xff\x00"
    assert checksum_ok(e)


def test_deterministic():
    assert make_edid(2560, 1440, 120) == make_edid(2560, 1440, 120)
    assert make_edid(2560, 1440, 120) != make_edid(2560, 1440, 60)


def test_dtd_encodes_requested_mode():
    e = make_edid(3120, 1440, 120)
    dtd = e[54:72]
    h_active = dtd[2] | ((dtd[4] >> 4) << 8)
    v_active = dtd[5] | ((dtd[7] >> 4) << 8)
    assert (h_active, v_active) == (3120, 1440)
    t = cvt_rb_timings(3120, 1440, 120)
    refresh = t.pclk_khz * 1000 / ((t.h_active + t.h_blank) * (t.v_active + t.v_blank))
    assert refresh == pytest.approx(120, abs=0.5)


@pytest.mark.parametrize("w,h,r", [(640, 480, 24), (1280, 720, 60),
                                   (3840, 2160, 60), (1920, 1080, 240)])
def test_various_modes_valid(w, h, r):
    e = make_edid(w, h, r)
    assert checksum_ok(e)


def test_rejects_out_of_range():
    with pytest.raises(ValueError):
        make_edid(8192, 2160, 60)
    with pytest.raises(ValueError):
        make_edid(1920, 1080, 480)
    with pytest.raises(ValueError):
        make_edid(2560, 1080, 240)  # ~793 MHz pixel clock, over the DTD ceiling


def test_max_fitting_fps_steps_down_over_dtd_ceiling():
    fps = max_fitting_fps(2560, 1080, 240, 24)
    assert fps < 240
    assert make_edid(2560, 1080, fps)          # result must be encodable
    assert max_fitting_fps(1920, 1080, 120, 24) == 120  # untouched when it fits


@pytest.mark.skipif(shutil.which("edid-decode") is None,
                    reason="edid-decode not installed")
@pytest.mark.parametrize("w,h,r", [(1920, 1080, 60), (3120, 1440, 120),
                                   (3840, 2160, 60)])
def test_edid_decode_conformity(w, h, r):
    res = subprocess.run(["edid-decode", "--check", "-"],
                         input=make_edid(w, h, r),
                         capture_output=True)
    assert b"EDID conformity: PASS" in res.stdout, res.stdout.decode()
