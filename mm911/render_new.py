"""Renderers for the v0.23.0 modes (Bowling Strike, Tower Stack, Bubble Pop, Hole Eater and the
Infinite Zoom Physics Loop). They reuse Renderer / BreakerRenderer machinery exactly like the
older modes in render_modes.py; registry.py wires mode -> renderer."""
from __future__ import annotations

import math
import random

import numpy as np
import pygame

from . import sprites
from .config import color_or, hex_to_rgb
from .render import Renderer, _font, _shade
from .render_modes import BreakerRenderer


# ==================== v0.23.0: Bowling Strike, Tower Stack, Bubble Pop, Hole Eater,
# ====================           Infinite Zoom Physics Loop ====================

def _blend(base, col, alpha: float):
    """Colour as it would look drawn with `alpha` over a dark background (opaque surface)."""
    return tuple(int(round(base[i] * (1 - alpha) + col[i] * alpha)) for i in range(3))


def _hex_col(h: str, fallback):
    try:
        return hex_to_rgb(h)
    except (ValueError, TypeError):
        return fallback


class _PopupMixin:
    """Floating 'MISS' / '+1' texts (shared by the new arena modes)."""

    def _draw_popups(self, sim, sx: float, sy: float) -> None:
        sc = self.scale
        for p in sim.popups:
            age = (sim.vt - p.born) / max(0.1, p.life)
            if age > 1.0:
                continue
            col = self._tier_color(p.tier)
            f = _font(self.cfg, max(10, int(44 * sc)))
            s = f.render(p.text, True, col)
            s.set_alpha(int(255 * (1 - age)))
            self.surface.blit(s, (round(p.x * sc + sx - s.get_width() / 2),
                                  round(p.y * sc + sy - 60 * sc * age - s.get_height() / 2)))


class BowlingRenderer(_PopupMixin, BreakerRenderer):
    """The Breaker arena as a bowling lane: white pins with a red stripe, dim lane markings."""

    def _brick_sprite(self, b, state: str) -> pygame.Surface:
        sc = self.scale
        w = max(3, int(round(b.w * sc)))
        h = max(3, int(round(b.h * sc)))
        key = ("pin", w, h, b.hp, b.max_hp, state)
        hit = self._brick_cache.get(key)
        if hit is not None:
            return hit
        pm = sprites.rounded_rect(w, h, w * 0.42, (232, 232, 240))
        body = sprites.rounded_rect(max(1, w - 3 * sc), max(1, h - 4 * sc), w * 0.38, (248, 248, 252))
        sprites.over(pm, body, int(1.5 * sc), int(2 * sc))
        stripe = sprites.rounded_rect(max(1, w - 5 * sc), max(2, int(h * 0.16)), w * 0.3, (214, 40, 57))
        sprites.over(pm, stripe, int(2.5 * sc), int(h * 0.38))
        hl = sprites.rounded_rect(max(1, int(w * 0.42)), max(2, int(h * 0.22)), w * 0.2, (255, 255, 255), 0.5)
        sprites.over(pm, hl, int(w * 0.18), int(h * 0.12))
        surf = sprites.to_surface(pm)
        if state == "flash":
            surf = surf.copy()
            surf.fill((90, 90, 110), special_flags=pygame.BLEND_RGB_ADD)
        if len(self._brick_cache) > 600:
            self._brick_cache.clear()
        self._brick_cache[key] = surf
        return surf

    def _under_balls(self, sim, dx: int, dy: int) -> None:
        """Dim lane markings: a centre guide line and the foul line."""
        sc, S = self.scale, self.surface
        x0, y0, x1, y1 = self.arena_px
        cx = (x0 + x1) / 2 + dx
        col = _blend((18, 22, 30), self.cont_col, 0.35)
        for k in range(6):
            yy = y1 - (y1 - y0) * (0.14 + k * 0.11) + dy
            ln = int((x1 - x0) * 0.10)
            pygame.draw.aaline(S, col, (cx - ln / 2, yy), (cx + ln / 2, yy))
        pygame.draw.aaline(S, _blend((18, 22, 30), self.cont_col, 0.5),
                           (x0 + 6, y1 - (y1 - y0) * 0.10 + dy), (x1 - 6, y1 - (y1 - y0) * 0.10 + dy))
        self._draw_popups(sim, dx, dy)

    def _over_balls(self, sim, sx: float, sy: float) -> None:
        self._draw_popups(sim, sx, sy)


class StackerRenderer(_PopupMixin, BreakerRenderer):
    """Arena + crane: settled blocks live on the cached brick layer, the falling block and the
    dead (toppled) ones are drawn as rotated block sprites every frame."""

    def _radius(self) -> float:
        return self.cfg.stacker_block_h / 2

    def _block_sprite(self, index: int, w: float, h: float, state: str = "n") -> pygame.Surface:
        from types import SimpleNamespace
        b = SimpleNamespace(row=index % max(1, self.cfg.tiers), w=w, h=h, hp=1, max_hp=1)
        return self._brick_sprite(b, state)

    def _under_balls(self, sim, dx: int, dy: int) -> None:
        sc, S = self.scale, self.surface
        c = self.cfg
        # the crane arm + cable above the hanging block
        fb = sim.falling
        if fb is not None and sim.finished_at is None:
            p = fb.body.position
            bx, by = p.x * sc + dx, p.y * sc + dy
            top = self.arena_px[1] + dy
            col = _blend((18, 22, 30), self.cont_col, 0.55)
            pygame.draw.aaline(S, col, (bx, top), (bx, by - c.stacker_block_h * sc * 0.7))
            pygame.draw.aaline(S, col, (bx - 14 * sc, top), (bx + 14 * sc, top))
            r = max(2, int(6 * sc))
            pygame.draw.circle(S, col, (round(bx), round(by - c.stacker_block_h * sc * 0.7)), r, 1)
        # falling + dead blocks (rotated with the physics)
        blocks = []
        if fb is not None:
            blocks.append(fb)
        blocks.extend(getattr(sim, "_dead_blocks", []))
        for b in blocks:
            spr = self._block_sprite(b.index, c.stacker_block_w, c.stacker_block_h)
            if b.body.angle:
                spr = pygame.transform.rotozoom(spr, -math.degrees(b.body.angle), 1.0)
            p = b.body.position
            S.blit(spr, (round(p.x * sc + dx - spr.get_width() / 2),
                         round(p.y * sc + dy - spr.get_height() / 2)))
        self._draw_popups(sim, dx, dy)


class BubbleRenderer(_PopupMixin, BreakerRenderer):
    """Arena + rising glossy bubbles."""

    def __init__(self, cfg, scale: float = 1.0):
        super().__init__(cfg, scale)
        self._bubble_cache: dict = {}

    def _bubble_sprite(self, r: float, col) -> pygame.Surface:
        key = (int(round(r)), col)
        spr = self._bubble_cache.get(key)
        if spr is not None:
            return spr
        n = int(2 * r) + 4
        d = sprites._grid(n, r + 2, r + 2)
        pm = sprites.solid(sprites.disc(d, r), (210, 235, 255), 0.16)
        ring = np.clip(sprites.disc(d, r) - sprites.disc(d, r - max(1.5, r * 0.09)), 0, 1)
        sprites.over(pm, sprites.solid(ring, (235, 248, 255), 0.85))
        hi_r = max(1.0, r * 0.30)
        d2 = sprites._grid(n, r + 2 - r * 0.34, r + 2 - r * 0.38)
        sprites.over(pm, sprites.solid(sprites.disc(d2, hi_r), (255, 255, 255), 0.65))
        spr = sprites.to_surface(pm)
        if len(self._bubble_cache) > 200:
            self._bubble_cache.clear()
        self._bubble_cache[key] = spr
        return spr

    def _under_balls(self, sim, dx: int, dy: int) -> None:
        sc, S = self.scale, self.surface
        for i, b in enumerate(sim.bubbles):
            spr = self._bubble_sprite(b.r * sc, 0)
            age = None
            if b.popped_vt is not None and sim.vt - b.popped_vt < 0.3:
                age = (sim.vt - b.popped_vt) / 0.3
            elif b.popped_vt is not None:
                continue
            k = 1.0 + (0.55 * age if age is not None else 0.0)
            s = spr if k == 1.0 else pygame.transform.rotozoom(spr, 0, k)
            if age is not None:
                s = s.copy()
                s.set_alpha(int(255 * (1 - age)))
            S.blit(s, (round(b.x * sc + dx - s.get_width() / 2),
                       round(b.y * sc + dy - s.get_height() / 2)))
        self._draw_popups(sim, dx, dy)


class HoleRenderer(BreakerRenderer):
    """Arena + the hungry hole: a dark disc with a glowing rim that grows with every ball it eats."""

    def __init__(self, cfg, scale: float = 1.0):
        super().__init__(cfg, scale)
        self._hole_cache: dict = {}

    def _hole_sprite(self, r: float) -> pygame.Surface:
        key = int(round(r * 2))
        spr = self._hole_cache.get(key)
        if spr is not None:
            return spr
        R = key / 2.0
        n = int(2 * R * 1.25) + 8
        cx = cy = n / 2
        d = sprites._grid(n, cx, cy)
        pm = sprites.solid(sprites.disc(d, R), (4, 2, 10), 1.0)
        swirl = sprites.solid(sprites.disc(d, R * 0.72), (30, 12, 60), 0.5)
        sprites.over(pm, swirl, 0, 0)
        rim_col = _blend((10, 6, 20), (168, 108, 255), 0.95)
        rim = np.clip(sprites.disc(d, R * 1.12) - sprites.disc(d, R * 0.94), 0, 1)
        sprites.over(pm, sprites.solid(rim, rim_col, 0.9))
        glow = np.clip(sprites.disc(d, R * 1.34) - sprites.disc(d, R * 1.05), 0, 1)
        sprites.over(pm, sprites.solid(glow, rim_col, 0.28))
        spr = sprites.to_surface(pm)
        if len(self._hole_cache) > 160:
            self._hole_cache.clear()
        self._hole_cache[key] = spr
        return spr

    def _under_balls(self, sim, dx: int, dy: int) -> None:
        sc, S = self.scale, self.surface
        spr = self._hole_sprite(sim.hole_r * sc)
        S.blit(spr, (round(sim.hole_x * sc + dx - spr.get_width() / 2),
                     round(sim.hole_y * sc + dy - spr.get_height() / 2)))
        # balls being swallowed: spiral in and shrink
        for idx, x, y, born in sim.eaten_anims:
            age = (sim.vt - born) / 0.45
            if age >= 1.0:
                continue
            info = self._ball(idx)
            k = max(0.05, (1 - age)) * (info["sprite"].get_width() / max(1, 2 * self._radius() * sc))
            s = pygame.transform.rotozoom(info["sprite"], 360 * age * 0.7, k)
            xx = x + (sim.hole_x - x) * age
            yy = y + (sim.hole_y - y) * age
            S.blit(s, (round(xx * sc + dx - s.get_width() / 2), round(yy * sc + dy - s.get_height() / 2)))


class ZoomRenderer(Renderer):
    """♾️ Infinite Zoom Physics Loop: pitch-black star space, glowing blue neon stairs, a raw meme
    cutout bouncing down, and an endless exponential camera zoom. The frame at the end of every
    step is identical to its start, so the loop never has to end."""

    def __init__(self, cfg, scale: float = 1.0):
        self._labels = cfg.show_tier_labels
        self._r0 = cfg.width * cfg.zoom_platform_w * cfg.zoom_ball_size * scale
        saved = (cfg.cutout_style, cfg.cutout_outline)
        cfg.cutout_style, cfg.cutout_outline = "sticker", False    # the raw, unedited cutout look
        try:
            super().__init__(cfg, scale)
        finally:
            cfg.cutout_style, cfg.cutout_outline = saved
        self._balls: dict = {}
        self._zoom_cache: dict = {}
        self.f_count = _font(cfg, int(cfg.escape_counter_size * 0.9 * scale), path=cfg.counter_font_path)
        self._stars = self._make_stars(cfg)
        self._col = _hex_col(cfg.zoom_line_color, (53, 200, 255))
        self._col2 = _hex_col(cfg.zoom_line_color2, (27, 111, 168))

    def build_tier(self, t: int, r_px: float | None = None) -> dict:
        return super().build_tier(t, self._r0 if r_px is None else r_px)

    def _make_container(self) -> None:
        pass                                    # no container: the stairs ARE the scene

    def _make_bg(self) -> pygame.Surface:
        if self.cfg.bg_mode == "palette":       # the default: pitch-black space
            s = pygame.Surface((self.W, self.H))
            s.fill((2, 3, 8))
            return s
        return super()._make_bg()

    def _make_stars(self, cfg) -> list:
        rng = random.Random(cfg.seed * 97 + 3)
        layers = []
        n = max(0, int(cfg.zoom_stars))
        for i in range(max(1, int(cfg.zoom_star_layers))):
            q = 0.22 + 0.5 * i / max(1, cfg.zoom_star_layers - 1)
            cnt = n // max(1, cfg.zoom_star_layers)
            stars = []
            for _ in range(cnt):
                stars.append((rng.random(), rng.random(), rng.uniform(0.9, 2.4) * max(0.5, self.scale),
                              rng.uniform(0.45, 1.0), rng.uniform(0, math.tau), rng.uniform(0.8, 2.6)))
            layers.append((q, stars))
        return layers

    def _ball(self, idx: int) -> dict:
        t = idx % max(1, self.cfg.tiers)
        info = self._balls.get(t)
        if info is None:
            info = self._balls[t] = self.tiers_info[t] if t < len(self.tiers_info) else self.build_tier(t)
        return info

    def _platform_screen(self, sim, j: int, P, z: float):
        """Centre + width on screen of platform j (world coords of the current frame)."""
        g = sim.g
        # centre of platform j: C_k = 0, C_{j+1} = C1 + C_j / g
        cx = cy = 0.0
        for _ in range(j - sim.idx):
            cx, cy = sim.C1[0] + cx / g, sim.C1[1] + cy / g
        Wj = sim.W / (g ** (j - sim.idx))
        Cx, Cy = self.W / 2, self.H * 0.42
        sx = Cx + z * (cx - P[0])
        sy = Cy + z * (cy - P[1])
        return sx, sy, Wj * z

    def _neon_line(self, S, x0, y0, x1, y1, th: float, col, glow: float) -> None:
        """Glowing line: wide soft pass, mid pass, bright anti-aliased core."""
        base = (8, 10, 18)
        if th >= 1.5 and glow > 0:
            pygame.draw.line(S, _blend(base, col, 0.10 + 0.10 * glow), (x0, y0), (x1, y1), max(1, int(th * 3.4)))
            pygame.draw.line(S, _blend(base, col, 0.30 + 0.20 * glow), (x0, y0), (x1, y1), max(1, int(th * 1.8)))
        pygame.draw.aaline(S, col, (x0, y0), (x1, y1))

    def draw(self, sim) -> pygame.Surface:
        cfg, sc, S = self.cfg, self.scale, self.surface
        if self.video_bg is not None:
            fr = self.video_bg.frame()
            S.blit(fr if fr is not None else self.bg, (0, 0))
        else:
            S.blit(self.bg, (0, 0))
        # camera
        fx, fy, z = sim.camera()
        P = (fx, fy)
        age = max(0.0, sim.vt - sim.finished_at) if sim.finished_at is not None else 0.0
        reveal = min(1.0, age / 0.9) if sim.finished_at is not None else 0.0
        z *= 1.0 / (1.0 + 0.55 * reveal)
        sx_off, sy_off = (v * sc for v in sim.shake_offset())
        dx, dy = int(round(sx_off)), int(round(sy_off))
        Cx, Cy = self.W / 2 + dx, self.H * 0.42 + dy
        # stars (parallax with the zoom)
        if cfg.bg_mode == "palette" and cfg.zoom_stars > 0:
            base = (2, 3, 8)
            for q, stars in self._stars:
                s = z ** q
                W, H = self.W, self.H
                for (x, y, sz, br, ph, spd) in stars:
                    px = (Cx + (x * W - Cx) * s) % W
                    py = (Cy + (y * H - Cy) * s) % H
                    tw = 1.0 - cfg.zoom_star_twinkle * 0.45 * (1 + math.sin(sim.vt * spd + ph)) / 2
                    a = br * tw
                    col = _blend(base, (225, 238, 255), a)
                    if sz <= 1.3:
                        S.set_at((int(px), int(py)), col)
                    else:
                        pygame.draw.circle(S, col, (int(px), int(py)), max(1, int(sz)))
        # stairs: the current platform plus the next few (each smaller by 1/growth)
        j = sim.idx
        while j <= sim.idx + 7:
            sx, sy, wj = self._platform_screen(sim, j, P, z)
            if sy > self.H + wj or sx < -wj * 2 or sx > self.W + wj * 2:
                j += 1
                continue
            th = max(1.5, cfg.zoom_platform_th * (z / (sim.g ** (j - sim.idx))) * sc)
            fade = max(0.25, 1.0 - 0.16 * (j - sim.idx))
            col = tuple(int(c * fade) for c in self._col)
            col2 = tuple(int(c * fade * 0.9) for c in self._col2)
            self._neon_line(S, sx - wj / 2, sy, sx + wj / 2, sy, th, col, cfg.zoom_glow)
            for ex in (sx - wj / 2, sx + wj / 2):     # neon end caps (riser stubs)
                self._neon_line(S, ex, sy, ex, sy + th * 2.4, th * 0.8, col2, cfg.zoom_glow * 0.7)
            if j + 1 <= sim.idx + 7:                 # dim riser down to the next step
                nx, ny, _nw = self._platform_screen(sim, j + 1, P, z)
                if ny <= self.H + wj:
                    pygame.draw.aaline(S, col2, (sx + wj / 2, sy), (nx - _nw / 2, ny))
            j += 1
        # the meme cutout, tumbling
        info = self._ball(sim.tier_now())
        bx = Cx + z * (sim.pos[0] - P[0])
        by = Cy + z * (sim.pos[1] - P[1])
        k = z
        if reveal > 0:                                # the ending: it grows into the centre
            bx = bx + (self.W / 2 - bx) * reveal * 0.65
            by = by + (self.H * 0.44 - by) * reveal * 0.65
            k *= 1 + 1.7 * reveal
        key = (sim.tier_now(), round(k * 200), round((sim.angle % 360) / 6))
        spr = self._zoom_cache.get(key)
        if spr is None:
            if len(self._zoom_cache) > 420:
                self._zoom_cache.clear()
            spr = self._zoom_cache[key] = pygame.transform.rotozoom(info["sprite"], -(sim.angle % 360), k)
        S.blit(spr, (round(bx - spr.get_width() / 2), round(by - spr.get_height() / 2)))
        # landing sparks (screen space)
        ncol = max(1, len(cfg.particle_colors))
        for sp in sim.sparks:
            x, y, _vx, _vy, life, mx, col_i, sz = sp
            a = max(0.0, life / mx)
            if cfg.particle_colors and col_i[1] < len(cfg.particle_colors):
                c = color_or(cfg.particle_colors[col_i[1]], None) or self._tier_color(col_i[0])
            else:
                c = self._tier_color(col_i[0])
            S.fill(_blend((2, 3, 8), c, a * 0.9),
                   (round(x + dx - sz), round(y + dy - sz), max(1, int(2 * sz)), max(1, int(2 * sz))))
        # flash on the final landing
        if sim.finished_at is not None and age < 0.3:
            fl = pygame.Surface((self.W, self.H))
            fl.fill((160, 205, 255))
            fl.set_alpha(int(110 * (1 - age / 0.3)))
            S.blit(fl, (0, 0))
        # texts
        y = int(cfg.hook_y * self.H)
        for line in self._wrap(self.f_hook, cfg.hook, self.W * 0.86):
            y += self._text_center(self.f_hook, line, y, self._tc(cfg.hook_color))
        ctext = getattr(sim, "counter_text", None) or cfg.zoom_counter_text
        if ctext and sim.finished_at is None:
            txt = ctext.replace("{broken}", str(sim.broken)).replace("{total}", str(sim.total))
            pulse = max(0.0, 1 - (sim.vt - sim._last_land_vt) / 0.2) if sim.broken else 0.0
            s = self.f_count.render(txt, True, self._tc(cfg.counter_color))
            if pulse > 0:
                s = pygame.transform.rotozoom(s, 0, 1 + 0.08 * pulse)
            S.blit(s, ((self.W - s.get_width()) // 2, int(self.H * 0.29) - s.get_height() // 2))
        if cfg.watermark:
            self._text_at(self.f_small, cfg.watermark, cfg.watermark_y, self._tc(cfg.watermark_color),
                          max(0, min(255, cfg.watermark_opacity)))
        final_col = self._tc(cfg.final_text_color)
        if sim.finished_at is not None:
            kk = min(1.0, (sim.vt - sim.finished_at) / 0.4)
            scale_f = 0.5 + 0.5 * (1 - (1 - kk) ** 3) + 0.08 * math.sin(kk * math.pi)
            s = self.f_big.render((getattr(sim, "final_text", None) or cfg.zoom_final_text), True, final_col)
            if s.get_width() * scale_f > self.W * 0.94:
                scale_f *= self.W * 0.94 / (s.get_width() * scale_f)
            s = pygame.transform.rotozoom(s, 0, scale_f)
            S.blit(s, ((self.W - s.get_width()) // 2, int(self.H * 0.42)))
        elif not cfg.until_finished and sim.vt > cfg.max_seconds - 2.0:
            s = self.f_hook.render(cfg.fail_text, True, final_col)
            S.blit(s, ((self.W - s.get_width()) // 2, int(self.H * 0.905)))
        elif sim.tension and cfg.near_miss_text:
            pulse = 0.5 + 0.5 * math.sin(sim.vt * 9)
            s = self.f_tension.render(cfg.near_miss_text, True, final_col)
            s = pygame.transform.rotozoom(s, 0, 0.92 + 0.08 * pulse)
            s.set_alpha(int(150 + 105 * pulse))
            S.blit(s, ((self.W - s.get_width()) // 2, int(self.H * 0.905)))
        return S
