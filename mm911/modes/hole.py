"""🕳️ Hole Eater: a hungry glowing hole glides around the arena swallowing drifting balls —
every ball it eats is a note higher and the hole grows a little. Eat them all: ALL EATEN!

Balls that get close try to flee, but the hole is patient and always catches up, so every seed
finishes. Built on the Breaker arena (shares its renderer machinery, sounds, particles, export)."""
from __future__ import annotations

import math

import pymunk

from .breaker import BBall, BreakerSim
from .merge import Particle, SoundEvent


class HoleSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        self.hole_x = 0.0
        self.hole_y = 0.0
        self.hole_r = cfg.hole_radius
        self.eaten_anims: list[list] = []      # [index, x, y, born_vt] — the suck-in animation
        super().__init__(cfg, seed)
        self.counter_text = cfg.hole_counter_text
        self.final_text = cfg.hole_final_text
        x0, y0, x1, y1 = self.arena
        self.hole_x = (x0 + x1) / 2
        self.hole_y = y0 + (y1 - y0) * 0.62
        self._wander = self.fx.uniform(0, math.tau)

    # ---------- setup ----------
    def _build_bricks(self) -> None:
        self.bricks = []
        self.total = max(2, int(self.cfg.hole_balls))

    def _radius(self) -> float:
        return self.cfg.hole_ball_radius

    def _start_balls(self) -> int:
        return max(1, self.cfg.hole_balls)

    def _add_ball(self, pos=None, from_vel=None) -> BBall:
        ball = super()._add_ball(pos)
        ball.shape.filter = pymunk.ShapeFilter(group=1)     # balls never push each other
        return ball

    # ---------- eating ----------
    def _eat(self, ball: BBall) -> None:
        c = self.cfg
        x, y = ball.shape.body.position.x, ball.shape.body.position.y
        self.space.remove(ball.shape, ball.shape.body)
        self.balls.remove(ball)
        self.eaten_anims.append([ball.index, x, y, self.vt])
        self.broken += 1
        self._last_break_vt = self.vt
        i = self.broken
        self.hole_r *= (1.0 + c.hole_growth)
        self.events.append(SoundEvent(self.t, min(i * c.tiers // max(1, self.total), c.tiers - 1),
                                      "merge", vt=self.vt, pitch=self._pitch(i)))
        self._burst(x, y, 6, i)
        if self.broken >= self.total and self.finished_at is None:
            self.finished_at = self.vt
            self.final_pos = (self.hole_x, self.hole_y)
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 2.0)

    def _pitch(self, i: int) -> float:
        c = self.cfg
        k = (i - 1) / max(1, self.total - 1)
        return c.breaker_pitch_low + (c.breaker_pitch_high - c.breaker_pitch_low) * k

    def _burst(self, x: float, y: float, n: int, i: int) -> None:
        c = self.cfg
        n = int(round(n * c.particle_amount))
        ncol = max(1, len(c.particle_colors))
        for _ in range(n):
            a = self.fx.uniform(0, 2 * math.pi)
            sp = self.fx.uniform(60, 360) * c.particle_speed
            life = self.fx.uniform(0.25, 0.55)
            self.particles.append(Particle(x, y, math.cos(a) * sp, math.sin(a) * sp, life,
                                           (i % max(1, c.tiers), self.fx.randrange(ncol)),
                                           self.fx.uniform(3, 6),
                                           self.fx.uniform(0, 360), self.fx.uniform(-540, 540), life))

    # ---------- main step ----------
    def step(self, dt: float) -> None:
        c = self.cfg
        super().step(dt)
        sp = c.hole_drift                        # the arena code normalises to breaker_speed;
        for b in self.balls:                     # re-normalise to the gentle drift speed
            v = b.shape.body.velocity
            n = math.hypot(v.x, v.y) or 1.0
            b.shape.body.velocity = (v.x / n * sp, v.y / n * sp)
        if self.finished_at is not None:
            self.eaten_anims = [a for a in self.eaten_anims if self.vt - a[3] < 0.5]
            return
        # the hole glides toward the nearest ball (it never gives up)
        self._wander += dt * 1.7
        if self.balls:
            tgt = min(self.balls, key=lambda b: (b.shape.body.position.x - self.hole_x) ** 2
                      + (b.shape.body.position.y - self.hole_y) ** 2)
            p = tgt.shape.body.position
            dx, dy = p.x - self.hole_x, p.y - self.hole_y
            dl = math.hypot(dx, dy) or 1.0
            wx, wy = math.cos(self._wander) * 0.35, math.sin(self._wander * 1.3) * 0.35
            k = min(1.0, 2.0 * dt)
            self.hole_x += ((dx / dl) * 1.0 + wx) * c.hole_speed * k
            self.hole_y += ((dy / dl) * 1.0 + wy) * c.hole_speed * k
        x0, y0, x1, y1 = self.arena
        self.hole_x = min(max(self.hole_x, x0 + self.hole_r), x1 - self.hole_r)
        self.hole_y = min(max(self.hole_y, y0 + self.hole_r), y1 - self.hole_r)
        # balls flee when the hole is close
        for b in self.balls:
            body = b.shape.body
            dx, dy = body.position.x - self.hole_x, body.position.y - self.hole_y
            d = math.hypot(dx, dy) or 1.0
            if d < self.hole_r * 5 and c.hole_flee > 0:
                k = min(1.0, 3.0 * dt) * c.hole_flee
                v = body.velocity
                sp_ = v.length or 1.0
                vx, vy = v.x / sp_, v.y / sp_
                fx_, fy_ = dx / d, dy / d
                vx, vy = vx + fx_ * k, vy + fy_ * k
                n = math.hypot(vx, vy) or 1.0
                body.velocity = (vx / n * sp_, vy / n * sp_)
        # eat anything that touches the mouth
        eat = self.hole_r * c.hole_eat_radius
        for b in list(self.balls):
            p = b.shape.body.position
            if math.hypot(p.x - self.hole_x, p.y - self.hole_y) < eat + self._radius() * 0.4:
                self._eat(b)
        self.eaten_anims = [a for a in self.eaten_anims if self.vt - a[3] < 0.5]

    @property
    def best_tier(self) -> int:
        return min(self.cfg.tiers - 1, self.broken * self.cfg.tiers // max(1, self.total))

    def stats(self) -> dict:
        return {"eaten": self.broken, "target": self.total, "hole_r": round(self.hole_r, 1)}
