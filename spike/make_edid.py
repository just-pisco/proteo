#!/usr/bin/env python3
"""Generate a minimal EDID 1.3 blob for an arbitrary mode (CVT reduced blanking).

Spike tool for Proteo; will graduate into core/ in Phase 1.

Usage: make_edid.py WIDTH HEIGHT REFRESH [-o FILE]
"""

import argparse
import math
import sys


def cvt_rb_timings(xres: int, yres: int, refresh: float) -> dict:
    """CVT 1.2 reduced-blanking v1 timings. evdi never drives real hardware,
    so exactness matters less than producing a well-formed, plausible DTD."""
    h_front, h_sync, h_back = 48, 32, 80
    h_blank = h_front + h_sync + h_back  # 160, fixed in CVT-RB
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

    return {
        "pclk_khz": pclk_khz,
        "h_active": xres, "h_blank": h_blank,
        "h_front": h_front, "h_sync": h_sync,
        "v_active": yres, "v_blank": act_vbi,
        "v_front": v_front_min, "v_sync": v_sync,
    }


def detailed_timing_descriptor(t: dict) -> bytes:
    pclk_10khz = t["pclk_khz"] // 10
    h_mm = round(t["h_active"] * 25.4 / 96)
    v_mm = round(t["v_active"] * 25.4 / 96)
    d = bytearray(18)
    d[0] = pclk_10khz & 0xFF
    d[1] = (pclk_10khz >> 8) & 0xFF
    d[2] = t["h_active"] & 0xFF
    d[3] = t["h_blank"] & 0xFF
    d[4] = ((t["h_active"] >> 8) << 4) | (t["h_blank"] >> 8)
    d[5] = t["v_active"] & 0xFF
    d[6] = t["v_blank"] & 0xFF
    d[7] = ((t["v_active"] >> 8) << 4) | (t["v_blank"] >> 8)
    d[8] = t["h_front"] & 0xFF
    d[9] = t["h_sync"] & 0xFF
    d[10] = ((t["v_front"] & 0xF) << 4) | (t["v_sync"] & 0xF)
    d[11] = (((t["h_front"] >> 8) & 0x3) << 6) | (((t["h_sync"] >> 8) & 0x3) << 4) \
        | (((t["v_front"] >> 4) & 0x3) << 2) | ((t["v_sync"] >> 4) & 0x3)
    d[12] = h_mm & 0xFF
    d[13] = v_mm & 0xFF
    d[14] = ((h_mm >> 8) << 4) | (v_mm >> 8)
    d[17] = 0x1E  # digital, separate sync, +hsync +vsync
    return bytes(d)


def text_descriptor(tag: int, text: str) -> bytes:
    payload = text.encode("ascii") + b"\x0a"
    return bytes([0, 0, 0, tag, 0]) + payload.ljust(13, b"\x20")


def range_limits_descriptor(v_min: int, v_max: int, h_min_khz: int,
                            h_max_khz: int, pclk_max_mhz: int) -> bytes:
    body = bytes([v_min, v_max, h_min_khz, h_max_khz, pclk_max_mhz // 10, 0x00])
    return bytes([0, 0, 0, 0xFD, 0]) + body + b"\x0a" + b"\x20" * 6


def make_edid(xres: int, yres: int, refresh: float) -> bytes:
    t = cvt_rb_timings(xres, yres, refresh)
    h_cm = round(t["h_active"] * 25.4 / 960)
    v_cm = round(t["v_active"] * 25.4 / 960)

    e = bytearray(128)
    e[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    # manufacturer "PRT" (Proteo): 5 bits per letter, A=1
    mfg = (ord("P") - 64) << 10 | (ord("R") - 64) << 5 | (ord("T") - 64)
    e[8], e[9] = mfg >> 8, mfg & 0xFF
    e[10:12] = (1).to_bytes(2, "little")      # product code
    e[12:16] = (1).to_bytes(4, "little")      # serial
    e[16] = 0                                 # week
    e[17] = 2026 - 1990                       # year
    e[18], e[19] = 1, 3                       # EDID 1.3
    e[20] = 0x80                              # digital input
    e[21], e[22] = h_cm & 0xFF, v_cm & 0xFF   # image size, cm
    e[23] = 120                               # gamma 2.2
    e[24] = 0x0E                              # RGB color, sRGB, preferred timing in DTD1
    e[25:35] = bytes.fromhex("ee91a3544c99260f5054")  # sRGB chromaticity
    e[35:38] = b"\x00\x00\x00"                # no established timings
    e[38:54] = b"\x01\x01" * 8                # no standard timings
    e[54:72] = detailed_timing_descriptor(t)
    e[72:90] = text_descriptor(0xFC, "Proteo VD")
    e[90:108] = range_limits_descriptor(24, 240, 15, 255, 2550)
    e[108:126] = bytes([0, 0, 0, 0x10, 0]) + b"\x00" * 13  # dummy
    e[126] = 0                                # no extension blocks
    e[127] = (-sum(e[0:127])) & 0xFF
    return bytes(e)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("width", type=int)
    p.add_argument("height", type=int)
    p.add_argument("refresh", type=float)
    p.add_argument("-o", "--output", default="/dev/stdout")
    a = p.parse_args()
    with open(a.output, "wb") as f:
        f.write(make_edid(a.width, a.height, a.refresh))
    return 0


if __name__ == "__main__":
    sys.exit(main())
