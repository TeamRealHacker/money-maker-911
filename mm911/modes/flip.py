"""🔄 Gravity Flip: balls tumble in a box and gravity flips direction every moment (down, up, left, right).
Every flip plays a note higher than the last; after the target number of flips: GRAVITY BROKEN!
Built on the Breaker arena (shares its renderer, sounds, particles, slow-mo and export)."""
from __future__ import annotations

import math

import pymunk

from .breaker import BreakerSim, BBall
from .merge import SoundEvent, Particle

DIRS = [(0, 1), (0, -1), (1, 0), (-1, 0)]       # down, up, right, left


class FlipSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        self.flips = 0
        self._dir = 0
        self._next_flip = cfg.flip_interval
        super().__init__(cfg, seed)
        self.constant_speed = False
        self.space.damping = 0.985
        self.space.gravity = (0, cfg.flip_gravity)
        self.counter_text = cfg.flip_counter_text
        self.final_text = cfg.flip_final_text
        self.total = max(2, int(cfg.flip_target))
        self.broken = 0
        self._last_break_vt = self.vt

    def _radius(self) -> float:
        return self.cfg.flip_ball_radius

    def _start_balls(self) -> int:
        return self.cfg.flip_balls

    def _build_bricks(self) -> None:
        self.bricks = []
        self.total = max(2, int(self.cfg.flip_target))

    def _add_ball(self, pos=None) -> BBall:
        x0, y0, x1, y1 = self.arena
        r = self._radius()
        if pos is None:
            pos = (self.rng.uniform(x0 + 2 * r, x1 - 2 * r), self.rng.uniform(y0 + 2 * r, y1 - 2 * r))
        ball = super()._add_ball(pos)
        ball.shape.elasticity = 0.82
        ball.shape.body.velocity = (self.rng.uniform(-300, 300), self.rng.uniform(-300, 300))
        ball.index = len(self.balls) - 1
        return ball

    def _flip(self) -> None:
        c = self.cfg
        choices = [i for i in range(4) if i != self._dir]
        self._dir = self.rng.choice(choices)
        gx, gy = DIRS[self._dir]
        self.space.gravity = (gx * c.flip_gravity, gy * c.flip_gravity)
        self.flips += 1
        self.broken = self.flips
        self._last_break_vt = self.vt
        k = self.flips / self.total
        self.events.append(SoundEvent(self.t, min(c.tiers - 1, int(k * c.tiers)), "merge", vt=self.vt,
                                      pitch=c.breaker_pitch_low + (c.breaker_pitch_high - c.breaker_pitch_low) * k))
        for ball in self.balls:                        # a little kick so the flip is felt
            ball.shape.body.apply_impulse_at_local_point((gx * 90, gy * 90))
            p = ball.shape.body.position
            for _ in range(int(round(3 * c.particle_amount))):
                a = self.fx.uniform(0, 2 * math.pi)
                s = self.fx.uniform(80, 260) * c.particle_speed
                life = self.fx.uniform(0.3, 0.5)
                self.particles.append(Particle(p.x, p.y, math.cos(a) * s, math.sin(a) * s, life,
                                               (ball.index, 0), self.fx.uniform(3, 5), 0.0, 0.0, life))
        if self.flips >= self.total:
            self.finished_at = self.vt
            self.final_pos = (self.cx, self.cy)
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 2.2)

    def step(self, dt: float) -> None:
        if self.finished_at is None and self.vt >= self._next_flip:
            self._flip()
            self._next_flip = self.vt + self.cfg.flip_interval
        super().step(dt)

    @property
    def best_tier(self) -> int:
        return self.cfg.tiers - 1 if self.won else min(self.cfg.tiers - 1, self.flips * self.cfg.tiers // self.total)

    def stats(self) -> dict:
        return {"flips": self.flips, "target": self.total}
