import pytest

from mm911 import render
from mm911.config import MergeConfig


def test_chain_pops_everything_and_is_deterministic():
    runs = [render.simulate(MergeConfig(mode="chain", seed=4)) for _ in range(2)]
    assert runs[0].won and runs[0].pops == runs[0].total == 70
    assert runs[0].finished_at == runs[1].finished_at and runs[0].sparks == runs[1].sparks
    assert 5 < runs[0].finished_at < 60


@pytest.mark.parametrize("kw", [dict(chain_balls=2), dict(chain_balls=300), dict(chain_radius=60), dict(chain_radius=500),
                                dict(chain_speed=60), dict(chain_speed=1500), dict(chain_ball_radius=60), dict(tiers=3), dict(tiers=15)])
def test_chain_settings_finish(kw):
    sim = render.simulate(MergeConfig(mode="chain", seed=2, until_finished=True, **kw))
    assert sim.won and sim.pops == sim.total


def test_chain_popped_pictures_leave_and_waves_trim():
    sim = render.make_sim(MergeConfig(mode="chain", seed=3))
    for _ in range(60 * 30):
        sim.step(1 / 60)
        assert len(sim.balls) <= sim.total
    assert sim.finished_at is not None and len(sim.balls) == 0


def test_chain_bad_values_clamped_and_draw():
    c = MergeConfig.from_dict({"mode": "chain", "chain_balls": 0, "chain_radius": "x", "chain_speed": -5, "chain_ball_radius": 1e9})
    c.clamp()
    assert c.chain_balls == 2 and c.chain_radius >= 60 and c.chain_speed >= 60 and c.chain_ball_radius <= 60
    c.width, c.height = 360, 640
    sim = render.make_sim(c)
    r = render.make_renderer(c, 1.0)
    for _ in range(240):
        sim.step(1 / 60)
        r.draw(sim)
    assert r.draw(sim).get_size() == (360, 640)


def test_chain_video_smoke(tmp_path):
    cfg = MergeConfig.load("presets/chain_reaction.json")
    cfg.width, cfg.height, cfg.max_seconds, cfg.fps = 360, 640, 3, 24
    out = tmp_path / "c.mp4"
    render.render_video(cfg, str(out))
    assert out.stat().st_size > 5000
