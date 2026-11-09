"""Renderers for the modes beyond Merge. They reuse Renderer's background, fonts, text, particles,
banner and ball sprites (pictures / emoji / cut-outs, built at their exact size, see sprites.py)."""
from __future__ import annotations

import math

import numpy as np
import pygame

from . import sprites
from .config import color_or, hex_to_rgb
from .render import Renderer, _font, _shade


class _RingSet:
    """Escape rings, drawn with exact anti-aliasing.

    All rings without their gaps are rotation invariant, so they are composed once into one layer
    (rebuilt only when a ring is escaped). Each frame only the pixels around each ring's gap are
    recomputed from the background: wall coverage with round caps at the gap edges."""

    def __init__(self, rend: "EscapeRenderer", radii: list[float], colors: list, th: float, glow: float):
        self.r = rend
        sc = rend.scale
        self.cx = rend.cfg.width / 2 * sc
        self.cy = rend.cfg.height * rend.cfg.escape_center_y * sc
        self.th = th * sc
        self.glow = glow
        self.rings = []
        outer = max(radii) * sc + self.th * 3 + 4
        self.x0 = int(math.floor(self.cx - outer))
        self.y0 = int(math.floor(self.cy - outer))
        self.size = int(math.ceil(2 * outer)) + 2
        S = self.size
        ys, xs = np.mgrid[0:S, 0:S].astype(np.float32)
        lx = xs + self.x0 + 0.5 - self.cx
        ly = ys + self.y0 + 0.5 - self.cy
        d = np.hypot(lx, ly)
        th_ = np.arctan2(ly, lx)
        half = self.th / 2
        sig = self.th * 0.9
        band = half + 1.5 + (sig * 2.2 if glow > 0 else 0)
        for i, R0 in enumerate(radii):
            R = R0 * sc
            m = np.abs(d - R) <= band
            yy, xx = np.nonzero(m)
            t = th_[m]
            order = np.argsort(t, kind="stable")
            ring = {"R": R, "col": colors[i], "ys": yy[order].astype(np.int32), "xs": xx[order].astype(np.int32),
                    "lx": lx[m][order], "ly": ly[m][order], "dr": (d[m] - R)[order], "t": t[order]}
            ring["a"] = self._alpha(ring["dr"], None)
            self.rings.append(ring)
        self.alive = set(range(len(radii)))
        self.layer = None
        self.rebuild()

    def _alpha(self, dr, dist_cap):
        """Wall coverage (1 px anti-aliased) + soft glow. dist_cap: distance to the gap's end cap."""
        half = self.th / 2
        dist = np.abs(dr) if dist_cap is None else dist_cap
        cov = np.clip(half - dist + 0.5, 0.0, 1.0)
        if self.glow > 0:
            g = np.exp(-(np.maximum(0.0, dist - half) / (self.th * 0.9)) ** 2) * 0.42 * self.glow
            cov = cov + (1 - cov) * g
        return cov.astype(np.float32)

    def rebuild(self) -> None:
        S = self.size
        pm = np.zeros((S, S, 4), np.float32)
        for i in sorted(self.alive):
            rg = self.rings[i]
            a = rg["a"]
            col = np.array(rg["col"], np.float32) / 255.0
            cur = pm[rg["ys"], rg["xs"]]
            src = np.empty((len(a), 4), np.float32)
            src[:, :3] = col[None, :] * a[:, None]
            src[:, 3] = a
            pm[rg["ys"], rg["xs"]] = src + cur * (1 - a[:, None])
        self.layer = sprites.to_surface(pm)

    def _window(self, rg, g: float, h: float):
        m = h + (self.th + 3) / max(1.0, rg["R"])
        t = rg["t"]
        lo = (g - m + math.pi) % (2 * math.pi) - math.pi
        hi = (g + m + math.pi) % (2 * math.pi) - math.pi
        a, b = np.searchsorted(t, lo), np.searchsorted(t, hi)
        if lo <= hi:
            return np.arange(a, b)
        return np.concatenate([np.arange(a, len(t)), np.arange(0, b)])

    def _gap_alpha(self, rg, idx, g: float, h: float):
        t, lx, ly, R = rg["t"][idx], rg["lx"][idx], rg["ly"][idx], rg["R"]
        delta = (t - g + math.pi) % (2 * math.pi) - math.pi
        inside = np.abs(delta) < h
        ae = g + np.sign(delta) * h
        dist = np.hypot(lx - R * np.cos(ae), ly - R * np.sin(ae))
        a_cap = self._alpha(None, dist)
        return np.where(inside, a_cap, rg["a"][idx])

    def draw(self, S: pygame.Surface, sim, bg_arr, dx: int, dy: int) -> None:
        alive_now = {r.index for r in sim.rings if r.escaped_vt is None}
        if alive_now != self.alive:
            self.alive = alive_now
            self.rebuild()
        S.blit(self.layer, (self.x0 + dx, self.y0 + dy))
        W, H = S.get_size()
        px = pygame.surfarray.pixels3d(S)
        try:
            for ring in sim.rings:
                rg = self.rings[ring.index]
                g, h = ring.gap0 + ring.angle, ring.gap / 2
                if ring.escaped_vt is None and ring.gap <= 0:
                    continue          # a closed ring (Glass Rush) is fully on the cached layer
                if ring.escaped_vt is None:
                    idx = self._window(rg, g, h)
                    a = self._gap_alpha(rg, idx, g, h)
                else:   # escaped: fade the ring out over 0.35 s (its own pixels only)
                    age = sim.vt - ring.escaped_vt
                    if age > 0.35:
                        continue
                    idx = np.arange(len(rg["t"]))
                    a = self._gap_alpha(rg, idx, g, h) * (1 - age / 0.35)
                xs, ys = rg["xs"][idx] + self.x0 + dx, rg["ys"][idx] + self.y0 + dy
                ok = (xs >= 0) & (xs < W) & (ys >= 0) & (ys < H)
                xs, ys, a = xs[ok], ys[ok], a[ok]
                base = bg_arr[xs, ys].astype(np.float32)
                if ring.escaped_vt is not None:
                    base = px[xs, ys].astype(np.float32)
                col = np.array(rg["col"], np.float32)
                px[xs, ys] = (base * (1 - a[:, None]) + col[None, :] * a[:, None] + 0.5).astype(np.uint8)
        finally:
            del px


class EscapeRenderer(Renderer):
    def __init__(self, cfg, scale: float = 1.0):
        from .modes.escape import ring_layout
        self._ring_radii = ring_layout(cfg)
        # a ball that never changes look shows no tier number
        self._labels = cfg.show_tier_labels and cfg.escape_evolve
        super().__init__(cfg, scale)
        self.f_count = _font(cfg, int(cfg.escape_counter_size * scale), path=cfg.counter_font_path)
        self._balls: dict = {}
        self._bg_arr = None
        self.strip_icons = []

    # Merge's container is replaced by the rings
    def _make_container(self) -> None:
        cfg = self.cfg
        cols = []
        for i in range(len(self._ring_radii)):
            c = cfg.escape_ring_colors[i] if i < len(cfg.escape_ring_colors) else ""
            cols.append(color_or(c, None) or self._tier_color(i))
        self.rings = _RingSet(self, self._ring_radii, cols, cfg.escape_ring_thickness, cfg.escape_ring_glow)

    def build_tier(self, t: int, r_px: float | None = None) -> dict:
        if r_px is None:
            from .modes.escape import ball_radius
            r_px = ball_radius(self.cfg, 0) * self.scale
        return super().build_tier(t, r_px)

    def _tier_color(self, t: int) -> tuple:
        if t == 0 and self.cfg.escape_ball_color and not self.cfg.tier_value("tier_colors", 0):
            return color_or(self.cfg.escape_ball_color, super()._tier_color(0))
        return super()._tier_color(t)

    def _ball(self, tier: int, r_px: float) -> dict:
        key = (tier, round(r_px * 4) / 4)
        info = self._balls.get(key)
        if info is None:
            if len(self._balls) > 64:
                self._balls.clear()
            info = self._balls[key] = Renderer.build_tier(self, tier, key[1])
            info["trail"] = None
        return info

    def _trail_sprites(self, info: dict, n: int) -> list:
        if info.get("trail") is None:
            L = info["layers"]
            R = L["radius"]
            col = info["look"].color
            out = []
            for k in range(n):
                f = (k + 1) / (n + 1)
                pm = sprites.solid(sprites.disc(sprites._grid(int(2 * R) + 4, R + 2, R + 2), R * (0.35 + 0.6 * f)),
                                   col, 0.45 * f)
                out.append(sprites.to_surface(pm))
            info["trail"] = out
        return info["trail"]

    def _background_array(self, frame_surface):
        if self.video_bg is not None:
            return pygame.surfarray.array3d(frame_surface)
        if self._bg_arr is None:
            self._bg_arr = pygame.surfarray.array3d(self.bg)
        return self._bg_arr

    def draw(self, sim) -> pygame.Surface:
        cfg, sc, S = self.cfg, self.scale, self.surface
        if self.video_bg is not None:
            fr = self.video_bg.frame()
            S.blit(fr if fr is not None else self.bg, (0, 0))
            if fr is not None and cfg.bg_dim > 0:
                dim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
                dim.fill((0, 0, 0, min(255, cfg.bg_dim)))
                S.blit(dim, (0, 0))
            bg_arr = pygame.surfarray.array3d(S)
        else:
            S.blit(self.bg, (0, 0))
            bg_arr = self._background_array(S)
        sx, sy = (v * sc for v in sim.shake_offset())
        # hook
        y = int(cfg.hook_y * self.H)
        hook_col = self._tc(cfg.hook_color)
        for line in self._wrap(self.f_hook, cfg.hook, self.W * 0.86):
            y += self._text_center(self.f_hook, line, y, hook_col)
        # counter "3/8"
        if self._counter_tpl():
            txt = (self._counter_tpl().replace("{escaped}", str(sim.escaped)).replace("{broken}", str(sim.escaped))
                   .replace("{rings}", str(len(sim.rings))).replace("{left}", str(len(sim.rings) - sim.escaped))
                   .replace("{time}", f"{sim.vt:.1f}"))
            pulse = max(0.0, 1 - (sim.vt - sim._last_escape_vt) / 0.35) if sim.escaped else 0.0
            s = self.f_count.render(txt, True, self._tc(cfg.counter_color))
            if pulse > 0:
                s = pygame.transform.rotozoom(s, 0, 1 + 0.18 * pulse)
            cy_ = max(int(self.H * cfg.escape_counter_y), y + int(14 * sc) + s.get_height() // 2)   # below a 2-line hook
            S.blit(s, ((self.W - s.get_width()) // 2, cy_ - s.get_height() // 2))
        # rings
        self.rings.draw(S, sim, bg_arr, int(round(sx)), int(round(sy)))
        self._after_rings(S, sim, sx, sy)
        # trail + ball
        body = sim.ball.body
        tier = sim.best_tier
        info = self._ball(tier, sim.ball_r * sc)
        if cfg.escape_trail > 0 and len(sim.trail) > 1 and not (sim.finished_at is not None and cfg.escape_final_zoom > 1.0):
            tr = self._trail_sprites(info, min(24, int(cfg.escape_trail)))
            pts = sim.trail[:-1][-len(tr):]
            off = len(tr) - len(pts)
            for k, (x, y_) in enumerate(pts):
                spr = tr[k + off]
                S.blit(spr, (round(x * sc + sx - spr.get_width() / 2), round(y_ * sc + sy - spr.get_height() / 2)))
        k = 1.0
        bx, by = body.position.x * sc + sx, body.position.y * sc + sy
        if sim.finished_at is not None and cfg.escape_final_zoom > 1.0:
            # reveal: the free ball glides to the centre and grows (sprite built big = stays sharp)
            e = min(1.0, (sim.vt - sim.finished_at) / 0.7)
            e = 1 - (1 - e) ** 3
            Z = cfg.escape_final_zoom
            big = self._ball(tier, sim.ball_r * sc * Z)
            cx, cy = self.rings.cx + sx, self.rings.cy + sy
            self._blit_info(big, bx + (cx - bx) * e, by + (cy - by) * e, (1 + (Z - 1) * e) / Z)
        else:
            if sim.escaped and sim.vt - sim._last_escape_vt < 0.25:    # pop on every escape
                e = (sim.vt - sim._last_escape_vt) / 0.25
                k = 1 + 0.22 * math.sin(e * math.pi)
            self._blit_info(info, bx, by, k)
        # particles
        for p in sim.particles:
            self._draw_particle(p, sx, sy)
        # banner (new ball look)
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
            ts = self._banner_surface(bn.tier, h)
            ts.set_alpha(int(255 * (1 - out)))
            S.blit(ts, (xoff + (self.W - ts.get_width()) // 2, yb + (h - ts.get_height()) // 2))
        # watermark
        if cfg.watermark:
            self._text_at(self.f_small, cfg.watermark, cfg.watermark_y, self._tc(cfg.watermark_color),
                          max(0, min(255, cfg.watermark_opacity)))
        # ending / tension
        final_col = self._tc(cfg.final_text_color)
        if sim.finished_at is not None:
            kk = min(1.0, (sim.vt - sim.finished_at) / 0.4)
            scale = 0.5 + 0.5 * (1 - (1 - kk) ** 3) + 0.08 * math.sin(kk * math.pi)
            s = self.f_big.render(self._final_txt(), True, final_col)
            if s.get_width() * scale > self.W * 0.94:
                scale *= self.W * 0.94 / (s.get_width() * scale)
            s = pygame.transform.rotozoom(s, 0, scale)
            S.blit(s, ((self.W - s.get_width()) // 2, int(self.H * min(cfg.final_text_y, 0.75))))
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

    def _counter_tpl(self) -> str:
        return self.cfg.escape_counter_text

    def _final_txt(self) -> str:
        return self.cfg.escape_final_text

    def _after_rings(self, S, sim, sx: float, sy: float) -> None:
        pass

    def _blit_info(self, info: dict, px: float, py: float, k: float = 1.0) -> None:
        spr = info["sprite"] if k == 1.0 else pygame.transform.rotozoom(info["sprite"], 0, k)
        self.surface.blit(spr, (round(px - spr.get_width() / 2), round(py - spr.get_height() / 2)))


class GlassRenderer(EscapeRenderer):
    """Glass Rush: Escape's closed rings + crack lines that spin with the ring + a flash on every hit."""

    def build_tier(self, t: int, r_px: float | None = None) -> dict:
        if r_px is None:
            from .modes.glass import glass_ball_radius
            r_px = glass_ball_radius(self.cfg, 0) * self.scale
        return Renderer.build_tier(self, t, r_px)

    def _counter_tpl(self) -> str:
        return self.cfg.glass_counter_text

    def _final_txt(self) -> str:
        return self.cfg.glass_final_text

    def _after_rings(self, S, sim, sx: float, sy: float) -> None:
        cfg, sc = self.cfg, self.scale
        cx, cy = sim.cx * sc + sx, sim.cy * sc + sy
        col = color_or(cfg.glass_crack_color, (255, 255, 255))
        w = max(1, int(round(1.6 * sc)))
        # hit flash: a bright arc where the ball just touched the glass
        for ring in sim.rings:
            i = ring.index
            if ring.escaped_vt is not None:
                continue
            age = sim.vt - sim.hit_vt.get(i, -9.0)
            if age < 0.12:
                self._flash(S, cx, cy, ring.radius * sc, cfg.escape_ring_thickness * sc,
                            sim.hit_angle[i], 1 - age / 0.12)
            if cfg.glass_cracks and sim.cracks[i]:
                R = ring.radius
                for line in sim.cracks[i]:
                    pts = []
                    for da, dr in line:
                        a = da + ring.angle
                        r = (R + dr) * sc
                        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
                    pygame.draw.lines(S, col, False, pts, w)

    def _flash(self, S, cx, cy, R, th, ang, k) -> None:
        span = 0.5 * 160.0 * self.scale / max(1.0, R) + 0.12
        pts = []
        for j in range(9):
            a = ang - span + 2 * span * j / 8
            pts.append((cx + (R + th * 0.7) * math.cos(a), cy + (R + th * 0.7) * math.sin(a)))
        for j in range(8, -1, -1):
            a = ang - span + 2 * span * j / 8
            pts.append((cx + (R - th * 0.7) * math.cos(a), cy + (R - th * 0.7) * math.sin(a)))
        x0, y0 = int(min(p[0] for p in pts)) - 1, int(min(p[1] for p in pts)) - 1
        x1, y1 = int(max(p[0] for p in pts)) + 2, int(max(p[1] for p in pts)) + 2
        tmp = pygame.Surface((max(1, x1 - x0), max(1, y1 - y0)), pygame.SRCALPHA)
        pygame.draw.polygon(tmp, (255, 255, 255, int(150 * k)), [(x - x0, y - y0) for x, y in pts])
        S.blit(tmp, (x0, y0))


class GhostRenderer(EscapeRenderer):
    """Ghost Escape: Escape in the dark. A soft ghost light follows the ball; a ring in ghost phase gets a pale halo."""

    _mask = None

    def _counter_tpl(self) -> str:
        return self.cfg.ghost_counter_text

    def _final_txt(self) -> str:
        return self.cfg.ghost_final_text

    def _light_mask(self, R: int):
        """Black layer with a soft round hole of radius R (alpha 0 in the middle, 255*dark outside)."""
        key = (R, round(self.cfg.ghost_dark, 3))
        if self._mask is None or self._mask[0] != key:
            n = R * 2
            ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
            d = np.hypot(xs + 0.5 - R, ys + 0.5 - R) / R
            a = np.clip((d - 0.25) / 0.75, 0, 1) ** 1.6
            surf = pygame.Surface((n, n), pygame.SRCALPHA)
            rgb = pygame.surfarray.pixels3d(surf)
            rgb[:] = 0
            del rgb
            al = pygame.surfarray.pixels_alpha(surf)
            al[:] = (a.T * 255 * self.cfg.ghost_dark).astype(np.uint8)
            del al
            self._mask = (key, surf)
        return self._mask[1]

    def _after_rings(self, S, sim, sx: float, sy: float) -> None:
        cfg, sc = self.cfg, self.scale
        cx, cy = sim.cx * sc + sx, sim.cy * sc + sy
        for ring in sim.rings:
            if sim.is_ghost(ring):
                k = 0.5 + 0.5 * math.sin(sim.vt * 14)
                w = max(2, int(cfg.escape_ring_thickness * sc * 1.6))
                r = int(ring.radius * sc)
                tmp = pygame.Surface((r * 2 + w * 2, r * 2 + w * 2), pygame.SRCALPHA)
                pygame.draw.circle(tmp, (235, 245, 255, int(60 + 60 * k)), (r + w, r + w), r, w)
                S.blit(tmp, (cx - r - w, cy - r - w))
        if cfg.ghost_dark <= 0:
            return
        W, H = S.get_size()
        p = sim.ball.body.position
        bx, by = p.x * sc + sx, p.y * sc + sy
        R = int(cfg.ghost_light * sc * (1.0 + 0.04 * math.sin(sim.vt * 5)))
        dark = pygame.Surface((W, H), pygame.SRCALPHA)
        dark.fill((0, 0, 0, int(255 * cfg.ghost_dark)))
        # punch the light hole: subtract the mask alpha
        hole = self._light_mask(R)
        full = pygame.Surface(hole.get_size(), pygame.SRCALPHA)
        full.fill((0, 0, 0, int(255 * cfg.ghost_dark)))
        full.blit(hole, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        x0, y0 = int(bx - R), int(by - R)
        dark.blit(full, (x0, y0), special_flags=pygame.BLEND_RGBA_MIN) if False else None
        rect = pygame.Rect(x0, y0, 2 * R, 2 * R)
        dark.fill((0, 0, 0, 0), rect)
        dark.blit(full, (x0, y0), special_flags=pygame.BLEND_RGBA_ADD)
        S.blit(dark, (0, 0))


class BreakerRenderer(Renderer):
    """Arena + brick wall + balls. Bricks live on one cached layer; only a brick that was hit or broken
    is redrawn, so a frame costs about the same as Merge."""

    break_grow = 0.35          # a broken brick pops up by this much while it fades

    def __init__(self, cfg, scale: float = 1.0):
        self._labels = cfg.show_tier_labels
        super().__init__(cfg, scale)
        self.f_count = _font(cfg, int(cfg.escape_counter_size * 0.9 * scale), path=cfg.counter_font_path)
        self._balls: dict = {}
        self._brick_cache: dict = {}
        self.layer = None
        self._drawn: dict = {}
        self.strip_icons = []

    def build_tier(self, t: int, r_px: float | None = None) -> dict:
        return super().build_tier(t, self._radius() * self.scale if r_px is None else r_px)

    def _radius(self) -> float:
        return self.cfg.breaker_ball_radius

    def _make_container(self) -> None:
        """The arena: anti-aliased rounded frame (+ glow), drawn once."""
        cfg, sc = self.cfg, self.scale
        m = cfg.breaker_arena_margin
        x0, y0, x1, y1 = m, cfg.height * cfg.breaker_arena_top, cfg.width - m, cfg.height * cfg.breaker_arena_bottom
        th = max(2.0, cfg.container_thickness * sc * 0.6)
        pad = int(th * 6) + 4
        self.arena_px = (x0 * sc, y0 * sc, x1 * sc, y1 * sc)
        w, h = int((x1 - x0) * sc) + 2 * pad, int((y1 - y0) * sc) + 2 * pad
        rr = min(28 * sc, w / 4)
        pts = []
        # rounded rectangle outline, centred on the arena edge (outside by th/2 so balls touch its inner edge)
        X0, Y0, X1, Y1 = pad - th / 2, pad - th / 2, w - pad + th / 2, h - pad + th / 2
        for cx, cy, a0 in ((X1 - rr, Y0 + rr, -90), (X1 - rr, Y1 - rr, 0), (X0 + rr, Y1 - rr, 90), (X0 + rr, Y0 + rr, 180)):
            for k in range(9):
                a = math.radians(a0 + 90 * k / 8)
                pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        gc = color_or(cfg.container_glow_color, self.cont_col)
        layer = sprites.stroke_polygon(pts, th, self.cont_col, (w, h), ss=3 if max(w, h) <= 1600 else 2,
                                       glow=cfg.container_glow, glow_color=gc)
        self.arena_layer = sprites.to_surface(layer)
        self.arena_pos = (x0 * sc - pad, y0 * sc - pad)

    def _brick_sprite(self, b, state: str) -> pygame.Surface:
        sc = self.scale
        col = self._tier_color(b.row)
        key = (b.row, round(b.w * sc, 2), round(b.h * sc, 2), b.hp, b.max_hp, state)
        hit = self._brick_cache.get(key)
        if hit is not None:
            return hit
        w, h = max(2, int(round(b.w * sc))), max(2, int(round(b.h * sc)))
        r = min(h, w) * self.cfg.breaker_brick_round
        if b.max_hp > 1 and b.hp < b.max_hp:     # damaged = lighter
            col = _shade(col, 1 + 0.35 * (1 - b.hp / b.max_hp))
        if state == "flash":
            col = _shade(col, 1.6)
        pm = sprites.rounded_rect(w, h, r, _shade(col, 0.78))
        inner = sprites.rounded_rect(w - 4 * sc, h - 6 * sc, max(0.0, r - 2 * sc), col)
        sprites.over(pm, inner, int(round(2 * sc)), int(round(2 * sc)))
        # glossy top band
        hl = sprites.rounded_rect(w - 10 * sc, max(2, h * 0.32), max(0.0, r * 0.6), (255, 255, 255), 0.28)
        sprites.over(pm, hl, int(round(5 * sc)), int(round(4 * sc)))
        surf = sprites.to_surface(pm)
        if b.max_hp > 1 and b.hp > 1:
            f = _font(self.cfg, max(8, int(h * 0.62)))
            ts = f.render(str(b.hp), True, (30, 30, 40) if sum(col) / 3 > 150 else (250, 250, 250))
            surf.blit(ts, ((w - ts.get_width()) // 2, (h - ts.get_height()) // 2))
        if len(self._brick_cache) > 600:
            self._brick_cache.clear()
        self._brick_cache[key] = surf
        return surf

    def _sync_layer(self, sim) -> None:
        if self.layer is None:
            self.layer = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            self._drawn = {}
        sc = self.scale
        for b in sim.bricks:
            state = None if b.broken_vt is not None else b.hp
            if self._drawn.get(id(b), "x") == state:
                continue
            w, h = int(round(b.w * sc)), int(round(b.h * sc))
            x, y = int(round(b.x * sc - w / 2)), int(round(b.y * sc - h / 2))
            self.layer.fill((0, 0, 0, 0), (x, y, w + 1, h + 1))
            if state is not None:
                self.layer.blit(self._brick_sprite(b, "n"), (x, y))
            self._drawn[id(b)] = state

    def _under_balls(self, sim, dx: int, dy: int) -> None:
        """Hook for modes that paint inside the arena (Drawer)."""

    def _over_balls(self, sim, sx: float, sy: float) -> None:
        """Hook for health bars, names ... drawn on top of the balls (Battle)."""

    def _ball(self, idx: int) -> dict:
        t = idx % max(1, self.cfg.tiers)
        info = self._balls.get(t)
        if info is None:
            info = self._balls[t] = self.tiers_info[t] if t < len(self.tiers_info) else self.build_tier(t)
        return info

    def draw(self, sim) -> pygame.Surface:
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
        sx, sy = (v * sc for v in sim.shake_offset())
        dx, dy = int(round(sx)), int(round(sy))
        y = int(cfg.hook_y * self.H)
        hook_col = self._tc(cfg.hook_color)
        for line in self._wrap(self.f_hook, cfg.hook, self.W * 0.86):
            y += self._text_center(self.f_hook, line, y, hook_col)
        ctext = getattr(sim, "counter_text", None) or cfg.breaker_counter_text
        if ctext:
            left = sim.total - sim.broken
            txt = (ctext.replace("{left}", str(left)).replace("{broken}", str(sim.broken))
                   .replace("{total}", str(sim.total)).replace("{balls}", str(len(sim.balls))).replace("{pct}", str(getattr(sim, "pct", 0)))
                   .replace("{score}", str(int(round(getattr(sim, "score", 0)))))
                   .replace("{time}", f"{sim.vt:.1f}"))
            pulse = max(0.0, 1 - (sim.vt - sim._last_break_vt) / 0.2) if sim.broken else 0.0
            s = self.f_count.render(txt, True, self._tc(cfg.counter_color))
            if pulse > 0:
                s = pygame.transform.rotozoom(s, 0, 1 + 0.08 * pulse)
            cy_ = max(int(self.H * (cfg.breaker_arena_top - 0.045)), y + int(10 * sc) + s.get_height() // 2)
            S.blit(s, ((self.W - s.get_width()) // 2, cy_ - s.get_height() // 2))
        S.blit(self.arena_layer, (round(self.arena_pos[0] + dx), round(self.arena_pos[1] + dy)))
        self._sync_layer(sim)
        S.blit(self.layer, (dx, dy))
        self._under_balls(sim, dx, dy)
        # hit flashes + breaking bricks (pop and fade)
        for b in sim.bricks:
            if b.broken_vt is None and sim.vt - b.hit_vt < 0.1:
                spr = self._brick_sprite(b, "flash")
                S.blit(spr, (round(b.x * sc - spr.get_width() / 2 + dx), round(b.y * sc - spr.get_height() / 2 + dy)))
            elif b.broken_vt is not None and sim.vt - b.broken_vt < 0.25:
                e = (sim.vt - b.broken_vt) / 0.25
                spr = self._brick_sprite(b, "flash")
                spr = pygame.transform.rotozoom(spr, 0, 1 + self.break_grow * e) if self.break_grow else spr.copy()
                spr.set_alpha(int(255 * (1 - e)))
                S.blit(spr, (round(b.x * sc - spr.get_width() / 2 + dx), round(b.y * sc - spr.get_height() / 2 + dy)))
        # balls + trails
        for ball in sim.balls:
            info = self._ball(ball.index)
            if cfg.breaker_trail > 0 and len(ball.trail) > 1:
                if info.get("trail") is None:
                    R = info["layers"]["radius"]
                    n = min(16, int(cfg.breaker_trail))
                    info["trail"] = [sprites.to_surface(sprites.solid(
                        sprites.disc(sprites._grid(int(2 * R) + 4, R + 2, R + 2), R * (0.3 + 0.6 * (k + 1) / (n + 1))),
                        info["look"].color, 0.4 * (k + 1) / (n + 1))) for k in range(n)]
                tr = info["trail"]
                pts = ball.trail[:-1][-len(tr):]
                off = len(tr) - len(pts)
                for k, (x, y_) in enumerate(pts):
                    spr = tr[k + off]
                    S.blit(spr, (round(x * sc + sx - spr.get_width() / 2), round(y_ * sc + sy - spr.get_height() / 2)))
            p = ball.shape.body.position
            k = 1.0
            if sim.vt - ball.born_vt < 0.25:
                e = (sim.vt - ball.born_vt) / 0.25
                k = 0.4 + 0.6 * e + 0.15 * math.sin(e * math.pi)
            k *= getattr(ball, "scale_k", 1.0)
            spr = info["sprite"] if k == 1.0 else pygame.transform.rotozoom(info["sprite"], 0, k)
            S.blit(spr, (round(p.x * sc + sx - spr.get_width() / 2), round(p.y * sc + sy - spr.get_height() / 2)))
        self._over_balls(sim, sx, sy)
        for p in sim.particles:
            self._draw_particle(p, sx, sy)
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
            ts = self._banner_surface(bn.tier, h)
            ts.set_alpha(int(255 * (1 - out)))
            S.blit(ts, (xoff + (self.W - ts.get_width()) // 2, yb + (h - ts.get_height()) // 2))
        if cfg.watermark:
            self._text_at(self.f_small, cfg.watermark, cfg.watermark_y, self._tc(cfg.watermark_color),
                          max(0, min(255, cfg.watermark_opacity)))
        final_col = self._tc(cfg.final_text_color)
        if sim.finished_at is not None:
            kk = min(1.0, (sim.vt - sim.finished_at) / 0.4)
            scale = 0.5 + 0.5 * (1 - (1 - kk) ** 3) + 0.08 * math.sin(kk * math.pi)
            s = self.f_big.render((getattr(sim, "final_text", None) or cfg.breaker_final_text).replace("{total}", str(sim.total)), True, final_col)
            if s.get_width() * scale > self.W * 0.94:
                scale *= self.W * 0.94 / (s.get_width() * scale)
            s = pygame.transform.rotozoom(s, 0, scale)
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


class RhythmicRenderer(EscapeRenderer):
    """Rhythmic: the Escape look, with the song counter."""

    def _counter_tpl(self) -> str:
        return self.cfg.rhythm_counter_text

    def _final_txt(self) -> str:
        return self.cfg.rhythm_final_text


def _plasma(w: int, h: int, cols: list, seed: int = 1) -> np.ndarray:
    """Generated artwork for Drawer when no picture is given: smooth waves through the palette colours."""
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xs / max(1, w), ys / max(1, h)
    rng = np.random.RandomState(seed)
    f = np.zeros_like(u)
    for _ in range(4):
        a, b = rng.uniform(1.5, 4.5, 2)
        ph = rng.uniform(0, 6.28)
        f += np.sin(u * a * 3.1 + v * b * 2.3 + ph + np.sin(v * 5 + ph) * 0.6)
    f = (f / 8.0 + 0.5) % 1.0
    pal = np.array(cols, np.float32)
    n = len(pal)
    pos = f * (n - 1)
    i0 = np.clip(pos.astype(np.int32), 0, n - 2)
    t = (pos - i0)[..., None]
    return (pal[i0] * (1 - t) + pal[i0 + 1] * t).astype(np.uint8)


class DrawerRenderer(BreakerRenderer):
    """Drawer: a hidden picture (dim at first) is painted in by the brushes. The picture lives on one
    arena-sized canvas; each frame only the new brush stamps are blitted onto it."""

    def __init__(self, cfg, scale: float = 1.0):
        super().__init__(cfg, scale)
        self._canvas = None
        self._sim_id = None
        self._stamped = 0
        self._last = None
        self._full = None
        self._ghost = None
        self._masks: dict = {}

    def _picture_rgb(self, w: int, h: int) -> np.ndarray:
        from PIL import Image
        cfg = self.cfg
        pal = [hex_to_rgb(c) for c in self.pal["tiers"]]
        src = None
        for path in (cfg.drawer_picture, self.images[0] if self.images else ""):
            if path:
                src = sprites.load_source(path)
                if src is not None:
                    break
        if src is None:
            return _plasma(w, h, pal + [pal[0]], cfg.seed)
        # cover-fit, smart crop around the subject; transparent pictures sit on generated art
        k = max(w / src.width, h / src.height)
        im = sprites.resize_hq(src, (max(w, round(src.width * k)), max(h, round(src.height * k))))
        fx, fy = sprites.smart_focus(src) if cfg.image_fit == "smart" else (0.5, 0.5)
        left = int(min(max(fx * im.width - w / 2, 0), im.width - w))
        top = int(min(max(fy * im.height - h / 2, 0), im.height - h))
        im = im.crop((left, top, left + w, top + h))
        base = Image.fromarray(_plasma(w, h, pal + [pal[0]], cfg.seed)).convert("RGBA")
        base.alpha_composite(im)
        return np.asarray(base.convert("RGB"))

    def _build_canvas(self) -> None:
        sc = self.scale
        x0, y0, x1, y1 = self.arena_px
        w, h = max(8, int(round(x1 - x0))), max(8, int(round(y1 - y0)))
        rgb = self._picture_rgb(w, h)
        rr = min(28 * sc, w / 4)
        mask = sprites.rounded_rect(w, h, rr, (255, 255, 255))[..., 3]
        full = np.dstack([rgb, np.clip(mask * 255, 0, 255).astype(np.uint8)]).astype(np.uint8)
        g = float(self.cfg.drawer_ghost)
        lum = (rgb[..., 0] * 0.3 + rgb[..., 1] * 0.59 + rgb[..., 2] * 0.11)[..., None]
        dim = np.repeat(lum, 3, axis=2) * g * 0.8 + rgb * g * 0.2
        ghost = np.dstack([np.clip(dim, 0, 255), full[..., 3]]).astype(np.uint8)

        def surf(a: np.ndarray) -> pygame.Surface:
            bgra = np.ascontiguousarray(a[..., [2, 1, 0, 3]])
            return pygame.image.frombuffer(bgra.tobytes(), (a.shape[1], a.shape[0]), "BGRA").copy()
        self._full, self._ghost = surf(full), surf(ghost)
        self._canvas = self._ghost.copy()
        self._corner = int(math.ceil(rr)) + 1
        self._corners = []
        c = self._corner
        white = np.full((h, w, 4), 255, np.uint8)
        white[..., 3] = full[..., 3]
        wsurf = surf(white)
        for (cx, cy) in ((0, 0), (w - c, 0), (0, h - c), (w - c, h - c)):
            self._corners.append(((cx, cy), wsurf.subsurface((cx, cy, c, c)).copy()))
        self._wh = (w, h)

    def _mask_for(self, R: int) -> pygame.Surface:
        m = self._masks.get(R)
        if m is None:
            n = 2 * R + 2
            a = np.zeros((n, n, 4), np.uint8)
            a[..., :3] = 255
            # steep edge: overlapping stamps leave no seams
            a[..., 3] = np.clip((R + 0.5 - sprites._grid(n, R + 1, R + 1)) * 4 * 255, 0, 255).astype(np.uint8)
            m = pygame.image.frombuffer(np.ascontiguousarray(a[..., [2, 1, 0, 3]]).tobytes(), (n, n), "BGRA").copy()
            self._masks[R] = m
        return m

    def _stamp(self, x: float, y: float, R: int) -> None:
        w, h = self._wh
        sx, sy = self.arena_px[0], self.arena_px[1]
        px, py = int(round(x - sx)) - R - 1, int(round(y - sy)) - R - 1
        n = 2 * R + 2
        box = pygame.Rect(px, py, n, n).clip(pygame.Rect(0, 0, w, h))
        if box.w <= 0 or box.h <= 0:
            return
        piece = self._full.subsurface(box).copy()
        mask = self._mask_for(R).subsurface(pygame.Rect(box.x - px, box.y - py, box.w, box.h))
        piece.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self._canvas.blit(piece, box.topleft)

    def _under_balls(self, sim, dx: int, dy: int) -> None:
        if self._canvas is None:
            self._build_canvas()
        if self._sim_id != id(sim) or self._stamped > len(sim.paint_log):
            self._canvas = self._ghost.copy()
            self._sim_id, self._stamped, self._last = id(sim), 0, None
        R = max(2, int(round(sim.brush * self.scale)) + 1)      # +1 px: neighbouring bands overlap, no hairline gaps
        log = sim.paint_log
        if self._stamped < len(log):
            step = max(1.5, R * 0.1)
            last = self._last if self._stamped else None
            for x, y in log[self._stamped:]:
                x, y = x * self.scale, y * self.scale
                if last is not None:
                    d = math.hypot(x - last[0], y - last[1])
                    if d < step * 0.7:
                        continue
                    if d < R * 2.5:          # fill in between the 60 Hz positions
                        n = int(d // step)
                        for k in range(1, n + 1):
                            self._stamp(last[0] + (x - last[0]) * k / (n + 1), last[1] + (y - last[1]) * k / (n + 1), R)
                self._stamp(x, y, R)
                last = (x, y)
            self._last = last
            self._stamped = len(log)
            c = self._corner
            for (cx, cy), piece in self._corners:        # keep the rounded arena corners clean
                self._canvas.blit(piece, (cx, cy), special_flags=pygame.BLEND_RGBA_MULT)
        out = self._canvas
        if sim.finished_at is not None:
            e = min(1.0, max(0.0, (sim.vt - sim.finished_at) / 0.4))
            if e > 0:
                out = self._canvas.copy()
                self._full.set_alpha(int(255 * e))
                out.blit(self._full, (0, 0))
                self._full.set_alpha(255)
        self.surface.blit(out, (round(self.arena_px[0] + dx), round(self.arena_px[1] + dy)))


class TowerRenderer(BreakerRenderer):
    """Glass Tower: translucent glass floors that crack where they were hit."""
    break_grow = 0.0

    def _brick_sprite(self, b, state: str) -> pygame.Surface:
        sc = self.scale
        cracks = getattr(b, "cracks", [])
        key = ("g", b.row, round(b.w * sc, 1), round(b.h * sc, 1), state, tuple(round(c, 2) for c in cracks[-12:]), len(cracks) > 12)
        hit = self._brick_cache.get(key)
        if hit is not None:
            return hit
        w, h = max(4, int(round(b.w * sc))), max(4, int(round(b.h * sc)))
        col = self._tier_color(b.row)
        light = _shade(col, 0.72)
        r = min(h / 2, 8 * sc)
        e = max(1, int(round(2.2 * sc)))
        pm = sprites.rounded_rect(w, h, r, light if state != "flash" else (255, 255, 255), 0.95)
        inner = sprites.rounded_rect(w - 2 * e, h - 2 * e, max(0.0, r - e), col if state != "flash" else (255, 255, 255), 0.85 if state == "flash" else 0.55)
        pm[e:h - e, e:w - e] = inner
        hl = sprites.rounded_rect(w - 16 * sc, max(2, h * 0.2), max(0.0, h * 0.1), (255, 255, 255), 0.55)
        sprites.over(pm, hl, int(round(8 * sc)), int(round(e + 1 * sc)))
        surf = sprites.to_surface(pm)
        import random as _r
        for i, fx in enumerate(cracks[-12:]):
            rng = _r.Random(b.row * 131 + i * 17 + 5)
            x, y = fx * w, h * 0.5
            for ang in (rng.uniform(-170, -110), rng.uniform(-70, -10), rng.uniform(10, 70), rng.uniform(110, 170)):
                pts = [(x, y)]
                a = math.radians(ang)
                for _ in range(4):
                    a += math.radians(rng.uniform(-35, 35))
                    ln = rng.uniform(0.35, 0.9) * h
                    x2 = min(w - 1, max(0, pts[-1][0] + math.cos(a) * ln * 1.3))
                    y2 = min(h - 1, max(0, pts[-1][1] + math.sin(a) * ln))
                    pts.append((x2, y2))
                pygame.draw.lines(surf, (255, 255, 255, 250), False, pts, max(1, int(round(1.6 * sc))))
        if len(self._brick_cache) > 600:
            self._brick_cache.clear()
        self._brick_cache[key] = surf
        return surf


class BattleRenderer(BreakerRenderer):
    """Flag Battle: balls with health bars, a white flash on every hit and the fighter's name underneath."""

    def __init__(self, cfg, scale: float = 1.0):
        super().__init__(cfg, scale)
        self._flash: dict = {}
        self.f_name = _font(cfg, max(10, int(26 * scale)))

    def _radius(self) -> float:
        return self.cfg.battle_radius

    def _flash_sprite(self, R: int) -> pygame.Surface:
        s = self._flash.get(R)
        if s is None:
            s = sprites.to_surface(sprites.solid(sprites.disc(sprites._grid(2 * R + 2, R + 1, R + 1), R), (255, 255, 255), 0.75))
            self._flash[R] = s
        return s

    def _over_balls(self, sim, sx: float, sy: float) -> None:
        cfg, sc, S = self.cfg, self.scale, self.surface
        r = cfg.battle_radius * sc
        for ball in sim.balls:
            p = ball.shape.body.position
            x, y = p.x * sc + sx, p.y * sc + sy
            k = getattr(ball, "scale_k", 1.0)
            rr = r * k
            age = sim.vt - ball.hit_vt
            if age < 0.14:
                f = self._flash_sprite(max(2, int(round(rr))))
                f.set_alpha(int(255 * (1 - age / 0.14)))
                S.blit(f, (round(x - f.get_width() / 2), round(y - f.get_height() / 2)))
            if sim.finished_at is not None and ball is not sim.winner:
                continue
            frac = max(0.0, min(1.0, ball.hp / ball.max_hp))
            if sim.winner is ball:
                continue
            bw, bh = rr * 2.0, max(5.0, 12 * sc)
            bx, by = x - bw / 2, y - rr - bh - 6 * sc
            pygame.draw.rect(S, (30, 30, 40), (bx - 2, by - 2, bw + 4, bh + 4), border_radius=int(bh))
            col = (int(235 * min(1, 2 * (1 - frac)) + 20), int(210 * min(1, 2 * frac) + 20), 60)
            if frac > 0:
                pygame.draw.rect(S, col, (bx, by, bw * frac, bh), border_radius=int(bh))
            name = cfg.tier_value("tier_names", ball.index % max(1, cfg.tiers))
            if name:
                ts = self.f_name.render(name, True, self._tc(cfg.counter_color))
                if ts.get_width() > bw * 1.6:
                    ts = pygame.transform.smoothscale(ts, (int(bw * 1.6), max(1, int(ts.get_height() * bw * 1.6 / ts.get_width()))))
                S.blit(ts, (x - ts.get_width() / 2, y + rr + 3 * sc))


class WeaponRenderer(BattleRenderer):
    """Weapon Battle: Flag Battle plus a sword / spear / mace turning around every fighter.
    Each weapon is drawn once (supersampled) pointing right and rotated per frame."""

    def __init__(self, cfg, scale: float = 1.0):
        super().__init__(cfg, scale)
        self._blades: dict = {}

    def _blade(self, kind: str, Lpx: float, rpx: float) -> pygame.Surface:
        key = (kind, round(Lpx), round(rpx))
        spr = self._blades.get(key)
        if spr is not None:
            return spr
        from .modes.weapon import WEAPONS
        SS = 3
        pad = int(rpx * 0.6) + 4
        half = int(Lpx) + pad
        size = half * 2
        big = pygame.Surface((size * SS, size * SS), pygame.SRCALPHA)
        c = half * SS
        r = rpx * SS
        L = Lpx * SS
        wid = WEAPONS[kind][3] * r
        steel, edge, wood, dark = (232, 238, 248), (70, 78, 98), (140, 92, 54), (50, 54, 66)

        def poly(pts, col, outline=edge):
            pygame.draw.polygon(big, col, [(c + x, c + y) for x, y in pts])
            pygame.draw.polygon(big, outline, [(c + x, c + y) for x, y in pts], max(2, int(r * 0.05)))
        a0 = r * 0.55
        if kind == "sword":
            poly([(a0, -wid * 0.28), (a0 + r * 0.3, -wid * 0.28), (a0 + r * 0.3, wid * 0.28), (a0, wid * 0.28)], wood)
            poly([(a0 + r * 0.3, -wid * 0.9), (a0 + r * 0.45, -wid * 0.9), (a0 + r * 0.45, wid * 0.9), (a0 + r * 0.3, wid * 0.9)], (240, 200, 90))
            poly([(a0 + r * 0.45, -wid * 0.5), (L - wid * 1.4, -wid * 0.42), (L, 0), (L - wid * 1.4, wid * 0.42), (a0 + r * 0.45, wid * 0.5)], steel)
            pygame.draw.line(big, (255, 255, 255), (c + a0 + r * 0.55, c), (c + L - wid * 1.6, c), max(2, int(r * 0.05)))
        elif kind == "spear":
            poly([(a0, -wid * 0.35), (L - r * 0.7, -wid * 0.35), (L - r * 0.7, wid * 0.35), (a0, wid * 0.35)], wood)
            poly([(L - r * 0.75, -wid * 1.3), (L, 0), (L - r * 0.75, wid * 1.3), (L - r * 0.62, 0)], steel)
        else:
            poly([(a0, -wid * 0.3), (L - r * 0.3, -wid * 0.3), (L - r * 0.3, wid * 0.3), (a0, wid * 0.3)], wood)
            hx, hr = L - r * 0.38, r * 0.4
            for k in range(8):
                ang = k * math.pi / 4
                poly([(hx + math.cos(ang - 0.28) * hr, math.sin(ang - 0.28) * hr),
                      (hx + math.cos(ang) * hr * 1.55, math.sin(ang) * hr * 1.55),
                      (hx + math.cos(ang + 0.28) * hr, math.sin(ang + 0.28) * hr)], steel)
            pygame.draw.circle(big, dark, (c + hx, c), hr)
            pygame.draw.circle(big, edge, (c + hx, c), hr, max(2, int(r * 0.05)))
        spr = pygame.transform.smoothscale(big, (size, size))
        self._blades[key] = spr
        return spr

    def _over_balls(self, sim, sx: float, sy: float) -> None:
        sc, S = self.scale, self.surface
        r = self.cfg.battle_radius * sc
        for ball in sim.balls:
            p = ball.shape.body.position
            k = getattr(ball, "scale_k", 1.0)
            spr = self._blade(ball.weapon, sim.weapon_len(ball) * sc, r)
            rot = pygame.transform.rotozoom(spr, -math.degrees(ball.angle), k)
            S.blit(rot, (round(p.x * sc + sx - rot.get_width() / 2), round(p.y * sc + sy - rot.get_height() / 2)))
        super()._over_balls(sim, sx, sy)


class PlinkoRenderer(BreakerRenderer):
    """Plinko: pegs (flash when hit), slot dividers with their point values, +points popups."""

    def __init__(self, cfg, scale: float = 1.0):
        super().__init__(cfg, scale)
        self._pegs_layer = None
        self._peg_spr: dict = {}
        self.f_slot = _font(cfg, max(10, int(40 * scale)))
        self.f_pop = _font(cfg, max(10, int(54 * scale)))

    def _radius(self) -> float:
        return self.cfg.plinko_ball_radius

    def _peg(self, r: float, hot: float):
        key = (round(r, 1), round(hot, 1))
        s = self._peg_spr.get(key)
        if s is None:
            R = r + 3
            col = tuple(int(self.cont_col[i] + (255 - self.cont_col[i]) * hot) for i in range(3))
            n = int(2 * R + 4)
            g = sprites._grid(n, n / 2, n / 2)
            base = sprites.solid(sprites.disc(g, r), col, 1.0)
            if hot > 0:
                glow = sprites.solid(sprites.disc(g, r + 3 * self.scale * hot), (255, 255, 255), 0.35 * hot)
                sprites.over(glow, base, 0, 0)
                base = glow
            s = sprites.to_surface(base)
            self._peg_spr[key] = s
        return s

    def _under_balls(self, sim, dx: int, dy: int) -> None:
        sc, S = self.scale, self.surface
        x0, y0, x1, y1 = (v * sc for v in sim.arena)
        pr = sim.peg_r * sc
        for x, y, row, shape in sim.pegs:
            age = sim.vt - sim.peg_hit.get(id(shape), -9.0)
            hot = max(0.0, 1 - age / 0.25)
            spr = self._peg(pr, round(hot, 1))
            S.blit(spr, (round(x * sc - spr.get_width() / 2 + dx), round(y * sc - spr.get_height() / 2 + dy)))
        n = self.cfg.plinko_slots
        top = sim.slot_top * sc
        for i in range(n):
            xa = x0 + i * sim.slot_w * sc
            age = sim.vt - sim.slot_hit.get(i, -9.0)
            hot = max(0.0, 1 - age / 0.35)
            col = self._tier_color(min(self.cfg.tiers - 1, i))
            band = pygame.Surface((int(sim.slot_w * sc) - 4, int(y1 - top)), pygame.SRCALPHA)
            band.fill((*col, int(60 + 120 * hot)))
            S.blit(band, (round(xa + 2 + dx), round(top + dy)))
            txt = f"x{sim.values[i]:g}"
            ts = self.f_slot.render(txt, True, _shade(col, 0.5) if hot < 0.3 else (255, 255, 255))
            S.blit(ts, (round(xa + sim.slot_w * sc / 2 - ts.get_width() / 2 + dx), round(y1 - ts.get_height() - 6 * sc + dy)))
            if i:
                pygame.draw.line(S, self.cont_col, (xa + dx, top + dy), (xa + dx, y1 + dy), max(2, int(5 * sc)))

    def _over_balls(self, sim, sx: float, sy: float) -> None:
        sc, S = self.scale, self.surface
        for pu in sim.popups:
            age = (sim.vt - pu.born) / pu.life
            pop = min(1.0, age / 0.15)
            s = self.f_pop.render(pu.text, True, (255, 255, 255))
            o = self.f_pop.render(pu.text, True, _shade(self._tier_color(pu.tier), 0.45))
            k = 0.6 + 0.5 * pop - 0.1 * pop * pop
            s, o = pygame.transform.rotozoom(s, 0, k), pygame.transform.rotozoom(o, 0, k)
            a = int(255 * max(0.0, 1 - max(0.0, age - 0.5) / 0.5))
            s.set_alpha(a); o.set_alpha(a)
            x = pu.x * sc + sx - s.get_width() / 2
            y_ = pu.y * sc + sy - s.get_height() / 2 - age * 140 * sc
            for ddx, ddy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
                S.blit(o, (x + ddx * sc, y_ + ddy * sc))
            S.blit(s, (x, y_))


class RaceRenderer(PlinkoRenderer):
    """Race: pegs plus a chequered finish line."""

    def _radius(self) -> float:
        return self.cfg.race_ball_radius

    def _under_balls(self, sim, dx: int, dy: int) -> None:
        sc, S = self.scale, self.surface
        x0, y0, x1, y1 = (v * sc for v in sim.arena)
        pr = sim.peg_r * sc
        for x, y, row, shape in sim.pegs:
            age = sim.vt - sim.peg_hit.get(id(shape), -9.0)
            spr = self._peg(pr, round(max(0.0, 1 - age / 0.25), 1))
            S.blit(spr, (round(x * sc - spr.get_width() / 2 + dx), round(y * sc - spr.get_height() / 2 + dy)))
        fy = sim.finish_y * sc
        sq = max(8, int(24 * sc))
        for j in range(2):
            for i in range(int((x1 - x0) // sq) + 1):
                col = (255, 255, 255) if (i + j) % 2 == 0 else (25, 25, 30)
                w = min(sq, int(x1 - x0 - i * sq))
                if w > 0:
                    pygame.draw.rect(S, col, (round(x0 + i * sq + dx), round(fy + j * sq + dy), w, sq))
        ts = self.f_slot.render("FINISH", True, self.cont_col)
        S.blit(ts, (round((x0 + x1) / 2 - ts.get_width() / 2 + dx), round(fy + 2 * sq + 10 * sc + dy)))


class FlipRenderer(BreakerRenderer):
    """Gravity Flip: the Breaker arena plus big chevrons that show where "down" is, flashing on every flip."""

    def __init__(self, cfg, scale: float = 1.0):
        super().__init__(cfg, scale)
        self._chev: dict = {}

    def _radius(self) -> float:
        return self.cfg.flip_ball_radius

    def _chevron(self, d: str, size: int, bright: float) -> pygame.Surface:
        key = (d, size, round(bright, 1))
        s = self._chev.get(key)
        if s is not None:
            return s
        gx, gy = {"down": (0, 1), "up": (0, -1), "right": (1, 0), "left": (-1, 0)}[d]
        pad = size
        s = pygame.Surface((2 * size + 2 * pad, 2 * size + 2 * pad), pygame.SRCALPHA)
        cx = cy = s.get_width() / 2
        a = int(34 + 120 * bright)
        th = max(3, int(size * 0.16))
        for k in range(3):                       # three chevrons marching in the gravity direction
            off = (k - 1) * size * 0.62
            px, py = -gy, gx                     # perpendicular
            tip = (cx + gx * (off + size * 0.35), cy + gy * (off + size * 0.35))
            l = (cx + gx * (off - size * 0.25) + px * size * 0.7, cy + gy * (off - size * 0.25) + py * size * 0.7)
            r = (cx + gx * (off - size * 0.25) - px * size * 0.7, cy + gy * (off - size * 0.25) - py * size * 0.7)
            col = (*self.cont_col[:3], int(a * (0.45 + 0.28 * k)))
            pygame.draw.lines(s, col, False, [l, tip, r], th)
        if len(self._chev) > 80:
            self._chev.clear()
        self._chev[key] = s
        return s

    def _under_balls(self, sim, dx: int, dy: int) -> None:
        sc, S = self.scale, self.surface
        x0, y0, x1, y1 = (v * sc for v in sim.arena)
        size = int(min(x1 - x0, y1 - y0) * 0.17)
        spr = self._chevron(sim.dir, size, max(0.0, 1 - (sim.vt - sim.flip_vt) / 0.5))
        S.blit(spr, (round((x0 + x1) / 2 - spr.get_width() / 2 + dx), round((y0 + y1) / 2 - spr.get_height() / 2 + dy)))


class SnakeRenderer(BreakerRenderer):
    """Snake Grow: the Breaker arena, the snake's pictures as balls and a pulsing picture as food."""

    def _radius(self) -> float:
        return self.cfg.snake_radius

    def _under_balls(self, sim, dx: int, dy: int) -> None:
        if sim.food is None:
            return
        sc, S = self.scale, self.surface
        fx, fy, idx = sim.food
        info = self._ball(idx)
        k = min(1.0, (sim.vt - sim.food_born) / 0.2)
        k = (0.3 + 0.7 * k + 0.07 * math.sin(sim.vt * 7)) * 1.3
        spr = pygame.transform.rotozoom(info["sprite"], 0, max(0.1, k))
        S.blit(spr, (round(fx * sc + dx - spr.get_width() / 2), round(fy * sc + dy - spr.get_height() / 2)))


class ChainRenderer(BreakerRenderer):
    """Chain Reaction: drifting pictures plus expanding shockwave rings."""

    def _radius(self) -> float:
        return self.cfg.chain_ball_radius

    def _under_balls(self, sim, dx: int, dy: int) -> None:
        sc, S = self.scale, self.surface
        for wx, wy, born, tier in sim.waves:
            age = sim.vt - born
            if age >= 0.5:
                continue
            R = int(sim.wave_radius(age) * sc)
            if R < 2:
                continue
            fade = 1 - age / 0.5
            col = self._tier_color(tier)
            th = max(2, int(10 * sc * fade))
            size = 2 * R + 4
            s = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.circle(s, (*col, int(70 * fade)), (size // 2, size // 2), R)
            pygame.draw.circle(s, (*col, int(210 * fade)), (size // 2, size // 2), R, th)
            S.blit(s, (round(wx * sc + dx - size / 2), round(wy * sc + dy - size / 2)))
