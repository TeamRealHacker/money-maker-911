import pytest

from mm911 import render
from mm911.config import MergeConfig
from mm911.modes.flip import flip_sequence
import random


def test_flip_sequences_never_repeat_a_direction():
    for pat in ("updown", "spin", "random"):
        s = flip_sequence(pat, 40, random.Random(1))
        assert len(s) == 41 and s[0] == "down"
        assert all(a != b for a, b in zip(s, s[1:]))
    assert flip_sequence("spin", 4, random.Random(0)) == ["down", "right", "up", "left", "down"]


def test_flip_wins_on_schedule_and_is_deterministic():
    c = MergeConfig(mode="flip", seed=5)
    runs = [render.simulate(MergeConfig(mode="flip", seed=5)) for _ in range(2)]
    assert runs[0].won and runs[0].flips == c.flip_count
    assert runs[0].finished_at == pytest.approx(c.flip_count * c.flip_every, abs=0.1)
    assert [(b.shape.body.position.x, b.shape.body.position.y) for b in runs[0].balls] == \
           [(b.shape.body.position.x, b.shape.body.position.y) for b in runs[1].balls]


@pytest.mark.parametrize("kw", [dict(flip_balls=1), dict(flip_balls=80, flip_ball_radius=30), dict(flip_pattern="spin"),
                                dict(flip_pattern="random"), dict(flip_every=0.4, flip_count=40),
                                dict(flip_ball_radius=80, flip_balls=30), dict(flip_gravity=5000)])
def test_flip_settings_finish_and_balls_stay_inside(kw):
    sim = render.make_sim(MergeConfig(mode="flip", seed=3, until_finished=True, **kw))
    x0, y0, x1, y1 = sim.arena
    while not sim.done:
        sim.step(1 / 60)
        for b in sim.balls:
            p = b.shape.body.position
            assert x0 - 5 < p.x < x1 + 5 and y0 - 5 < p.y < y1 + 5
    assert sim.won


def test_flip_bad_values_clamped_and_draw():
    c = MergeConfig.from_dict({"mode": "flip", "flip_balls": 0, "flip_every": "x", "flip_count": -3,
                               "flip_pattern": "zigzag", "flip_gravity": 1})
    c.clamp()
    assert c.flip_balls == 1 and c.flip_every >= 0.4 and c.flip_count == 2 and c.flip_pattern == "updown" and c.flip_gravity >= 500
    c.width, c.height = 360, 640
    sim = render.make_sim(c)
    r = render.make_renderer(c, 1.0)
    for _ in range(200):
        sim.step(1 / 60)
        r.draw(sim)
    assert r.draw(sim).get_size() == (360, 640)


def test_flip_video_smoke(tmp_path):
    cfg = MergeConfig.load("presets/gravity_flip.json")
    cfg.width, cfg.height, cfg.max_seconds, cfg.fps = 360, 640, 3, 24
    out = tmp_path / "f.mp4"
    render.render_video(cfg, str(out))
    assert out.stat().st_size > 5000
