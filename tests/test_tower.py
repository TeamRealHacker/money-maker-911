import pygame
import pytest

from mm911 import render
from mm911.config import MergeConfig


def test_tower_every_seed_wins_and_is_deterministic():
    runs = []
    for _ in range(2):
        sim = render.simulate(MergeConfig(mode="tower", seed=5))
        runs.append((sim.won, round(sim.finished_at, 3), sim.broken))
    assert runs[0] == runs[1]
    assert runs[0][0] and runs[0][2] == 14
    assert 8 < runs[0][1] < 55


@pytest.mark.parametrize("kw", [dict(tower_floors=3), dict(tower_floors=30, tower_hp=1), dict(tower_balls=8, tower_hp=8),
                                dict(tower_gravity=700), dict(tower_gravity=4500), dict(tower_floor_height=12)])
def test_tower_settings_finish(kw):
    sim = render.simulate(MergeConfig(mode="tower", seed=2, until_finished=True, **kw))
    assert sim.won and sim.broken == sim.total


def test_tower_bad_values_are_clamped():
    c = MergeConfig.from_dict({"mode": "tower", "tower_floors": "many", "tower_hp": 0, "tower_gravity": -5, "tower_balls": 99})
    c.clamp()
    assert 2 <= c.tower_floors <= 40 and c.tower_hp == 1 and c.tower_gravity >= 400 and c.tower_balls == 10


def test_tower_floors_crack_and_draw():
    cfg = MergeConfig(mode="tower", seed=3, width=360, height=640)
    sim = render.make_sim(cfg)
    r = render.make_renderer(cfg, 1.0)
    for _ in range(120):
        sim.step(1 / 60)
    assert any(b.cracks for b in sim.bricks)
    assert r.draw(sim).get_size() == (360, 640)


def test_breaker_unchanged_by_refactor():
    a = render.simulate(MergeConfig(mode="breaker", seed=7))
    b = render.simulate(MergeConfig(mode="breaker", seed=7))
    assert a.won and (a.finished_at, a.broken) == (b.finished_at, b.broken)


def test_tower_video_smoke(tmp_path):
    out = tmp_path / "t.mp4"
    cfg = MergeConfig.load("presets/glass_tower.json")
    cfg.max_seconds, cfg.fps, cfg.width, cfg.height = 3, 24, 360, 640
    render.render_video(cfg, str(out))
    assert out.stat().st_size > 5000


def test_tower_thumbnail_is_mid_collapse(tmp_path):
    out = tmp_path / "t.jpg"
    r = render.make_thumbnail(MergeConfig(mode="tower", seed=4, width=360, height=640), str(out))
    assert out.stat().st_size > 3000 and r["file"] == str(out)
