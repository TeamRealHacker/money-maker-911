"""🫧 Bubble Pop: glossy bubbles rise from the bottom of the arena, your meme ball bounces around
and pops them one by one — every pop is a note higher and the counter climbs. Pop the target
for the ALL POPPED! ending.

Built on the Breaker arena (shares its renderer machinery, sounds, particles, slow-mo, export)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import pymunk

from .breaker import BBall, BreakerSim
from .merge import Particle, SoundEvent


@dataclass
class Bubble:
    x: float
    y: float
    r: float
    base_x: float
    phase: float
    born_vt: float
    popped_vt: float | None = None


class BubbleSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        self._spawn_acc = 0.0
        super().__init__(cfg, seed)
        self.counter_text = cfg.bubble_counter_text
        self.final_text = cfg.bubble_final_text
        self.bubbles: list[Bubble] = []

    # ---------- setup ----------
    def _build_bricks(self) -> None:
        self.bricks = []
        self.total = max(2, int(self.cfg.bubble_target))

    def _radius(self) -> float:
        return self.cfg.bubble_ball_radius

    def _start_balls(self) -> int:
        return 1

    # ---------- bubbles ----------
    def _spawn_bubble(self) -> None:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        r = c.bubble_radius * self.fx.uniform(0.8, 1.2)
        x = self.fx.uniform(x0 + r * 2, x1 - r * 2)
        self.bubbles.append(Bubble(x, y1 + r, r, x, self.fx.uniform(0, math.tau), self.vt))

    def _pop(self, b: Bubble) -> None:
        c = self.cfg
        b.popped_vt = self.vt
        self.broken += 1
        self._last_break_vt = self.vt
        i = self.broken
        self.events.append(SoundEvent(self.t, min(i * c.tiers // max(1, self.total), c.tiers - 1),
                                      "merge", vt=self.vt, pitch=self._pitch(i)))
        self._burst(b.x, b.y, 12, i)
        if self.broken >= self.total and self.finished_at is None:
            self.finished_at = self.vt
            self.final_pos = (b.x, b.y)
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 2.0)
            self._burst(b.x, b.y, 40, i)

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
            sp = self.fx.uniform(100, 480) * c.particle_speed
            life = self.fx.uniform(0.3, 0.7)
            self.particles.append(Particle(x, y, math.cos(a) * sp, math.sin(a) * sp, life,
                                           (i % max(1, c.tiers), self.fx.randrange(ncol)),
                                           self.fx.uniform(3, 7),
                                           self.fx.uniform(0, 360), self.fx.uniform(-540, 540), life))

    # ---------- main step ----------
    def step(self, dt: float) -> None:
        c = self.cfg
        if self.finished_at is None:
            # adaptive spawning: never let the arena run dry, catch up when behind schedule
            left = self.total - self.broken
            budget = max(0.2, (c.max_seconds if not c.until_finished else 120.0) * 0.75 - self.vt)
            interval = min(c.bubble_spawn_interval, max(0.08, budget / max(1, left) * 0.8))
            self._spawn_acc += dt
            while self._spawn_acc >= interval:
                self._spawn_acc -= interval
                if len(self.bubbles) < 26:
                    self._spawn_bubble()
        for b in self.bubbles:
            if b.popped_vt is not None:
                continue
            b.y -= c.bubble_speed * dt
            b.phase += c.bubble_wobble_speed * dt
            b.x = b.base_x + math.sin(b.phase) * c.bubble_wobble
            if b.y < self.arena[1] - b.r:              # floated away unpopped
                b.popped_vt = self.vt - 10.0            # mark gone (below the pop window)
        # steering: bend the ball toward the nearest bubble so every seed finishes
        alive = [b for b in self.bubbles if b.popped_vt is None]
        if alive and self.balls and self.finished_at is None:
            body = self.balls[0].shape.body
            tgt = min(alive, key=lambda b: (b.x - body.position.x) ** 2 + (b.y - body.position.y) ** 2)
            dx, dy = tgt.x - body.position.x, tgt.y - body.position.y
            dl = math.hypot(dx, dy) or 1.0
            v = body.velocity
            sp = v.length or 1.0
            k = min(1.0, 3.2 * dt)
            vx, vy = v.x / sp + (dx / dl - v.x / sp) * k, v.y / sp + (dy / dl - v.y / sp) * k
            n = math.hypot(vx, vy) or 1.0
            body.velocity = (vx / n * c.bubble_ball_speed, vy / n * c.bubble_ball_speed)
            # pop on contact
            r = self._radius()
            for b in alive:
                if math.hypot(b.x - body.position.x, b.y - body.position.y) < r + b.r * 0.92:
                    self._pop(b)
                    break
        self.bubbles = [b for b in self.bubbles
                        if b.popped_vt is None or self.vt - b.popped_vt < 0.3]
        super().step(dt)
        sp = c.bubble_ball_speed                       # the arena code normalises to breaker_speed;
        for b in self.balls:                           # re-normalise to the bubble ball speed
            v = b.shape.body.velocity
            n = math.hypot(v.x, v.y) or 1.0
            b.shape.body.velocity = (v.x / n * sp, v.y / n * sp)
        # popups float up
        self.popups = [p for p in self.popups if self.vt - p.born < p.life]

    @property
    def best_tier(self) -> int:
        return min(self.cfg.tiers - 1, self.broken * self.cfg.tiers // max(1, self.total))

    def stats(self) -> dict:
        return {"popped": self.broken, "target": self.total, "floating": len(self.bubbles)}
