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

## Status

⚠️ **Pre-alpha.** Currently in Phase 0: validating that KWin adopts externally-created
virtual outputs on this stack. See `CHANGELOG.md` for progress and `AGENTS.md` for the
full design.

## License

TBD.
