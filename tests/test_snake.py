import math

import pytest

from mm911 import render
from mm911.config import MergeConfig


def test_snake_grows_to_target_and_is_deterministic():
    runs = [render.simulate(MergeConfig(mode="snake", seed=4)) for _ in range(2)]
    assert runs[0].won and runs[0].length == runs[0].total == 30
    assert runs[0].finished_at == runs[1].finished_at
    assert 5 < runs[0].finished_at < 60


@pytest.mark.parametrize("kw", [dict(snake_target=5), dict(snake_target=120), dict(snake_speed=300), dict(snake_speed=3000),
                                dict(snake_turn=1.5), dict(snake_radius=60), dict(snake_radius=8), dict(tiers=3), dict(tiers=15)])
def test_snake_settings_finish_and_stay_inside(kw):
    sim = render.make_sim(MergeConfig(mode="snake", seed=2, until_finished=True, **kw))
    x0, y0, x1, y1 = sim.arena
    while not sim.done:
        sim.step(1 / 60)
        for b in sim.balls:
            p = b.shape.body.position
            assert x0 - 2 <= p.x <= x1 + 2 and y0 - 2 <= p.y <= y1 + 2
    assert sim.won and len(sim.balls) == sim.total


def test_snake_body_is_connected_and_head_is_last():
    sim = render.make_sim(MergeConfig(mode="snake", seed=7))
    for _ in range(600):
        sim.step(1 / 60)
    pts = [b.shape.body.position for b in sim.balls]
    for a, b in zip(pts, pts[1:]):
        assert math.hypot(a.x - b.x, a.y - b.y) <= 2.1 * sim._spacing
    assert sim.balls[-1].scale_k > 1.0


def test_snake_bad_values_clamped_and_draw():
    c = MergeConfig.from_dict({"mode": "snake", "snake_target": 0, "snake_speed": "x", "snake_turn": -1, "snake_radius": 9999})
    c.clamp()
    assert c.snake_target == 5 and c.snake_speed >= 200 and c.snake_turn >= 1.5 and c.snake_radius <= 60
    c.width, c.height = 360, 640
    sim = render.make_sim(c)
    r = render.make_renderer(c, 1.0)
    for _ in range(300):
        sim.step(1 / 60)
        r.draw(sim)
    assert r.draw(sim).get_size() == (360, 640)


def test_snake_video_smoke(tmp_path):
    cfg = MergeConfig.load("presets/snake_grow.json")
    cfg.width, cfg.height, cfg.max_seconds, cfg.fps = 360, 640, 3, 24
    out = tmp_path / "s.mp4"
    render.render_video(cfg, str(out))
    assert out.stat().st_size > 5000
