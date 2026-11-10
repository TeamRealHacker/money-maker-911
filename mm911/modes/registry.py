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
    "rhythmic": "🎵 Rhythmic",
    "accumulate": "➕ Accumulate",
    "drawer": "✏️ Drawer",
    "tower": "🏢 Glass Tower",
    "battle": "🚩 Flag Battle",
    "weapon": "⚔️ Weapon Battle",
    "plinko": "🎯 Plinko",
    "race": "🏁 Race",
    "flip": "🔄 Gravity Flip",
    "snake": "🐍 Snake Grow",
    "chain": "💥 Chain Reaction",
    "countdown": "⏳ Countdown Survival",
    "colorsort": "🎨 Color Sort",
    "voting": "🗳️ Voting",
}


def sim_for(cfg):
    m = getattr(cfg, "mode", "merge")
    if m == "escape":
        from .escape import EscapeSim
        return EscapeSim(cfg)
    if m == "breaker":
        from .breaker import BreakerSim
        return BreakerSim(cfg)
    if m == "accumulate":
        from .accumulate import AccumulateSim
        return AccumulateSim(cfg)
    if m == "voting":
        from .voting import VotingSim
        return VotingSim(cfg)
    if m == "colorsort":
        from .colorsort import ColorSortSim
        return ColorSortSim(cfg)
    if m == "countdown":
        from .countdown import CountdownSim
        return CountdownSim(cfg)
    if m == "chain":
        from .chain import ChainSim
        return ChainSim(cfg)
    if m == "snake":
        from .snake import SnakeSim
        return SnakeSim(cfg)
    if m == "flip":
        from .flip import FlipSim
        return FlipSim(cfg)
    if m == "race":
        from .race import RaceSim
        return RaceSim(cfg)
    if m == "plinko":
        from .plinko import PlinkoSim
        return PlinkoSim(cfg)
    if m == "weapon":
        from .weapon import WeaponSim
        return WeaponSim(cfg)
    if m == "battle":
        from .battle import BattleSim
        return BattleSim(cfg)
    if m == "tower":
        from .tower import TowerSim
        return TowerSim(cfg)
    if m == "drawer":
        from .drawer import DrawerSim
        return DrawerSim(cfg)
    if m == "ghost":
        from .ghost import GhostSim
        return GhostSim(cfg)
    if m == "rhythmic":
        from .rhythmic import RhythmicSim
        return RhythmicSim(cfg)
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
    if m == "voting":
        from ..render_modes import VotingRenderer
        return VotingRenderer(cfg, scale)
    if m == "colorsort":
        from ..render_modes import ColorSortRenderer
        return ColorSortRenderer(cfg, scale)
    if m in ("flip", "snake", "chain", "countdown"):
        from ..render_modes import BreakerRenderer
        return BreakerRenderer(cfg, scale)
    if m == "accumulate":
        from ..render_modes import BreakerRenderer
        return BreakerRenderer(cfg, scale)
    if m == "race":
        from ..render_modes import RaceRenderer
        return RaceRenderer(cfg, scale)
    if m == "plinko":
        from ..render_modes import PlinkoRenderer
        return PlinkoRenderer(cfg, scale)
    if m == "weapon":
        from ..render_modes import WeaponRenderer
        return WeaponRenderer(cfg, scale)
    if m == "battle":
        from ..render_modes import BattleRenderer
        return BattleRenderer(cfg, scale)
    if m == "tower":
        from ..render_modes import TowerRenderer
        return TowerRenderer(cfg, scale)
    if m == "drawer":
        from ..render_modes import DrawerRenderer
        return DrawerRenderer(cfg, scale)
    if m == "ghost":
        from ..render_modes import GhostRenderer
        return GhostRenderer(cfg, scale)
    if m == "rhythmic":
        from ..render_modes import RhythmicRenderer
        return RhythmicRenderer(cfg, scale)
    if m == "glass":
        from ..render_modes import GlassRenderer
        return GlassRenderer(cfg, scale)
    from ..render import Renderer
    return Renderer(cfg, scale)
