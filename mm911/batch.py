"""Batch factory: many unique videos + titles CSV, with an anti-repeat shuffle."""
from __future__ import annotations

import csv
import os
import re
import random
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .config import BREAKER_PATTERNS
from .config import MergeConfig, PALETTES, SHAPES, HOOKS, PARTICLE_STYLES, SATISFYING_KEYWORDS, MIN_TIERS, MAX_TIERS
from .render import render_video, simulate
from .dedupe import HashBook, check

EMOJI = {"Fruit": "🍉", "Animal": "🐾", "Planet": "🪐", "Food": "🍔", "Gem": "💎", "Sport": "⚽", "Meme": "😂"}


MODE_WORD = {"merge": ("Merge", "#merge"), "escape": ("Escape", "#escape #rings"),
             "breaker": ("Breaker", "#breaker #bricks"), "glass": ("Glass Rush", "#glass #asmr")}


def make_title(cfg: MergeConfig) -> str:
    word = MODE_WORD.get(cfg.mode, MODE_WORD["merge"])[0]
    if cfg.mode == "escape":
        return f"Can it escape? 🌀 {cfg.hook} #shorts"
    if cfg.mode == "glass":
        return f"Will the glass hold? 🥛 {cfg.hook} #shorts"
    if cfg.mode == "breaker":
        return f"Brick Breaker 🧱 {cfg.hook} #shorts"
    e = EMOJI.get(cfg.theme_name, "✨")
    return f"{cfg.theme_name} {word} {e} {cfg.hook} #shorts"


def make_description(cfg: MergeConfig) -> tuple[str, str]:
    word, tags = MODE_WORD.get(cfg.mode, MODE_WORD["merge"])
    hashtags = f"#shorts #satisfying {tags} #simulation"
    return f"{cfg.theme_name} {word.lower()} simulation. {cfg.hook} {hashtags}", hashtags


def _hsv_hex(rng: random.Random, s: float, v: float) -> str:
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(rng.random(), s, v)
    return "#%02X%02X%02X" % (int(r * 255), int(g * 255), int(b * 255))


def vary(base: MergeConfig, i: int, rng: random.Random, randomize: bool) -> MergeConfig:
    """One batch video's settings. Only the knobs ticked in base.random_knobs change."""
    if not randomize:
        return replace(base, seed=base.seed + i)
    knobs = set(base.random_knobs or [])
    pals = list(PALETTES)
    shapes = [s for s in SHAPES if s not in ("star", "custom", "triangle")]
    ch: dict = {"seed": rng.randint(1, 10_000_000)}
    # rotate (not random) so neighbours never repeat
    if "palette" in knobs:
        ch["palette"] = pals[(pals.index(base.palette) + i) % len(pals)] if base.palette in pals else rng.choice(pals)
    if "shape" in knobs:
        ch["container_shape"] = shapes[i % len(shapes)]
    if "hook" in knobs:
        ch["hook"] = HOOKS[i % len(HOOKS)]
    if "spin" in knobs:
        ch["container_spin"] = rng.choice([0, 0, 0, 12, -12, 20, -20])
    if "drop_interval" in knobs:
        ch["spawn_interval"] = round(base.spawn_interval * rng.uniform(0.9, 1.15), 3)
    if "gravity" in knobs:
        ch["gravity"] = round(base.gravity * rng.uniform(0.8, 1.25))
    if "bounce" in knobs:
        ch["bounce"] = round(min(0.8, max(0.0, base.bounce + rng.uniform(-0.08, 0.2))), 2)
    if "friction" in knobs:
        ch["friction"] = round(min(1.0, max(0.05, base.friction * rng.uniform(0.6, 1.4))), 2)
    if "ball_size" in knobs:
        ch["ball_scale"] = round(base.ball_scale * rng.uniform(0.9, 1.08), 3)
    if "tiers" in knobs:
        ch["tiers"] = max(MIN_TIERS, min(MAX_TIERS, base.tiers + rng.choice([-1, 0, 0, 1])))
    if "background" in knobs:
        ch["bg_mode"] = "gradient"
        ch["bg_colors"] = [_hsv_hex(rng, 0.35, 0.95), _hsv_hex(rng, 0.45, 0.75)]
        ch["bg_angle"] = rng.choice([90, 90, 60, 120, 45])
    if "particles" in knobs:
        ch["particle_style"] = PARTICLE_STYLES[(PARTICLE_STYLES.index(base.particle_style) + i) % len(PARTICLE_STYLES)] \
            if base.particle_style in PARTICLE_STYLES else rng.choice(PARTICLE_STYLES)
    if "container_color" in knobs:
        ch["container_color"] = _hsv_hex(rng, 0.55, 0.6)
    if "sound_keyword" in knobs:
        pool = [k for k in (base.batch_sound_keywords or []) if k.strip()] or SATISFYING_KEYWORDS
        ch["auto_sounds"] = True
        ch["auto_sound_keywords"] = pool[i % len(pool)] if len(pool) > 1 else pool[0]
    if base.mode == "escape":      # the Merge-only knobs mean something else here
        ch.pop("container_shape", None)
        if "shape" in knobs:
            ch["escape_rings"] = max(3, min(30, base.escape_rings + (i % 3) - 1))
        if "spin" in knobs:
            ch["escape_spin"] = round(base.escape_spin * rng.uniform(0.8, 1.3), 1)
            ch["escape_alternate"] = rng.random() < 0.7
        if "drop_interval" in knobs:
            ch["escape_gap_deg"] = round(base.escape_gap_deg * rng.uniform(0.9, 1.12), 1)
        ch.pop("container_spin", None)
        ch.pop("spawn_interval", None)
    elif base.mode == "glass":
        for k in ("container_shape", "container_spin", "spawn_interval"):
            ch.pop(k, None)
        if "shape" in knobs:
            ch["escape_rings"] = max(3, min(30, base.escape_rings + (i % 3) - 1))
        if "spin" in knobs:
            ch["glass_spin"] = round(base.glass_spin * rng.uniform(0.7, 1.4), 1)
            ch["escape_alternate"] = rng.random() < 0.7
        if "drop_interval" in knobs:
            ch["glass_hp"] = max(2, min(10, base.glass_hp + rng.choice([-1, 0, 1])))
    elif base.mode == "breaker":
        ch.pop("container_shape", None)
        ch.pop("container_spin", None)
        ch.pop("spawn_interval", None)
        if "shape" in knobs:
            ch["breaker_pattern"] = BREAKER_PATTERNS[i % len(BREAKER_PATTERNS)]
        if "spin" in knobs:
            ch["breaker_balls"] = max(1, min(6, base.breaker_balls + rng.choice([0, 0, 1])))
    cfg = replace(base, **ch)
    if "tiers" in knobs and cfg.tier_emojis:
        cfg.tier_emojis = list(cfg.tier_emojis)[: cfg.tiers]
    return cfg


def run_batch(base: MergeConfig, count: int, out_dir: str, randomize: bool = True, only_wins: bool = True,
              progress: Callable[[int, int, float], None] | None = None,
              stop: Callable[[], bool] | None = None, lock=None) -> list[dict]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(base.seed)
    book = HashBook(out) if base.batch_dedupe else None
    results = []
    for i in range(count):
        if stop and stop():
            break
        cfg = vary(base, i, rng, randomize)
        meta = None
        for attempt in range(3 if (book and base.dedupe_action == "skip") else 1):
            if only_wins:  # fast physics-only check, retry seeds until it wins
                for _ in range(25):
                    if simulate(cfg).won:
                        break
                    cfg = replace(cfg, seed=rng.randint(1, 10_000_000))
            safe = re.sub(r"[^\w\-]+", "_", cfg.theme_name.lower()).strip("_") or "video"   # Windows-safe file name
            name = f"{safe}_{cfg.mode}_{i + 1:03d}_{cfg.seed}.mp4"
            meta = render_video(cfg, str(out / name),
                                progress=(lambda p, i=i: progress(i, count, p)) if progress else None, lock=lock)
            if not book:
                break
            chk = check(meta["file"], book, base.dedupe_threshold)
            meta["similarity"] = chk["score"]
            meta["similar_to"] = chk["match"] if chk["duplicate"] else ""
            if chk["duplicate"] and base.dedupe_action == "skip" and attempt < 2:
                for f in (meta["file"], meta.get("thumbnail")):     # too close to an earlier video: redo it
                    if f:
                        try:
                            os.remove(f)
                        except OSError:
                            pass
                cfg = replace(cfg, seed=rng.randint(1, 10_000_000))
                continue
            book.add(Path(meta["file"]).name, chk["sig"])
            break
        meta["title"] = make_title(cfg)
        meta["description"], meta["hashtags"] = make_description(cfg)
        meta["palette"], meta["shape"] = cfg.palette, cfg.container_shape
        meta["sounds"] = ", ".join(meta.get("sounds") or []) or "built-in"
        if cfg.auto_sounds:
            meta["sound_keyword"] = cfg.auto_sound_keywords or "auto"
        results.append(meta)
        with open(out / "titles.csv", "w", newline="", encoding="utf-8-sig") as f:
            keys = list(dict.fromkeys(k for r in results for k in r))
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(results)
    return results
