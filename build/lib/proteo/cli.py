"""proteo CLI — do / undo / status / rescue / profile / profiles (+ hidden _hold).

do/undo contract (AGENTS.md): `do` reads SUNSHINE_CLIENT_*, brings up the
virtual output at that format and makes it the stream target; `undo` tears it
down and restores the physical configuration. Both are idempotent and safe to
call in any order.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict

from . import __version__
from .adapters import evdi, gamefiles, kscreen, proc
from .core import guard, layout, profiles, state
from .core.config import Config, load_config
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


def cmd_guard(args) -> int:
    """Failsafe daemon: restores physical displays when the session is
    orphaned (host crashed, holder died) or the machine is about to sleep."""
    # GLib/Gio only here: the plain CLI must not depend on a main loop
    from gi.repository import GLib

    from .adapters import logind

    cfg = load_config()
    spath = state.state_path()
    debouncer = guard.Debouncer(cfg.guard_debounce)

    def observe() -> guard.Observation:
        return guard.Observation(
            session=state.load(spath) is not None,
            hold_active=proc.hold_active(),
            host_active=proc.unit_active(cfg.host_unit))

    def restore(reason: str) -> None:
        _say(f"guard: restoring physical displays — {reason}")
        res = subprocess.run([sys.executable, "-m", "proteo", "undo"],
                             capture_output=True, text=True)
        for line in (res.stdout + res.stderr).splitlines():
            print(f"  {line}", flush=True)
        if res.returncode != 0:
            _say("guard: undo failed, attempting rescue")
            subprocess.run([sys.executable, "-m", "proteo", "rescue"])

    def tick() -> bool:
        reason = guard.decide(observe())
        if debouncer.update(reason is not None):
            restore(reason or "invariant violated")
        return True  # keep the timer

    inhibitor = {"fd": -1}

    def arm_inhibitor(bus) -> None:
        if inhibitor["fd"] < 0:
            inhibitor["fd"] = logind.take_sleep_inhibitor(
                bus, "restoring physical displays before sleep")

    def on_sleep(bus, going_to_sleep: bool) -> None:
        if going_to_sleep:
            if state.load(spath) is not None:
                restore("system is suspending")
            if inhibitor["fd"] >= 0:       # release: let the system sleep
                os.close(inhibitor["fd"])
                inhibitor["fd"] = -1
        else:
            arm_inhibitor(bus)             # re-arm after resume

    try:
        bus = logind.system_bus()
        arm_inhibitor(bus)
        logind.on_prepare_for_sleep(bus, lambda going: on_sleep(bus, going))
        _say("guard: sleep inhibitor armed")
    except Exception as e:  # noqa: BLE001 — keep guarding even without logind
        _say(f"guard: WARNING: no sleep integration ({e}); polling only")

    loop = GLib.MainLoop()
    GLib.timeout_add(cfg.guard_poll_seconds * 1000, tick)
    for sig in (2, 15):  # SIGINT, SIGTERM
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, lambda *_: loop.quit())
    _say(f"guard: watching {cfg.host_unit} and {proc.UNIT} "
         f"every {cfg.guard_poll_seconds}s")
    loop.run()

    # on shutdown of the guard itself: restore immediately if orphaned
    reason = guard.decide(observe())
    if reason:
        restore(reason)
    _say("guard: stopped")
    return 0


def cmd_hold(args) -> int:
    with open(args.edid, "rb") as f:
        edid = f.read()
    return evdi.hold(edid)


class _ProfileSession:
    """Swaps a game's settings to match the current display, then learns from
    what the game wrote on the way out.

    Every method is failure-tolerant on purpose: this code sits between Steam
    and the game's executable, so a bug here must cost a profile, never a
    launch. Anything unexpected disables the session and the game still runs.
    """

    def __init__(self, cfg: Config, env: dict[str, str], command: list[str],
                 verbose: bool):
        self.cfg = cfg
        self.env = env
        self.command = command
        self.verbose = verbose
        self.active = False
        self.app = ""
        self.key = ""
        self.scope: list = []
        self.manifest: profiles.Manifest | None = None
        self.before: dict = {}

    def begin(self) -> None:
        if not self.cfg.profiles_enabled:
            return
        self.app = gamefiles.app_id(self.env) or ""
        if not self.app:
            _say("profile: no Steam app id in the environment; passing through")
            return
        self.scope = gamefiles.roots(
            self.env, self.cfg, gamefiles.name_hints(self.env, self.command))
        if not self.scope:
            _say(f"profile: no config scope found for app {self.app}; passing through")
            return
        self.key = profiles.display_key(kscreen.snapshot())
        self.manifest = (profiles.manifest_load(
            profiles.manifest_path(self.app, self.env))
            or profiles.Manifest(app_id=self.app))
        if not self.manifest.name:
            self.manifest.name = self._guess_name()
        self.manifest.roots = [r.label for r in self.scope]
        self.active = True
        self._install()
        self.before = gamefiles.scan(self.scope, self.cfg)

    def _guess_name(self) -> str:
        install = (self.env.get("STEAM_COMPAT_INSTALL_PATH") or "").strip()
        return os.path.basename(install.rstrip("/")) if install else ""

    def _install(self) -> None:
        """Bring in the profile stored for this display shape, if we have one.

        When there is none, the game keeps whatever it last wrote and configures
        itself for the new screen — which is precisely the state we want to
        capture on the way out as this shape's first profile.
        """
        assert self.manifest is not None
        source = profiles.key_dir(self.app, self.key, self.env)
        stored = set(gamefiles.stored_keys(source))
        swappable = [f for f in self.manifest.files if f in stored]
        if not swappable:
            _say(f"profile: nothing to restore for {self.key} yet — "
                 f"observing this launch")
            return
        self._backup(swappable)
        restored = gamefiles.copy_in(swappable, self.scope, source)
        _say(f"profile: restored {len(restored)} file(s) for {self.key}")

    def _backup(self, keys: list[str]) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = profiles.backup_dir(self.app, stamp, self.env)
        gamefiles.copy_out(keys, self.scope, dest)
        gamefiles.prune_backups(self.app, self.cfg.profile_backups_kept, self.env)

    def finish(self) -> None:
        """Learn what the game changed, then store it as this shape's profile."""
        if not self.active or self.manifest is None:
            return
        after = gamefiles.scan(self.scope, self.cfg)
        changed = profiles.changed_paths(self.before, after)
        observed, ignored = profiles.classify(changed, self.cfg)
        if self.verbose and ignored:
            _say(f"profile: ignored {len(ignored)} changed file(s) "
                 f"(not configuration, or excluded)")
        self.manifest.learn(observed, ignored)

        # store this shape's copy of everything watched, then let the evidence
        # across shapes decide what is actually display-dependent
        saved = gamefiles.copy_out(self.manifest.watched, self.scope,
                                   profiles.key_dir(self.app, self.key, self.env))
        digests = gamefiles.digests_by_display_key(self.app, self.env)
        promoted = self.manifest.promote(
            profiles.discriminating(digests) & set(self.manifest.watched))
        profiles.manifest_save(self.manifest,
                               profiles.manifest_path(self.app, self.env))

        _say(f"profile: saved {len(saved)} file(s) for {self.key}; "
             f"{len(self.manifest.files)} swapped, "
             f"{len(self.manifest.candidates)} still observed"
             + (f" (+{len(promoted)} newly swapped)" if promoted else ""))


def _run_child(command: list[str]) -> int:
    """Run the game, forwarding termination signals so Steam's Stop button
    still reaches it through this wrapper."""
    child = subprocess.Popen(command)
    previous = {}

    def forward(signum, _frame):
        child.send_signal(signum)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        previous[sig] = signal.signal(sig, forward)
    try:
        code = child.wait()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    # a child killed by signal reports a negative code; Steam wants a real one
    return code if code >= 0 else 128 - code


def cmd_profile(args) -> int:
    """Launch wrapper for Steam launch options: `proteo profile -- %command%`."""
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        _say("ERROR: nothing to launch — use: proteo profile -- %command%")
        return 2

    cfg = load_config()
    env = dict(os.environ)
    session = _ProfileSession(cfg, env, command, args.verbose)
    try:
        session.begin()
    except Exception as e:  # noqa: BLE001 — a profile is never worth a failed launch
        _say(f"profile: WARNING: setup failed ({e}); launching unchanged")
        session.active = False

    try:
        return _run_child(command)
    finally:
        try:
            session.finish()
        except Exception as e:  # noqa: BLE001 — the game already exited; just report
            _say(f"profile: WARNING: could not save profile ({e})")


def cmd_profiles(args) -> int:
    env = dict(os.environ)
    if args.action == "list":
        root = profiles.store_dir(env)
        games = sorted(d for d in root.iterdir() if d.is_dir()) \
            if root.is_dir() else []
        if not games:
            _say("no game profiles learned yet")
            return 0
        for game in games:
            manifest = profiles.manifest_load(game / "manifest.json")
            keys = sorted(k.name for k in (game / "keys").iterdir()) \
                if (game / "keys").is_dir() else []
            name = (manifest.name if manifest and manifest.name else "?")
            _say(f"{game.name} ({name}): "
                 f"{len(manifest.files) if manifest else 0} file(s), "
                 f"profiles for {', '.join(keys) or 'none'}")
        return 0

    manifest = profiles.manifest_load(profiles.manifest_path(args.app_id, env))
    if manifest is None:
        _say(f"no profiles for app {args.app_id}")
        return 1

    if args.action == "show":
        _say(f"{manifest.app_id} ({manifest.name or '?'}) roots={manifest.roots}")
        for key in manifest.files:
            _say(f"  swapped:  {key}")
        for key in manifest.candidates:
            _say(f"  observed: {key}")
        for key in manifest.ignored:
            _say(f"  ignored:  {key}")
        keys_dir = profiles.game_dir(args.app_id, env) / "keys"
        for key in sorted(keys_dir.iterdir()) if keys_dir.is_dir() else []:
            _say(f"  profile {key.name}: "
                 f"{len(gamefiles.stored_keys(key))} file(s)")
        return 0

    if args.action == "promote":
        if args.path not in manifest.candidates + manifest.ignored:
            _say(f"{args.path} is neither observed nor ignored for this game")
            return 1
        manifest.promote({args.path})
        profiles.manifest_save(manifest, profiles.manifest_path(args.app_id, env))
        _say(f"{args.path} will be swapped from the next launch")
        return 0

    if args.action == "forget":
        shutil.rmtree(profiles.game_dir(args.app_id, env), ignore_errors=True)
        _say(f"forgot every profile for app {args.app_id}")
        return 0
    return 1


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
    sub.add_parser("guard", help="failsafe daemon (run via proteo-guard.service)")
    profile = sub.add_parser(
        "profile",
        help="launch wrapper keeping game settings per display "
             "(Steam launch options: proteo profile -- %%command%%)")
    profile.add_argument("command", nargs=argparse.REMAINDER)
    manage = sub.add_parser("profiles", help="inspect and edit learned profiles")
    actions = manage.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="games with learned profiles")
    for name, helptext in (("show", "tracked files and stored profiles"),
                           ("forget", "delete every profile for a game")):
        one = actions.add_parser(name, help=helptext)
        one.add_argument("app_id")
    promote = actions.add_parser(
        "promote", help="start swapping a file proteo is only observing")
    promote.add_argument("app_id")
    promote.add_argument("path")
    hold = sub.add_parser("_hold")  # internal: EVDI connection holder
    hold.add_argument("--edid", required=True)

    args = p.parse_args(argv)
    handler = {"do": cmd_do, "undo": cmd_undo, "status": cmd_status,
               "rescue": cmd_rescue, "guard": cmd_guard, "_hold": cmd_hold,
               "profile": cmd_profile, "profiles": cmd_profiles}[args.cmd]
    try:
        return handler(args)
    except Exception as e:  # noqa: BLE001 — prep_cmd needs a clean exit code
        _say(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
