# Proteo — AGENTS.md (single source of truth)

Proteo (after Proteus, the shape-shifting sea god) creates a **client-matched virtual
display** for Sunshine/Apollo game streaming on **KDE Plasma Wayland + AMD**. When a
Moonlight client starts a stream, Proteo spins up a virtual output at the client's exact
resolution/refresh rate, makes it the stream target, and tears it down afterwards,
restoring the physical monitors. This replicates what Apollo does on Windows via SudoVDA,
which is Windows-only.

**All agent instructions live here.** `CLAUDE.md` and `GEMINI.md` only point to this file.
Keep this file updated when architecture or decisions change.

## Environment (verify, never assume)

- OS: Kubuntu 26.04 LTS, KDE Plasma 6, KWin **Wayland**. User `pisco`, host `nauta`.
- Kernel: 7.0.x-generic (check `uname -r`; DKMS modules must build against it).
- GPU: AMD Radeon RX 6900 XT (RDNA2), amdgpu driver, VAAPI encoding.
- Physical monitor: 32:9 ultrawide, 5120x1440@240Hz HDR, on connector **DP-2**.
- `kscreen-doctor` available at `/usr/bin/kscreen-doctor`.
- `evdi-dkms` 1.14.15 available in Ubuntu repos (not installed by default).
- Apollo/Sunshine runs (or will run) as a `systemd --user` service.

## Strategy decision

Two possible roads were analyzed:

- **Road A (CHOSEN): external decoupled daemon.** No changes to Apollo's C++ code. Talks
  to the host only through the `SUNSHINE_CLIENT_WIDTH/HEIGHT/FPS/HDR` env vars passed to
  `global_prep_cmd` (stable API) and to KWin via kscreen-doctor/output-management.
  Survives Apollo updates without rebasing, works with both Sunshine and Apollo, packages
  cleanly as a .deb. Smallest maintenance surface for a single maintainer.
  Living reference (study, don't copy blindly): `frostplexx/sunshine_virt_display`.
- **Road B (rejected unless the gate fails): fork of Apollo with native virtual display**
  (EVDI/Hermes-KMS in the C++). Windows-like UX, but requires rebasing every release and
  maintaining a kernel module → fork-rot risk. Only durable if patches land upstream.
  References: `Sgtmetalmex/Apollo-CachyOS` (~19 EVDI+kwin patches, AMD),
  `MrOz59/Apollo-Linux`, `MrOz59/Hermes`.

## Phase 0 decision gate (MANDATORY before any daemon code)

The critical unknown is not host code — it's whether **KWin actually adopts an
externally-created virtual output** (enables it, renders into it) instead of leaving it
disabled. The Apollo-CachyOS fork had to patch C++ because kscreen-doctor alone wasn't
enough from outside. On this 6900 XT + KWin combo the answer is unknown a priori.

Spike protocol:
1. Manually create a virtual output (EVDI; document exact commands).
2. Check `kscreen-doctor -o`: does KWin see it? Enable it, set an arbitrary mode, verify
   KWin genuinely renders into it (content check, not just "enabled" state).
3. Outcome:
   - KWin adopts it from outside → proceed with Road A;
   - KWin refuses → STOP and report: the durable path becomes a PR to
     Hermes/Apollo-Linux, not an external daemon.

Record the outcome in `CHANGELOG.md` and in the "Spike results" section below.
**Do not start Phase 1 without explicit user confirmation.**

### Spike results (2026-07-05) — **GATE PASSED → Road A confirmed**

Environment as verified: Kubuntu 26.04, kernel 7.0.0-27-generic, Plasma/KWin Wayland,
RX 6900 XT on DP-2 (5120x1440@120 at test time, HDR on). Secure Boot disabled, but the
signed prebuilt module was used anyway (no DKMS needed).

Exact reproduction steps:

```sh
sudo apt-get install -y linux-modules-evdi-generic libevdi1 libevdi-dev
sudo modprobe evdi initial_device_count=1        # -> /dev/dri/card0 (evdi)
cd spike
python3 make_edid.py 1920 1080 60 -o edid-1920x1080-60.bin   # edid-decode: PASS
gcc -Wall -O2 -o evdi_client evdi_client.c -levdi
./evdi_client edid-1920x1080-60.bin               # keep running during the session
```

Findings, in decision order:

1. **KWin adopts the output from outside, fully and automatically.** As soon as
   `evdi_connect()` supplied the EDID, a `DVI-I-1` connector appeared and KWin
   auto-enabled it at the EDID's preferred mode (1920x1080@59.93 CVT-RB), extending the
   desktop at 4096,0. No kscreen-doctor `enable` was even needed. KWin immediately
   modeset the device (client received `mode_changed 1920x1080@60`, ARGB8888).
2. **Content proof, not just state:** the client's `evdi_request_update` +
   `evdi_grab_pixels` returned 8,294,397/8,294,400 non-zero bytes once a window caused
   damage on the virtual screen → KWin genuinely renders into it. Note: KWin only
   presents frames on damage; a static, untouched screen can legitimately grab as black.
3. **Priority is scriptable from outside:** `kscreen-doctor output.DVI-I-1.priority.1`
   made the virtual output primary; reverting worked identically.
4. **Teardown is clean:** SIGTERM → `evdi_disconnect()` → connector disappears; DP-2
   came back exactly as snapshotted (enabled, priority 1, 5120x1440@120, HDR on).
5. **The evdi client process must stay alive for the whole session** — the connector
   exists only while a client holds the connection. The daemon therefore owns a
   long-running child (or thread) per virtual display.
6. Permissions: logind grants the seat user an rw ACL on evdi's `/dev/dri/cardX`
   automatically — the daemon needs no root at runtime. Root is only needed once for
   module install/load (`modprobe evdi initial_device_count=1`; make it persistent via
   `/etc/modules-load.d/` + `/etc/modprobe.d/` in the .deb).
7. No native KWin DBus API for virtual outputs exists (checked `org.kde.KWin` on this
   Plasma version), so EVDI remains the right mechanism.

## Architecture (Road A)

- `core/` — deterministic and headless, no graphical-environment dependencies, testable
  in isolation: env-var parsing, output-slot selection, EDID generation, session state
  machine (`idle → active → restoring`).
- `adapters/` — everything that touches the world: kscreen-doctor/KWin DBus, EVDI device
  management, systemd/login1 DBus. Thin, replaceable, kept out of core's tests.
- Automated tests on `core/` (no display server required).

## do/undo contract

- `do`: reads `SUNSHINE_CLIENT_WIDTH/HEIGHT/FPS/HDR`, creates/enables the virtual output
  at that format, makes it primary/the stream target. Idempotent: a second `do` must not
  create a second display.
- `undo`: tears the virtual output down and restores the physical monitor configuration
  exactly as it was. Safe to call without a prior `do` (no-op that still restores).

## Robustness requirements (this is 70% of the project's value)

- Watch the Sunshine/Apollo systemd user service via DBus: if it goes
  `inactive`/`failed`, restore physical monitors automatically, no manual intervention.
- Sleep inhibitor (`org.freedesktop.login1`): on suspend tear down the virtual output, on
  resume restore — never leave the session stuck on a dead virtual display.
- Teardown also on SIGTERM/shutdown; persist session state to disk for post-crash
  recovery.
- HDR is OUT of scope until everything else is solid; then opt-in via config only
  (notoriously unstable on virtual displays).
- No hard-coding: physical resolution, output name, user — all from config.

## Emergency escape hatch

If the screen is ever stuck on a broken virtual output, SSH into `nauta` and run:

```sh
# force-restore the physical monitor (works even with the daemon wedged):
kscreen-doctor output.DP-2.enable output.DP-2.mode.5120x1440@240 output.DP-2.priority.1
# then, if a virtual output lingers, disable it:
kscreen-doctor -o        # find the virtual output name
kscreen-doctor output.<VIRTUAL_NAME>.disable
# nuclear option — unload the virtual display kernel module:
sudo modprobe -r evdi
```

Once Phase 2 lands, `proteo rescue` wraps all of this in one command.

## Build / test / install

_To be filled in Phase 1 (core+adapter) and Phase 3 (.deb packaging)._

## Way of working

- Phased plan: 0 = spike (gate), 1 = core+adapter, 2 = robustness/failsafe,
  3 = .deb packaging, 4 = optional HDR. Each phase needs user confirmation.
- Update `CHANGELOG.md` (Keep a Changelog + SemVer) at every step.
- Small, descriptive commits.
