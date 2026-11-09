"""🐍 Snake Grow: a snake made of your pictures hunts dots around the arena; every dot eaten adds a segment (the
next picture in your Tiers) and plays a note a little higher than the last. Reach the target length for the ending.

Built on the Breaker arena (shares its renderer, sounds, particles, slow-mo and export). Movement is
kinematic: the head steers toward the food with a limited turn rate, the body follows the head's path."""
from __future__ import annotations

import dataclasses
import math

import pymunk

from .breaker import BreakerSim, BBall
from .merge import SoundEvent, Popup, Particle

START_LEN = 3


class SnakeSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        cfg = dataclasses.replace(cfg, breaker_trail=0)        # the body is the trail
        self.food = None                                       # (x, y, picture index)
        self.food_born = 0.0
        self.eaten = 0
        self.path: list[tuple[float, float]] = []              # head positions, newest last
        self.angle = 0.0
        self.last_eat_vt = 0.0
        self.length = START_LEN
        super().__init__(cfg, seed)
        self.constant_speed = False
        self.space.gravity = (0, 0)
        self.counter_text = cfg.snake_counter_text
        self.final_text = cfg.snake_final_text
        self._spacing = 1.55 * self._radius()
        x0, y0, x1, y1 = self.arena
        self.angle = self.rng.uniform(-math.pi, math.pi)
        hx, hy = (x0 + x1) / 2, (y0 + y1) / 2
        # lay the starting body straight behind the head
        n = int(self._spacing * (START_LEN + 1) / 2.0) + 10
        self.path = [(hx - math.cos(self.angle) * d * 2.0, hy - math.sin(self.angle) * d * 2.0) for d in range(n, -1, -1)]
        self._rebuild(START_LEN)
        self.broken = self.length
        self.total = max(START_LEN + 1, int(cfg.snake_target))
        self._spawn_food()
        self._last_break_vt = self.vt

    def _build_bricks(self) -> None:
        self.bricks = []
        self.total = max(START_LEN + 1, int(self.cfg.snake_target))

    def _radius(self) -> float:
        return self.cfg.snake_radius

    def _start_balls(self) -> int:
        return 0

    def _add_ball(self, pos=None, from_vel=None) -> BBall:
        r = self._radius()
        body = pymunk.Body(1.0, 1.0, body_type=pymunk.Body.KINEMATIC)    # not added to the space: we move it ourselves
        body.position = pos or (0, 0)
        shape = pymunk.Circle(body, r)
        ball = BBall(shape, len(self.balls), self.vt, [])
        ball.body_ref = body                                  # pymunk shapes only hold a weak reference to their body
        self.balls.append(ball)
        return ball

    def _rebuild(self, n: int) -> None:
        """Make sure there are n segments; tail first so the head is drawn on top."""
        while len(self.balls) < n:
            b = self._add_ball()
            b.born_vt = self.vt
        for i, b in enumerate(self.balls):                    # balls[0] = tail ... balls[-1] = head
            b.index = (n - 1 - i) % max(1, self.cfg.tiers)    # head wears picture 1, then 2, 3 ...
            b.scale_k = 1.0 if i < n - 1 else 1.18

    def _spawn_food(self) -> None:
        x0, y0, x1, y1 = self.arena
        r = self._radius()
        hx, hy = self.path[-1]
        for _ in range(40):
            x = self.rng.uniform(x0 + 2.5 * r, x1 - 2.5 * r)
            y = self.rng.uniform(y0 + 2.5 * r, y1 - 2.5 * r)
            if math.hypot(x - hx, y - hy) > 6 * r and all(math.hypot(x - b.shape.body.position.x, y - b.shape.body.position.y) > 2.2 * r for b in self.balls):
                break
        self.food = (x, y, (self.length) % max(1, self.cfg.tiers))
        self.food_born = self.vt

    def _eat(self) -> None:
        c = self.cfg
        fx, fy, idx = self.food
        self.length += 1
        self.eaten += 1
        self.broken = self.length
        self.last_eat_vt = self.vt
        self._last_break_vt = self.vt
        self._rebuild(self.length)
        k = (self.length - START_LEN) / max(1, self.total - START_LEN)
        self.events.append(SoundEvent(self.t, min(c.tiers - 1, idx), "merge", vt=self.vt,
                                      pitch=c.breaker_pitch_low + (c.breaker_pitch_high - c.breaker_pitch_low) * k))
        for _ in range(int(round(10 * c.particle_amount))):
            a = self.fx.uniform(0, 2 * math.pi)
            s = self.fx.uniform(100, 380) * c.particle_speed
            life = self.fx.uniform(0.3, 0.6)
            self.particles.append(Particle(fx, fy, math.cos(a) * s, math.sin(a) * s, life, (idx, self.fx.randrange(max(1, len(c.particle_colors)))),
                                           self.fx.uniform(3, 6), self.fx.uniform(0, 360), self.fx.uniform(-540, 540), life))
        if self.length >= self.total:
            self.finished_at = self.vt
            self.final_pos = (fx, fy)
            self.food = None
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 2.0)
        else:
            self._spawn_food()

    def _move(self, sdt: float) -> None:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        r = self._radius()
        hx, hy = self.path[-1]
        speed = c.snake_speed * (1.0 + 0.25 * (self.length - START_LEN) / max(1, self.total))
        # steer: toward the food (or wander at the end), away from walls
        if self.food is not None:
            want = math.atan2(self.food[1] - hy, self.food[0] - hx)
        else:
            want = self.angle + 0.8
        m = 2.2 * r
        if hx < x0 + m or hx > x1 - m or hy < y0 + m or hy > y1 - m:
            toward_centre = math.atan2((y0 + y1) / 2 - hy, (x0 + x1) / 2 - hx)
            d = math.atan2(math.sin(want - self.angle), math.cos(want - self.angle))
            if abs(math.atan2(math.sin(toward_centre - self.angle), math.cos(toward_centre - self.angle))) > 1.2 or \
               hx < x0 + 1.2 * r or hx > x1 - 1.2 * r or hy < y0 + 1.2 * r or hy > y1 - 1.2 * r:
                want = toward_centre
        turn = c.snake_turn * (1.0 + (self.vt - self.last_eat_vt) / 0.9)       # circling the food? turn tighter
        d = math.atan2(math.sin(want - self.angle), math.cos(want - self.angle))
        self.angle += max(-turn * sdt, min(turn * sdt, d))
        step = speed * sdt
        nx, ny = hx + math.cos(self.angle) * step, hy + math.sin(self.angle) * step
        nx, ny = min(max(nx, x0 + r), x1 - r), min(max(ny, y0 + r), y1 - r)
        # keep the path sampled every ~2 px so the body follows it smoothly
        seg = math.hypot(nx - hx, ny - hy)
        n = max(1, int(seg / 2.0))
        for k in range(1, n + 1):
            self.path.append((hx + (nx - hx) * k / n, hy + (ny - hy) * k / n))
        # keep only the part of the path the body needs
        need = int(self._spacing * (self.length + 1) / 2.0) + 8
        if len(self.path) > need * 2:
            self.path = self.path[-need:]
        # place the segments along the path, head first
        L = len(self.path)
        per = max(1, int(round(self._spacing / 2.0)))
        for i, b in enumerate(reversed(self.balls)):
            j = max(0, L - 1 - i * per)
            b.shape.body.position = self.path[j]

    def step(self, dt: float) -> None:
        sdt = dt * self.cfg.speed * self.time_scale()
        self._move(sdt)
        if self.food is not None and self.finished_at is None:
            hx, hy = self.path[-1]
            if math.hypot(self.food[0] - hx, self.food[1] - hy) < 1.9 * self._radius():
                self._eat()
        super().step(dt)

    @property
    def best_tier(self) -> int:
        return min(self.cfg.tiers - 1, (self.length - START_LEN) * self.cfg.tiers // max(1, self.total))

    def stats(self) -> dict:
        return {"length": self.length, "target": self.total, "eaten": self.eaten}
