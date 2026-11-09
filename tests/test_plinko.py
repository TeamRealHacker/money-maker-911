import pytest

from mm911 import render
from mm911.config import MergeConfig
from mm911.modes.plinko import slot_values


def test_slot_values_edges_pay_most():
    for n in (3, 5, 7, 11):
        v = slot_values(n)
        assert len(v) == n and v == v[::-1] and max(v) == v[0] and min(v) == v[n // 2]


def test_plinko_reaches_target_and_is_deterministic():
    runs = [render.simulate(MergeConfig(mode="plinko", seed=3)) for _ in range(2)]
    assert runs[0].won and (runs[0].finished_at, runs[0].score) == (runs[1].finished_at, runs[1].score)
    assert 8 < runs[0].finished_at < 55


@pytest.mark.parametrize("kw", [dict(plinko_rows=3), dict(plinko_rows=16, plinko_slots=11), dict(plinko_slots=3),
                                dict(plinko_target=500, plinko_balls=1000, plinko_interval=0.05),
                                dict(plinko_gravity=700), dict(plinko_peg_radius=30)])
def test_plinko_settings_finish(kw):
    sim = render.simulate(MergeConfig(mode="plinko", seed=2, until_finished=True, **kw))
    assert sim.won


def test_plinko_balls_never_pile_up():
    sim = render.make_sim(MergeConfig(mode="plinko", seed=1))
    for _ in range(60 * 12):
        sim.step(1 / 60)
        assert len(sim.balls) < 30


def test_plinko_bad_values_clamped_and_draw():
    c = MergeConfig.from_dict({"mode": "plinko", "plinko_rows": 0, "plinko_slots": 99, "plinko_target": "x", "plinko_gravity": -1})
    c.clamp()
    assert c.plinko_rows == 3 and c.plinko_slots == 11 and c.plinko_target >= 5 and c.plinko_gravity >= 400
    c.width, c.height = 360, 640
    sim = render.make_sim(c)
    r = render.make_renderer(c, 1.0)
    for _ in range(240):
        sim.step(1 / 60)
    assert r.draw(sim).get_size() == (360, 640)


def test_plinko_video_smoke(tmp_path):
    cfg = MergeConfig.load("presets/plinko_jackpot.json")
    cfg.width, cfg.height, cfg.max_seconds, cfg.fps = 360, 640, 3, 24
    out = tmp_path / "p.mp4"
    render.render_video(cfg, str(out))
    assert out.stat().st_size > 5000
