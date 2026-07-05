# Changelog

All notable changes to Proteo will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
