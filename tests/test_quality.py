"""v0.6.0 picture quality + round balls: sprites are built at their final size from full-resolution
sources, edges are anti-aliased without dark halos, exports are BT.709 tagged at a high quality."""
import os
import subprocess
import tempfile

import numpy as np
import pytest
from PIL import Image

os.environ.setdefault("APPDATA", os.path.join(tempfile.gettempdir(), "mm911_test_appdata"))

import pygame  # noqa: E402

from mm911 import sprites  # noqa: E402
from mm911.config import MergeConfig  # noqa: E402
from mm911.render import Renderer, video_encode_cmd, raw_format, frame_bytes  # noqa: E402
from mm911.ffmpeg import ffmpeg_exe, encoder_args  # noqa: E402


def _alpha(surf):
    return pygame.surfarray.array_alpha(surf).T


def _rgb(surf):
    return pygame.surfarray.array3d(surf).transpose(1, 0, 2)


@pytest.fixture
def portrait(tmp_path):
    """3000 px tall photo-like picture with fine detail and a red top / blue bottom."""
    h, w = 3000, 2000
    ys, xs = np.mgrid[0:h, 0:w]
    arr = np.zeros((h, w, 3), np.uint8)
    arr[..., 0] = np.where(ys < h / 2, 220, 20)
    arr[..., 2] = np.where(ys >= h / 2, 220, 20)
    arr[..., 1] = ((xs // 3 + ys // 3) % 2) * 120     # fine checker = detail that blurs easily
    p = tmp_path / "portrait.jpg"
    Image.fromarray(arr).save(p, quality=95)
    return str(p)


def test_full_resolution_source(portrait):
    im = sprites.load_source(portrait)
    assert im.size == (2000, 3000)          # no 1024 px cap any more


def test_exif_rotation(tmp_path):
    im = Image.new("RGB", (400, 200), (200, 10, 10))
    exif = Image.Exif()
    exif[0x0112] = 6                           # "rotate 90 CW" like a phone photo
    p = tmp_path / "phone.jpg"
    im.save(p, exif=exif.tobytes())
    sprites.clear_caches()
    assert sprites.load_source(str(p)).size == (200, 400)


def test_photo_fills_the_circle_and_edges_are_antialiased(portrait):
    cfg = MergeConfig(tiers=3, tier_images=[portrait, "", ""])
    r = Renderer(cfg, 1.0)
    spr = r.sprites[0]
    a = _alpha(spr)
    h, w = a.shape
    c = h // 2
    R = cfg.tier_radius(0)
    # inside the ball everything is opaque (a portrait used to leave transparent side bars)
    for dx, dy in ((0, 0), (int(R * 0.8), 0), (-int(R * 0.8), 0), (0, int(R * 0.8))):
        assert a[c + dy, c + dx] == 255
    # anti-aliased rim: some partially transparent pixels along the edge, none outside
    partial = ((a > 0) & (a < 255)).sum()
    assert partial > 2 * 3.14 * R * 0.5          # a soft 1 px ring all the way round
    assert a[0, 0] == 0


def test_no_dark_halo_on_edges():
    cfg = MergeConfig(tiers=3, palette="Mono", tier_colors=["#FFFFFF", "#FFFFFF", "#FFFFFF"])
    r = Renderer(cfg, 2.0)
    spr = r.sprites[2]
    a, rgb = _alpha(spr), _rgb(spr).astype(int)
    edge = (a > 5) & (a < 250)
    # rim of a white ball is light grey; straight-alpha resampling used to make these near black
    assert rgb[edge].mean() > 120


def test_rotation_keeps_rim_crisp(portrait):
    """The picture rolls (content layer); base + rim overlay stay unrotated."""
    cfg = MergeConfig(tiers=3, tier_images=[portrait, "", ""])
    r = Renderer(cfg, 1.0)
    info = r.tiers_info[0]
    assert info["parts"] is not None and info["parts"][2] is not None
    r.surface.fill((0, 0, 0))
    r.blit_ball(0, 200, 200, angle=0.7)
    out = _rgb(r.surface)
    assert out[200, 200].sum() > 0


def test_sticker_style_has_no_disc(tmp_path):
    im = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
    from PIL import ImageDraw
    ImageDraw.Draw(im).ellipse((150, 100, 450, 500), fill=(250, 180, 30, 255))
    p = tmp_path / "cut.png"
    im.save(p)
    cfg = MergeConfig(tiers=3, tier_images=[str(p), "", ""], cutout_style="sticker")
    r = Renderer(cfg, 1.0)
    a = _alpha(r.sprites[0])
    h = a.shape[0]
    assert a[h // 2, h // 2] == 255
    assert a[int(h * 0.5), 2] == 0     # left side of the ball is empty: no tier disc
    assert a.max() == 255 and (a == 0).mean() > 0.2


def test_encoder_settings_high_quality_bt709():
    cmd, name = video_encode_cmd(MergeConfig(export_encoder="cpu"), 1080, 1920)
    j = " ".join(cmd)
    assert "out_color_matrix=bt709" in j and "accurate_rnd" in j
    assert "-colorspace bt709" in j and "-color_primaries bt709" in j and "-color_trc bt709" in j
    args, _ = encoder_args("h264", 17, "cpu")
    assert args[args.index("-crf") + 1] == "17"
    assert args[args.index("-preset") + 1] == "medium"
    assert "scale=" not in j.split("pad=")[0]          # no resize: frames are drawn at the export size


def test_raw_pipe_colours_are_right(tmp_path):
    surf = pygame.Surface((64, 64))
    surf.fill((230, 20, 30))
    fmt = raw_format(surf)
    out = tmp_path / "c.mp4"
    cmd, _ = video_encode_cmd(MergeConfig(export_encoder="cpu", fps=30), 64, 64, None, str(out), fmt)
    data = bytes(frame_bytes(surf, fmt))
    subprocess.run(cmd, input=data * 3, check=True)
    png = tmp_path / "c.png"
    subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-i", str(out), "-frames:v", "1", str(png)], check=True)
    px = np.asarray(Image.open(png).convert("RGB"))[32, 32].astype(int)
    assert abs(px[0] - 230) < 14 and px[1] < 40 and px[2] < 45
