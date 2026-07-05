"""EDID 1.3 generation for the virtual display (CVT reduced blanking).

Pure and deterministic: same inputs always produce the same 128-byte blob.
evdi never drives real hardware, so timing exactness matters less than a
well-formed EDID whose preferred mode is exactly what the client asked for —
KWin modesets to the preferred DTD automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

_SRGB_CHROMATICITY = bytes.fromhex("ee91a3544c99260f5054")

# hard ceiling of the EDID detailed-timing-descriptor format (16-bit, 10 kHz units)
DTD_MAX_PCLK_KHZ = 655_350


@dataclass(frozen=True)
class Timings:
    pclk_khz: int
    h_active: int
    h_blank: int
    h_front: int
    h_sync: int
    v_active: int
    v_blank: int
    v_front: int
    v_sync: int


def cvt_rb_timings(xres: int, yres: int, refresh: float) -> Timings:
    """CVT 1.2 reduced-blanking v1."""
    h_front, h_sync, h_back = 48, 32, 80
    h_blank = h_front + h_sync + h_back  # fixed 160 in CVT-RB
    v_front_min, v_back_min = 3, 6

    if xres * 3 == yres * 4:
        v_sync = 4
    elif xres * 9 == yres * 16:
        v_sync = 5
    elif xres * 10 == yres * 16:
        v_sync = 6
    else:
        v_sync = 10  # CVT: aspect ratios outside the standard set

    # minimum vertical blanking interval is 460 us
    h_period_est_us = ((1_000_000 / refresh) - 460) / yres
    vbi_lines = int(460 / h_period_est_us) + 1
    act_vbi = max(vbi_lines, v_front_min + v_sync + v_back_min)

    h_total = xres + h_blank
    v_total = yres + act_vbi
    pclk_khz = int(refresh * h_total * v_total / 1000 / 250) * 250  # 0.25 MHz step

    return Timings(
        pclk_khz=pclk_khz,
        h_active=xres, h_blank=h_blank, h_front=h_front, h_sync=h_sync,
        v_active=yres, v_blank=act_vbi, v_front=v_front_min, v_sync=v_sync,
    )


def fits_dtd(xres: int, yres: int, refresh: float) -> bool:
    """Whether the mode's CVT-RB pixel clock fits the DTD 16-bit field."""
    if not (256 <= xres <= 4095 and 256 <= yres <= 4095):
        return False
    return cvt_rb_timings(xres, yres, refresh).pclk_khz <= DTD_MAX_PCLK_KHZ


def max_fitting_fps(xres: int, yres: int, fps: int, min_fps: int) -> int:
    """Highest refresh <= fps whose mode is DTD-encodable (wide + fast modes
    can exceed the 655.35 MHz DTD pixel-clock ceiling, e.g. 2560x1080@240)."""
    for candidate in range(fps, min_fps - 1, -1):
        if fits_dtd(xres, yres, candidate):
            return candidate
    raise ValueError(f"no DTD-encodable refresh for {xres}x{yres} "
                     f"down to {min_fps} Hz")


def _detailed_timing_descriptor(t: Timings) -> bytes:
    pclk_10khz = t.pclk_khz // 10
    if pclk_10khz > 0xFFFF:
        raise ValueError(f"pixel clock {t.pclk_khz} kHz does not fit a DTD")
    h_mm = round(t.h_active * 25.4 / 96)
    v_mm = round(t.v_active * 25.4 / 96)
    d = bytearray(18)
    d[0] = pclk_10khz & 0xFF
    d[1] = (pclk_10khz >> 8) & 0xFF
    d[2] = t.h_active & 0xFF
    d[3] = t.h_blank & 0xFF
    d[4] = ((t.h_active >> 8) << 4) | (t.h_blank >> 8)
    d[5] = t.v_active & 0xFF
    d[6] = t.v_blank & 0xFF
    d[7] = ((t.v_active >> 8) << 4) | (t.v_blank >> 8)
    d[8] = t.h_front & 0xFF
    d[9] = t.h_sync & 0xFF
    d[10] = ((t.v_front & 0xF) << 4) | (t.v_sync & 0xF)
    d[11] = (((t.h_front >> 8) & 0x3) << 6) | (((t.h_sync >> 8) & 0x3) << 4) \
        | (((t.v_front >> 4) & 0x3) << 2) | ((t.v_sync >> 4) & 0x3)
    d[12] = h_mm & 0xFF
    d[13] = v_mm & 0xFF
    d[14] = ((h_mm >> 8) << 4) | (v_mm >> 8)
    d[17] = 0x1E  # digital, separate sync, +hsync +vsync
    return bytes(d)


def _text_descriptor(tag: int, text: str) -> bytes:
    payload = text.encode("ascii") + b"\x0a"
    if len(payload) > 13:
        raise ValueError(f"descriptor text too long: {text!r}")
    return bytes([0, 0, 0, tag, 0]) + payload.ljust(13, b"\x20")


def _range_limits_descriptor(v_min: int, v_max: int, h_min_khz: int,
                             h_max_khz: int, pclk_max_mhz: int) -> bytes:
    body = bytes([v_min, v_max, h_min_khz, h_max_khz, pclk_max_mhz // 10, 0x00])
    return bytes([0, 0, 0, 0xFD, 0]) + body + b"\x0a" + b"\x20" * 6


def make_edid(xres: int, yres: int, refresh: float,
              name: str = "Proteo VD", serial: int = 1) -> bytes:
    """Build a 128-byte EDID 1.3 whose preferred mode is xres x yres @ refresh."""
    if not (256 <= xres <= 4095 and 256 <= yres <= 4095):
        raise ValueError(f"resolution {xres}x{yres} outside DTD-encodable range")
    if not (23 < refresh <= 240):
        raise ValueError(f"refresh {refresh} outside supported range (24-240)")

    t = cvt_rb_timings(xres, yres, refresh)
    h_cm = round(t.h_active * 25.4 / 960)
    v_cm = round(t.v_active * 25.4 / 960)

    e = bytearray(128)
    e[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    # manufacturer "PRT" (Proteo): 5 bits per letter, A=1
    mfg = (ord("P") - 64) << 10 | (ord("R") - 64) << 5 | (ord("T") - 64)
    e[8], e[9] = mfg >> 8, mfg & 0xFF
    e[10:12] = (1).to_bytes(2, "little")      # product code
    e[12:16] = serial.to_bytes(4, "little")
    e[16] = 0                                 # week
    e[17] = 2026 - 1990                       # year
    e[18], e[19] = 1, 3                       # EDID 1.3
    e[20] = 0x80                              # digital input
    e[21], e[22] = h_cm & 0xFF, v_cm & 0xFF   # image size, cm
    e[23] = 120                               # gamma 2.2
    e[24] = 0x0E                              # RGB color, sRGB, preferred timing in DTD1
    e[25:35] = _SRGB_CHROMATICITY
    e[35:38] = b"\x00\x00\x00"                # no established timings
    e[38:54] = b"\x01\x01" * 8                # no standard timings
    e[54:72] = _detailed_timing_descriptor(t)
    e[72:90] = _text_descriptor(0xFC, name)
    e[90:108] = _range_limits_descriptor(24, 240, 15, 255, 2550)
    e[108:126] = bytes([0, 0, 0, 0x10, 0]) + b"\x00" * 13  # dummy
    e[126] = 0                                # no extension blocks
    e[127] = (-sum(e[0:127])) & 0xFF
    return bytes(e)
