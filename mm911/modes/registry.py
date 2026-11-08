"""Game modes: one place that maps cfg.mode to its simulation and renderer.
Every mode shares MergeConfig (mode-specific settings are prefixed: escape_*, breaker_*, glass_*), the export
pipeline, sounds, batch, thumbnails and the GUI preview."""
from __future__ import annotations

MODES = {
    "merge": "🍉 Merge Evolution",
    "escape": "🌀 Escape",
    "breaker": "🧱 Breaker",
    "glass": "🥛 Glass Rush",
    "ghost": "👻 Ghost Escape",
    "rhythm": "🎵 Rhythmic",
}


def sim_for(cfg):
    m = getattr(cfg, "mode", "merge")
    if m == "escape":
        from .escape import EscapeSim
        return EscapeSim(cfg)
    if m == "breaker":
        from .breaker import BreakerSim
        return BreakerSim(cfg)
    if m == "rhythm":
        from .rhythm import RhythmSim
        return RhythmSim(cfg)
    if m == "ghost":
        from .ghost import GhostSim
        return GhostSim(cfg)
    if m == "glass":
        from .glass import GlassSim
        return GlassSim(cfg)
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
    if m == "rhythm":
        from ..render_modes import RhythmRenderer
        return RhythmRenderer(cfg, scale)
    if m == "ghost":
        from ..render_modes import GhostRenderer
        return GhostRenderer(cfg, scale)
    if m == "glass":
        from ..render_modes import GlassRenderer
        return GlassRenderer(cfg, scale)
    from ..render import Renderer
    return Renderer(cfg, scale)
