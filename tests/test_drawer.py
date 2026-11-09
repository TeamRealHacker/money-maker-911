import numpy as np
import pygame
import pytest

from mm911 import render
from mm911.config import MergeConfig


def test_drawer_wins_and_is_deterministic():
    runs = []
    for _ in range(2):
        sim = render.simulate(MergeConfig(mode="drawer", seed=4))
        runs.append((sim.won, round(sim.finished_at, 3), len(sim.paint_log)))
    assert runs[0] == runs[1] and runs[0][0]
    assert 5 < runs[0][1] < 55          # fits a Short


@pytest.mark.parametrize("kw", [dict(drawer_balls=3), dict(drawer_brush=6), dict(drawer_target=100), dict(drawer_brush=2.0)])
def test_drawer_settings_still_finish(kw):
    sim = render.simulate(MergeConfig(mode="drawer", seed=2, until_finished=True, **kw))
    assert sim.won and sim.pct == 100


def test_drawer_bad_values_are_clamped():
    c = MergeConfig.from_dict({"mode": "drawer", "drawer_brush": "x", "drawer_balls": -3, "drawer_target": 9999, "drawer_ghost": 5})
    c.clamp()
    assert 2 <= c.drawer_brush <= 6 and c.drawer_balls == 1 and c.drawer_target == 100 and c.drawer_ghost <= 0.8
    assert c.hook == "Can it paint the whole picture?"        # the untouched default hook follows the mode


def test_drawer_renders_picture_where_the_brush_went(tmp_path):
    from PIL import Image
    pic = tmp_path / "p.png"
    Image.new("RGB", (400, 600), (10, 200, 30)).save(pic)
    cfg = MergeConfig(mode="drawer", seed=3, drawer_picture=str(pic), width=540, height=960)
    sim = render.make_sim(cfg)
    r = render.make_renderer(cfg, 1.0)
    for _ in range(240):
        sim.step(1 / 60)
    surf = r.draw(sim)
    arr = pygame.surfarray.array3d(surf)
    green = ((arr[..., 1] > 150) & (arr[..., 0] < 60)).sum()
    assert green > 20000                    # painted area shows the picture
    assert sim.pct > 5
    # a fresh sim on the same renderer starts from the unpainted canvas again
    sim2 = render.make_sim(cfg)
    arr2 = pygame.surfarray.array3d(r.draw(sim2))
    assert ((arr2[..., 1] > 150) & (arr2[..., 0] < 60)).sum() < green // 4


def test_drawer_broken_picture_falls_back(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    cfg = MergeConfig(mode="drawer", seed=1, drawer_picture=str(bad), width=360, height=640)
    sim = render.make_sim(cfg)
    r = render.make_renderer(cfg, 1.0)
    for _ in range(60):
        sim.step(1 / 60)
    assert r.draw(sim).get_width() == 360


def test_drawer_video_smoke(tmp_path):
    out = tmp_path / "d.mp4"
    cfg = MergeConfig.load("presets/drawer_art.json")
    cfg.max_seconds, cfg.fps, cfg.width, cfg.height = 3, 24, 360, 640
    render.render_video(cfg, str(out))
    assert out.stat().st_size > 5000
