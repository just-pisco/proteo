# Proteo

[![Release](https://img.shields.io/github/v/release/just-pisco/proteo)](https://github.com/just-pisco/proteo/releases/latest)
[![License: MIT](https://img.shields.io/github/license/just-pisco/proteo)](LICENSE)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-buy%20me%20a%20coffee-ff5f5f?logo=ko-fi&logoColor=white)](https://ko-fi.com/italopiscopiello)

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

If you stream Steam Big Picture: the Steam client intermittently ignores
`steam://open/bigpicture` (especially right after a `steam://close/bigpicture` and
around display reconfigurations — i.e. at every reconnect), so Sunshine's stock
one-shot launch can leave you staring at a bare desktop. `contrib/steam-bigpicture.sh`
re-asserts the URL until the Big Picture window actually exists; point the app's
detached command at it in `apps.json`:

```json
{
  "name": "Steam Big Picture",
  "detached": ["/home/YOU/.local/bin/steam-bigpicture.sh"],
  "prep-cmd": [{"do": "", "undo": "setsid steam steam://close/bigpicture"}],
  "image-path": "steam.png"
}
```

Defaults live in `/etc/proteo/config.toml` (override per-user in
`~/.config/proteo/config.toml`). While a stream is active your physical screens go
dark by design (`physical_during_stream = "disable"`); they are restored when the
stream ends — or automatically by the `proteo-guard` failsafe if anything crashes or
the machine suspends. Emergency restore, also over SSH: `proteo rescue`.

## Keeping game settings per screen

A virtual display at the client's resolution has a side effect: the game reconfigures
*itself* for that screen and keeps those settings when you come back to the desk. RDR2
runs borderless, follows whatever display it finds, and writes the result to its own
config — so a session on the TV leaves a 1920x1080 window on a 32:9 monitor.

There is nothing to set up per game. With Steam closed:

```sh
proteo profiles hook          # every installed game; or pass specific app ids
```

From then on `proteo-guard` keeps it up to date on its own: whenever Steam has been
closed for a moment it picks up games you have installed since. Steam keeps this
config in memory and rewrites it on exit, so the hook only works while Steam is
closed — it refuses to run otherwise rather than make an edit Steam would silently
revert. Existing launch options are preserved (the wrapper is inserted just before
`%command%`, so `WINEDLLOVERRIDES=... %command%` keeps working), the file is backed
up before every write, and `proteo profiles hook --remove` undoes it.

If you prefer to do it by hand, the equivalent launch option is
`proteo profile -- %command%`, and `profile_hook_auto = false` stops the guard from
touching Steam's config.

From then on proteo keeps one copy of that game's settings per screen shape
(`5120x1440`, `1920x1080`, …) and swaps the right one in at launch. The same rule
covers Sunshine+proteo, Steam Remote Play and simply plugging in another monitor —
the key is the screen, not how the pixels travel.

Nothing is declared by hand: proteo watches which files the game changes around a
session and learns. It is deliberately slow to trust them — a file is only swapped
once **two different screens have been seen to hold different content** for it, so
the first session on a new display only observes, and files a game rewrites
identically every launch (launcher manifests, update metadata) are never swapped.

Save games are kept out of range by construction: only configuration file extensions
are eligible, and any path containing `save`, `profile`, `cloud` and friends is
excluded — for RDR2 that is exactly the line between `Settings/system.xml` (tracked)
and `Profiles/` (never touched). Every swap is preceded by a rotating backup under
`~/.local/share/proteo/profiles/<appid>/backups/`.

```sh
proteo profiles list              # games with learned profiles
proteo profiles show 1174180      # what is swapped, observed, ignored
proteo profiles promote 1174180 <path>   # start swapping a file proteo left alone
proteo profiles forget 1174180    # delete everything learned for a game
```

If anything goes wrong the game still launches, unchanged. Set
`profiles_enabled = false` to turn the feature off entirely.

## Status

**0.1.1.** Working end-to-end in real Moonlight sessions: client-matched virtual
display, exact restore, crash/suspend failsafes, .deb packaging. HDR on the virtual
display is currently impossible upstream — the evdi kernel module lacks the DRM
HDR connector properties KWin requires (details in `AGENTS.md`). See `CHANGELOG.md`
for history.

## Support

If Proteo saved you an evening of resolution juggling, you can
[buy me a coffee on Ko-fi](https://ko-fi.com/italopiscopiello). ☕

## License

MIT.
