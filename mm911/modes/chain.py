"""💥 Chain Reaction: a swarm of pictures drifts around the arena. One pops, its shockwave pops every picture it
touches, those pop the next ... Each pop plays a note a little higher than the last; when the chain dies out a
spark pops the nearest survivor so the video always ends with every picture popped.

Built on the Breaker arena (shares its renderer, sounds, particles, slow-mo and export)."""
from __future__ import annotations

import math

import pymunk

from .breaker import BreakerSim, BBall
from .merge import SoundEvent, Particle

POP_LIFE = 0.5            # seconds a popped picture swells and fades while its shockwave runs


class ChainSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        self.waves: list = []              # (x, y, born_vt, tier)
        self.pops = 0
        self.sparks = 0
        self._next_spark = 0.8
        self.dead: list = []
        super().__init__(cfg, seed)
        self.constant_speed = False
        self.counter_text = cfg.chain_counter_text
        self.final_text = cfg.chain_final_text
        self._last_break_vt = self.vt

    def _build_bricks(self) -> None:
        self.bricks = []
        self.total = max(2, int(self.cfg.chain_balls))

    def _radius(self) -> float:
        return self.cfg.chain_ball_radius

    def _start_balls(self) -> int:
        return self.cfg.chain_balls

    def _add_ball(self, pos=None, from_vel=None) -> BBall:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        r = self._radius()
        if pos is None:
            pos = (self.rng.uniform(x0 + 2 * r, x1 - 2 * r), self.rng.uniform(y0 + 2 * r, y1 - 2 * r))
        ball = super()._add_ball(pos)
        ball.shape.filter = pymunk.ShapeFilter(group=1)              # pictures drift through each other
        a = self.rng.uniform(0, 2 * math.pi)
        ball.shape.body.velocity = (math.cos(a) * c.chain_speed, math.sin(a) * c.chain_speed)
        ball.pop_vt = None
        return ball

    def wave_radius(self, age: float) -> float:
        e = min(1.0, age / POP_LIFE)
        return self.cfg.chain_radius * (1 - (1 - e) ** 2)

    def _pop(self, ball: BBall) -> None:
        c = self.cfg
        body = ball.shape.body
        p = body.position
        ball.pop_vt = self.vt
        body.velocity = (0, 0)                                       # freeze where it popped, collide with nothing
        ball.shape.filter = pymunk.ShapeFilter(mask=0)
        self.waves.append((p.x, p.y, self.vt, ball.index))
        self.pops += 1
        self.broken = self.pops
        self._last_break_vt = self.vt
        k = self.pops / self.total
        self.events.append(SoundEvent(self.t, min(c.tiers - 1, ball.index), "merge", vt=self.vt,
                                      pitch=c.breaker_pitch_low + (c.breaker_pitch_high - c.breaker_pitch_low) * k))
        for _ in range(int(round(9 * c.particle_amount))):
            a = self.fx.uniform(0, 2 * math.pi)
            s = self.fx.uniform(120, 420) * c.particle_speed
            life = self.fx.uniform(0.3, 0.7)
            self.particles.append(Particle(p.x, p.y, math.cos(a) * s, math.sin(a) * s, life,
                                           (ball.index, self.fx.randrange(max(1, len(c.particle_colors)))),
                                           self.fx.uniform(3, 7), self.fx.uniform(0, 360), self.fx.uniform(-540, 540), life))
        if c.shake_strength > 0:
            self.shake = max(self.shake, c.shake_strength * 0.25)
        if self.pops >= self.total and self.finished_at is None:
            self.finished_at = self.vt
            self.final_pos = (p.x, p.y)
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 2.0)

    def alive(self) -> list:
        return [b for b in self.balls if b.pop_vt is None]

    def step(self, dt: float) -> None:
        super().step(dt)
        r = self._radius()
        sp = self.cfg.chain_speed
        for b in self.balls:                                         # drifters keep a steady speed
            if b.pop_vt is None:
                v = b.shape.body.velocity
                n = v.length or 1.0
                b.shape.body.velocity = (v.x / n * sp, v.y / n * sp)
        waves = [w for w in self.waves if self.vt - w[2] < POP_LIFE]
        alive = self.alive()
        # shockwaves pop whatever they touch (a ball popped this frame joins the next frame's waves)
        for ball in alive:
            p = ball.shape.body.position
            for wx, wy, born, _ in waves:
                if math.hypot(p.x - wx, p.y - wy) < self.wave_radius(self.vt - born) + r * 0.6:
                    self._pop(ball)
                    break
        # chain died out: spark the survivor nearest to the last wave (or a random one at the start)
        alive = self.alive()
        if alive and self.finished_at is None and not [w for w in self.waves if self.vt - w[2] < POP_LIFE * 0.8] \
                and self.vt >= self._next_spark:
            if self.waves:
                lx, ly = self.waves[-1][0], self.waves[-1][1]
                tgt = min(alive, key=lambda b: (b.shape.body.position.x - lx) ** 2 + (b.shape.body.position.y - ly) ** 2)
            else:
                tgt = alive[self.rng.randrange(len(alive))]
            self.sparks += 1
            self._pop(tgt)
            self._next_spark = self.vt + 0.6
        # popped pictures swell and fade, then leave the list
        for b in list(self.balls):
            if b.pop_vt is not None:
                age = self.vt - b.pop_vt
                if age >= POP_LIFE:
                    self.balls.remove(b)
                else:
                    b.scale_k = 1.0 + 0.6 * math.sin(min(1.0, age / POP_LIFE) * math.pi / 2)
        self.waves = [w for w in self.waves if self.vt - w[2] < POP_LIFE + 0.1] if len(self.waves) > 64 else self.waves

    @property
    def best_tier(self) -> int:
        return min(self.cfg.tiers - 1, self.pops * self.cfg.tiers // max(1, self.total))

    def stats(self) -> dict:
        return {"pops": self.pops, "total": self.total, "sparks": self.sparks}
