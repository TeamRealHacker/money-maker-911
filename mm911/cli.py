"""Command line: `python -m mm911.cli render ...` / `batch ...` (also used by Colab later)."""
from __future__ import annotations

import argparse
import json

from .config import MergeConfig
from .render import render_video
from .batch import run_batch


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="mm911", description="Money Maker 911 renderer")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render", help="render one Merge video")
    r.add_argument("--preset", help="preset .json")
    r.add_argument("--seed", type=int)
    r.add_argument("--out", default="output/merge.mp4")
    b = sub.add_parser("batch", help="render many videos")
    b.add_argument("--preset")
    b.add_argument("--count", type=int, default=10)
    b.add_argument("--out", default="output")
    b.add_argument("--no-random", action="store_true")
    b.add_argument("--allow-fails", action="store_true", help="keep runs that miss the Final Form")
    a = p.parse_args(argv)
    cfg = MergeConfig.load(a.preset) if a.preset else MergeConfig()
    if a.cmd == "render":
        if a.seed is not None:
            cfg.seed = a.seed
        print(json.dumps(render_video(cfg, a.out, progress=lambda x: print(f"\r{x*100:5.1f}%", end="")), indent=2))
    else:
        def prog(i, n, x):
            print(f"\rvideo {i + 1}/{n}  {x*100:5.1f}%", end="")
        res = run_batch(cfg, a.count, a.out, randomize=not a.no_random, only_wins=not a.allow_fails, progress=prog)
        print(f"\nDone: {len(res)} videos in {a.out}")


if __name__ == "__main__":
    main()
