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
    "bowling": "🎳 Bowling Strike",
    "stacker": "🏗️ Tower Stack",
    "bubble": "🫧 Bubble Pop",
    "hole": "🕳️ Hole Eater",
    "zoom": "♾️ Infinite Zoom",
    "orbit3d": "🪐 Orbit 3D",
}


def sim_for(cfg):
    m = getattr(cfg, "mode", "merge")
    if m == "orbit3d":
        from .orbit3d import Orbit3DSim
        return Orbit3DSim(cfg)
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
    if m == "zoom":
        from .zoom import ZoomSim
        return ZoomSim(cfg)
    if m == "bowling":
        from .bowling import BowlingSim
        return BowlingSim(cfg)
    if m == "stacker":
        from .stacker import StackerSim
        return StackerSim(cfg)
    if m == "bubble":
        from .bubble import BubbleSim
        return BubbleSim(cfg)
    if m == "hole":
        from .hole import HoleSim
        return HoleSim(cfg)
    from .merge import MergeSim
    return MergeSim(cfg)


def renderer_for(cfg, scale: float = 1.0):
    m = getattr(cfg, "mode", "merge")
    if m == "orbit3d":
        from ..render_modes import Orbit3DRenderer
        return Orbit3DRenderer(cfg, scale)
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
    if m == "zoom":
        from ..render_new import ZoomRenderer
        return ZoomRenderer(cfg, scale)
    if m == "bowling":
        from ..render_new import BowlingRenderer
        return BowlingRenderer(cfg, scale)
    if m == "stacker":
        from ..render_new import StackerRenderer
        return StackerRenderer(cfg, scale)
    if m == "bubble":
        from ..render_new import BubbleRenderer
        return BubbleRenderer(cfg, scale)
    if m == "hole":
        from ..render_new import HoleRenderer
        return HoleRenderer(cfg, scale)
    from ..render import Renderer
    return Renderer(cfg, scale)
