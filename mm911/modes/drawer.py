"""✏️ Drawer: the ball is a paint brush. It bounces around the arena and wherever it passes a hidden picture
(your photo, or a generated artwork) appears. Every few percent plays a note higher than the last; at the target
the rest of the picture fades in.

Built on the Breaker arena (shares its renderer, sounds, particles, slow-mo and export)."""
from __future__ import annotations

import math

import numpy as np
import pymunk

from .breaker import BreakerSim, BBall
from .merge import SoundEvent, Particle

CELL = 18.0     # coverage grid cell, px (video space)


class DrawerSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        self.paint_log: list[tuple[float, float]] = []     # brush positions, the renderer stamps them
        self._painted = 0
        self._step_n = 0
        self._last_step_pct = 0
        self._mark_vt = 0.0
        self._mark_painted = 0
        self._steer_to = None
        super().__init__(cfg, seed)
        self.counter_text = cfg.drawer_counter_text
        self.final_text = cfg.drawer_final_text
        self.brush = cfg.breaker_ball_radius * cfg.drawer_brush
        self._last_break_vt = self.vt

    def _start_balls(self) -> int:
        return self.cfg.drawer_balls

    def _build_bricks(self) -> None:
        x0, y0, x1, y1 = self.arena
        self.cols = max(4, int((x1 - x0) / CELL))
        self.rows = max(4, int((y1 - y0) / CELL))
        cw, ch = (x1 - x0) / self.cols, (y1 - y0) / self.rows
        self.cell_w, self.cell_h = cw, ch
        xs = x0 + (np.arange(self.cols) + 0.5) * cw
        ys = y0 + (np.arange(self.rows) + 0.5) * ch
        self.cx_grid, self.cy_grid = np.meshgrid(xs, ys)
        self.painted = np.zeros((self.rows, self.cols), bool)
        self.bricks = []
        self.cells = self.rows * self.cols
        self.total = max(2, int(self.cells * min(99.0, self.cfg.drawer_target) / 100.0))   # the last 1 % fades in at the end

    def _add_ball(self, pos=None, from_vel=None) -> BBall:
        ball = super()._add_ball(pos)
        ball.shape.filter = pymunk.ShapeFilter(group=1)      # brushes never push each other
        # any direction (Breaker starts upwards): an angled start draws diagonals instead of plain stripes
        a = math.radians(self.rng.uniform(20, 70) + 90 * self.rng.randrange(4))
        ball.shape.body.velocity = (math.cos(a) * self.cfg.breaker_speed, math.sin(a) * self.cfg.breaker_speed)
        return ball

    @property
    def pct(self) -> int:
        """Shown percentage: reaches 100 exactly when the target is reached."""
        return min(100, int(round(100.0 * self._painted / max(1, self.total))))

    def _paint(self) -> int:
        """Mark the cells under every brush; returns the number of new cells."""
        new = 0
        R = self.brush
        for ball in self.balls:
            p = ball.shape.body.position
            c0 = max(0, int((p.x - R - self.arena[0]) / self.cell_w))
            c1 = min(self.cols, int((p.x + R - self.arena[0]) / self.cell_w) + 2)
            r0 = max(0, int((p.y - R - self.arena[1]) / self.cell_h))
            r1 = min(self.rows, int((p.y + R - self.arena[1]) / self.cell_h) + 2)
            if c0 >= c1 or r0 >= r1:
                continue
            inside = (self.cx_grid[r0:r1, c0:c1] - p.x) ** 2 + (self.cy_grid[r0:r1, c0:c1] - p.y) ** 2 <= R * R
            sub = self.painted[r0:r1, c0:c1]
            fresh = inside & ~sub
            n = int(fresh.sum())
            if n:
                sub |= inside
                new += n
            self.paint_log.append((p.x, p.y))
        return new

    def _steer(self, dt: float) -> None:
        """Brushes that stop finding new paint bend toward the nearest unpainted spot."""
        if self.finished_at is not None:
            return
        if self.vt - self._mark_vt >= 1.0:
            gained = self._painted - self._mark_painted
            self._steer_to = gained < 0.012 * self.cells and self._painted > 0.2 * self.cells
            if self.total - self._painted < 0.04 * self.cells:
                self._steer_to = True
            self._mark_vt, self._mark_painted = self.vt, self._painted
        if not self._steer_to:
            return
        un = ~self.painted
        if not un.any():
            return
        ux, uy = self.cx_grid[un], self.cy_grid[un]
        k = min(1.0, (12.0 if self.total - self._painted < 0.04 * self.cells else 2.2) * dt)
        for ball in self.balls:
            body = ball.shape.body
            p = body.position
            d = (ux - p.x) ** 2 + (uy - p.y) ** 2
            j = int(d.argmin())
            dx, dy = ux[j] - p.x, uy[j] - p.y
            dl = math.hypot(dx, dy) or 1.0
            v = body.velocity
            sp = v.length or 1.0
            vx, vy = v.x / sp + (dx / dl - v.x / sp) * k, v.y / sp + (dy / dl - v.y / sp) * k
            n = math.hypot(vx, vy) or 1.0
            body.velocity = (vx / n * sp, vy / n * sp)

    def step(self, dt: float) -> None:
        super().step(dt)
        c = self.cfg
        new = self._paint() if self.finished_at is None else 0
        self._step_n += 1
        if new:
            self._painted += new
            self.broken = min(self.total, self._painted)
            step_pct = int(self._painted / max(1, self.total) * 100 / 2)    # a note every 2 %
            if step_pct > self._last_step_pct:
                self._last_step_pct = step_pct
                self._last_break_vt = self.vt
                k = min(1.0, self._painted / self.total)
                self.events.append(SoundEvent(self.t, min(c.tiers - 1, int(k * c.tiers)), "merge", vt=self.vt,
                                              pitch=c.breaker_pitch_low + (c.breaker_pitch_high - c.breaker_pitch_low) * k))
                if step_pct % 5 == 0:
                    self._pop(self.balls[0].shape.body.position, 10)
            if self._painted >= self.total:
                p = self.balls[0].shape.body.position
                self.finished_at = self.vt
                self.final_pos = (p.x, p.y)
                self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
                if c.slowmo_final:
                    self._slow(c.slowmo_factor, c.slowmo_seconds)
                if c.shake_strength > 0:
                    self.shake = max(self.shake, c.shake_strength * 2.0)
                self._pop(p, 60)
        if self._step_n % 3 == 0:
            self._steer(dt * 3)

    def _pop(self, pos, n: int) -> None:
        c = self.cfg
        ncol = max(1, len(c.particle_colors))
        for _ in range(int(round(n * c.particle_amount))):
            a = self.fx.uniform(0, 2 * math.pi)
            s = self.fx.uniform(120, 520) * c.particle_speed
            life = self.fx.uniform(0.35, 0.8)
            self.particles.append(Particle(pos[0], pos[1], math.cos(a) * s, math.sin(a) * s, life,
                                           (0, self.fx.randrange(ncol)), self.fx.uniform(3, 8),
                                           self.fx.uniform(0, 360), self.fx.uniform(-720, 720), life))

    @property
    def best_tier(self) -> int:
        return self.cfg.tiers - 1 if self.won else min(self.cfg.tiers - 1, self._painted * self.cfg.tiers // max(1, self.total))

    def stats(self) -> dict:
        return {"percent": self.pct, "balls": len(self.balls)}
