import pytest

from mm911 import render
from mm911.config import MergeConfig


def test_voting_one_survivor_deterministic():
    runs = [render.simulate(MergeConfig(mode="voting", seed=4, until_finished=True)) for _ in range(2)]
    assert runs[0].won and len(runs[0].balls) == 1
    assert runs[0].finished_at == runs[1].finished_at
    assert 12 < runs[0].finished_at < 30


@pytest.mark.parametrize("kw", [dict(voting_balls=2), dict(voting_balls=30, voting_seconds=10), dict(voting_seconds=4),
                                dict(voting_speed=900), dict(voting_ball_radius=70), dict(tiers=3)])
def test_voting_settings_finish(kw):
    sim = render.simulate(MergeConfig(mode="voting", seed=2, until_finished=True, **kw))
    assert sim.won and len(sim.balls) == 1


def test_voting_video_smoke(tmp_path):
    cfg = MergeConfig.load("presets/voting.json")
    cfg.width, cfg.height, cfg.max_seconds, cfg.fps = 360, 640, 3, 24
    out = tmp_path / "c.mp4"
    render.render_video(cfg, str(out))
    assert out.stat().st_size > 5000
