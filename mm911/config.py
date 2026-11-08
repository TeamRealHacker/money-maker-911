"""Settings for Money Maker 911 renders. Everything a user can edit lives here."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

APP_NAME = "Money Maker 911"
CREDIT = "made by TeamRealHackers"
VERSION = "0.3.0"

# Soft, non-neon palettes. Each: background top, background bottom, container, text, tier colors
PALETTES: dict[str, dict] = {
    "Candy": {
        "bg_top": "#FDE2E4", "bg_bottom": "#E2ECE9", "container": "#5B5F97", "text": "#2B2D42",
        "tiers": ["#FFB5A7", "#FCD5CE", "#F8EDEB", "#F9DCC4", "#FEC89A", "#B5E2FA",
                  "#90DBF4", "#A3C4F3", "#CFBAF0", "#F1C0E8", "#FFD6A5", "#CAFFBF"],
    },
    "Forest": {
        "bg_top": "#283618", "bg_bottom": "#1B2412", "container": "#DDA15E", "text": "#FEFAE0",
        "tiers": ["#FEFAE0", "#E9EDC9", "#CCD5AE", "#A3B18A", "#588157", "#DDA15E",
                  "#BC6C25", "#E76F51", "#F4A261", "#E9C46A", "#2A9D8F", "#FFD166"],
    },
    "Ocean": {
        "bg_top": "#0B2545", "bg_bottom": "#13315C", "container": "#EEF4ED", "text": "#EEF4ED",
        "tiers": ["#E0FBFC", "#C2DFE3", "#9DB4C0", "#8DA9C4", "#5C6B73", "#F2CC8F",
                  "#E07A5F", "#81B29A", "#F4F1DE", "#3D405B", "#FFB4A2", "#FFD166"],
    },
    "Sunset": {
        "bg_top": "#3D348B", "bg_bottom": "#191334", "container": "#F7B801", "text": "#FFFFFF",
        "tiers": ["#F7B801", "#F18701", "#F35B04", "#E5989B", "#B5838D", "#6D6875",
                  "#FFCDB2", "#FFB4A2", "#7678ED", "#A0C4FF", "#FDFFB6", "#FFADAD"],
    },
    "Mono": {
        "bg_top": "#F5F5F5", "bg_bottom": "#DADADA", "container": "#222222", "text": "#111111",
        "tiers": ["#FFFFFF", "#EEEEEE", "#DDDDDD", "#CCCCCC", "#BBBBBB", "#AAAAAA",
                  "#999999", "#888888", "#777777", "#555555", "#333333", "#111111"],
    },
    "Mint": {
        "bg_top": "#D8F3DC", "bg_bottom": "#95D5B2", "container": "#1B4332", "text": "#081C15",
        "tiers": ["#FFFFFF", "#F1FAEE", "#B7E4C7", "#74C69D", "#52B788", "#40916C",
                  "#FFE66D", "#FF6B6B", "#4ECDC4", "#F7FFF7", "#FFB703", "#FB8500"],
    },
}

SHAPES = ["circle", "hexagon", "octagon", "square", "heart", "star"]

# Length presets (button label -> max seconds before the run stops; +end hold = final length)
LENGTH_PRESETS = {"30s": 28.0, "45s": 43.0, "60s": 58.0}

# Ready-made emoji tier sets (smallest first). Any emoji works; these ship offline.
EMOJI_SETS = {
    "Fruit": ["🍒", "🍓", "🍇", "🍋", "🍊", "🍎", "🍐", "🍑", "🍍", "🍈", "🍉"],
    "Animal": ["🐭", "🐱", "🐶", "🦊", "🐼", "🐻", "🐯", "🦁", "🐘", "🐳", "🐳"],
    "Planet": ["⭐", "🌑", "🌙", "🌍", "🪐", "☀️", "☀️", "☀️", "☀️", "☀️", "☀️"],
    "Food": ["🍪", "🍩", "🍕", "🍔", "🍎", "🍉", "🍍", "🥥", "🍈", "🍑", "🍇"],
    "Meme": ["💀", "😂", "🗿", "🔥", "💎", "⚽", "🏀", "🍕", "🍔", "🪐", "☀️"],
}

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

HOOKS = [
    "Will it reach the Final Form?",
    "Can it make the biggest one?",
    "Wait for the last merge...",
    "Bet it won't make it",
    "Watch them merge",
    "How far will it go?",
]


@dataclass
class MergeConfig:
    # video
    width: int = 1080
    height: int = 1920
    fps: int = 60
    max_seconds: float = 58.0
    end_hold_seconds: float = 2.0
    # look
    palette: str = "Candy"
    container_shape: str = "circle"
    container_radius: int = 470
    container_thickness: int = 18
    container_spin: float = 0.0        # degrees per second, 0 = still
    background_image: str = ""         # optional path
    show_tier_labels: bool = True
    show_progress: bool = True
    # text
    theme_name: str = "Fruit"
    hook: str = "Will it reach the Final Form?"
    watermark: str = ""
    font_path: str = ""                # optional .ttf
    # gameplay
    tiers: int = 9
    base_radius: float = 20.0
    growth: float = 1.414
    spawn_interval: float = 0.18       # seconds between drops
    spawn_max_tier: int = 4            # random spawn tier upper bound (exclusive of final)
    gravity: float = 1800.0
    bounce: float = 0.15
    friction: float = 0.5
    speed: float = 1.0                 # sim speed multiplier
    # assets
    tier_images: list[str] = field(default_factory=list)   # one image per tier (optional)
    tier_names: list[str] = field(default_factory=list)    # labels per tier (optional)
    ai_cutout: bool = False            # remove image backgrounds with rembg
    cutout_model: str = "birefnet-general"
    reject_text_images: bool = False   # skip images that contain text (OCR)
    tier_image_folder: str = ""        # folder of images, sorted by name = tier order (overrides tier_images)
    tier_colors: list[str] = field(default_factory=list)   # custom hex per tier ("" = palette colour)
    tier_emojis: list[str] = field(default_factory=list)   # emoji per tier ("" = number/name)
    export_thumbnail: bool = True      # save a .jpg thumbnail next to every video
    sound_path: str = ""               # any sound (Myinstants etc). Empty = built-in pop
    sound_volume: float = 0.8
    music_path: str = ""               # optional background music (off by default)
    music_volume: float = 0.25
    # randomness
    seed: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MergeConfig":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "MergeConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def resolved_tier_images(self) -> list[str]:
        """Images per tier: folder (natural name order) wins over the picked list."""
        if self.tier_image_folder and Path(self.tier_image_folder).is_dir():
            import re
            files = [p for p in Path(self.tier_image_folder).iterdir() if p.suffix.lower() in IMAGE_EXTS]
            key = lambda p: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]
            imgs = [str(p) for p in sorted(files, key=key)][: self.tiers]
        else:
            imgs = list(self.tier_images)
        if imgs and (self.ai_cutout or self.reject_text_images):
            from . import cutout
            imgs = cutout.prepare(imgs, self.cutout_model if self.ai_cutout else "", self.reject_text_images) if self.ai_cutout else [i for i in imgs if not cutout.has_text(i)]
        return imgs

    def tier_value(self, attr: str, t: int) -> str:
        lst = getattr(self, attr)
        return lst[t] if t < len(lst) and lst[t] else ""

    def tier_radius(self, tier: int) -> float:
        return self.base_radius * (self.growth ** tier)


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
