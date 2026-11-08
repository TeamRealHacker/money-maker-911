"""Command line: `python -m mm911.cli render ...` / `batch ...` (also used by Colab later)."""
from __future__ import annotations

import argparse
import json

from .config import MergeConfig
from .config import LENGTH_PRESETS, EMOJI_SETS
from .render import render_video, make_thumbnail
from .batch import run_batch


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="mm911", description="Money Maker 911 renderer")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="render one Merge video")
    r.add_argument("--preset", help="preset .json")
    r.add_argument("--seed", type=int)
    r.add_argument("--out", default="output/merge.mp4")
    t = sub.add_parser("thumb", help="save only a thumbnail .jpg")
    t.add_argument("--preset")
    t.add_argument("--seed", type=int)
    t.add_argument("--out", default="output/thumb.jpg")
    for sp in (r, t):
        sp.add_argument("--length", choices=["30", "45", "60"], help="Shorts length preset")
        sp.add_argument("--emoji-set", choices=list(EMOJI_SETS), help="use a built-in emoji tier set")
        sp.add_argument("--image-folder", help="folder of tier images (sorted by name)")
        sp.add_argument("--cutout", action="store_true", help="AI background removal (needs rembg)")
        sp.add_argument("--cutout-model", default="birefnet-general", choices=["birefnet-general","isnet-general-use","u2net"])
        sp.add_argument("--reject-text", action="store_true", help="skip images containing text (needs rapidocr)")
    b = sub.add_parser("batch", help="render many videos")
    b.add_argument("--preset")
    b.add_argument("--count", type=int, default=10)
    b.add_argument("--out", default="output")
    b.add_argument("--no-random", action="store_true")
    b.add_argument("--length", choices=["30", "45", "60"])
    b.add_argument("--emoji-set", choices=list(EMOJI_SETS))
    b.add_argument("--image-folder")
    b.add_argument("--cutout", action="store_true")
    b.add_argument("--cutout-model", default="birefnet-general")
    b.add_argument("--reject-text", action="store_true")
    b.add_argument("--allow-fails", action="store_true", help="keep runs that miss the Final Form")
    a = p.parse_args(argv)
    cfg = MergeConfig.load(a.preset) if a.preset else MergeConfig()
    if a.length:
        cfg.max_seconds = LENGTH_PRESETS[a.length + "s"]
    if a.emoji_set:
        cfg.tier_emojis = EMOJI_SETS[a.emoji_set][: cfg.tiers]
    if a.cutout:
        cfg.ai_cutout, cfg.cutout_model = True, a.cutout_model
    if a.reject_text:
        cfg.reject_text_images = True
    if a.image_folder:
        cfg.tier_image_folder = a.image_folder
    if a.cmd in ("render", "thumb") and a.seed is not None:
        cfg.seed = a.seed
    if a.cmd == "thumb":
        print(json.dumps(make_thumbnail(cfg, a.out), indent=2))
    elif a.cmd == "render":
        print(json.dumps(render_video(cfg, a.out, progress=lambda x: print(f"\r{x*100:5.1f}%", end="")), indent=2))
    else:
        def prog(i, n, x):
            print(f"\rvideo {i + 1}/{n}  {x*100:5.1f}%", end="")
        res = run_batch(cfg, a.count, a.out, randomize=not a.no_random, only_wins=not a.allow_fails, progress=prog)
        print(f"\nDone: {len(res)} videos in {a.out}")


if __name__ == "__main__":
    main()
