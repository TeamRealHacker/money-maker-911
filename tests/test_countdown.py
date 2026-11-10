import pytest

from mm911 import render
from mm911.config import MergeConfig


def test_countdown_one_survivor_deterministic():
    runs = [render.simulate(MergeConfig(mode="countdown", seed=4, until_finished=True)) for _ in range(2)]
    assert runs[0].won and len(runs[0].balls) == 1
    assert runs[0].finished_at == runs[1].finished_at
    assert 15 < runs[0].finished_at < 30


@pytest.mark.parametrize("kw", [dict(countdown_balls=2), dict(countdown_balls=200, countdown_seconds=10), dict(countdown_seconds=3),
                                dict(countdown_speed=1500), dict(countdown_ball_radius=70), dict(tiers=3)])
def test_countdown_settings_finish(kw):
    sim = render.simulate(MergeConfig(mode="countdown", seed=2, until_finished=True, **kw))
    assert sim.won and len(sim.balls) == 1


def test_countdown_video_smoke(tmp_path):
    cfg = MergeConfig.load("presets/countdown_survival.json")
    cfg.width, cfg.height, cfg.max_seconds, cfg.fps = 360, 640, 3, 24
    out = tmp_path / "c.mp4"
    render.render_video(cfg, str(out))
    assert out.stat().st_size > 5000
