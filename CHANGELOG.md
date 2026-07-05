# Changelog

All notable changes to Proteo will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Phase 4: opt-in HDR support on the virtual display.

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
