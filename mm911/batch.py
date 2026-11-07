"""Batch factory: many unique videos + titles CSV, with an anti-repeat shuffle."""
from __future__ import annotations

import csv
import random
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .config import MergeConfig, PALETTES, SHAPES, HOOKS
from .render import render_video, simulate

EMOJI = {"Fruit": "🍉", "Animal": "🐾", "Planet": "🪐", "Food": "🍔", "Gem": "💎", "Sport": "⚽", "Meme": "😂"}


def make_title(cfg: MergeConfig) -> str:
    e = EMOJI.get(cfg.theme_name, "✨")
    return f"{cfg.theme_name} Merge {e} {cfg.hook} #shorts"


def vary(base: MergeConfig, i: int, rng: random.Random, randomize: bool) -> MergeConfig:
    if not randomize:
        return replace(base, seed=base.seed + i)
    pals = list(PALETTES)
    shapes = [s for s in SHAPES if s not in ("star",)]
    # rotate (not random) so neighbours never repeat
    return replace(
        base,
        seed=rng.randint(1, 10_000_000),
        palette=pals[(pals.index(base.palette) + i) % len(pals)] if base.palette in pals else rng.choice(pals),
        container_shape=shapes[i % len(shapes)],
        hook=HOOKS[i % len(HOOKS)],
        container_spin=rng.choice([0, 0, 0, 12, -12, 20]),
        spawn_interval=round(base.spawn_interval * rng.uniform(0.9, 1.15), 3),
    )


def run_batch(base: MergeConfig, count: int, out_dir: str, randomize: bool = True, only_wins: bool = True,
              progress: Callable[[int, int, float], None] | None = None,
              stop: Callable[[], bool] | None = None, lock=None) -> list[dict]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(base.seed)
    results = []
    for i in range(count):
        if stop and stop():
            break
        cfg = vary(base, i, rng, randomize)
        if only_wins:  # fast physics-only check, retry seeds until it reaches the Final Form
            for _ in range(25):
                if simulate(cfg).won:
                    break
                cfg = replace(cfg, seed=rng.randint(1, 10_000_000))
        name = f"{cfg.theme_name.lower()}_merge_{i + 1:03d}_{cfg.seed}.mp4"
        meta = render_video(cfg, str(out / name),
                            progress=(lambda p, i=i: progress(i, count, p)) if progress else None, lock=lock)
        meta["title"] = make_title(cfg)
        meta["description"] = f"{cfg.theme_name} merge simulation. {cfg.hook} #shorts #satisfying #merge"
        meta["hashtags"] = "#shorts #satisfying #merge #simulation"
        meta["palette"], meta["shape"] = cfg.palette, cfg.container_shape
        results.append(meta)
        with open(out / "titles.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader()
            w.writerows(results)
    return results
