"""🥛 Glass Rush: every seed shatters all rings, hits crack them, pitch rises, renders, CLI + batch."""
import os
import random
import tempfile
from pathlib import Path

os.environ.setdefault("APPDATA", os.path.join(tempfile.gettempdir(), "mm911_test_appdata"))

import pygame  # noqa: E402

from mm911.config import MergeConfig  # noqa: E402
from mm911.modes.glass import ring_hp  # noqa: E402
from mm911.render import render_video, simulate, make_sim, make_renderer, make_thumbnail  # noqa: E402
from mm911.batch import vary, make_title  # noqa: E402
from mm911.cli import main as cli_main  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_glass_always_shatters_and_is_deterministic():
    for s in range(1, 6):
        sim = simulate(MergeConfig(mode="glass", seed=s))
        assert sim.won and sim.escaped == len(sim.rings)
        assert 8 < sim.finished_at < 40          # a Shorts-sized video, not 5 s and not endless
    a, b = simulate(MergeConfig(mode="glass", seed=3)), simulate(MergeConfig(mode="glass", seed=3))
    assert (a.finished_at, a.hits) == (b.finished_at, b.hits)


def test_hits_equal_ring_toughness_and_pitch_rises():
    cfg = MergeConfig(mode="glass", seed=2)
    sim = simulate(cfg)
    assert sim.hits >= sum(ring_hp(cfg, i) for i in range(cfg.escape_rings))
    p = [e.pitch for e in sim.events if e.kind == "merge"]
    assert p == sorted(p) and p[0] < p[-1]
    assert any(e.kind == "final" for e in sim.events)


def test_cracks_appear_and_bad_values_are_clamped():
    cfg = MergeConfig(mode="glass", seed=1, glass_hp=99, glass_hp_growth=-5, glass_spin=-1, glass_speed_gain=9)
    sim = make_sim(cfg)
    assert (cfg.glass_hp, cfg.glass_hp_growth, cfg.glass_spin, cfg.glass_speed_gain) == (12, 0.0, 0.0, 0.3)
    for _ in range(60 * 4):
        sim.step(1 / 60)
    assert sim.hits > 0 and any(sim.cracks.values())
    assert all(len(line) >= 2 for ls in sim.cracks.values() for line in ls)


def test_glass_frame_draws_cracks():
    cfg = MergeConfig(mode="glass", seed=1, bg_mode="solid", bg_colors=["#000000"], hook="", glass_counter_text="",
                      escape_ring_glow=0)
    sim = make_sim(cfg)
    for _ in range(60 * 3):
        sim.step(1 / 60)
    rend = make_renderer(cfg, 0.5)
    arr = pygame.surfarray.array3d(rend.draw(sim))
    assert arr.max() > 200 and arr.sum() > 0       # rings, ball and crack lines drawn on black
    rend.close()


def test_glass_render_thumb_cli_batch(tmp_path):
    cfg = MergeConfig.load(ROOT / "presets" / "glass_rush.json")
    assert cfg.mode == "glass"
    cfg.max_seconds, cfg.fps, cfg.export_resolution = 3, 24, "720p"
    meta = render_video(cfg, str(tmp_path / "g.mp4"))
    assert meta["mode"] == "glass" and meta["rings"] == 8 and Path(meta["file"]).stat().st_size > 10_000
    assert cli_main(["thumb", "--mode", "glass", "--seed", "2", "--out", str(tmp_path / "t.jpg")]) in (0, None)
    assert (tmp_path / "t.jpg").stat().st_size > 5_000
    for i in range(4):
        c = vary(MergeConfig(mode="glass"), i, random.Random(1), True)
        assert c.mode == "glass" and 3 <= c.escape_rings <= 30 and 2 <= c.glass_hp <= 10
    assert "glass" in make_title(MergeConfig(mode="glass")).lower()
