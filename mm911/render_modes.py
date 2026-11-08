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


class BreakerRenderer(Renderer):
    """Arena + brick wall + balls. Bricks live on one cached layer; only a brick that was hit or broken
    is redrawn, so a frame costs about the same as Merge."""

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
        return super().build_tier(t, self.cfg.breaker_ball_radius * self.scale if r_px is None else r_px)

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
        if cfg.breaker_counter_text:
            left = sim.total - sim.broken
            txt = (cfg.breaker_counter_text.replace("{left}", str(left)).replace("{broken}", str(sim.broken))
                   .replace("{total}", str(sim.total)).replace("{balls}", str(len(sim.balls)))
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
        # hit flashes + breaking bricks (pop and fade)
        for b in sim.bricks:
            if b.broken_vt is None and sim.vt - b.hit_vt < 0.1:
                spr = self._brick_sprite(b, "flash")
                S.blit(spr, (round(b.x * sc - spr.get_width() / 2 + dx), round(b.y * sc - spr.get_height() / 2 + dy)))
            elif b.broken_vt is not None and sim.vt - b.broken_vt < 0.25:
                e = (sim.vt - b.broken_vt) / 0.25
                spr = pygame.transform.rotozoom(self._brick_sprite(b, "flash"), 0, 1 + 0.35 * e)
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
            spr = info["sprite"] if k == 1.0 else pygame.transform.rotozoom(info["sprite"], 0, k)
            S.blit(spr, (round(p.x * sc + sx - spr.get_width() / 2), round(p.y * sc + sy - spr.get_height() / 2)))
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
            s = self.f_big.render(cfg.breaker_final_text, True, final_col)
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
