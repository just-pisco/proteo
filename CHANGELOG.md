# Changelog

All notable changes to Proteo will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Per-display game settings profiles** (`proteo profile -- %command%`, used as
  a Steam launch option). A game started on a client-matched virtual display
  reconfigures itself for that screen and leaves those settings behind for the
  desk monitor — the counterpart problem to the one the virtual display solves.
  Proteo now keeps one copy of a game's configuration per display shape and
  swaps the right one in at launch.
  - Profiles are keyed on **display geometry** (`5120x1440`, `1920x1080`), not
    on the streaming mechanism, so the same rule covers Sunshine+proteo, Steam
    Remote Play and simply plugging in another monitor.
  - Which files belong to a profile is **learned**, not declared: the wrapper
    fingerprints the game's config scope around each session. A Proton game's
    scope is its own prefix; a native game gets only the XDG directories whose
    name matches it (never `~/.config` wholesale).
  - A file is swapped only once **two display shapes have been seen to hold
    different content** for it. Files a game rewrites identically on every
    launch — launcher component manifests, update metadata — are observed but
    never swapped, so proteo cannot make them regress.
  - Save data is kept out of range by an allow-list of configuration
    extensions plus a path-word exclusion list (`save`, `profile`, `cloud`, …),
    and every swap is preceded by a rotating backup (`profile_backups_kept`).
  - `proteo profiles list|show|promote|forget` to inspect and correct what was
    learned; `profiles_enabled = false` turns the whole thing off.
  - **No per-game setup**: `proteo profiles hook` writes the wrapper into
    Steam's launch options for every installed game, and `proteo-guard`
    re-applies it to newly installed games whenever Steam has been closed for
    `profile_hook_delay_seconds`. Steam rewrites `localconfig.vdf` as it exits,
    so the hook refuses to run while Steam is up rather than making an edit
    that would be silently reverted.
  - `core/steamvdf.py` is a KeyValues reader/writer that round-trips a real
    `localconfig.vdf` byte for byte, so editing one leaf leaves the other
    thousands of keys untouched. The wrapper is inserted immediately before
    `%command%`, never at the front, so an existing
    `WINEDLLOVERRIDES=... %command%` keeps working. A rotating backup of the
    file is taken before every write, and proteo never deletes a key from it.
  - The wrapper never blocks a launch: any failure in profile handling is
    reported and the game starts unchanged, with the child's exit code and
    termination signals forwarded through.

### Changed
- Phase 4 (HDR) feasibility probe: **blocked upstream**. The evdi kernel module
  (1.14.15) does not expose the `Colorspace`/`HDR_OUTPUT_METADATA` DRM connector
  properties, so KWin cannot drive the virtual output in HDR no matter what EDID it
  gets (`kscreen-doctor -j`: no `hdr` key on DVI-I-1; DP-2 has `hdr: true`).
  Documented in `AGENTS.md`; `hdr_enabled` stays as a reserved opt-in. The unlock is
  an upstream evdi patch, tracked as a possible future contribution.

## [0.1.1] - 2026-07-06

### Fixed
- **Multi-second stream lag**: the EVDI holder held the connector but never
  consumed frames, so KWin's page flips on the virtual output never completed
  promptly — compositing fell behind and every KWin-ScreenCast frame Sunshine
  captured arrived late (fluid metadata cursor, hugely delayed UI reactions:
  the reported "click lag"). The holder now registers a framebuffer and drains
  updates (`evdi_request_update`/`evdi_grab_pixels`, the Phase-0 spike client's
  behavior — a protocol obligation, not an optimization). Measured ~58 fps
  drained on a 60 Hz 2340x1080 mode under animation, ~11% of one CPU core.
- Steam Big Picture opening *behind* the desktop (start sound audible, desktop
  shown): KWin focus-stealing prevention keeps windows spawned by background
  processes below; `contrib/steam-bigpicture.sh` now force-activates the Big
  Picture window via KWin scripting once it appears.
- First real Moonlight session showed a frozen desktop with an invisible cursor while
  audio proved the app was running. Diagnosis: Proteo/KWin were fine (a screenshot
  confirmed Steam Big Picture rendering full-screen on the virtual output); the fault
  was Sunshine's default **KMS capture**, which cannot read from the EVDI device (no
  render node → `No render device name for /dev/dri/cardX`, frozen first frame; cursor
  on a separate hardware plane → `Cursor plane spans multiple CRTCs!`). Fix: set
  `capture = kwin` in `sunshine.conf` — the KWin ScreenCast backend streams
  compositor-rendered frames via PipeWire (DMA-BUF), cursor included. Verified:
  kwingrab binds `zkde_screencast_unstable_v1` via Sunshine's shipped permission file
  and encoder validation passes (h264/hevc_vulkan on RADV). Documented in `README.md`
  and `AGENTS.md`.
- Heavy stream latency with `capture = kwin`: Sunshine's encoder auto-probe selected
  Vulkan video encode (h264_vulkan on RADV) instead of VAAPI. Fixed with
  `encoder = vaapi` in `sunshine.conf` (h264/hevc_vaapi on radeonsi validated).
- Verified via KWin scripting that Steam Big Picture lands fullscreen on the virtual
  output in both flows (cold start ~45 s; warm reopen after Sunshine's
  `steam://close/bigpicture` undo ~15 s) — "Steam never appears" reports were the
  client disconnecting before Steam finished starting, compounded by the encoder lag.
- Field validation of the guard: Sunshine hung at session teardown
  (`Fatal: Hang detected!`) and crashed without running `proteo undo`; proteo-guard
  detected the dead host and restored the physical displays automatically.

### Added
- `contrib/steam-bigpicture.sh`: watchdog launcher for Sunshine's "Steam Big Picture"
  app. The Steam client intermittently ignores `steam://open/bigpicture` (a pre-existing
  upstream flakiness, unrelated to Proteo — every server-side flow replication
  succeeded, including simultaneous `close/bigpicture` + `proteo undo` and immediate
  reconnect), and Sunshine fires the URL once, blind. The watchdog re-asserts it until
  the Big Picture window exists on Xwayland (up to ~2 min, covering Steam cold start).

## [0.1.0] - 2026-07-05

### Added
- Phase 3 — Debian packaging: `proteo_0.1.0_all.deb` (debhelper 13 + pybuild from
  pyproject). Ships `/usr/bin/proteo`, the `proteo-guard` user unit (auto-enabled via
  deb-systemd-helper), `/etc/proteo/config.toml` with documented defaults, and
  modules-load.d/modprobe.d so evdi is ready at boot. Depends on
  `linux-modules-evdi-generic | evdi-dkms`, `libevdi1`, `libkscreen-bin`, `python3-gi`.
  MIT license.
- Phase 2 — `proteo guard` failsafe daemon (`proteo-guard.service`, enabled): 1 s
  reconciliation polling with 2-poll debounce; auto-restores physical displays when the
  streaming host stops or the EVDI holder dies; login1 sleep delay-inhibitor with
  teardown on PrepareForSleep and re-arm on resume; orphan check on guard shutdown.
  Live-tested: holder SIGKILL, host stop mid-session, reshape false-positive immunity.
  Suspend/resume cycle still needs a manual test.
- Phase 1 — `proteo` Python package: headless `core/` (CVT-RB EDID generation with DTD
  pixel-clock ceiling handling, `SUNSHINE_CLIENT_*` parsing with clamping, TOML config,
  kscreen layout planning, atomic session state) plus `adapters/` (kscreen-doctor JSON,
  libevdi via ctypes, hold process as transient systemd user unit) and the
  `proteo do|undo|status|rescue` CLI. 31 core unit tests.
- Phase 1 E2E verified live on KWin: do (3120x1440@120), idempotent double-do, reshape
  (1280x800@60), undo with exact DP-2 restore, full disable-physical cycle, and rescue
  after simulated state loss.
- Host integration: Sunshine v2026.516 (official Ubuntu 26.04 .deb) installed as the
  systemd user service `app-dev.lizardbyte.app.Sunshine.service`, with proteo hooked
  into `global_prep_cmd`; verified proteo runs correctly from a systemd service
  environment. Awaiting first real Moonlight session test.
- Project scaffolding: `AGENTS.md` (single source of truth), `CLAUDE.md`/`GEMINI.md`
  pointers, this changelog, public `README.md`.
- Phase-0 spike tools: `spike/make_edid.py` (parametric CVT-RB EDID generator,
  edid-decode conformity PASS) and `spike/evdi_client.c` (EVDI client with pixel-grab
  content proof).

### Phase 0 decision gate — PASSED (2026-07-05)
- KWin (Plasma 6, Wayland, RX 6900 XT) **adopts an externally-created EVDI output
  automatically**: connector appears on `evdi_connect()`, is auto-enabled at the EDID
  preferred mode, and KWin demonstrably renders into it (pixel grab: 8,294,397/8,294,400
  non-zero bytes). Priority (primary display) is scriptable via kscreen-doctor; teardown
  restores the physical monitor exactly. **Road A (external daemon) confirmed.**
  Full details and reproduction steps in `AGENTS.md` → "Spike results".
