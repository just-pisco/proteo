"""Client stream request: parsed from the SUNSHINE_CLIENT_* environment
variables that Sunshine/Apollo export to global_prep_cmd (the stable API
this whole project leans on), clamped to configured limits.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .edid import max_fitting_fps


@dataclass(frozen=True)
class StreamRequest:
    width: int
    height: int
    fps: int
    hdr: bool

    @property
    def mode_str(self) -> str:
        return f"{self.width}x{self.height}@{self.fps}"


def _parse_int(raw: str | None, default: int) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _parse_bool(raw: str | None) -> bool:
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def request_from_env(env: dict[str, str], cfg: Config) -> StreamRequest:
    width = _parse_int(env.get("SUNSHINE_CLIENT_WIDTH"), cfg.default_width)
    height = _parse_int(env.get("SUNSHINE_CLIENT_HEIGHT"), cfg.default_height)
    fps = _parse_int(env.get("SUNSHINE_CLIENT_FPS"), cfg.default_fps)
    hdr = _parse_bool(env.get("SUNSHINE_CLIENT_HDR"))

    width = max(cfg.min_width, min(width, cfg.max_width))
    height = max(cfg.min_height, min(height, cfg.max_height))
    fps = max(cfg.min_fps, min(fps, cfg.max_fps))
    # keep multiples of 2: video encoders dislike odd dimensions
    width -= width % 2
    height -= height % 2
    # wide+fast combos can exceed the EDID DTD pixel-clock ceiling: step the
    # refresh down to the fastest encodable value rather than fail
    fps = max_fitting_fps(width, height, fps, cfg.min_fps)

    # HDR is opt-in via config AND requested by the client (Phase 4 turf)
    return StreamRequest(width=width, height=height, fps=fps,
                         hdr=hdr and cfg.hdr_enabled)
