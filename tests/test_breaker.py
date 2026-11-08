"""🧱 Breaker mode: clears the wall, pitch rises per brick, balls multiply, renders + CLI."""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("APPDATA", os.path.join(tempfile.gettempdir(), "mm911_test_appdata"))

from mm911.config import MergeConfig, BREAKER_PATTERNS  # noqa: E402
from mm911.modes.breaker import pattern_cells  # noqa: E402
from mm911.render import render_video, simulate  # noqa: E402
from mm911.batch import vary  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_breaker_clears_and_pitch_rises():
    sim = simulate(MergeConfig(mode="breaker", seed=1))
    assert sim.won and sim.broken == sim.total
    p = [e.pitch for e in sim.events if e.kind == "merge"]
    assert p == sorted(p) and p[0] < p[-1]
    assert len(sim.balls) > 1                       # extra balls joined in


def test_patterns():
    for pat in BREAKER_PATTERNS:
        cells = pattern_cells(pat, 8, 8)
        assert 0 < len(cells) <= 64
    assert len(pattern_cells("heart", 10, 9)) < 90


def test_breaker_render(tmp_path):
    cfg = MergeConfig.load(ROOT / "presets" / "breaker_heart.json")
    cfg.max_seconds, cfg.fps, cfg.export_resolution = 3, 24, "720p"
    meta = render_video(cfg, str(tmp_path / "b.mp4"))
    assert meta["mode"] == "breaker" and meta["bricks"] > 0 and Path(meta["file"]).stat().st_size > 10_000


def test_batch_vary_keeps_mode():
    import random
    base = MergeConfig(mode="breaker")
    for i in range(4):
        c = vary(base, i, random.Random(1), True)
        assert c.mode == "breaker" and c.breaker_pattern in BREAKER_PATTERNS
