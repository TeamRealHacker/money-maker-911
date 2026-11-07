"""Draws Merge frames with pygame (offscreen) and exports MP4 with FFmpeg."""
from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import contextlib
import time
from pathlib import Path
from typing import Callable

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

from .audio import AudioTrack, SoundBank, load_sound, load_music  # noqa: E402
from .emoji import render_emoji  # noqa: E402
from .config import MergeConfig, PALETTES, CREDIT, hex_to_rgb, color_or  # noqa: E402
from .ffmpeg import ffmpeg_exe, best_encoder, encoder_args  # noqa: E402
from .config import QUALITIES  # noqa: E402
from .modes.merge import MergeSim  # noqa: E402
from . import imageprep  # noqa: E402

if not pygame.get_init():
    pygame.init()


def asset_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "mm911" / "assets" / Path(*parts)
    if p.exists():
        return p
    return Path(__file__).resolve().parent / "assets" / Path(*parts)


def _font(cfg: MergeConfig, size: int, bold: bool = True, path: str = "") -> pygame.font.Font:
    """Per-text font file > global font_path > bundled Poppins."""
    for cand in (path, cfg.font_path):
        if cand and Path(cand).exists():
            try:
                return pygame.font.Font(str(cand), max(6, size))
            except Exception:
                pass
    try:
        return pygame.font.Font(str(asset_path("fonts", "Poppins-Bold.ttf" if bold else "Poppins-SemiBold.ttf")),
                                max(6, size))
    except Exception:
        return pygame.font.Font(None, max(6, size))


def gradient_surface(w: int, h: int, colors: list[tuple], angle: float) -> pygame.Surface:
    """Linear gradient with 2-3 colour stops at any angle (degrees, 90 = top to bottom). numpy, fast."""
    import numpy as np
    a = math.radians(angle)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    proj = (xs - w / 2) * math.cos(a) + (ys - h / 2) * math.sin(a)
    half = abs(w / 2 * math.cos(a)) + abs(h / 2 * math.sin(a)) or 1.0
    k = np.clip((proj / half + 1) / 2, 0, 1)
    cols = np.array(colors, dtype=np.float32)
    n = len(cols) - 1
    pos = k * n
    i = np.minimum(pos.astype(np.int32), n - 1) if n > 0 else np.zeros_like(pos, dtype=np.int32)
    f = (pos - i)[..., None] if n > 0 else np.zeros((h, w, 1), np.float32)
    rgb = cols[i] * (1 - f) + cols[np.minimum(i + 1, n)] * f
    surf = pygame.Surface((w, h))
    pygame.surfarray.blit_array(surf, rgb.transpose(1, 0, 2).astype(np.uint8))
    return surf


class VideoBackground:
    """Looping background video: FFmpeg decodes frames (scaled + cropped to fill) into a pipe."""

    def __init__(self, path: str, w: int, h: int, fps: int):
        self.w, self.h, self.size = w, h, w * h * 3
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps}"
        cmd = [ffmpeg_exe(), "-v", "error", "-stream_loop", "-1", "-i", path, "-vf", vf, "-an",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        creation = 0x08000000 if os.name == "nt" else 0
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=creation)
        self.last: pygame.Surface | None = None

    def frame(self) -> pygame.Surface | None:
        try:
            raw = self.proc.stdout.read(self.size) if self.proc.stdout else b""
        except Exception:
            raw = b""
        if len(raw) == self.size:
            self.last = pygame.image.frombuffer(raw, (self.w, self.h), "RGB").copy()
        return self.last

    def close(self) -> None:
        try:
            self.proc.kill()
            self.proc.wait(timeout=2)
        except Exception:
            pass


def _shade(c: tuple, f: float) -> tuple:
    if f < 1:
        return tuple(max(0, int(v * f)) for v in c)
    return tuple(min(255, int(v + (255 - v) * (f - 1))) for v in c)


def _luma(c) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


_IMG_CACHE: dict = {}


def _load_image(path: str, size: int = 0):
    """Load a user picture once, shrunk to max 1024 px (12 MP phone photos made every settings
    change slow). Returns None for missing / broken files instead of crashing the renderer."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, st.st_mtime, st.st_size)
    hit = _IMG_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        img = pygame.image.load(path)
    except Exception:
        return None
    iw, ih = img.get_size()
    if iw < 1 or ih < 1:
        return None
    if max(iw, ih) > 1024:
        k = 1024 / max(iw, ih)
        img = pygame.transform.smoothscale(img, (max(1, int(iw * k)), max(1, int(ih * k))))
    if len(_IMG_CACHE) > 64:
        _IMG_CACHE.clear()
    _IMG_CACHE[key] = img
    return img


class Renderer:
    def __init__(self, cfg: MergeConfig, scale: float = 1.0):
        self.cfg = cfg
        self.scale = scale
        self.W, self.H = int(round(cfg.width * scale)), int(round(cfg.height * scale))
        self.pal = PALETTES.get(cfg.palette, PALETTES["Candy"])
        self.surface = pygame.Surface((self.W, self.H))
        cfg.clamp()
        # cached text-check + cut-outs only (instant); prepare_images() fills the caches beforehand
        self.images = imageprep.tier_images(cfg)["images"]
        self.text_col = color_or("", hex_to_rgb(self.pal["text"]))
        self.cont_col = color_or(cfg.container_color, hex_to_rgb(self.pal["container"]))
        self.video_bg: VideoBackground | None = None
        self.bg = self._make_bg()
        self.sprites = [self._make_sprite(t) for t in range(cfg.tiers)]
        self.shadows = [self._make_shadow(s) for s in self.sprites] if cfg.ball_shadow > 0 else []
        self.glows = [self._make_glow(t) for t in range(cfg.tiers)] if cfg.ball_glow > 0 else []
        self.f_hook = _font(cfg, int(cfg.hook_size * scale), path=cfg.hook_font_path)
        self.f_small = _font(cfg, int(cfg.watermark_size * scale), bold=False, path=cfg.watermark_font_path)
        self.f_big = _font(cfg, int(cfg.final_text_size * scale))
        self.f_label = _font(cfg, int(30 * scale))
        self.f_counter = _font(cfg, int(cfg.counter_size * scale), path=cfg.counter_font_path)
        self.f_popup = _font(cfg, int(54 * scale))
        self.f_banner = _font(cfg, int(70 * scale))
        self.f_tension = _font(cfg, int(64 * scale))
        self.p_cols = [color_or(c, (255, 255, 255)) for c in cfg.particle_colors if c]
        self._bar = 0.0
        self._bar_t = -1.0

    # ---------- prebuilt layers ----------
    def _make_bg(self) -> pygame.Surface:
        cfg = self.cfg
        s = pygame.Surface((self.W, self.H))
        mode = cfg.bg_mode
        if mode == "video" and cfg.background_video and Path(cfg.background_video).exists():
            try:
                self.video_bg = VideoBackground(cfg.background_video, self.W, self.H, cfg.fps)
            except Exception:
                self.video_bg = None
        if mode == "solid":
            s.fill(color_or(cfg.bg_colors[0] if cfg.bg_colors else "", hex_to_rgb(self.pal["bg_top"])))
            return s
        if mode == "gradient":
            cols = [color_or(c, None) for c in cfg.bg_colors[:3]]
            cols = [c for c in cols if c is not None]
            if len(cols) < 2:
                cols = [hex_to_rgb(self.pal["bg_top"]), hex_to_rgb(self.pal["bg_bottom"])]
            return gradient_surface(self.W, self.H, cols, cfg.bg_angle)
        use_image = mode in ("image", "palette") or mode not in ("solid", "gradient", "video")
        if use_image and self.cfg.background_image and Path(self.cfg.background_image).exists():
            img = pygame.image.load(self.cfg.background_image).convert() if pygame.display.get_init() and pygame.display.get_surface() else pygame.image.load(self.cfg.background_image)
            iw, ih = img.get_size()
            k = max(self.W / iw, self.H / ih)
            img = pygame.transform.smoothscale(img, (int(iw * k) + 1, int(ih * k) + 1))
            s.blit(img, ((self.W - img.get_width()) // 2, (self.H - img.get_height()) // 2))
            dim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            dim.fill((0, 0, 0, max(0, min(255, cfg.bg_dim))))
            s.blit(dim, (0, 0))
            return s
        top, bot = hex_to_rgb(self.pal["bg_top"]), hex_to_rgb(self.pal["bg_bottom"])
        for y in range(self.H):
            k = y / max(1, self.H - 1)
            pygame.draw.line(s, tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3)), (0, y), (self.W, y))
        return s

    def _tier_color(self, t: int) -> tuple:
        custom = self.cfg.tier_value("tier_colors", t)
        if custom:
            try:
                return hex_to_rgb(custom)
            except ValueError:
                pass
        tiers = self.pal["tiers"]
        return hex_to_rgb(tiers[t % len(tiers)])

    def _make_sprite(self, t: int) -> pygame.Surface:
        """Supersampled ball sprite: fill, rim, soft highlight, label or image."""
        cfg = self.cfg
        r = cfg.tier_radius(t) * self.scale
        ss = 3 if r < 450 else 2 if r < 900 else 1     # supersample, but keep huge sprites in memory
        R = max(2, int(r * ss))
        big = pygame.Surface((R * 2 + 4, R * 2 + 4), pygame.SRCALPHA)
        c = (R + 2, R + 2)
        col = self._tier_color(t)
        img_path = self.images[t] if t < len(self.images) else ""
        img_src = _load_image(img_path, 2 * R) if img_path else None
        if img_src is None:
            img_path = ""  # unreadable / missing picture: fall back to a normal ball instead of crashing
        emo = cfg.tier_value("tier_emojis", t)
        emo_surf = render_emoji(emo, R * 1.3) if emo and not (img_path and Path(img_path).exists()) else None
        if emo_surf is not None:
            pygame.draw.circle(big, _shade(col, 0.72), c, R)
            pygame.draw.circle(big, col, c, int(R * 0.9))
            sh = emo_surf.copy()
            sh.fill((0, 0, 0, 60), special_flags=pygame.BLEND_RGBA_MULT)
            big.blit(sh, (c[0] - sh.get_width() // 2 + R // 30, c[1] - sh.get_height() // 2 + R // 18))
            big.blit(emo_surf, (c[0] - emo_surf.get_width() // 2, c[1] - emo_surf.get_height() // 2))
            hl = pygame.Surface(big.get_size(), pygame.SRCALPHA)
            pygame.draw.ellipse(hl, (255, 255, 255, 45), (c[0] - R * 0.55, c[1] - R * 0.75, R * 0.7, R * 0.4))
            big.blit(hl, (0, 0))
        elif img_path and imageprep.is_cutout(img_path) and Path(img_path).exists():
            self._draw_cutout(big, c, R, col, img_path)
        elif img_path and img_src is not None:
            img = img_src
            iw, ih = img.get_size()
            k = (2 * R) / max(iw, ih)
            img = pygame.transform.smoothscale(img, (max(1, int(iw * k)), max(1, int(ih * k))))
            has_alpha = img.get_flags() & pygame.SRCALPHA or img.get_alpha() is not None
            if has_alpha:
                big.blit(img, (c[0] - img.get_width() // 2, c[1] - img.get_height() // 2))
            else:  # circle-mask photos
                mask = pygame.Surface(big.get_size(), pygame.SRCALPHA)
                pygame.draw.circle(mask, (255, 255, 255, 255), c, R)
                tmp = pygame.Surface(big.get_size(), pygame.SRCALPHA)
                tmp.blit(img, (c[0] - img.get_width() // 2, c[1] - img.get_height() // 2))
                tmp.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
                big.blit(tmp, (0, 0))
                pygame.draw.circle(big, _shade(col, 0.7), c, R, max(2, R // 14))
        else:
            pygame.draw.circle(big, _shade(col, 0.72), c, R)
            pygame.draw.circle(big, col, c, int(R * 0.9))
            hl = pygame.Surface(big.get_size(), pygame.SRCALPHA)
            pygame.draw.ellipse(hl, (255, 255, 255, 70),
                                (c[0] - R * 0.55, c[1] - R * 0.7, R * 0.8, R * 0.5))
            big.blit(hl, (0, 0))
            if cfg.show_tier_labels:
                label = cfg.tier_names[t] if t < len(cfg.tier_names) and cfg.tier_names[t] else str(t + 1)
                f = _font(cfg, max(10, int(R * (0.9 if len(label) <= 2 else 0.5))))
                txt_col = (30, 30, 40) if _luma(col) > 140 else (250, 250, 250)
                ts = f.render(label, True, txt_col)
                big.blit(ts, (c[0] - ts.get_width() // 2, c[1] - ts.get_height() // 2))
        if cfg.ball_outline > 0:
            oc = color_or(cfg.ball_outline_color, _shade(col, 0.55))
            pygame.draw.circle(big, oc, c, R, max(1, int(cfg.ball_outline * ss * self.scale)))
        size = (max(1, big.get_width() // ss), max(1, big.get_height() // ss))
        return pygame.transform.smoothscale(big, size)

    def _draw_cutout(self, big: pygame.Surface, c, R: int, col, path: str) -> None:
        """Meme cut-out as a sticker: tier disc, soft shadow, white outline, subject on top."""
        src = pygame.image.load(path)
        img = pygame.Surface(src.get_size(), pygame.SRCALPHA, 32)
        img.blit(src, (0, 0))
        side = int(R * 1.62)
        img = pygame.transform.smoothscale(img, (side, side))
        pygame.draw.circle(big, _shade(col, 0.72), c, R)
        pygame.draw.circle(big, col, c, int(R * 0.9))
        x, y = c[0] - side // 2, c[1] - side // 2
        mask = pygame.mask.from_surface(img, 100)
        sh = mask.to_surface(setcolor=(0, 0, 0, 70), unsetcolor=(0, 0, 0, 0))
        big.blit(sh, (x + R // 30, y + R // 16))
        if self.cfg.cutout_outline:
            w = max(2, R // 22)
            ol = mask.to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
            for k in range(16):
                a = k * math.pi / 8
                big.blit(ol, (x + round(math.cos(a) * w), y + round(math.sin(a) * w)))
        big.blit(img, (x, y))
        hl = pygame.Surface(big.get_size(), pygame.SRCALPHA)
        pygame.draw.ellipse(hl, (255, 255, 255, 38), (c[0] - R * 0.55, c[1] - R * 0.78, R * 0.7, R * 0.36))
        big.blit(hl, (0, 0))

    def _make_shadow(self, spr: pygame.Surface) -> pygame.Surface:
        sh = spr.copy()
        sh.fill((0, 0, 0, int(140 * min(1.0, self.cfg.ball_shadow))), special_flags=pygame.BLEND_RGBA_MIN)
        sh.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGB_MULT)
        w, h = sh.get_size()
        small = pygame.transform.smoothscale(sh, (max(1, w // 4), max(1, h // 4)))  # cheap blur
        return pygame.transform.smoothscale(small, (w, h))

    def _make_glow(self, t: int) -> pygame.Surface:
        r = self.cfg.tier_radius(t) * self.scale
        R = int(r * 1.6) + 2
        g = pygame.Surface((R * 2, R * 2), pygame.SRCALPHA)
        col = self._tier_color(t)
        a = int(110 * min(1.0, self.cfg.ball_glow))
        for i in range(12, 0, -1):
            k = i / 12
            pygame.draw.circle(g, (*col, int(a * (1 - k) ** 1.5 + 2)), (R, R), int(r + (R - r) * k))
        return g

    def close(self) -> None:
        if self.video_bg:
            self.video_bg.close()
            self.video_bg = None

    def _spins(self, t: int) -> bool:
        """Pictures and emoji roll with the physics; plain numbered balls stay upright."""
        if not hasattr(self, "_spin_cache"):
            self._spin_cache = [bool((i < len(self.images) and self.images[i]) or self.cfg.tier_value("tier_emojis", i))
                                for i in range(self.cfg.tiers)]
        return self._spin_cache[t]

    # ---------- drawing ----------
    def _text_center(self, font, text, y, color, shadow=True):
        s = font.render(text, True, color)
        x = (self.W - s.get_width()) // 2
        if shadow:
            sh = font.render(text, True, (0, 0, 0))
            sh.set_alpha(70)
            self.surface.blit(sh, (x + 3 * self.scale, y + 4 * self.scale))
        self.surface.blit(s, (x, y))
        return s.get_height()

    def _wrap(self, font, text, max_w):
        words, lines, cur = text.split(), [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if font.size(test)[0] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines[:3]

    def _tc(self, h: str) -> tuple:
        return color_or(h, self.text_col)

    def _text_at(self, font, text, y_frac, color, alpha=255):
        s = font.render(text, True, color)
        if alpha < 255:
            s.set_alpha(alpha)
        self.surface.blit(s, ((self.W - s.get_width()) // 2, int(self.H * y_frac)))

    def _draw_particle(self, p, sx, sy):
        cfg, sc, S = self.cfg, self.scale, self.surface
        col = self.p_cols[p.color[1] % len(self.p_cols)] if self.p_cols else self._tier_color(p.color[0])
        x, y = p.x * sc + sx, p.y * sc + sy
        size = max(1.0, p.size * sc * min(1, p.life * 2))
        st = cfg.particle_style
        if st == "squares" or st == "confetti":
            w, h = (size * 2, size * (0.9 if st == "confetti" else 2))
            surf = pygame.Surface((max(1, int(w)), max(1, int(h))), pygame.SRCALPHA)
            surf.fill(col)
            surf = pygame.transform.rotate(surf, p.rot)
            S.blit(surf, (x - surf.get_width() / 2, y - surf.get_height() / 2))
        elif st == "stars":
            pts = []
            for i in range(10):
                a = math.radians(p.rot) + math.pi * i / 5
                rr = size * 1.5 if i % 2 == 0 else size * 0.65
                pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
            pygame.draw.polygon(S, col, pts)
        elif st == "sparks":
            k = 0.035
            pygame.draw.line(S, col, (x, y), (x - p.vx * k * sc, y - p.vy * k * sc), max(1, int(size * 0.6)))
        elif st == "rings":
            pygame.draw.circle(S, col, (x, y), size * 1.4, max(1, int(size * 0.35)))
        else:
            pygame.draw.circle(S, col, (x, y), size)

    def draw(self, sim: MergeSim) -> pygame.Surface:
        cfg, sc, S = self.cfg, self.scale, self.surface
        if self.video_bg is not None:
            fr = self.video_bg.frame()
            S.blit(fr if fr is not None else self.bg, (0, 0))
            if fr is not None and cfg.bg_dim > 0:
                dim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
                dim.fill((0, 0, 0, min(255, cfg.bg_dim)))
                S.blit(dim, (0, 0))
        else:
            S.blit(self.bg, (0, 0))
        text_col = self.text_col
        cont_col = self.cont_col
        sx, sy = (v * sc for v in sim.shake_offset())

        # hook text
        y = int(cfg.hook_y * self.H)
        hook_col = self._tc(cfg.hook_color)
        for line in self._wrap(self.f_hook, cfg.hook, self.W * 0.86):
            y += self._text_center(self.f_hook, line, y, hook_col)

        # tier progress strip
        if cfg.show_progress:
            n = cfg.tiers
            dot = int(min(70 * sc, (self.W * 0.8) / n))
            gap = dot * 0.2
            total = n * dot + (n - 1) * gap
            x0 = (self.W - total) / 2
            yy = y + int(30 * sc)
            for t in range(n):
                small = pygame.transform.smoothscale(self.sprites[t], (max(1, dot), max(1, dot)))
                if t > sim.best_tier:
                    small.set_alpha(60)
                S.blit(small, (x0 + t * (dot + gap), yy))

        # container glow + shadow + walls
        pts = [(x * sc + sx, y_ * sc + sy) for x, y_ in sim.outline_world()]
        th = max(2, int(cfg.container_thickness * sc))
        if cfg.container_glow > 0:
            gc = color_or(cfg.container_glow_color, cont_col)
            gl = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            for i in range(6, 0, -1):
                a = int(28 * cfg.container_glow * (7 - i) / 6)
                pygame.draw.lines(gl, (*gc, a), True, pts, th + int(i * 7 * sc))
            S.blit(gl, (0, 0))
        shadow = [(x + 6 * sc, y_ + 10 * sc) for x, y_ in pts]
        sh = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        pygame.draw.lines(sh, (0, 0, 0, 55), True, shadow, th)
        S.blit(sh, (0, 0))
        pygame.draw.lines(S, cont_col, True, pts, th)
        for p in pts:
            pygame.draw.circle(S, cont_col, p, th / 2)

        # balls (glow -> shadow -> sprite)
        for b in sim.balls:
            pos = b.shape.body.position
            px, py = pos.x * sc + sx, pos.y * sc + sy
            e = 1 - (1 - b.pop) ** 3
            k = 0.6 + 0.4 * e + 0.12 * math.sin(e * math.pi) if b.pop < 1 else 1.0
            if self.glows:
                g = self.glows[b.tier] if k == 1.0 else pygame.transform.rotozoom(self.glows[b.tier], 0, k)
                S.blit(g, (px - g.get_width() / 2, py - g.get_height() / 2))
            if self.shadows:
                shd = self.shadows[b.tier] if k == 1.0 else pygame.transform.rotozoom(self.shadows[b.tier], 0, k)
                off = 8 * sc * (1 + b.tier * 0.15)
                S.blit(shd, (px - shd.get_width() / 2 + off * 0.5, py - shd.get_height() / 2 + off))
            spr = self.sprites[b.tier]
            ang = -math.degrees(b.shape.body.angle) if self._spins(b.tier) else 0
            if k != 1.0 or ang:
                spr = pygame.transform.rotozoom(spr, ang, k)
            S.blit(spr, (px - spr.get_width() / 2, py - spr.get_height() / 2))

        # particles
        for p in sim.particles:
            self._draw_particle(p, sx, sy)

        # combo popups (float up and fade)
        for pu in sim.popups:
            age = (sim.vt - pu.born) / pu.life
            pop = min(1.0, age / 0.15)
            s = self.f_popup.render(pu.text, True, (255, 255, 255))
            o = self.f_popup.render(pu.text, True, _shade(self._tier_color(pu.tier), 0.45))
            k = 0.6 + 0.5 * pop - 0.1 * pop * pop
            s, o = pygame.transform.rotozoom(s, 0, k), pygame.transform.rotozoom(o, 0, k)
            a = int(255 * max(0.0, 1 - max(0.0, age - 0.6) / 0.4))
            s.set_alpha(a); o.set_alpha(a)
            x = pu.x * sc + sx - s.get_width() / 2
            y_ = pu.y * sc + sy - s.get_height() / 2 - age * 120 * sc
            for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
                S.blit(o, (x + dx * sc, y_ + dy * sc))
            S.blit(s, (x, y_))

        # tier-reached banner
        for bn in sim.banners:
            age = (sim.vt - bn.born) / bn.life
            slide = min(1.0, age / 0.18)
            out = min(1.0, max(0.0, (age - 0.8) / 0.2))
            col = self._tier_color(bn.tier)
            h = int(110 * sc)
            yb = int(self.H * 0.21)
            band = pygame.Surface((self.W, h), pygame.SRCALPHA)
            band.fill((*_shade(col, 0.55), int(200 * (1 - out))))
            xoff = int((1 - (1 - (1 - slide) ** 3)) * -self.W + out * self.W)
            S.blit(band, (xoff, yb))
            txt = cfg.banner_text.replace("{name}", cfg.tier_label(bn.tier)).replace("{tier}", str(bn.tier + 1))
            try:
                ts = self.f_banner.render(txt, True, (255, 255, 255))
            except Exception:
                ts = self.f_banner.render(f"Tier {bn.tier + 1}!", True, (255, 255, 255))
            ts.set_alpha(int(255 * (1 - out)))
            S.blit(ts, (xoff + (self.W - ts.get_width()) // 2, yb + (h - ts.get_height()) // 2))

        # progress bar toward the Final Form
        if cfg.show_progress_bar:
            goal = sim.best_tier / max(1, cfg.tiers - 1)
            gap_t = sim.vt - self._bar_t
            self._bar_t = sim.vt
            if gap_t <= 0 or gap_t > 0.5:      # first frame / thumbnail: show the real value
                self._bar = goal
            else:                               # ease toward the goal (frame-rate independent)
                self._bar += (goal - self._bar) * (1 - math.exp(-gap_t * 9))
            bw, bh = int(self.W * 0.7), max(4, int(22 * sc))
            bx, by = (self.W - bw) // 2, int(self.H * cfg.progress_bar_y)
            bc = self._tc(cfg.progress_bar_color)
            track = pygame.Surface((bw, bh), pygame.SRCALPHA)
            pygame.draw.rect(track, (*bc, 60), (0, 0, bw, bh), border_radius=bh // 2)
            S.blit(track, (bx, by))
            if self._bar > 0.01:
                pygame.draw.rect(S, bc, (bx, by, max(bh, int(bw * self._bar)), bh), border_radius=bh // 2)
            pct = self.f_label.render(f"{int(round(self._bar * 100))}%", True, bc)
            S.blit(pct, (bx + bw + int(14 * sc), by + (bh - pct.get_height()) // 2))

        # merge counter
        if cfg.show_counter:
            txt = (cfg.counter_text.replace("{merges}", str(sim.merges)).replace("{tier}", str(sim.best_tier + 1))
                   .replace("{tiers}", str(cfg.tiers)).replace("{time}", f"{sim.vt:.1f}")
                   .replace("{combo}", str(sim.best_combo)))
            self._text_at(self.f_counter, txt, cfg.counter_y, self._tc(cfg.counter_color))

        # watermark / credit
        wm = cfg.watermark or ""
        if wm:
            self._text_at(self.f_small, wm, cfg.watermark_y, self._tc(cfg.watermark_color),
                          max(0, min(255, cfg.watermark_opacity)))

        # ending
        final_col = self._tc(cfg.final_text_color)
        if sim.finished_at is not None:
            k = min(1.0, (sim.vt - sim.finished_at) / 0.4)
            scale = 0.5 + 0.5 * (1 - (1 - k) ** 3) + 0.08 * math.sin(k * math.pi)
            s = self.f_big.render(cfg.final_text, True, final_col)
            if s.get_width() * scale > self.W * 0.94:
                scale *= self.W * 0.94 / (s.get_width() * scale)
            s = pygame.transform.rotozoom(s, 0, scale)
            S.blit(s, ((self.W - s.get_width()) // 2, int(self.H * cfg.final_text_y)))
        elif not cfg.until_finished and sim.vt > cfg.max_seconds - 2.0:
            s = self.f_hook.render(cfg.fail_text, True, final_col)
            S.blit(s, ((self.W - s.get_width()) // 2, int(self.H * (cfg.final_text_y + 0.01))))
        elif sim.tension and cfg.near_miss_text:
            pulse = 0.5 + 0.5 * math.sin(sim.vt * 9)
            s = self.f_tension.render(cfg.near_miss_text, True, final_col)
            s = pygame.transform.rotozoom(s, 0, 0.92 + 0.08 * pulse)
            s.set_alpha(int(150 + 105 * pulse))
            S.blit(s, ((self.W - s.get_width()) // 2, int(self.H * (cfg.final_text_y + 0.01))))
        return S


PHYSICS_HZ = 60


def physics_steps(fps: int):
    """Physics runs at a fixed 60 Hz (or the frame rate when it is higher), whatever FPS you export.
    So a seed plays out the same at 24, 30 or 60 fps, and 'only wins' seeds stay wins.
    Yields, for each video frame, how many physics steps to run and their dt."""
    fps = max(1, int(fps))
    hz = max(PHYSICS_HZ, fps)
    per = hz / fps
    acc = 0.0
    while True:
        acc += per
        n = int(acc + 1e-9)
        acc -= n
        yield n, 1.0 / hz


def simulate(cfg: MergeConfig) -> MergeSim:
    """Run the physics only (fast) — used to find winning seeds."""
    sim = MergeSim(cfg)
    hz = max(PHYSICS_HZ, int(cfg.fps))
    while not sim.done:
        sim.step(1.0 / hz)
    return sim


def _step_frame(sim: MergeSim, steps) -> None:
    n, dt = next(steps)
    for _ in range(n):
        if sim.done:
            break
        sim.step(dt)


def render_video(cfg: MergeConfig, out_path: str, progress: Callable[[float], None] | None = None,
                 encoder: list[str] | None = None, lock=None) -> dict:
    """Render one Merge video to MP4. Returns metadata.
    `lock`: optional lock held around every pygame call (the desktop app passes one so the
    render thread never draws at the same time as the live preview — pygame is not thread-safe)."""
    lock = lock or contextlib.nullcontext()
    t0 = time.time()
    cfg.sanitize_export()
    prepare_images(cfg, lock)
    sound_plan = None
    if cfg.auto_sounds:      # Myinstants auto sounds (cached; offline = built-in pop)
        from .sounds import resolve_auto
        sound_plan = resolve_auto(cfg)
    sim = MergeSim(cfg)
    with lock:
        rend = Renderer(cfg, cfg.export_scale())
    steps = physics_steps(cfg.fps)
    est_frames = int(cfg.video_seconds() * cfg.fps)
    out_path = str(out_path)
    out_path = str(Path(out_path).with_suffix("." + cfg.export_format))   # .mp4 or .mov from Export settings
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="mm911_")
    silent = os.path.join(tmpdir, "video" + Path(out_path).suffix)
    if encoder:
        enc, enc_name = encoder, encoder[1] if len(encoder) > 1 else "custom"
    else:
        enc, enc_name = encoder_args(cfg.export_codec, QUALITIES.get(cfg.export_quality, 18), cfg.export_encoder)
    cmd = [ffmpeg_exe(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{rend.W}x{rend.H}", "-r", str(cfg.fps), "-i", "-",
           "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",   # encoders need even sizes
           *enc, "-pix_fmt", "yuv420p", "-r", str(cfg.fps), "-movflags", "+faststart", silent]
    creation = 0x08000000 if os.name == "nt" else 0  # no console window on Windows
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creation)
    frames = 0
    thumb = None
    try:
        while not sim.done:
            _step_frame(sim, steps)
            with lock:
                surf = rend.draw(sim)
                if cfg.export_thumbnail and thumb is None and _thumb_moment_frame(sim, cfg):
                    thumb = surf.copy()
                raw = pygame.image.tobytes(surf, "RGB")
            try:
                proc.stdin.write(raw)
            except (BrokenPipeError, OSError):
                break   # encoder died; the error is reported below
            frames += 1
            if progress and frames % 15 == 0:
                progress(min(0.97, frames / est_frames))
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        proc.wait()
        rend.close()
    if proc.returncode != 0:
        raise RuntimeError(f"Video encoder ({enc_name}) failed: {err.strip()[-400:]}")
    seconds = frames / cfg.fps
    thumb_path = ""
    if cfg.export_thumbnail:
        thumb_path = str(Path(out_path).with_suffix(".jpg"))
        with lock:
            _save_jpg(thumb if thumb is not None else rend.surface, thumb_path)
    if cfg.export_audio:
        wav = os.path.join(tmpdir, "audio.wav")
        build_audio(cfg, sim, seconds).write(wav, seconds)
        r = subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-i", silent, "-i", wav, "-map", "0:v:0", "-map", "1:a:0",
                            "-c:v", "copy", "-c:a", "aac", "-b:a", f"{int(cfg.audio_bitrate)}k", "-ar", "44100",
                            "-ac", "2", "-movflags", "+faststart", "-shortest", out_path],
                           capture_output=True, creationflags=creation)
        if r.returncode != 0:
            raise RuntimeError("Adding the sound failed: " + r.stderr.decode("utf-8", "replace").strip()[-400:])
        _rm(wav)
        _rm(silent)
    else:
        os.replace(silent, out_path)
    try:
        os.rmdir(tmpdir)
    except OSError:
        pass
    if progress:
        progress(1.0)
    return {"file": out_path, "seed": cfg.seed, "won": sim.won, "best_tier": sim.best_tier + 1,
            "seconds": round(seconds, 2), "merges": sim.merges, "best_combo": sim.best_combo,
            "thumbnail": thumb_path, "fps": cfg.fps, "size": f"{rend.W}x{rend.H}", "encoder": enc_name,
            "render_seconds": round(time.time() - t0, 1),
            "sounds": [d["name"] for d in (sound_plan or {}).get("sounds", [])]
            + [f"{k}: {Path(getattr(cfg, k)).name}" for k in ("drop_sound", "final_sound") if getattr(cfg, k)]}


def _rm(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def build_audio(cfg: MergeConfig, sim: MergeSim, seconds: float) -> AudioTrack:
    """Mix the pitched pops (drop / merge / final, per-tier sounds via SoundBank) and optional music.
    Events are placed at their VIDEO time (ev.vt), so they stay in sync with Speed, slow motion
    and the near-miss pause (ev.t is simulation time)."""
    track = AudioTrack(seconds)
    bank = SoundBank(cfg)
    last_t = -1.0
    for ev in sim.events:
        at = getattr(ev, "vt", None)
        if at is None:
            at = ev.t / max(0.05, cfg.speed)
        if ev.kind == "drop":
            if not cfg.drop_sounds or at - last_t < 0.05:
                continue
            last_t = at
        sample, semis, vol = bank.event(ev.kind, ev.tier)
        track.add(sample, at, semis, vol)
    if cfg.music_path and cfg.music_volume > 0:
        track.add_music(load_music(cfg.music_path, seconds + 3), cfg.music_volume)
    return track


def prepare_images(cfg: MergeConfig, lock=None, note=None) -> dict:
    """Run the text check / cut-outs the config asks for (cached, so repeat renders are free)."""
    if not (cfg.ai_cutout or cfg.reject_text) or not imageprep.candidate_images(cfg):
        return {"images": [], "skipped": [], "cut": 0, "errors": []}
    return imageprep.tier_images(cfg, prepare=True, lock=lock, note=note)


def _thumb_moment_frame(sim: MergeSim, cfg: MergeConfig) -> bool:
    """First frame at/after the Final Form has popped in (works at any FPS)."""
    return sim.finished_at is not None and sim.vt >= sim.finished_at + 0.45   # finished_at is video time


def _thumb_moment(sim: MergeSim, cfg: MergeConfig) -> bool:
    """Best frame for a thumbnail: FINAL FORM fully popped in (or the last second of a near miss)."""
    if sim.finished_at is not None:
        return sim.finished_at + 0.45 <= sim.vt < sim.finished_at + 0.45 + 1.0 / cfg.fps
    return False


def _save_jpg(surf: pygame.Surface, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surf, path)


def make_thumbnail(cfg: MergeConfig, out_path: str) -> dict:
    """Thumbnail only (no video): runs the physics fast and grabs the Final Form moment."""
    prepare_images(cfg)
    sim = MergeSim(cfg)
    rend = Renderer(cfg)
    steps = physics_steps(cfg.fps)
    shot = None
    while not sim.done:
        _step_frame(sim, steps)
        if _thumb_moment_frame(sim, cfg):
            shot = rend.draw(sim).copy()
            break
    if shot is None:
        shot = rend.draw(sim)
    _save_jpg(shot, out_path)
    rend.close()
    return {"file": out_path, "seed": cfg.seed, "won": sim.won, "best_tier": sim.best_tier + 1}


def render_preview_frame(cfg: MergeConfig, sim: MergeSim, rend: Renderer) -> bytes:
    """JPEG bytes of the current frame (for the live preview in the app)."""
    import io
    surf = rend.draw(sim)
    buf = io.BytesIO()
    pygame.image.save(surf, buf, "preview.jpg")
    return buf.getvalue()


__all__ = ["Renderer", "render_video", "build_audio", "make_thumbnail", "simulate", "render_preview_frame",
           "prepare_images", "CREDIT"]
