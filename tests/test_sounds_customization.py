"""Offline tests for Myinstants parsing / pitch mapping and the deep Merge customization (no network)."""
import json

import numpy as np

from mm911 import sounds
from mm911.config import MergeConfig, MAX_TIERS, SHAPES, PARTICLE_STYLES
from mm911.modes.merge import MergeSim, container_points
from mm911.render import Renderer, simulate, make_thumbnail
from mm911.batch import vary

SEARCH_HTML = """
<div class="instant"><button class="small-button" onclick="play('/media/sounds/pop_7e9Is8L.mp3', 'loader-1', 'pop-sfx-75405')" title="Play Pop SFX sound" type="button"></button>
<button type="button" class="webshare instant-action-button" onclick="share('Pop SFX', 'https://www.myinstants.com/en/instant/pop-sfx-75405/', '/media/sounds/pop_7e9Is8L.mp3', 'pop-sfx-75405')"></button></div>
<div class="instant"><button onclick="share('It\\'s a \\u002D boing &amp; more', 'https://www.myinstants.com/en/instant/b/', '/media/sounds/boing.mp3', 'b')"></button></div>
"""


def test_parse_search():
    res = sounds.parse_search(SEARCH_HTML)
    assert [r.name for r in res] == ["Pop SFX", "It's a - boing & more"]
    assert res[0].mp3_url == "https://www.myinstants.com/media/sounds/pop_7e9Is8L.mp3"


def test_tier_pitches_rise_low_to_high():
    measured = [800, 800, 800, 1500, 1500, 1500, 2600, 2600, 2600]
    shifts = sounds.tier_pitches(measured, 9, step=1.6)
    final = [sounds.semitones(h) + s for h, s in zip(measured, shifts)]
    assert all(b > a for a, b in zip(final, final[1:]))
    assert shifts[0] == 0


def test_auto_offline_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("MM911_SOUND_CACHE", str(tmp_path))

    def offline(*a, **k):
        raise ConnectionError("offline")
    monkeypatch.setattr(sounds, "_get", offline)
    cfg = MergeConfig(auto_sounds=True, auto_sound_keywords="pop")
    sounds.resolve_auto(cfg)                     # must not raise
    assert cfg.sound_path == "" and cfg.tier_sounds == []


def test_soundbank_pitch_order():
    from mm911.audio import SoundBank
    cfg = MergeConfig(tier_semitones=[0, None, 9])
    bank = SoundBank(cfg)
    assert bank.event("merge", 1)[1] == 1.6       # auto
    assert bank.event("merge", 2)[1] == 9         # manual override
    assert bank.event("final", 8)[1] > bank.event("merge", 8)[1]


def test_every_shape_and_style_renders(tmp_path):
    for i, shape in enumerate(SHAPES):
        c = MergeConfig(container_shape=shape, max_seconds=1.5, fps=20, particle_style=PARTICLE_STYLES[i % 6],
                        container_points=[[-1, -0.5], [0, 1], [1, -0.5]], bg_mode="gradient",
                        bg_colors=["#112233", "#445566", "#778899"], ball_glow=0.5, ball_shadow=0.5,
                        ball_outline=3, show_counter=True, show_progress_bar=True, shake_strength=8)
        assert len(container_points(shape, 0, 0, 100, custom=c.container_points)) >= 3
        sim, rend = MergeSim(c), Renderer(c, 0.25)
        while not sim.done:
            sim.step(1 / c.fps)
            rend.draw(sim)
        rend.close()


def test_sizes_fit_and_curves():
    for curve in ("exponential", "linear"):
        for n in (3, 9, MAX_TIERS):
            c = MergeConfig(tiers=n, size_curve=curve)
            r = [c.tier_radius(t) for t in range(n)]
            assert r == sorted(r) and r[-1] <= c.container_radius * 0.7 + 1e-6
    c = MergeConfig(size_curve="custom", tier_sizes=[10, 20, 9999])
    assert c.tier_radius(2) <= c.container_radius * 0.95


def test_seeds_unchanged_by_visual_settings():
    base = dict(seed=3, max_seconds=12, fps=30)
    a = simulate(MergeConfig(**base))
    b = simulate(MergeConfig(**base, particle_colors=["#fff", "#000"], particle_style="stars", shake_strength=10))
    assert (a.merges, a.best_tier) == (b.merges, b.best_tier)


def test_batch_knobs_and_presets(tmp_path):
    import random
    base = MergeConfig(random_knobs=["tiers", "background", "particles", "sound_keyword"],
                       batch_sound_keywords=["pop", "boing"])
    cfgs = [vary(base, i, random.Random(1), True) for i in range(4)]
    assert {c.auto_sound_keywords for c in cfgs} == {"pop", "boing"}
    assert all(c.bg_mode == "gradient" for c in cfgs)
    from pathlib import Path
    for p in Path(__file__).resolve().parent.parent.glob("presets/*.json"):
        MergeConfig.from_dict(json.loads(p.read_text(encoding="utf-8")))
