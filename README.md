# Proteo

**Client-matched virtual displays for Sunshine/Apollo game streaming on KDE Plasma
Wayland + AMD.**

Named after Proteus, the shape-shifting sea god: your display takes whatever form the
client asks for.

## The problem

You stream games from your Linux PC with [Sunshine](https://github.com/LizardByte/Sunshine)
or [Apollo](https://github.com/ClassicOldSong/Apollo) to a phone, tablet or TV — and the
stream is stuck in your desktop monitor's shape. With a 32:9 ultrawide host and a 16:9 or
20:9 client, every session starts with manual resolution juggling and ends with a
misconfigured desktop.

On Windows, Apollo solves this automatically with SudoVDA: a virtual display is created
at the client's exact resolution and refresh rate for the duration of the stream. That
component is Windows-only. Proteo brings the same behavior to Linux:

- when a Moonlight client connects, a **virtual output is created at the client's
  requested resolution/refresh rate** and becomes the stream target;
- when the stream ends (or crashes, or the machine suspends), the virtual output is torn
  down and your **physical monitor configuration is restored automatically**.

## Scope

Proteo deliberately targets a niche that existing tools leave uncovered:

- **KDE Plasma 6 on Wayland** (KWin output management via kscreen-doctor/DBus);
- **AMD GPUs** (developed on RDNA2 / RX 6900 XT with VAAPI encoding);
- works with **both Sunshine and Apollo** — it hooks in via the stable
  `global_prep_cmd` interface and `SUNSHINE_CLIENT_*` env vars, no fork, no patches.

If you're on Hyprland/wlroots or NVIDIA, other solutions may serve you better.

## Install

Build and install the .deb (Ubuntu 25.10+/26.04, KDE Plasma 6 Wayland):

```sh
sudo apt install debhelper dh-python python3-all python3-setuptools pybuild-plugin-pyproject
dpkg-buildpackage -us -uc -b
sudo apt install ../proteo_*_all.deb
sudo modprobe evdi initial_device_count=1   # loaded automatically from next boot
systemctl --user start proteo-guard.service # started automatically from next login
```

Hook it into Sunshine (`~/.config/sunshine/sunshine.conf`):

```
global_prep_cmd = [{"do":"/usr/bin/proteo do","undo":"/usr/bin/proteo undo","elevated":"false"}]
capture = kwin
encoder = vaapi
```

`capture = kwin` is required: Sunshine's default KMS capture cannot read from the EVDI
virtual device (it has no render node), producing a frozen frame and an invisible
cursor. The KWin ScreenCast backend (`kwin`) captures compositor-rendered frames over
PipeWire, cursor included; the needed KWin permission file ships with Sunshine's .deb.
If `kwin` is unavailable in your build, `capture = portal` is the fallback.
`encoder = vaapi` avoids Sunshine auto-picking the immature Vulkan encoder on AMD/RADV,
which caused heavy stream latency.

Defaults live in `/etc/proteo/config.toml` (override per-user in
`~/.config/proteo/config.toml`). While a stream is active your physical screens go
dark by design (`physical_during_stream = "disable"`); they are restored when the
stream ends — or automatically by the `proteo-guard` failsafe if anything crashes or
the machine suspends. Emergency restore, also over SSH: `proteo rescue`.

## Status

**0.1.0.** Working end-to-end: client-matched virtual display, exact restore,
crash/suspend failsafes, .deb packaging. HDR is planned (opt-in) but not implemented.
See `CHANGELOG.md` for details and `AGENTS.md` for the full design.

## License

MIT.
