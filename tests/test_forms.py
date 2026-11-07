from mm911.config import MergeConfig, MIN_TIERS, MAX_TIERS
from mm911.render import Renderer, make_thumbnail


def test_tiers_clamped():
    assert MergeConfig.from_dict({"tiers": 99}).tiers == MAX_TIERS
    assert MergeConfig.from_dict({"tiers": 1}).tiers == MIN_TIERS


def test_final_form_always_fits():
    for n in range(MIN_TIERS, MAX_TIERS + 1):
        c = MergeConfig(tiers=n)
        radii = [c.tier_radius(t) for t in range(n)]
        assert radii == sorted(radii)
        assert radii[-1] <= c.container_radius * 0.7 + 1e-6
        assert radii[-1] >= c.container_radius * 0.4 - 1e-6


def test_broken_and_missing_images_dont_crash(tmp_path):
    (tmp_path / "1.png").write_bytes(b"not an image")
    c = MergeConfig(tiers=4, tier_images=[str(tmp_path / "1.png"), str(tmp_path / "missing.jpg")], max_seconds=2)
    Renderer(c, 0.3)
    make_thumbnail(c, str(tmp_path / "t.jpg"))
    assert (tmp_path / "t.jpg").exists()
