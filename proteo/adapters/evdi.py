"""libevdi ctypes adapter.

`hold()` is the long-running guts of the `proteo _hold` subprocess: it connects
an available EVDI device with the given EDID (making the virtual connector
appear) and keeps the connection alive — the connector exists only while a
client holds it (Phase-0 spike, finding 5).

The holder must also CONSUME frames (register a buffer, request updates, grab
pixels), even though the pixels themselves go unused — Sunshine captures
compositor-side. An EVDI client that never drains updates leaves the DRM
present pipeline for the output waiting on flip completions, which KWin's
frame scheduler experiences as a stalled display: compositing falls behind and
every screencast frame arrives late (seconds of UI lag on the stream). The
Phase-0 spike client consumed frames — this is a protocol obligation, not an
optimization.

Struct layouts mirror /usr/include/evdi_lib.h (libevdi 1.14).
"""

from __future__ import annotations

import ctypes as ct
import os
import select
import signal

MAX_DRM_CARDS = 32
_PIXEL_AREA_LIMIT = 4096 * 2160

# enum evdi_device_status
AVAILABLE, UNRECOGNIZED, NOT_PRESENT = 0, 1, 2


class EvdiMode(ct.Structure):
    _fields_ = [("width", ct.c_int), ("height", ct.c_int),
                ("refresh_rate", ct.c_int), ("bits_per_pixel", ct.c_int),
                ("pixel_format", ct.c_uint)]


class EvdiRect(ct.Structure):
    _fields_ = [("x1", ct.c_int), ("y1", ct.c_int),
                ("x2", ct.c_int), ("y2", ct.c_int)]


class EvdiBuffer(ct.Structure):
    _fields_ = [("id", ct.c_int), ("buffer", ct.c_void_p),
                ("width", ct.c_int), ("height", ct.c_int),
                ("stride", ct.c_int),
                ("rects", ct.POINTER(EvdiRect)), ("rect_count", ct.c_int)]


class EvdiCursorSet(ct.Structure):
    _fields_ = [("hot_x", ct.c_int32), ("hot_y", ct.c_int32),
                ("width", ct.c_uint32), ("height", ct.c_uint32),
                ("enabled", ct.c_uint8), ("buffer_length", ct.c_uint32),
                ("buffer", ct.POINTER(ct.c_uint32)),
                ("pixel_format", ct.c_uint32), ("stride", ct.c_uint32)]


class EvdiCursorMove(ct.Structure):
    _fields_ = [("x", ct.c_int32), ("y", ct.c_int32)]


class EvdiDdcciData(ct.Structure):
    _fields_ = [("address", ct.c_uint16), ("flags", ct.c_uint16),
                ("buffer_length", ct.c_uint32),
                ("buffer", ct.POINTER(ct.c_uint8))]


_DPMS_CB = ct.CFUNCTYPE(None, ct.c_int, ct.c_void_p)
_MODE_CB = ct.CFUNCTYPE(None, EvdiMode, ct.c_void_p)
_UPDATE_CB = ct.CFUNCTYPE(None, ct.c_int, ct.c_void_p)
_CRTC_CB = ct.CFUNCTYPE(None, ct.c_int, ct.c_void_p)
_CURSOR_SET_CB = ct.CFUNCTYPE(None, EvdiCursorSet, ct.c_void_p)
_CURSOR_MOVE_CB = ct.CFUNCTYPE(None, EvdiCursorMove, ct.c_void_p)
_DDCCI_CB = ct.CFUNCTYPE(None, EvdiDdcciData, ct.c_void_p)


class EvdiEventContext(ct.Structure):
    _fields_ = [("dpms_handler", _DPMS_CB),
                ("mode_changed_handler", _MODE_CB),
                ("update_ready_handler", _UPDATE_CB),
                ("crtc_state_handler", _CRTC_CB),
                ("cursor_set_handler", _CURSOR_SET_CB),
                ("cursor_move_handler", _CURSOR_MOVE_CB),
                ("ddcci_data_handler", _DDCCI_CB),
                ("user_data", ct.c_void_p)]


def _load() -> ct.CDLL:
    lib = ct.CDLL("libevdi.so.1", use_errno=True)
    lib.evdi_check_device.restype = ct.c_int
    lib.evdi_check_device.argtypes = [ct.c_int]
    lib.evdi_open.restype = ct.c_void_p
    lib.evdi_open.argtypes = [ct.c_int]
    lib.evdi_connect.restype = None
    lib.evdi_connect.argtypes = [ct.c_void_p, ct.c_char_p, ct.c_uint, ct.c_uint32]
    lib.evdi_disconnect.restype = None
    lib.evdi_disconnect.argtypes = [ct.c_void_p]
    lib.evdi_close.restype = None
    lib.evdi_close.argtypes = [ct.c_void_p]
    lib.evdi_get_event_ready.restype = ct.c_int
    lib.evdi_get_event_ready.argtypes = [ct.c_void_p]
    lib.evdi_handle_events.restype = None
    lib.evdi_handle_events.argtypes = [ct.c_void_p, ct.POINTER(EvdiEventContext)]
    lib.evdi_register_buffer.restype = None
    lib.evdi_register_buffer.argtypes = [ct.c_void_p, EvdiBuffer]
    lib.evdi_unregister_buffer.restype = None
    lib.evdi_unregister_buffer.argtypes = [ct.c_void_p, ct.c_int]
    lib.evdi_request_update.restype = ct.c_bool
    lib.evdi_request_update.argtypes = [ct.c_void_p, ct.c_int]
    lib.evdi_grab_pixels.restype = None
    lib.evdi_grab_pixels.argtypes = [ct.c_void_p, ct.POINTER(EvdiRect),
                                     ct.POINTER(ct.c_int)]
    return lib


def find_available_device(lib: ct.CDLL | None = None) -> int:
    lib = lib or _load()
    for i in range(MAX_DRM_CARDS):
        if lib.evdi_check_device(i) == AVAILABLE:
            return i
    return -1


def hold(edid: bytes, log=print) -> int:
    """Blocks until SIGTERM/SIGINT. Returns a process exit code."""
    lib = _load()
    card = find_available_device(lib)
    if card < 0:
        log("no AVAILABLE evdi device — is the module loaded? "
            "(sudo modprobe evdi initial_device_count=1)")
        return 3
    handle = lib.evdi_open(card)
    if not handle:
        log(f"evdi_open(card{card}) failed, errno={ct.get_errno()}")
        return 4
    log(f"holding /dev/dri/card{card} with {len(edid)}-byte EDID")

    # signal → wakeup pipe, so poll() reliably returns even mid-syscall
    r, w = os.pipe()
    os.set_blocking(w, False)
    signal.set_wakeup_fd(w)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: None)

    # framebuffer state: one registered buffer per current mode, drained
    # continuously so KWin's flips complete on time (see module docstring)
    _MAX_RECTS = 16
    state: dict = {"buf": None, "mem": None, "rects": None,
                   "pending": False, "frames": 0}

    def register_for(mode: EvdiMode) -> None:
        if state["buf"] is not None:
            lib.evdi_unregister_buffer(handle, state["buf"].id)
        stride = mode.width * 4
        mem = ct.create_string_buffer(stride * mode.height)
        rects = (EvdiRect * _MAX_RECTS)()
        buf = EvdiBuffer(id=1, buffer=ct.cast(mem, ct.c_void_p),
                         width=mode.width, height=mode.height, stride=stride,
                         rects=ct.cast(rects, ct.POINTER(EvdiRect)),
                         rect_count=_MAX_RECTS)
        lib.evdi_register_buffer(handle, buf)
        state.update(buf=buf, mem=mem, rects=rects)
        state["pending"] = bool(lib.evdi_request_update(handle, buf.id))

    def on_mode(mode: EvdiMode, _ud) -> None:
        log(f"mode_changed: {mode.width}x{mode.height}@{mode.refresh_rate} "
            f"bpp={mode.bits_per_pixel}")
        register_for(mode)

    def on_update_ready(_buf, _ud) -> None:
        state["pending"] = True

    def drain() -> None:
        # cap per wakeup so signals stay responsive even under a frame flood
        for _ in range(8):
            if not state["pending"] or state["buf"] is None:
                return
            state["pending"] = False
            n = ct.c_int(_MAX_RECTS)
            lib.evdi_grab_pixels(handle, state["rects"], ct.byref(n))
            state["frames"] += 1
            if state["frames"] % 3600 == 0:
                log(f"{state['frames']} frames consumed")
            state["pending"] = bool(
                lib.evdi_request_update(handle, state["buf"].id))

    # keep callback objects referenced for the whole loop lifetime (ctypes
    # would otherwise free the trampolines while the kernel still calls them)
    ctx = EvdiEventContext(
        dpms_handler=_DPMS_CB(lambda m, _u: log(f"dpms: {m}")),
        mode_changed_handler=_MODE_CB(on_mode),
        update_ready_handler=_UPDATE_CB(on_update_ready),
        crtc_state_handler=_CRTC_CB(lambda _s, _u: None),
        cursor_set_handler=_CURSOR_SET_CB(lambda _c, _u: None),
        cursor_move_handler=_CURSOR_MOVE_CB(lambda _c, _u: None),
        ddcci_data_handler=_DDCCI_CB(lambda _d, _u: None),
        user_data=None,
    )

    lib.evdi_connect(handle, edid, len(edid), _PIXEL_AREA_LIMIT)
    evdi_fd = lib.evdi_get_event_ready(handle)
    poller = select.poll()
    poller.register(evdi_fd, select.POLLIN)
    poller.register(r, select.POLLIN)

    stop = False
    while not stop:
        try:
            events = poller.poll(1000)
        except InterruptedError:
            events = []
        for fd, _ in events:
            if fd == r:
                stop = True
            elif fd == evdi_fd:
                lib.evdi_handle_events(handle, ct.byref(ctx))
        drain()

    log(f"disconnecting after {state['frames']} frames")
    if state["buf"] is not None:
        lib.evdi_unregister_buffer(handle, state["buf"].id)
    lib.evdi_disconnect(handle)
    lib.evdi_close(handle)
    return 0
