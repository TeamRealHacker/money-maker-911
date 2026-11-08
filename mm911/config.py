"""Settings for Money Maker 911 renders. Everything a user can edit lives here."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

APP_NAME = "Money Maker 911"
CREDIT = "made by TeamRealHackers"
VERSION = "0.9.0"

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

SHAPES = ["circle", "hexagon", "octagon", "square", "heart", "star", "triangle", "pentagon", "diamond",
          "rounded", "custom"]
BG_MODES = ["palette", "solid", "gradient", "image", "video"]
SIZE_CURVES = ["exponential", "linear", "custom"]
PARTICLE_STYLES = ["dots", "squares", "stars", "sparks", "rings", "confetti"]
SOUND_MODES = ["single", "per_tier"]
SOUND_STRATEGIES = ["pitch_up", "sorted"]
TEXT_ALIGNS = ["center", "left", "right"]
IMAGE_FITS = ["smart", "center", "top", "fit"]          # how a picture is cropped into a round ball
CUTOUT_STYLES = ["disc", "sticker", "circle"]           # cut-out on a tier disc | free sticker | fills the ball

# Length presets (button label -> max seconds before the run stops; +end hold = final length)
LENGTH_PRESETS = {"15s": 13.0, "30s": 28.0, "45s": 43.0, "60s": 58.0}

# Ready-made emoji tier sets (smallest first). Any emoji works; these ship offline.
EMOJI_SETS = {
    "Fruit": ["🍒", "🍓", "🍇", "🍋", "🍊", "🍎", "🍐", "🍑", "🍍", "🍈", "🍉"],
    "Animal": ["🐭", "🐱", "🐶", "🦊", "🐼", "🐻", "🐯", "🦁", "🐘", "🐳", "🐳"],
    "Planet": ["⭐", "🌑", "🌙", "🌍", "🪐", "☀️", "☀️", "☀️", "☀️", "☀️", "☀️"],
    "Food": ["🍪", "🍩", "🍕", "🍔", "🍎", "🍉", "🍍", "🥥", "🍈", "🍑", "🍇"],
    "Meme": ["💀", "😂", "🗿", "🔥", "💎", "⚽", "🏀", "🍕", "🍔", "🪐", "☀️"],
}

MIN_TIERS, MAX_TIERS = 3, 15
FPS_CHOICES = [24, 25, 30, 48, 50, 60, 90, 120]
RESOLUTIONS = {"720p": (720, 1280), "1080p": (1080, 1920), "1440p": (1440, 2560), "4k": (2160, 3840)}
QUALITIES = {"max": 14, "high": 17, "balanced": 20, "small": 24}   # x264-style CRF (v0.6: one step sharper)
CODECS = ["h264", "h265"]
ENCODERS = ["auto", "cpu", "nvidia", "intel", "amd"]
FORMATS = ["mp4", "mov"]
AUDIO_BITRATES = [128, 160, 192, 256, 320]

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

HOOKS = [
    "Will it reach the Final Form?",
    "Can it make the biggest one?",
    "Wait for the last merge...",
    "Bet it won't make it",
    "Watch them merge",
    "How far will it go?",
]


# Satisfying Myinstants keywords used when "auto sounds" has no keyword of its own.
SATISFYING_KEYWORDS = ["pop", "bubble pop", "boing", "bloop", "water drop", "plop", "ding", "pluck",
                       "xylophone", "click"]

# Knobs the batch factory can randomize per video (GUI shows these as checkboxes).
RANDOM_KNOBS = {
    "palette": "Palette", "shape": "Container shape", "hook": "Hook text", "spin": "Spin",
    "drop_interval": "Drop interval", "gravity": "Gravity", "bounce": "Bounciness", "friction": "Friction",
    "ball_size": "Ball size", "tiers": "Number of tiers", "background": "Background gradient",
    "particles": "Particle style", "container_color": "Container colour", "sound_keyword": "Sound keyword",
}
DEFAULT_RANDOM_KNOBS = ["palette", "shape", "hook", "spin", "drop_interval"]


MODES = ["merge", "escape", "breaker", "glass", "ghost", "rhythm"]
BREAKER_PATTERNS = ["full", "pyramid", "diamond", "heart", "checker", "stripes"]


@dataclass
class MergeConfig:
    """Settings for every mode (the name stays for old presets / imports). mode picks the game."""
    mode: str = "merge"                # merge | escape | breaker | glass | ghost | rhythm
    # video
    width: int = 1080
    height: int = 1920
    fps: int = 60
    max_seconds: float = 58.0          # video seconds before the run stops ("So close...")
    end_hold_seconds: float = 2.0      # how long the Final Form ending stays on screen
    until_finished: bool = False       # ignore max_seconds and keep going until Final Form (hard cap 180 s)
    # look
    palette: str = "Candy"
    container_shape: str = "circle"
    container_points: list = field(default_factory=list)   # custom shape: [[x, y], ...] in -1..1 (y down)
    container_radius: int = 470
    container_thickness: int = 18
    container_y: float = 0.53          # container centre, fraction of the height
    container_color: str = ""          # "" = palette colour
    container_glow: float = 0.0        # 0..1
    container_glow_color: str = ""     # "" = container colour
    container_spin: float = 0.0        # degrees per second, 0 = still, negative = counter-clockwise
    spin_wobble: float = 0.0           # extra +/- degrees per second, swinging back and forth
    spin_wobble_period: float = 4.0    # seconds per swing
    # background
    bg_mode: str = "palette"           # palette | solid | gradient | image | video
    bg_colors: list = field(default_factory=list)   # solid: 1 colour, gradient: 2-3 colours
    bg_angle: float = 90.0             # gradient angle in degrees (90 = top to bottom)
    background_image: str = ""         # image file (bg_mode image, or any mode when set — legacy)
    background_video: str = ""         # looping video file (bg_mode video)
    bg_dim: int = 70                   # 0..255 darkening over image / video backgrounds
    show_tier_labels: bool = True
    show_progress: bool = True         # tier strip under the hook
    # balls
    ball_scale: float = 1.0            # multiplies every ball size
    size_curve: str = "exponential"    # exponential (growth^tier) | linear | custom
    tier_sizes: list = field(default_factory=list)  # custom radii per tier (px)
    auto_fit: bool = True              # adjust growth so the Final Form always fits the container
    ball_outline: int = 0              # outline width in px (0 = default rim)
    ball_outline_color: str = ""       # "" = darker tier colour
    ball_shadow: float = 0.0           # 0..1 drop shadow under balls
    ball_glow: float = 0.0             # 0..1 soft glow around balls
    ball_highlight: float = 0.5        # 0..1 glossy highlight (top-left light)
    ball_inner_shadow: float = 0.25    # 0..1 3D shading toward the lower-right rim
    ball_rim: float = 0.06             # rim around picture balls, fraction of the radius (0 = no rim)
    image_fit: str = "smart"           # smart (centre on the subject) | center | top | fit (whole picture)
    image_zoom: float = 1.0            # 1 = picture fills the ball, 2 = zoom in 2x on the subject
    cutout_style: str = "disc"         # cut-outs: disc (sticker on a tier disc) | sticker (no circle) | circle
    # particles + juice
    particle_amount: float = 1.0       # 0 = off, 1 = normal, 3 = a lot
    particle_style: str = "dots"
    particle_colors: list = field(default_factory=list)  # "" / empty = tier colour
    particle_speed: float = 1.0
    particle_gravity: float = 900.0
    shake_strength: float = 0.0        # px of screen shake on merges (0 = off)
    shake_min_tier: int = 3            # only merges into this tier (1-based) or above shake
    combo_popups: bool = True          # "x3 COMBO!" when merges chain quickly
    combo_window: float = 0.5          # a merged ball merging again within this many seconds = chain
    combo_min: int = 3                 # smallest chain that gets a popup
    tier_banners: bool = True          # "NEW: Tier 6!" banner when a new tier is reached
    banner_min_tier: int = 4           # first tier (1-based) that gets a banner
    slowmo_final: bool = True          # slow motion on the final merge
    slowmo_factor: float = 0.3         # sim speed during slow motion
    slowmo_seconds: float = 1.2        # video seconds of slow motion
    near_miss: bool = True             # tension: "ALMOST..." + random pause before the last merge
    near_miss_chance: float = 0.6      # 0..1 chance of a dramatic pause when one tier away
    show_progress_bar: bool = False    # bar filling toward the Final Form
    progress_bar_y: float = 0.955      # fraction of the height
    progress_bar_color: str = ""       # "" = text colour
    # text (font_path is the default font for every text)
    theme_name: str = "Fruit"
    hook: str = "Will it reach the Final Form?"
    hook_size: int = 64
    hook_color: str = ""               # "" = palette text colour
    hook_y: float = 0.078              # fraction of the height
    hook_font_path: str = ""
    show_counter: bool = False         # merge counter text
    counter_text: str = "{merges} merges"   # {merges} {tier} {tiers} {time} {combo}
    counter_size: int = 44
    counter_color: str = ""
    counter_y: float = 0.80
    counter_font_path: str = ""
    watermark: str = ""
    watermark_size: int = 34
    watermark_color: str = ""
    watermark_y: float = 0.91
    watermark_opacity: int = 150
    watermark_font_path: str = ""
    final_text: str = "FINAL FORM!"
    final_text_size: int = 120
    final_text_color: str = ""
    final_text_y: float = 0.83
    fail_text: str = "So close..."
    near_miss_text: str = "ALMOST..."
    combo_text: str = "x{n} COMBO!"
    banner_text: str = "NEW: {name}!"
    font_path: str = ""                # optional .ttf for all text
    # gameplay
    tiers: int = 9                     # "forms": any number from MIN_TIERS to MAX_TIERS (3-15)
    base_radius: float = 20.0
    growth: float = 1.414
    spawn_interval: float = 0.18       # seconds between drops
    spawn_jitter: float = 0.2          # +/- random fraction on the interval
    drop_speed: float = 120.0          # px/s downward speed of a new drop
    spawn_max_tier: int = 4            # random spawn tier upper bound (exclusive of final)
    fill_cap: float = 0.8              # stop dropping when the container is this full
    gravity: float = 1800.0
    bounce: float = 0.15
    friction: float = 0.5
    speed: float = 1.0                 # sim speed multiplier
    # assets
    tier_images: list[str] = field(default_factory=list)   # one image per tier (optional)
    tier_names: list[str] = field(default_factory=list)    # labels per tier (optional)
    tier_image_folder: str = ""        # folder of images, sorted by name = tier order (overrides tier_images)
    tier_colors: list[str] = field(default_factory=list)   # custom hex per tier ("" = palette colour)
    tier_emojis: list[str] = field(default_factory=list)   # emoji per tier ("" = number/name)
    export_thumbnail: bool = True      # save a .jpg thumbnail next to every video
    ai_cutout: bool = False            # remove image backgrounds (AI model or quick flat-bg cut)
    cutout_model: str = "isnet-general-use"   # birefnet-general | isnet-general-use | u2net | quick
    cutout_outline: bool = True        # white sticker outline around cut-outs
    reject_text: bool = False          # skip tier images that contain text (meme captions, watermarks)
    # sound
    sound_path: str = ""               # any sound (Myinstants etc). Empty = built-in pop
    sound_volume: float = 0.8
    tier_sounds: list[str] = field(default_factory=list)   # sound per tier ("" = sound_path)
    tier_semitones: list = field(default_factory=list)     # pitch per tier in semitones (null = auto)
    pitch_step: float = 1.6            # auto pitch: semitones higher per tier
    pitch_jitter: float = 0.0          # random +/- semitones per hit
    drop_sound: str = ""               # "" = same as merge sound
    final_sound: str = ""              # "" = same as merge sound
    drop_pitch: float = -4.0           # semitones added for drops
    final_pitch: float = 7.0           # semitones added for the Final Form
    drop_volume: float = 0.35          # relative to sound_volume
    final_volume: float = 1.3
    auto_sounds: bool = False          # fetch sounds from Myinstants at render time
    auto_sound_keywords: str = ""      # comma separated, "" = built-in satisfying list
    auto_sound_strategy: str = "sorted"   # pitch_up (one sound, pitched up per tier) | sorted (several, low->high)
    auto_sound_count: int = 4          # different sounds for "sorted"
    auto_sound_separate: bool = True   # pick separate drop / final sounds too
    auto_drop_keyword: str = ""        # e.g. "click" ("" = shortest clip of the main search)
    auto_final_keyword: str = ""       # e.g. "vine boom" ("" = top tier sound, pitched up)
    music_path: str = ""               # optional background music (off by default)
    music_volume: float = 0.25
    drop_sounds: bool = True           # quiet sound on every drop (merges always make a sound)
    # export
    export_resolution: str = "1080p"   # 720p | 1080p | 1440p | 4k (always 9:16)
    export_quality: str = "high"       # max | high | balanced | small
    export_codec: str = "h264"         # h264 (plays everywhere) | h265 (smaller files)
    export_encoder: str = "auto"       # auto | cpu | nvidia | intel | amd
    export_format: str = "mp4"         # mp4 | mov
    export_audio: bool = True          # False = silent video
    audio_bitrate: int = 192           # kbps
    open_folder_after: bool = False
    # 🌀 Escape mode (balls / pictures, sounds, particles, texts, export: shared with Merge)
    escape_rings: int = 8              # how many rings to escape (2-30)
    escape_inner_radius: float = 140.0 # px, innermost ring
    escape_outer_radius: float = 480.0 # px, outermost ring
    escape_ring_thickness: float = 12.0
    escape_center_y: float = 0.52      # ring centre, fraction of the height
    escape_gap_deg: float = 56.0       # gap width in degrees
    escape_gap_jitter: float = 12.0    # +/- random degrees per ring
    escape_spin: float = 70.0          # degrees per second (innermost ring)
    escape_spin_step: float = 0.12     # each ring spins this much faster than the one inside it
    escape_alternate: bool = True      # neighbouring rings spin in opposite directions
    escape_ball_radius: float = 34.0
    escape_ball_growth: float = 1.0    # ball size x this per escape (1.08 = grows)
    escape_ball_speed: float = 900.0   # start speed px/s
    escape_min_speed: float = 650.0    # never slower than this
    escape_max_speed: float = 1700.0   # never faster than this
    escape_gravity: float = 1400.0
    escape_bounce: float = 1.0         # elasticity of ball + rings
    escape_assist: bool = True         # a ring nobody escapes for a while slowly opens its gap
    escape_assist_after: float = 3.5   # seconds without an escape before the gap starts opening
    escape_assist_speed: float = 14.0  # degrees per second the gap opens
    escape_trail: int = 10             # trail length in frames (0 = off)
    escape_ring_glow: float = 0.5      # 0..1
    escape_ring_colors: list = field(default_factory=list)   # "" / empty = palette tier colours
    escape_ball_color: str = ""        # plain ball colour ("" = first tier colour)
    escape_evolve: bool = True         # the ball changes to the next tier picture / emoji per escape
    escape_shatter: bool = True        # rings burst into particles when escaped
    escape_counter_text: str = "{escaped}/{rings}"
    escape_counter_size: int = 96
    escape_counter_y: float = 0.165
    escape_final_text: str = "ESCAPED!"
    escape_final_zoom: float = 4.0     # the ball glides to the centre and grows this much at the end (1 = off)
    escape_pitch_low: float = -5.0     # semitones of the first escape
    escape_pitch_high: float = 12.0    # semitones of the last escape
    escape_bounce_pitch: float = -7.0  # bounce sound relative to the current escape pitch
    # 🧱 Breaker mode: balls bounce around an arena and smash a wall of bricks
    breaker_rows: int = 8
    breaker_cols: int = 8
    breaker_pattern: str = "full"      # full | pyramid | diamond | heart | checker | stripes
    breaker_hp: int = 2                # toughest bricks take this many hits (top rows are toughest)
    breaker_balls: int = 1             # balls at the start
    breaker_split_every: int = 6       # +1 ball every N bricks broken (0 = never)
    breaker_max_balls: int = 9
    breaker_ball_radius: float = 22.0
    breaker_speed: float = 1300.0      # ball speed px/s (kept constant)
    breaker_gravity: float = 0.0       # 0 = classic straight bounces
    breaker_arena_top: float = 0.2     # arena, fractions of the height
    breaker_arena_bottom: float = 0.88
    breaker_arena_margin: float = 50.0 # px from the left / right edge
    breaker_brick_height: float = 46.0
    breaker_brick_gap: float = 8.0
    breaker_brick_round: float = 0.3   # brick corner roundness 0..0.5
    breaker_wall_rows_y: float = 0.08  # gap between the arena top and the first brick row (fraction of arena)
    breaker_trail: int = 6
    breaker_counter_text: str = "{left} left"
    breaker_final_text: str = "CLEARED!"
    breaker_pitch_low: float = -5.0    # first brick
    breaker_pitch_high: float = 14.0   # last brick
    # Glass Rush (also uses the escape_* rings / ball / trail / glow settings)
    glass_hp: int = 6                  # hits the innermost glass ring takes
    glass_hp_growth: float = 1.5       # extra hits per ring further out
    glass_spin: float = 25.0           # degrees per second (rings alternate direction)
    glass_cracks: bool = True          # draw crack lines on hit rings
    glass_crack_color: str = "#FFFFFF"
    glass_counter_text: str = "{broken}/{rings}"
    glass_final_text: str = "SHATTERED!"
    ghost_dark: float = 0.82           # how dark the room is (0 = lights on, 1 = pitch black)
    ghost_light: float = 230.0         # radius (px) of the ghost light that follows the ball
    ghost_phase_every: float = 3.0     # seconds between ghost phases of the front ring (0 = never)
    ghost_phase_len: float = 1.3       # how long the ring stays a ghost
    ghost_counter_text: str = "{escaped}/{rings}"
    ghost_final_text: str = "ESCAPED!"
    rhythm_song: str = "ode_to_joy"    # built-in melody (ode_to_joy, twinkle, fur_elise, jingle_bells, scale_up)
    rhythm_midi: str = ""              # path of a .mid file (overrides the built-in song)
    rhythm_tempo: float = 1.0          # tempo multiplier (the song is also sped up to fit the length)
    rhythm_lanes: int = 8              # keys the notes are spread over (low pitch left, high right)
    rhythm_hop: float = 1.0            # how high the ball hops
    rhythm_floor_y: float = 0.80       # height of the keys (fraction of the video)
    rhythm_ball_radius: float = 56.0
    rhythm_trail: int = 14
    rhythm_evolve: bool = True         # the ball wears your Tiers pictures as the song goes on
    rhythm_guides: bool = True         # falling note markers show what is coming
    rhythm_lead: float = 0.9           # seconds before the first note
    rhythm_pitch_shift: float = 0.0    # semitones added to every note's sound
    rhythm_counter_text: str = "{notes}/{total}"
    rhythm_final_text: str = "SONG COMPLETE!"
    glass_speed_gain: float = 0.04     # ball speeds up by this fraction with every ring broken
    # batch
    random_knobs: list[str] = field(default_factory=lambda: list(DEFAULT_RANDOM_KNOBS))
    batch_sound_keywords: list[str] = field(default_factory=list)  # one picked per video when "sound_keyword" is on
    batch_dedupe: bool = True          # duplicate checker: compare every new video with the folder's videos
    dedupe_threshold: float = 0.9      # 0..1 similarity (perceptual hash of sampled frames) = "too similar"
    dedupe_action: str = "skip"        # skip (delete + re-render with a new seed) | flag (keep, mark in titles.csv)
    # randomness
    seed: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MergeConfig":
        """Build a config from saved / hand-edited data. A value of the wrong type (or a whole file of
        junk) falls back to that setting's default instead of crashing the app on startup."""
        if not isinstance(d, dict):
            d = {}
        base = cls()
        known = {}
        for k, v in d.items():
            if k not in cls.__dataclass_fields__:
                continue
            cur = getattr(base, k)
            try:
                if isinstance(cur, bool):
                    v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "yes")
                elif isinstance(cur, int):
                    if isinstance(v, bool) or v is None:
                        continue
                    v = int(round(float(v)))
                elif isinstance(cur, float):
                    if isinstance(v, bool) or v is None:
                        continue
                    v = float(v)
                elif isinstance(cur, str):
                    if not isinstance(v, (str, int, float)):
                        continue
                    v = str(v)
                elif isinstance(cur, list):
                    if not isinstance(v, list):
                        continue
            except (TypeError, ValueError, OverflowError):
                continue
            known[k] = v
        try:
            cfg = cls(**known)
        except TypeError:
            cfg = cls()
        cfg.tiers = max(MIN_TIERS, min(MAX_TIERS, int(cfg.tiers)))
        cfg.sanitize_export()
        try:
            cfg.clamp()
        except (TypeError, ValueError):
            pass
        return cfg

    def sanitize_export(self) -> None:
        """Clamp export settings to supported values (old/hand-edited presets can't break a render)."""
        try:
            self.fps = max(15, min(120, int(self.fps)))
        except (TypeError, ValueError):
            self.fps = 60
        if self.export_resolution not in RESOLUTIONS: self.export_resolution = "1080p"
        if self.export_quality not in QUALITIES: self.export_quality = "high"
        if self.export_codec not in CODECS: self.export_codec = "h264"
        if self.export_encoder not in ENCODERS: self.export_encoder = "auto"
        if self.export_format not in FORMATS: self.export_format = "mp4"
        try:
            self.audio_bitrate = max(64, min(320, int(self.audio_bitrate)))
        except (TypeError, ValueError):
            self.audio_bitrate = 192

    def export_scale(self) -> float:
        return RESOLUTIONS.get(self.export_resolution, (1080, 1920))[0] / self.width

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "MergeConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def resolved_tier_images(self) -> list[str]:
        """Images per tier: folder (natural name order) wins over the picked list."""
        if self.tier_image_folder and Path(self.tier_image_folder).is_dir():
            import re
            files = [p for p in Path(self.tier_image_folder).iterdir() if p.suffix.lower() in IMAGE_EXTS]
            key = lambda p: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]
            return [str(p) for p in sorted(files, key=key)][: self.tiers]
        return list(self.tier_images)

    def tier_value(self, attr: str, t: int) -> str:
        lst = getattr(self, attr)
        return lst[t] if t < len(lst) and lst[t] else ""

    def tier_radius(self, tier: int) -> float:
        """Ball radius per tier. With auto_fit (default) the growth is adjusted so the Final Form always
        fits the container whatever number of forms (3-15) is picked: at most 70% of the container
        radius, and at least 40% so few forms still end big and satisfying. size_curve / ball_scale on top."""
        hard_max = self.container_radius * 0.95          # never bigger than the container
        if self.size_curve == "custom" and tier < len(self.tier_sizes):
            try:
                r = float(self.tier_sizes[tier])
                if r > 0:
                    return min(hard_max, r * self.ball_scale)
            except (TypeError, ValueError):
                pass
        n = max(2, int(self.tiers))
        g = self.growth
        if self.auto_fit:
            cap = self.container_radius * 0.7
            floor = self.container_radius * 0.4
            if self.base_radius * g ** (n - 1) < floor:
                g = (floor / self.base_radius) ** (1 / (n - 1))
            if self.base_radius * g ** (n - 1) > cap:
                g = (cap / self.base_radius) ** (1 / (n - 1))
        t = min(tier, n - 1)
        if self.size_curve == "linear":
            # same first and last size as the exponential curve, evenly spaced in between
            top = self.base_radius * g ** (n - 1)
            r = self.base_radius + (top - self.base_radius) * t / (n - 1)
        else:
            r = self.base_radius * (g ** t)
        return min(hard_max, r * self.ball_scale)

    def tier_label(self, t: int) -> str:
        return self.tier_value("tier_names", t) or self.tier_value("tier_emojis", t) or f"Tier {t + 1}"

    def tier_pitch(self, t: int) -> float:
        """Semitones for a merge into tier t: manual override, else auto pitch_step per tier."""
        if t < len(self.tier_semitones) and self.tier_semitones[t] not in (None, ""):
            try:
                return float(self.tier_semitones[t])
            except (TypeError, ValueError):
                pass
        return t * self.pitch_step

    def clamp(self) -> "MergeConfig":
        """Keep values in a range the engine can handle (presets / GUI / batch can send anything)."""
        self.tiers = max(MIN_TIERS, min(MAX_TIERS, int(self.tiers)))
        self.fps = max(15, min(120, int(self.fps)))
        self.spawn_interval = max(0.03, float(self.spawn_interval))
        self.ball_scale = max(0.2, min(4.0, float(self.ball_scale)))
        self.slowmo_factor = max(0.05, min(1.0, float(self.slowmo_factor)))
        self.container_radius = max(120, int(self.container_radius))
        self.container_thickness = max(1, int(self.container_thickness))
        self.fill_cap = max(0.2, min(1.2, float(self.fill_cap)))
        self.auto_sound_count = max(1, min(12, int(self.auto_sound_count)))
        if self.mode not in MODES: self.mode = "merge"
        self.escape_rings = max(1, min(30, int(self.escape_rings)))
        self.escape_ring_thickness = max(2.0, float(self.escape_ring_thickness))
        self.escape_inner_radius = max(40.0, float(self.escape_inner_radius))
        self.escape_outer_radius = max(self.escape_inner_radius, min(1000.0, float(self.escape_outer_radius)))
        self.escape_min_speed = max(50.0, float(self.escape_min_speed))
        self.escape_max_speed = max(self.escape_min_speed, float(self.escape_max_speed))
        self.breaker_rows = max(1, min(20, int(self.breaker_rows)))
        self.breaker_cols = max(1, min(16, int(self.breaker_cols)))
        self.breaker_hp = max(1, min(5, int(self.breaker_hp)))
        self.breaker_balls = max(1, min(12, int(self.breaker_balls)))
        self.breaker_max_balls = max(self.breaker_balls, min(30, int(self.breaker_max_balls)))
        self.ghost_dark = max(0.0, min(1.0, float(self.ghost_dark)))
        self.ghost_light = max(60.0, min(600.0, float(self.ghost_light)))
        self.ghost_phase_every = max(0.0, min(20.0, float(self.ghost_phase_every)))
        self.ghost_phase_len = max(0.2, min(6.0, float(self.ghost_phase_len)))
        self.rhythm_tempo = max(0.25, min(4.0, float(self.rhythm_tempo)))
        self.rhythm_lanes = max(2, min(16, int(self.rhythm_lanes)))
        self.rhythm_hop = max(0.2, min(3.0, float(self.rhythm_hop)))
        self.rhythm_floor_y = max(0.45, min(0.92, float(self.rhythm_floor_y)))
        self.rhythm_ball_radius = max(10.0, min(160.0, float(self.rhythm_ball_radius)))
        self.rhythm_trail = max(0, min(30, int(self.rhythm_trail)))
        self.rhythm_lead = max(0.2, min(5.0, float(self.rhythm_lead)))
        self.rhythm_pitch_shift = max(-24.0, min(24.0, float(self.rhythm_pitch_shift)))
        self.glass_hp = max(1, min(12, int(self.glass_hp)))
        self.glass_hp_growth = max(0.0, min(4.0, float(self.glass_hp_growth)))
        self.glass_spin = max(0.0, min(360.0, float(self.glass_spin)))
        self.glass_speed_gain = max(0.0, min(0.3, float(self.glass_speed_gain)))
        if self.breaker_pattern not in BREAKER_PATTERNS: self.breaker_pattern = "full"
        if self.dedupe_action not in ("skip", "flag"): self.dedupe_action = "skip"
        self.dedupe_threshold = max(0.5, min(1.0, float(self.dedupe_threshold)))
        if self.image_fit not in IMAGE_FITS: self.image_fit = "smart"
        if self.cutout_style not in CUTOUT_STYLES: self.cutout_style = "disc"
        self.image_zoom = max(1.0, min(4.0, float(self.image_zoom or 1.0)))
        self.ball_rim = max(0.0, min(0.3, float(self.ball_rim)))
        return self

    def video_seconds(self) -> float:
        """Upper bound of the video length (for progress bars)."""
        return (180.0 if self.until_finished else self.max_seconds) + self.end_hold_seconds


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def color_or(h: str, fallback: tuple) -> tuple:
    """Hex colour, or the fallback when empty / invalid."""
    if not h:
        return fallback
    try:
        return hex_to_rgb(h)
    except (ValueError, TypeError):
        return fallback
