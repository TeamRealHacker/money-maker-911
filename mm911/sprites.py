"""High-quality ball sprites (v0.6.0).

Why this exists: the old sprites were built at 3x with pygame (hard-edged pygame.draw circles and
masks, photos shrunk to 1024 px then stretched back up, smoothscale on straight alpha), then shrunk
with smoothscale, then rotozoomed every frame. Every step softened the picture a little and the
straight-alpha resampling gave dark halos around every edge.

Now every layer is built once, directly at its final on-screen pixel size:
  * pictures are decoded at full resolution with Pillow (EXIF rotation applied) and resampled ONCE
    with Lanczos in premultiplied alpha (no dark fringes), cover-cropped around the subject;
  * circles, rims and rings use exact analytic anti-aliasing (pixel coverage of the disc), so the
    edges are as clean as a vector renderer's, and the rim is computed from the same circle as
    the mask (no seams, no mismatched outline);
  * emoji SVGs are rasterised at the exact pixel size they are shown at;
  * cut-outs are colour-decontaminated (no white/green fringe from the old background) and get a
    smooth round sticker outline;
  * a ball is split into a static base (disc), a content layer (the picture, which rolls with the
    physics) and a static overlay (rim, highlight, inner shadow), so rotation never blurs the rim and
    the light stays on the top-left like real light;
  * transparent pixels are "colour bled" so per-frame rotozoom can't pull black into the edges.
Results are cached per (picture, size, look), so the preview and batch renders reuse them.
"""
from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict

import numpy as np

try:
    from PIL import Image, ImageFilter, ImageOps
    Image.MAX_IMAGE_PIXELS = 250_000_000
    HAS_PIL = True
except Exception:  # pragma: no cover - Pillow is in requirements; keep the app alive without it
    HAS_PIL = False

MAX_SOURCE_SIDE = 4096   # decode cap (a 4K Final Form needs ~1400 px; 4096 leaves room for zoom)


# ---------------------------------------------------------------- byte-bounded LRU caches
class _LRU:
    def __init__(self, max_bytes: int):
        self.max, self.used, self.d = max_bytes, 0, OrderedDict()
        self.lock = threading.Lock()

    def get(self, k):
        with self.lock:
            v = self.d.get(k)
            if v is not None:
                self.d.move_to_end(k)
            return v[0] if v else None

    def put(self, k, v, nbytes: int):
        with self.lock:
            if k in self.d:
                self.used -= self.d.pop(k)[1]
            self.d[k] = (v, nbytes)
            self.used += nbytes
            while self.used > self.max and len(self.d) > 1:
                _, (_, b) = self.d.popitem(last=False)
                self.used -= b

    def clear(self):
        with self.lock:
            self.d.clear()
            self.used = 0


_SOURCES = _LRU(320 << 20)    # decoded pictures
_LAYERS = _LRU(384 << 20)     # finished numpy layers per (picture, size, look)


def clear_caches() -> None:
    _SOURCES.clear()
    _LAYERS.clear()


# ---------------------------------------------------------------- loading & resampling
def file_key(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (os.path.abspath(path), st.st_mtime_ns, st.st_size)


def load_source(path: str):
    """Full-resolution RGBA PIL image (EXIF-rotated), or None for missing / broken files."""
    if not HAS_PIL or not path:
        return None
    key = file_key(path)
    if key is None:
        return None
    hit = _SOURCES.get(key)
    if hit is not None:
        return hit
    try:
        im = Image.open(path)
        if im.format == "JPEG":
            im.draft("RGB", (MAX_SOURCE_SIDE, MAX_SOURCE_SIDE))   # fast DCT downscale, stays >= cap
        try:
            im.seek(0)
        except Exception:
            pass
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA")
        if max(im.size) > MAX_SOURCE_SIDE:
            k = MAX_SOURCE_SIDE / max(im.size)
            im = resize_hq(im, (max(1, round(im.width * k)), max(1, round(im.height * k))))
        im.load()
    except Exception:
        return None
    if im.width < 1 or im.height < 1:
        return None
    _SOURCES.put(key, im, im.width * im.height * 4)
    return im


def resize_hq(im, size: tuple[int, int]):
    """Lanczos resample in premultiplied alpha (no dark halos), one step from the source."""
    size = (max(1, int(size[0])), max(1, int(size[1])))
    if im.size == size:
        return im
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    if im.getextrema()[3][0] == 255:            # fully opaque: plain RGB resample is exact and faster
        return im.convert("RGB").resize(size, Image.LANCZOS, reducing_gap=3.0).convert("RGBA")
    pm = im.convert("RGBa").resize(size, Image.LANCZOS, reducing_gap=3.0)
    return pm.convert("RGBA")


def to_premul(im) -> np.ndarray:
    """PIL RGBA -> float32 premultiplied HxWx4 in 0..1."""
    a = np.asarray(im.convert("RGBA"), dtype=np.float32) / 255.0
    a[..., :3] *= a[..., 3:4]
    return a


# ---------------------------------------------------------------- analytic anti-aliasing
def _grid(size: int, cx: float, cy: float):
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    return np.hypot(xs + 0.5 - cx, ys + 0.5 - cy)


def disc(d: np.ndarray, r: float) -> np.ndarray:
    """Exact-ish pixel coverage of a disc of radius r (d = distance of each pixel centre)."""
    return np.clip(r - d + 0.5, 0.0, 1.0)


def ring(d: np.ndarray, r_out: float, r_in: float) -> np.ndarray:
    return np.clip(disc(d, r_out) - disc(d, r_in), 0.0, 1.0)


def solid(cov: np.ndarray, rgb, alpha: float = 1.0) -> np.ndarray:
    """Coverage map -> premultiplied RGBA layer of one colour."""
    a = cov * alpha
    out = np.empty(cov.shape + (4,), np.float32)
    for i in range(3):
        out[..., i] = a * (rgb[i] / 255.0)
    out[..., 3] = a
    return out


def over(dst: np.ndarray, src: np.ndarray, x: int = 0, y: int = 0) -> np.ndarray:
    """Premultiplied 'over' of src onto dst at (x, y) (clipped)."""
    H, W = dst.shape[:2]
    h, w = src.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1:
        return dst
    s = src[y0 - y:y1 - y, x0 - x:x1 - x]
    d = dst[y0:y1, x0:x1]
    d *= (1.0 - s[..., 3:4])
    d += s
    return dst


def _blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur of a float map (3 box passes = near-Gaussian, full float precision)."""
    if sigma <= 0.3:
        return a
    r = max(1, int(round((math.sqrt(4 * sigma * sigma + 1) - 1) / 2)))
    out = a.astype(np.float32)
    for _ in range(3):
        out = _box(out, r)
    return out


def _box(a: np.ndarray, r: int) -> np.ndarray:
    """Fast separable box blur (any channels), edges clamped."""
    if r < 1:
        return a
    out = a
    for axis in (0, 1):
        pad = [(0, 0)] * a.ndim
        pad[axis] = (r + 1, r)
        p = np.pad(out, pad, mode="edge")
        c = np.cumsum(p, axis=axis, dtype=np.float32)
        n = out.shape[axis]
        hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
        lo = np.take(c, np.arange(0, n), axis=axis)
        out = (hi - lo) / (2 * r + 1)
    return out


def bleed(pm: np.ndarray) -> np.ndarray:
    """Straight-alpha RGBA uint8 from premultiplied float, with the colour of (semi-)transparent
    pixels filled from their neighbours, so bilinear rotation / scaling never drags black into the
    edges (bilinear only ever mixes direct neighbours, so a 2 px reach is all it needs)."""
    a = pm[..., 3]
    out = np.zeros(pm.shape[:2] + (4,), np.uint8)
    nz = a > 1e-4
    rgb = np.zeros(pm.shape[:2] + (3,), np.float32)
    rgb[nz] = pm[..., :3][nz] / a[nz][:, None]
    fix = a < 0.5
    if fix.any() and nz.any():
        ys, xs = np.nonzero(nz)
        y0, y1 = max(0, ys.min() - 3), min(a.shape[0], ys.max() + 4)
        x0, x1 = max(0, xs.min() - 3), min(a.shape[1], xs.max() + 4)
        sub = pm[y0:y1, x0:x1]
        blur = _box(sub, 2)
        den = blur[..., 3]
        ok = den > 1e-5
        est = np.zeros(sub.shape[:2] + (3,), np.float32)
        est[ok] = blur[..., :3][ok] / den[ok][:, None]
        f = fix[y0:y1, x0:x1] & ok
        k = np.clip(1.0 - a[y0:y1, x0:x1][f] * 2.0, 0, 1)[:, None]
        r = rgb[y0:y1, x0:x1]
        r[f] = r[f] * (1 - k) + est[f] * k
    out[..., :3] = np.clip(rgb * 255.0 + 0.5, 0, 255)
    out[..., 3] = np.clip(a * 255.0 + 0.5, 0, 255)
    return out


def to_surface(pm: np.ndarray):
    """Premultiplied float layer -> pygame SRCALPHA surface (straight alpha, colour-bled edges)."""
    import pygame
    rgba = bleed(pm)
    h, w = rgba.shape[:2]
    # BGRA bytes = the native ARGB layout of pygame's SRCALPHA surfaces: blits take the SIMD fast
    # path (an "RGBA" buffer surface blits ~14x slower)
    bgra = np.ascontiguousarray(rgba[..., [2, 1, 0, 3]])
    return pygame.image.frombuffer(bgra.tobytes(), (w, h), "BGRA").copy()


# ---------------------------------------------------------------- cropping
def alpha_bbox(im, thresh: int = 24):
    a = np.asarray(im.getchannel("A"))
    ys, xs = np.nonzero(a > thresh)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def has_alpha(im) -> bool:
    return im.mode == "RGBA" and im.getextrema()[3][0] < 250


def smart_focus(im) -> tuple[float, float]:
    """Where the subject probably is (0..1, 0..1). Cheap saliency: edge energy weighted by a centre
    prior, blended toward the centre, nudged up a little on tall pictures (faces sit high)."""
    th = im.convert("L")
    th.thumbnail((128, 128), Image.BILINEAR)
    g = np.asarray(th, dtype=np.float32)
    if g.shape[0] < 4 or g.shape[1] < 4:
        return 0.5, 0.5
    gx = np.abs(np.diff(g, axis=1))[:-1, :]
    gy = np.abs(np.diff(g, axis=0))[:, :-1]
    e = _box((gx + gy) ** 1.5, 2)
    h, w = e.shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    prior = np.exp(-(((xs / w - 0.5) / 0.38) ** 2 + ((ys / h - 0.45) / 0.38) ** 2))
    wgt = e * prior
    s = float(wgt.sum())
    if s <= 1e-6:
        return 0.5, 0.5
    fx, fy = float((wgt * xs).sum() / s / w), float((wgt * ys).sum() / s / h)
    fx, fy = 0.5 + (fx - 0.5) * 0.7, 0.5 + (fy - 0.5) * 0.7
    if im.height > im.width * 1.15:
        fy -= 0.06
    return min(1, max(0, fx)), min(1, max(0, fy))


def square_crop_box(im, fit: str = "smart", zoom: float = 1.0) -> tuple[float, float, float, float]:
    """Square region of the picture that fills the ball without stretching."""
    w, h = im.size
    zoom = max(1.0, min(4.0, float(zoom or 1.0)))
    if has_alpha(im):                       # transparent PNG / cut-out: crop around the subject
        bb = alpha_bbox(im)
        if bb:
            x0, y0, x1, y1 = bb
            side = max(x1 - x0, y1 - y0) / zoom
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            return cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2
    side = min(w, h) / zoom
    if fit == "center":
        fx, fy = 0.5, 0.5
    elif fit == "top":
        fx, fy = 0.5, 0.0
    else:
        fx, fy = smart_focus(im)
    cx = min(max(fx * w, side / 2), w - side / 2)
    cy = min(max(fy * h, side / 2), h - side / 2)
    return cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2


def cover_square(im, px: int, fit: str = "smart", zoom: float = 1.0):
    """px x px picture that fills a circle: crop around the subject, then ONE Lanczos resample."""
    if fit == "fit":                         # whole picture, letterboxed (transparent bars)
        k = px / max(im.size)
        small = resize_hq(im, (round(im.width * k), round(im.height * k)))
        out = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        out.paste(small, ((px - small.width) // 2, (px - small.height) // 2))
        return out
    box = square_crop_box(im, fit, zoom)
    pm = im.convert("RGBa") if has_alpha(im) else im.convert("RGB")
    res = pm.resize((px, px), Image.LANCZOS, box=box, reducing_gap=3.0)
    return res.convert("RGBA")


def decontaminate(im):
    """Cut-out edges still carry the old background colour (white / green fringe). Replace the
    colour of semi-transparent edge pixels with the colour of the solid subject next to them."""
    arr = np.asarray(im.convert("RGBA"), dtype=np.float32) / 255.0
    a = arr[..., 3]
    edge = (a > 0.0) & (a < 0.92)
    if not edge.any():
        return im
    solid_m = (a >= 0.92).astype(np.float32)
    r = max(2, int(round(max(im.size) / 300)))
    num = _box(arr[..., :3] * solid_m[..., None], r)
    den = _box(solid_m, r)
    for _ in range(2):
        ok = den > 1e-3
        if (edge & ~ok).any():
            r *= 2
            num, den = _box(arr[..., :3] * solid_m[..., None], r), _box(solid_m, r)
    ok = edge & (den > 1e-3)
    est = num[ok] / den[ok][:, None]
    k = np.clip((0.92 - a[ok]) / 0.92, 0, 1)[:, None] ** 0.5
    arr[..., :3][ok] = arr[..., :3][ok] * (1 - k) + est * k
    return Image.fromarray(np.clip(arr * 255 + 0.5, 0, 255).astype(np.uint8), "RGBA")


def fit_subject(im, max_radius: float):
    """Cut-out scaled so its farthest opaque pixel sits within max_radius of the centre
    (no stretching, nothing pokes out of the ball). Returns (premultiplied array, its size)."""
    bb = alpha_bbox(im) or (0, 0, im.width, im.height)
    sub = im.crop(bb)
    a = np.asarray(sub.getchannel("A"), dtype=np.float32)
    ys, xs = np.nonzero(a > 24)
    if len(xs) == 0:
        far = max(sub.size) / 2
    else:
        cx, cy = sub.width / 2, sub.height / 2
        far = float(np.sqrt(((xs + 0.5 - cx) ** 2 + (ys + 0.5 - cy) ** 2).max()))
    k = max_radius / max(1.0, far)
    sub = resize_hq(sub, (max(1, round(sub.width * k)), max(1, round(sub.height * k))))
    return to_premul(sub)


def sticker_outline(alpha: np.ndarray, width: float) -> np.ndarray:
    """Round, smooth outline mask: alpha grown by `width` px (blur + soft threshold = a rounded
    dilation, much cleaner than stamping the shape at 16 offsets)."""
    if width <= 0:
        return alpha
    pad = int(math.ceil(width * 2)) + 2
    a = np.pad(alpha, pad)
    s = width * 0.6
    b = _blur(a, s)
    # a blurred straight edge at distance x outside is 0.5*erfc(x / (s*sqrt2)): the iso-line at
    # x = width is a rounded dilation; divide by the local slope for a 1 px anti-aliased edge.
    t = 0.5 * math.erfc(width / (s * math.sqrt(2)))
    gy, gx = np.gradient(b)
    g = np.hypot(gx, gy) + 1e-6   # local slope: (b - t) / |grad b| = signed distance to the iso-line in px
    grown = np.clip((b - t) / g + 0.5, 0, 1)
    return np.maximum(grown, a)


# ---------------------------------------------------------------- the ball itself
def rasterize_svg(path: str, px: int):
    """SVG rasterised at exactly px x px (premultiplied float), cached."""
    px = max(4, int(px))
    key = ("svg", file_key(path), px)
    hit = _LAYERS.get(key)
    if hit is not None:
        return hit
    import pygame
    try:
        surf = pygame.image.load_sized_svg(str(path), (px, px))
    except Exception:
        return None
    if surf.get_size() != (px, px):      # keep aspect: centre on a px x px canvas
        canvas = pygame.Surface((px, px), pygame.SRCALPHA)
        canvas.blit(surf, ((px - surf.get_width()) // 2, (px - surf.get_height()) // 2))
        surf = canvas
    arr = np.frombuffer(pygame.image.tobytes(surf, "RGBA"), np.uint8).reshape(px, px, 4).astype(np.float32) / 255
    arr[..., :3] *= arr[..., 3:4]
    _LAYERS.put(key, arr, arr.nbytes)
    return arr


def _shade(c, f: float):
    if f < 1:
        return tuple(max(0, int(v * f)) for v in c)
    return tuple(min(255, int(v + (255 - v) * (f - 1))) for v in c)


def _highlight(size: int, cx: float, cy: float, R: float, strength: float, clip: np.ndarray) -> np.ndarray:
    """Soft specular blob top-left (white, premultiplied), clipped to the ball."""
    if strength <= 0:
        return np.zeros((size, size, 4), np.float32)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    hx, hy = cx - R * 0.32, cy - R * 0.42
    e = ((xs + 0.5 - hx) / (R * 0.42)) ** 2 + ((ys + 0.5 - hy) / (R * 0.26)) ** 2
    a = np.exp(-e * 1.6) * 0.42 * strength * clip
    return solid(np.ones_like(a), (255, 255, 255), 1.0) * a[..., None]


def _inner_shadow(d: np.ndarray, size: int, cx: float, cy: float, R: float, strength: float,
                  clip: np.ndarray) -> np.ndarray:
    """Darkening toward the lower-right rim: makes a flat picture read as a sphere."""
    if strength <= 0:
        return np.zeros((size, size, 4), np.float32)
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    ox, oy = cx - R * 0.18, cy - R * 0.22
    k = np.clip((np.hypot(xs + 0.5 - ox, ys + 0.5 - oy) - R * 0.55) / (R * 0.75), 0, 1) ** 1.8
    a = k * 0.55 * strength * clip
    return solid(np.ones_like(a), (0, 0, 0), 1.0) * a[..., None]


class BallLook:
    """Everything that changes how a ball is drawn (also the cache key)."""
    __slots__ = ("kind", "radius", "color", "image", "emoji_svg", "fit", "zoom", "rim", "outline", "outline_color",
                 "highlight", "inner_shadow", "cutout_style", "cutout_outline")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def key(self):
        return tuple((k, file_key(self.image) if k == "image" and self.image else getattr(self, k))
                     for k in self.__slots__)


def build_ball(look: BallLook) -> dict:
    """{'base','content','overlay'} premultiplied float layers (content may be None), all the same
    square size, ball centre at the exact centre. Cached."""
    key = look.key()
    hit = _LAYERS.get(key)
    if hit is not None:
        return hit
    R = max(1.0, float(look.radius))
    out_w = max(0.0, float(look.outline or 0))
    pad = int(math.ceil(max(2.0, out_w, R * 0.06))) + 2
    S = int(math.ceil(2 * R)) + 2 * pad
    S += S % 2
    c = S / 2.0
    d = _grid(S, c, c)
    col = tuple(look.color)
    clip_ball = disc(d, R)
    base = np.zeros((S, S, 4), np.float32)
    content = None
    overlay = np.zeros((S, S, 4), np.float32)
    hl = float(look.highlight if look.highlight is not None else 0.5)
    ish = float(look.inner_shadow or 0.0)
    kind = look.kind

    def plain_disc():
        over(base, solid(clip_ball, _shade(col, 0.72)))
        over(base, solid(disc(d, R * 0.9), col))

    if kind in ("photo", "cutout_circle"):
        src = load_source(look.image)
        rim = max(0.0, float(look.rim if look.rim is not None else 0.06)) * R
        if out_w > 0:
            rim = out_w
        r_pic = R - rim + (0.75 if rim > 0 else 0.0)        # tucks under the rim: no seam
        px = int(math.ceil(2 * r_pic)) + 2
        over(base, solid(clip_ball, col))                     # tier colour behind transparent pictures
        if src is not None:
            sq = cover_square(src, px, look.fit or "smart", look.zoom or 1.0)
            if kind == "cutout_circle":
                sq = decontaminate(sq)
            pic = to_premul(sq)
            content = np.zeros((S, S, 4), np.float32)
            o = int(round(c - px / 2))
            over(content, pic, o, o)
            content *= disc(_grid(S, c, c), r_pic)[..., None]
        if rim > 0:
            rc = look.outline_color if (out_w > 0 and look.outline_color) else _shade(col, 0.7)
            over(overlay, solid(ring(d, R, R - rim), rc))
    elif kind == "emoji":
        plain_disc()
        content = np.zeros((S, S, 4), np.float32)
        e = rasterize_svg(look.emoji_svg, int(round(R * 1.3))) if look.emoji_svg else None
        if e is not None:
            if True:
                h = e.shape[0]
                o = int(round(c - h / 2))
                sh = _blur(np.pad(e[..., 3], 4), max(1.0, R * 0.05)) * 0.28    # soft contact shadow
                shl = solid(np.ones_like(sh), (0, 0, 0)) * sh[..., None]
                over(content, shl, o - 4, o - 4 + max(1, int(R * 0.03)))
                over(content, e, o, o)
    elif kind in ("cutout_disc", "sticker"):
        src = load_source(look.image)
        if kind == "cutout_disc":
            plain_disc()
        if src is not None:
            src = decontaminate(src)
            ow = max(1.5, R * 0.045) if look.cutout_outline else 0.0
            sub = fit_subject(src, (R * 0.8 if kind == "cutout_disc" else R * 0.97) - ow)
            h, w = sub.shape[:2]
            layer = np.zeros((S, S, 4), np.float32)
            ox, oy = int(round(c - w / 2)), int(round(c - h / 2))
            if ow > 0:
                ol = sticker_outline(sub[..., 3], ow)
                pad_o = (ol.shape[0] - h) // 2
                sh = _blur(ol, max(1.5, R * 0.04)) * 0.32
                over(layer, solid(np.ones_like(sh), (0, 0, 0)) * sh[..., None], ox - pad_o, oy - pad_o + max(1, int(R * 0.025)))
                over(layer, solid(ol, (255, 255, 255)), ox - pad_o, oy - pad_o)
            else:
                sh = _blur(np.pad(sub[..., 3], 6), max(1.5, R * 0.04)) * 0.3
                over(layer, solid(np.ones_like(sh), (0, 0, 0)) * sh[..., None], ox - 6, oy - 6 + max(1, int(R * 0.025)))
            over(layer, sub, ox, oy)
            content = layer
        if kind == "sticker":
            hl, ish = 0.0, 0.0      # no ball lighting on a free-form sticker
    else:   # plain numbered ball
        plain_disc()
    if kind != "sticker":
        clip = clip_ball
        if ish > 0:
            over(overlay, _inner_shadow(d, S, c, c, R, ish, clip))
        if hl > 0:
            over(overlay, _highlight(S, c, c, R, hl, clip))
        if out_w > 0 and kind not in ("photo", "cutout_circle"):
            oc = look.outline_color or _shade(col, 0.55)
            over(overlay, solid(ring(d, R, R - out_w), oc))
    res = {"base": base, "content": content, "overlay": overlay, "size": S, "radius": R}
    nbytes = base.nbytes * (3 if content is not None else 2)
    _LAYERS.put(key, res, nbytes)
    return res


def flatten(layers: dict) -> np.ndarray:
    out = layers["base"].copy()
    if layers["content"] is not None:
        over(out, layers["content"])
    over(out, layers["overlay"])
    return out


def soft_shadow(pm: np.ndarray, blur: float, opacity: float) -> np.ndarray:
    """Blurred black copy of a layer's alpha (with room for the blur)."""
    pad = int(math.ceil(blur * 2.5)) + 2
    a = np.pad(pm[..., 3], pad)
    a = _blur(a, blur) * opacity
    return solid(np.ones_like(a), (0, 0, 0)) * a[..., None]


def soft_glow(radius: float, color, strength: float) -> np.ndarray:
    """Smooth coloured halo around a ball of `radius`."""
    R = radius * 1.6 + 4
    S = int(math.ceil(2 * R))
    S += S % 2
    d = _grid(S, S / 2, S / 2)
    k = np.clip((d - radius * 0.85) / max(1.0, R - radius * 0.85), 0, 1)
    a = (1 - k) ** 2.2 * 0.5 * strength * disc(d, R)
    return solid(np.ones_like(a), color) * a[..., None]


def pill(w: int, h: int, color, alpha: float = 1.0) -> np.ndarray:
    """Anti-aliased rounded bar (radius h/2)."""
    w, h = max(1, int(w)), max(1, int(h))
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    r = h / 2.0
    cx = np.clip(xs + 0.5, r, max(r, w - r))
    dd = np.hypot(xs + 0.5 - cx, ys + 0.5 - r)
    return solid(disc(dd, r), color, alpha)


def rounded_rect(w: int, h: int, radius: float, color, alpha: float = 1.0) -> np.ndarray:
    w, h = max(1, int(w)), max(1, int(h))
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    r = min(radius, w / 2, h / 2)
    cx = np.clip(xs + 0.5, r, w - r)
    cy = np.clip(ys + 0.5, r, h - r)
    return solid(disc(np.hypot(xs + 0.5 - cx, ys + 0.5 - cy), r), color, alpha)


def stroke_polygon(points, width: float, color, size: tuple[int, int], offset=(0, 0), ss: int = 3,
                   glow: float = 0.0, glow_color=None) -> np.ndarray:
    """Closed polygon stroke (round joins) drawn supersampled then Lanczos-reduced: crisp, no jaggies.
    points are in pixel coords of the output; returns a premultiplied layer of `size`."""
    from PIL import ImageDraw
    W, H = size
    ss = max(1, int(ss))
    m = Image.new("L", (W * ss, H * ss), 0)
    dr = ImageDraw.Draw(m)
    pts = [((x + offset[0]) * ss, (y + offset[1]) * ss) for x, y in points]
    pts.append(pts[0])
    wpx = max(1, int(round(width * ss)))
    dr.line(pts, fill=255, width=wpx, joint="curve")
    for p in pts:   # round caps at every corner
        dr.ellipse((p[0] - wpx / 2, p[1] - wpx / 2, p[0] + wpx / 2, p[1] + wpx / 2), fill=255)
    if ss > 1:
        m = m.reduce(ss)
    cov = np.asarray(m, dtype=np.float32) / 255.0
    layer = solid(cov, color)
    if glow > 0:
        g = _blur(cov, max(2.0, width * 1.6)) * 1.8
        g = np.clip(g, 0, 1) * 0.55 * glow
        gl = solid(np.ones_like(g), glow_color or color) * g[..., None]
        over(gl, layer)
        layer = gl
    return layer
