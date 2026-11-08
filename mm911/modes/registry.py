"""Game modes: one place that maps cfg.mode to its simulation and renderer.
Every mode shares MergeConfig (mode-specific settings are prefixed: escape_*, breaker_*), the export
pipeline, sounds, batch, thumbnails and the GUI preview."""
from __future__ import annotations

MODES = {
    "merge": "🍉 Merge Evolution",
    "escape": "🌀 Escape",
    "breaker": "🧱 Breaker",
}


def sim_for(cfg):
    m = getattr(cfg, "mode", "merge")
    if m == "escape":
        from .escape import EscapeSim
        return EscapeSim(cfg)
    if m == "breaker":
        from .breaker import BreakerSim
        return BreakerSim(cfg)
    from .merge import MergeSim
    return MergeSim(cfg)


def renderer_for(cfg, scale: float = 1.0):
    m = getattr(cfg, "mode", "merge")
    if m == "escape":
        from ..render_modes import EscapeRenderer
        return EscapeRenderer(cfg, scale)
    if m == "breaker":
        from ..render_modes import BreakerRenderer
        return BreakerRenderer(cfg, scale)
    from ..render import Renderer
    return Renderer(cfg, scale)
