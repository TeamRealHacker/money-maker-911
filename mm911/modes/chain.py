"""💥 Chain Reaction: pictures drift around the arena, one of them pops, and every picture that touches the blast pops too.
Each pop plays a note higher than the last; when the last one is gone: CHAIN COMPLETE!
If the chain dies out, a new spark lights the nearest survivor so every seed finishes.
Built on the Breaker arena (shares its renderer, sounds, particles, slow-mo and export)."""
from __future__ import annotations

import math

import pymunk

from .breaker import BreakerSim, BBall
from .merge import SoundEvent, Particle


class ChainSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        self.pops = 0
        self.sparks = 0
        self._blasts: list[tuple[float, float, float]] = []      # x, y, start vt
        self._ignite_at = 0.9
        super().__init__(cfg, seed)
        self.constant_speed = False
        self.space.gravity = (0, 0)
        self.space.damping = 1.0
        self.counter_text = cfg.chain_counter_text
        self.final_text = cfg.chain_final_text
        self.total = max(2, int(cfg.chain_balls))
        self.broken = 0
        self._last_break_vt = self.vt

    def _radius(self) -> float:
        return self.cfg.chain_ball_radius

    def _start_balls(self) -> int:
        return self.cfg.chain_balls

    def _build_bricks(self) -> None:
        self.bricks = []
        self.total = max(2, int(self.cfg.chain_balls))

    def _add_ball(self, pos=None) -> BBall:
        x0, y0, x1, y1 = self.arena
        r = self._radius()
        pos = (self.rng.uniform(x0 + 2 * r, x1 - 2 * r), self.rng.uniform(y0 + 2 * r, y1 - 2 * r))
        ball = super()._add_ball(pos)
        ball.shape.filter = pymunk.ShapeFilter(group=1)       # pictures never push each other
        a = self.rng.uniform(0, 2 * math.pi)
        sp = self.cfg.chain_speed
        ball.shape.body.velocity = (math.cos(a) * sp, math.sin(a) * sp)
        ball.index = self.rng.randrange(max(1, self.cfg.tiers))
        return ball

    def _pop(self, ball: BBall) -> None:
        c = self.cfg
        p = ball.shape.body.position
        self.space.remove(ball.shape, ball.shape.body)
        self.balls.remove(ball)
        i = self.pops
        self.pops += 1
        self.broken = self.pops
        self._last_break_vt = self.vt
        self._blasts.append((p.x, p.y, self.vt))
        n = int(round(10 * c.particle_amount))
        for _ in range(n):
            a = self.fx.uniform(0, 2 * math.pi)
            s = self.fx.uniform(120, 420) * c.particle_speed
            life = self.fx.uniform(0.3, 0.6)
            self.particles.append(Particle(p.x, p.y, math.cos(a) * s, math.sin(a) * s, life,
                                           (ball.index, 0), self.fx.uniform(3, 7), 0.0, 0.0, life))
        if self.pops >= self.total:
            self.finished_at = self.vt
            self.final_pos = (p.x, p.y)
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 2.2)
        else:
            k = i / (self.total - 1)
            self.events.append(SoundEvent(self.t, min(c.tiers - 1, int(k * c.tiers)), "merge", vt=self.vt,
                                          pitch=c.breaker_pitch_low + (c.breaker_pitch_high - c.breaker_pitch_low) * k))
            if c.shake_strength > 0 and self.pops % 8 == 0:
                self.shake = max(self.shake, c.shake_strength * 0.5)

    def _chain(self) -> None:
        c = self.cfg
        if self.finished_at is not None:
            return
        if not self._blasts and not self.pops and self.vt >= self._ignite_at:
            self._pop(self.balls[0])                         # the first spark
        grew = True
        while grew and self.balls:
            grew = False
            for (x, y, t0) in list(self._blasts):
                rad = c.chain_radius * min(1.0, (self.vt - t0) / 0.35 + 0.35)
                for b in list(self.balls):
                    p = b.shape.body.position
                    if math.hypot(p.x - x, p.y - y) <= rad + b.shape.radius * 0.5 and self.finished_at is None:
                        self._pop(b)
                        grew = True
        self._blasts = [bl for bl in self._blasts if self.vt - bl[2] < 0.6]
        if self.pops and not self._blasts and self.balls and self.vt - self._last_break_vt > 0.8:
            self.sparks += 1                                 # chain died: light the survivor nearest the middle
            b = min(self.balls, key=lambda q: (q.shape.body.position.x - self.cx) ** 2 + (q.shape.body.position.y - self.cy) ** 2)
            self._pop(b)

    def step(self, dt: float) -> None:
        if self.finished_at is None:
            self._chain()
        sp = self.cfg.chain_speed
        for b in self.balls:
            v = b.shape.body.velocity
            n = v.length or 1.0
            b.shape.body.velocity = (v.x / n * sp, v.y / n * sp)
        super().step(dt)

    @property
    def best_tier(self) -> int:
        return self.cfg.tiers - 1 if self.won else min(self.cfg.tiers - 1, self.pops * self.cfg.tiers // self.total)

    def stats(self) -> dict:
        return {"pops": self.pops, "target": self.total, "sparks": self.sparks}
