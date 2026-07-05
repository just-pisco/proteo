"""proteo CLI — do / undo / status / rescue (+ hidden _hold).

do/undo contract (AGENTS.md): `do` reads SUNSHINE_CLIENT_*, brings up the
virtual output at that format and makes it the stream target; `undo` tears it
down and restores the physical configuration. Both are idempotent and safe to
call in any order.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import asdict

from . import __version__
from .adapters import evdi, kscreen, proc
from .core import layout, state
from .core.config import load_config
from .core.edid import make_edid
from .core.model import request_from_env


def _say(msg: str) -> None:
    print(f"proteo: {msg}", flush=True)


def cmd_do(args) -> int:
    cfg = load_config()
    req = request_from_env(dict(os.environ), cfg)
    spath = state.state_path()
    st = state.load(spath)

    if st and proc.hold_active():
        if st.request == asdict(req):
            _say(f"session already active on {st.virtual_output} "
                 f"({req.mode_str}); nothing to do")
            return 0
        # client format changed: replace the virtual display but KEEP the
        # original pre-session snapshot — that is what undo must restore
        _say(f"reshaping active session to {req.mode_str}")
        original_snapshot = st.snapshot
        proc.stop_hold()
        kscreen.wait_for_output_gone(st.virtual_output)
    elif st:
        _say("stale session state found (helper not running); reusing its "
             "snapshot for restore")
        original_snapshot = st.snapshot
    else:
        original_snapshot = kscreen.snapshot()

    edid_path = state.runtime_dir() / f"edid-{req.mode_str}.bin"
    edid_path.parent.mkdir(parents=True, exist_ok=True)
    edid_path.write_bytes(make_edid(req.width, req.height, req.fps,
                                    name=cfg.virtual_name))

    pre = kscreen.snapshot()
    proc.start_hold(edid_path)
    virtual = kscreen.wait_for_new_output(pre)
    if virtual is None:
        proc.stop_hold()
        _say("ERROR: KWin did not adopt the virtual output within the timeout")
        return 1

    kscreen.apply(layout.stream_layout_commands(original_snapshot, virtual, cfg),
                  verbose=args.verbose)
    state.save(state.SessionState(
        virtual_output=virtual, helper_pid=proc.hold_pid(),
        edid_path=str(edid_path), request=asdict(req),
        snapshot=original_snapshot), spath)
    _say(f"virtual display {virtual} up at {req.mode_str}"
         + (" (HDR)" if req.hdr else "")
         + (", physical outputs disabled"
            if cfg.physical_during_stream == "disable" else ""))
    return 0


def _restore_and_teardown(st: state.SessionState | None, cfg, verbose: bool) -> None:
    # order matters: bring physical outputs back BEFORE removing the virtual
    # one, so KWin never faces a moment with zero enabled outputs
    if st:
        kscreen.apply(layout.restore_commands(st.snapshot, kscreen.snapshot()),
                      verbose=verbose)
    proc.stop_hold()
    if st:
        kscreen.wait_for_output_gone(st.virtual_output)
        # re-assert after topology change: KWin may have shuffled priorities
        # when the virtual output vanished
        kscreen.apply(layout.restore_commands(st.snapshot, kscreen.snapshot()),
                      verbose=verbose)
    if not kscreen.enabled_names(kscreen.snapshot()):
        # never leave the seat with no display at all
        kscreen.apply(layout.rescue_commands(cfg), verbose=verbose)


def cmd_undo(args) -> int:
    cfg = load_config()
    spath = state.state_path()
    st = state.load(spath)
    if st is None and not proc.hold_active():
        _say("no session to undo")
        return 0
    _restore_and_teardown(st, cfg, args.verbose)
    state.clear(spath)
    _say("session torn down, physical configuration restored")
    return 0


def cmd_rescue(args) -> int:
    """Force everything back to physical, best effort, ignore errors."""
    cfg = load_config()
    spath = state.state_path()
    st = state.load(spath)
    try:
        proc.stop_hold()
    except Exception as e:  # noqa: BLE001 — rescue must not stop halfway
        _say(f"stop_hold failed, continuing: {e}")
    try:
        if st:
            kscreen.apply(layout.restore_commands(st.snapshot, kscreen.snapshot()),
                          verbose=args.verbose)
        else:
            kscreen.apply(layout.rescue_commands(cfg), verbose=args.verbose)
    except Exception as e:  # noqa: BLE001
        _say(f"restore failed: {e}; trying rescue commands")
        kscreen.apply(layout.rescue_commands(cfg), verbose=args.verbose)
    state.clear(spath)
    _say("rescue completed")
    return 0


def cmd_status(args) -> int:
    st = state.load(state.state_path())
    active = proc.hold_active()
    if st:
        req = st.request
        _say(f"session: {st.virtual_output} at {req['width']}x{req['height']}"
             f"@{req['fps']}, hold unit {'active' if active else 'DEAD'}")
    else:
        _say(f"no session; hold unit {'active (stray!)' if active else 'inactive'}")
    snap = kscreen.snapshot()
    for o in layout.outputs(snap):
        mode = layout.current_mode(o) or {}
        _say(f"  {o['name']}: "
             f"{'enabled' if o.get('enabled') else 'disabled'}"
             f" priority={o.get('priority')} mode={mode.get('name', '?')}")
    return 0


def cmd_hold(args) -> int:
    with open(args.edid, "rb") as f:
        edid = f.read()
    return evdi.hold(edid)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="proteo",
                                description="Client-matched virtual displays "
                                            "for Sunshine/Apollo on KDE Wayland")
    p.add_argument("--version", action="version", version=f"proteo {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("do", help="create the client-matched virtual display")
    sub.add_parser("undo", help="tear down and restore physical displays")
    sub.add_parser("status", help="show session and output state")
    sub.add_parser("rescue", help="force-restore physical displays (emergency)")
    hold = sub.add_parser("_hold")  # internal: EVDI connection holder
    hold.add_argument("--edid", required=True)

    args = p.parse_args(argv)
    handler = {"do": cmd_do, "undo": cmd_undo, "status": cmd_status,
               "rescue": cmd_rescue, "_hold": cmd_hold}[args.cmd]
    try:
        return handler(args)
    except Exception as e:  # noqa: BLE001 — prep_cmd needs a clean exit code
        _say(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
