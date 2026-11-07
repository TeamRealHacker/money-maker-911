"""Command line: `python -m mm911.cli render ...` / `batch ...` (also used by Colab later)."""
from __future__ import annotations

import argparse
import json

from .config import MergeConfig
from .config import LENGTH_PRESETS, EMOJI_SETS, RESOLUTIONS, QUALITIES, CODECS, ENCODERS, FORMATS
from .render import render_video, make_thumbnail
from .batch import run_batch
from . import imageprep

CUT_CHOICES = list(imageprep.MODELS) + [imageprep.QUICK]


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
    b = sub.add_parser("batch", help="render many videos")
    b.add_argument("--preset")
    b.add_argument("--count", type=int, default=10)
    b.add_argument("--out", default="output")
    b.add_argument("--no-random", action="store_true")
    b.add_argument("--allow-fails", action="store_true", help="keep runs that miss the Final Form")
    for sp in (r, t, b):
        sp.add_argument("--length", choices=["30", "45", "60"], help="Shorts length preset")
        sp.add_argument("--emoji-set", choices=list(EMOJI_SETS), help="use a built-in emoji tier set")
        sp.add_argument("--image-folder", help="folder of tier images (sorted by name)")
        sp.add_argument("--cutout", nargs="?", const=imageprep.DEFAULT_MODEL, choices=CUT_CHOICES,
                        help="AI background removal for tier images (default model: isnet-general-use)")
        sp.add_argument("--reject-text", action="store_true", help="skip tier images that contain text")
        sp.add_argument("--fps", type=int, help="frames per second, 15-120 (24, 30, 50, 60, 120...)")
        sp.add_argument("--res", choices=list(RESOLUTIONS), help="export resolution (9:16)")
        sp.add_argument("--quality", choices=list(QUALITIES))
        sp.add_argument("--codec", choices=CODECS)
        sp.add_argument("--encoder", choices=ENCODERS)
        sp.add_argument("--format", choices=FORMATS)
        sp.add_argument("--no-audio", action="store_true", help="export a silent video")
        sp.add_argument("--sound", help="sound file for drops/merges (mp3, wav...)")
        sp.add_argument("--music", help="background music file")
    c = sub.add_parser("cutout", help="cut out every image in a folder (AI background removal)")
    c.add_argument("--in", dest="src", required=True, help="folder of images")
    c.add_argument("--out", default="output/cutouts")
    c.add_argument("--model", default=imageprep.DEFAULT_MODEL, choices=CUT_CHOICES)
    c.add_argument("--reject-text", action="store_true", help="skip (don't cut) images that contain text")
    a = p.parse_args(argv)
    if a.cmd == "cutout":
        res = imageprep.cutout_folder(a.src, a.out, a.model, a.reject_text, note=lambda m: print(f"\r{m[:70]:70}", end=""))
        print()
        print(json.dumps(res, indent=2))
        return
    cfg = MergeConfig.load(a.preset) if a.preset else MergeConfig()
    if a.length:
        cfg.max_seconds = LENGTH_PRESETS[a.length + "s"]
    if a.emoji_set:
        cfg.tier_emojis = EMOJI_SETS[a.emoji_set][: cfg.tiers]
    if a.image_folder:
        cfg.tier_image_folder = a.image_folder
    if a.cutout:
        cfg.ai_cutout, cfg.cutout_model = True, a.cutout
    if a.reject_text:
        cfg.reject_text = True
    for arg, attr in (("fps", "fps"), ("res", "export_resolution"), ("quality", "export_quality"),
                      ("codec", "export_codec"), ("encoder", "export_encoder"), ("format", "export_format"),
                      ("sound", "sound_path"), ("music", "music_path")):
        if getattr(a, arg) is not None:
            setattr(cfg, attr, getattr(a, arg))
    if a.no_audio:
        cfg.export_audio = False
    cfg.sanitize_export()
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
