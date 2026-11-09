"""Command line: `python -m mm911.cli render ...` / `batch ...` (also used by Colab later)."""
from __future__ import annotations

import argparse
import json

from .config import MergeConfig, MODES
from .config import (LENGTH_PRESETS, EMOJI_SETS, SHAPES, BG_MODES, PARTICLE_STYLES, RANDOM_KNOBS, MIN_TIERS,
                     MAX_TIERS, RESOLUTIONS, QUALITIES, CODECS, ENCODERS, FORMATS)
from .render import render_video, make_thumbnail
from .batch import run_batch
from . import imageprep

CUT_CHOICES = list(imageprep.MODELS) + [imageprep.QUICK]


def _add_look_args(sp) -> None:
    """Common overrides for render / thumb / batch (anything else: put it in a preset .json)."""
    sp.add_argument("--mode", choices=MODES, help="game mode: " + ", ".join(MODES) + " (default merge)")
    sp.add_argument("--picture", help="Drawer: the picture the brush reveals (default: your first tier picture)")
    sp.add_argument("--rings", type=int, help="Escape: number of rings (1-30)")
    sp.add_argument("--gap", type=float, help="Escape: ring gap in degrees")
    sp.add_argument("--ring-spin", type=float, help="Escape: ring spin in degrees/second")
    sp.add_argument("--bricks", type=int, help="Breaker: brick rows")
    sp.add_argument("--length", choices=["15", "30", "45", "60"], help="Shorts length preset")
    sp.add_argument("--seconds", type=float, help="custom max length in seconds")
    sp.add_argument("--until-finished", action="store_true", help="run until the Final Form (cap 180 s)")
    sp.add_argument("--fps", type=int, help="frames per second, 15-120 (24, 30, 50, 60, 120...)")
    sp.add_argument("--res", choices=list(RESOLUTIONS), help="export resolution (9:16)")
    sp.add_argument("--quality", choices=list(QUALITIES))
    sp.add_argument("--codec", choices=CODECS)
    sp.add_argument("--encoder", choices=ENCODERS)
    sp.add_argument("--format", choices=FORMATS)
    sp.add_argument("--no-audio", action="store_true", help="export a silent video")
    sp.add_argument("--music", help="background music file")
    sp.add_argument("--emoji-set", choices=list(EMOJI_SETS), help="use a built-in emoji tier set")
    sp.add_argument("--image-folder", help="folder of tier images (sorted by name)")
    sp.add_argument("--cutout", nargs="?", const=imageprep.DEFAULT_MODEL, choices=CUT_CHOICES,
                    help="AI background removal for tier images (default model: isnet-general-use)")
    sp.add_argument("--reject-text", action="store_true", help="skip tier images that contain text")
    sp.add_argument("--tiers", "--forms", dest="tiers", type=int,
                    help=f"number of forms / tiers ({MIN_TIERS}-{MAX_TIERS})")
    sp.add_argument("--shape", choices=SHAPES)
    sp.add_argument("--gravity", type=float)
    sp.add_argument("--bounce", type=float)
    sp.add_argument("--friction", type=float)
    sp.add_argument("--spin", type=float, help="container spin in degrees/second (negative = other way)")
    sp.add_argument("--ball-scale", type=float)
    sp.add_argument("--drop-interval", type=float)
    sp.add_argument("--bg", choices=BG_MODES, help="background mode")
    sp.add_argument("--bg-colors", help="comma separated hex colours, e.g. '#1a1a40,#ff6f61'")
    sp.add_argument("--bg-angle", type=float)
    sp.add_argument("--bg-image")
    sp.add_argument("--bg-video")
    sp.add_argument("--particles", choices=PARTICLE_STYLES)
    sp.add_argument("--shake", type=float, help="screen shake strength in px (0 = off)")
    sp.add_argument("--hook")
    sp.add_argument("--watermark")
    sp.add_argument("--final-text")
    sp.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="set any config field, e.g. --set ball_glow=0.6 --set show_counter=true (repeatable)")
    # sounds
    sp.add_argument("--sound", help="sound file used for every tier (auto pitched)")
    sp.add_argument("--myinstants", metavar="KEYWORDS",
                    help="fetch sounds from Myinstants for these comma separated keywords, e.g. 'pop' or 'bubble,boing'")
    sp.add_argument("--auto-sounds", action="store_true",
                    help="fetch sounds from Myinstants using the built-in satisfying keyword list")
    sp.add_argument("--sound-strategy", choices=["pitch_up", "sorted"],
                    help="pitch_up = one sound pitched up per tier, sorted = several sounds sorted low->high")
    sp.add_argument("--sound-count", type=int, help="how many different sounds for 'sorted'")
    sp.add_argument("--no-separate-sounds", action="store_true", help="no separate drop / final sounds")
    sp.add_argument("--drop-keyword", help="Myinstants keyword for the drop sound, e.g. 'click'")
    sp.add_argument("--final-keyword", help="Myinstants keyword for the Final Form sound, e.g. 'vine boom'")


def _parse_value(cur, raw: str):
    if isinstance(cur, bool):
        return raw.lower() in ("1", "true", "yes", "on")
    if isinstance(cur, int):
        return int(float(raw))
    if isinstance(cur, float):
        return float(raw)
    if isinstance(cur, list):
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else [v]
        except json.JSONDecodeError:
            return [x.strip() for x in raw.split(",")]
    return raw


def apply_args(cfg: MergeConfig, a) -> MergeConfig:
    if a.length:
        cfg.max_seconds = LENGTH_PRESETS[a.length + "s"]
    simple = {"mode": "mode", "picture": "drawer_picture", "rings": "escape_rings", "gap": "escape_gap_deg", "ring_spin": "escape_spin",
              "bricks": "breaker_rows", "seconds": "max_seconds", "fps": "fps", "tiers": "tiers", "shape": "container_shape",
              "gravity": "gravity", "bounce": "bounce", "friction": "friction", "spin": "container_spin",
              "ball_scale": "ball_scale", "drop_interval": "spawn_interval", "bg": "bg_mode", "bg_angle": "bg_angle",
              "bg_image": "background_image", "bg_video": "background_video", "particles": "particle_style",
              "shake": "shake_strength", "hook": "hook", "watermark": "watermark", "final_text": "final_text",
              "sound": "sound_path", "sound_strategy": "auto_sound_strategy", "sound_count": "auto_sound_count",
              "drop_keyword": "auto_drop_keyword", "final_keyword": "auto_final_keyword",
              "res": "export_resolution", "quality": "export_quality", "codec": "export_codec",
              "encoder": "export_encoder", "format": "export_format", "music": "music_path"}
    for arg, field_ in simple.items():
        v = getattr(a, arg, None)
        if v is not None:
            setattr(cfg, field_, v)
    if a.until_finished:
        cfg.until_finished = True
    if a.no_audio:
        cfg.export_audio = False
    if a.bg_colors:
        cfg.bg_colors = [c.strip() for c in a.bg_colors.split(",") if c.strip()]
        if not a.bg:
            cfg.bg_mode = "gradient" if len(cfg.bg_colors) > 1 else "solid"
    if a.bg_image and not a.bg:
        cfg.bg_mode = "image"
    if a.bg_video and not a.bg:
        cfg.bg_mode = "video"
    if a.emoji_set:
        cfg.tier_emojis = EMOJI_SETS[a.emoji_set][: cfg.tiers]
    if a.image_folder:
        cfg.tier_image_folder = a.image_folder
    if a.cutout:
        cfg.ai_cutout, cfg.cutout_model = True, a.cutout
    if a.reject_text:
        cfg.reject_text = True
    if a.myinstants:
        cfg.auto_sounds, cfg.auto_sound_keywords = True, a.myinstants
    if a.auto_sounds:
        cfg.auto_sounds = True
    if a.no_separate_sounds:
        cfg.auto_sound_separate = False
    for item in a.set:
        k, _, raw = item.partition("=")
        k = k.strip()
        if k not in MergeConfig.__dataclass_fields__:
            raise SystemExit(f"--set: unknown setting '{k}'")
        setattr(cfg, k, _parse_value(getattr(cfg, k), raw))
    cfg.sanitize_export()
    return cfg.clamp()


def sounds_cmd(a) -> None:
    from . import sounds
    if a.action == "search":
        for r in sounds.search(a.query, pages=a.pages):
            print(f"{r.name}\t{r.mp3_url}")
    elif a.action == "fetch":
        print(sounds.download(a.query))
    elif a.action == "analyze":
        print(json.dumps(sounds.analyze(a.query), indent=2))
    elif a.action == "auto":
        print(json.dumps(sounds.auto_plan(a.query, tiers=a.tiers, strategy=a.strategy, count=a.count,
                                          seed=a.seed), indent=2, ensure_ascii=False))
    elif a.action == "cache":
        print(sounds.cache_dir())
        for s in sounds.cached_sounds():
            print(f"{s['name']}\t{s['path']}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="mm911", description="Money Maker 911 renderer")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="render one video (any mode)")
    r.add_argument("--preset", help="preset .json")
    r.add_argument("--seed", type=int)
    r.add_argument("--out", default="output/merge.mp4")
    t = sub.add_parser("thumb", help="save only a thumbnail .jpg")
    t.add_argument("--preset")
    t.add_argument("--seed", type=int)
    t.add_argument("--out", default="output/thumb.jpg")
    b = sub.add_parser("batch", help="render many videos")
    b.add_argument("--preset")
    b.add_argument("--count", type=int, default=10)
    b.add_argument("--out", default="output")
    b.add_argument("--no-random", action="store_true")
    b.add_argument("--allow-fails", action="store_true", help="keep runs that miss the Final Form")
    b.add_argument("--randomize", help="comma separated knobs to vary per video: " + ",".join(RANDOM_KNOBS))
    b.add_argument("--sound-keywords", help="comma separated Myinstants keywords, one picked per video")
    b.add_argument("--no-dedupe", action="store_true", help="don't check new videos for look-alikes")
    b.add_argument("--dedupe-threshold", type=float, help="0.5-1.0 similarity that counts as a duplicate (default 0.9)")
    b.add_argument("--dedupe-action", choices=["skip", "flag"], help="skip = re-render with a new seed, flag = keep + mark")
    d = sub.add_parser("dedupe", help="find look-alike videos in a folder (perceptual hash of sampled frames)")
    d.add_argument("--in", dest="src", required=True, help="folder of videos")
    d.add_argument("--threshold", type=float, default=0.9)
    d.add_argument("--delete", action="store_true", help="delete the newer video of every look-alike pair")
    for sp in (r, t, b):
        _add_look_args(sp)
    c = sub.add_parser("cutout", help="cut out every image in a folder (AI background removal)")
    c.add_argument("--in", dest="src", required=True, help="folder of images")
    c.add_argument("--out", default="output/cutouts")
    c.add_argument("--model", default=imageprep.DEFAULT_MODEL, choices=CUT_CHOICES)
    c.add_argument("--reject-text", action="store_true", help="skip (don't cut) images that contain text")
    s = sub.add_parser("sounds", help="Myinstants: search / fetch / analyze / auto / cache")
    s.add_argument("action", choices=["search", "fetch", "analyze", "auto", "cache"])
    s.add_argument("query", nargs="?", default="", help="keyword(s), instant page URL, mp3 URL or file")
    s.add_argument("--pages", type=int, default=1)
    s.add_argument("--tiers", type=int, default=9)
    s.add_argument("--strategy", choices=["pitch_up", "sorted"], default="sorted")
    s.add_argument("--count", type=int, default=4)
    s.add_argument("--seed", type=int, default=1)
    a = p.parse_args(argv)
    if a.cmd == "sounds":
        return sounds_cmd(a)
    if a.cmd == "dedupe":
        from .dedupe import scan_folder
        pairs = scan_folder(a.src, a.threshold)
        print(json.dumps(pairs, indent=2))
        if a.delete:
            from pathlib import Path
            gone = set()
            for pr in pairs:
                if pr["a"] in gone or pr["b"] in gone:
                    continue
                pa, pb = Path(a.src) / pr["a"], Path(a.src) / pr["b"]
                newer = pb if pb.stat().st_mtime >= pa.stat().st_mtime else pa
                newer.unlink(missing_ok=True)
                newer.with_suffix(".jpg").unlink(missing_ok=True)
                gone.add(newer.name)
                print(f"deleted {newer.name}")
        return
    if a.cmd == "cutout":
        res = imageprep.cutout_folder(a.src, a.out, a.model, a.reject_text, note=lambda m: print(f"\r{m[:70]:70}", end=""))
        print()
        print(json.dumps(res, indent=2))
        return
    cfg = MergeConfig.load(a.preset) if a.preset else MergeConfig()
    apply_args(cfg, a)
    if a.cmd in ("render", "thumb") and a.seed is not None:
        cfg.seed = a.seed
    if a.cmd == "thumb":
        print(json.dumps(make_thumbnail(cfg, a.out), indent=2))
    elif a.cmd == "render":
        print(json.dumps(render_video(cfg, a.out, progress=lambda x: print(f"\r{x*100:5.1f}%", end="")), indent=2))
    else:
        if a.randomize:
            cfg.random_knobs = [k.strip() for k in a.randomize.split(",") if k.strip() in RANDOM_KNOBS]
        if a.no_dedupe:
            cfg.batch_dedupe = False
        if a.dedupe_threshold is not None:
            cfg.dedupe_threshold = a.dedupe_threshold
        if a.dedupe_action:
            cfg.dedupe_action = a.dedupe_action
        if a.sound_keywords:
            cfg.batch_sound_keywords = [k.strip() for k in a.sound_keywords.split(",") if k.strip()]
            if "sound_keyword" not in cfg.random_knobs:
                cfg.random_knobs = list(cfg.random_knobs) + ["sound_keyword"]

        def prog(i, n, x):
            print(f"\rvideo {i + 1}/{n}  {x*100:5.1f}%", end="")
        res = run_batch(cfg, a.count, a.out, randomize=not a.no_random, only_wins=not a.allow_fails, progress=prog)
        print(f"\nDone: {len(res)} videos in {a.out}")


if __name__ == "__main__":
    main()
