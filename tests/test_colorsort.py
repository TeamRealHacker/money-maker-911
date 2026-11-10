import pytest

from mm911 import render
from mm911.config import MergeConfig


def test_colorsort_one_sorted_deterministic():
    runs = [render.simulate(MergeConfig(mode="colorsort", seed=4, until_finished=True)) for _ in range(2)]
    assert runs[0].won and len(runs[0].balls) == 0
    assert runs[0].finished_at == runs[1].finished_at
    assert 4 < runs[0].finished_at < 40


@pytest.mark.parametrize("kw", [dict(colorsort_balls=2), dict(colorsort_balls=200), dict(colorsort_zones=8), dict(colorsort_zones=2),
                                dict(colorsort_speed=1500), dict(colorsort_ball_radius=60), dict(tiers=3)])
def test_colorsort_settings_finish(kw):
    sim = render.simulate(MergeConfig(mode="colorsort", seed=2, until_finished=True, **kw))
    assert sim.won and len(sim.balls) == 0


def test_colorsort_video_smoke(tmp_path):
    cfg = MergeConfig.load("presets/color_sort.json")
    cfg.width, cfg.height, cfg.max_seconds, cfg.fps = 360, 640, 3, 24
    out = tmp_path / "c.mp4"
    render.render_video(cfg, str(out))
    assert out.stat().st_size > 5000
