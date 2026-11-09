"""🏢 Glass Tower: balls fall through a tower of glass floors. Every bounce on a floor cracks it; when it has
taken all its hits it shatters and the balls drop to the next one. Every floor is a note higher than the last.

Built on the Breaker arena (shares its renderer, sounds, particles, slow-mo and export), with real gravity."""
from __future__ import annotations

import math

import pymunk

from .breaker import BreakerSim, Brick, BBall


class TowerSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        self._spawned = 0
        super().__init__(cfg, seed)
        self.constant_speed = False
        self.space.gravity = (0, cfg.tower_gravity)
        self.counter_text = cfg.tower_counter_text
        self.final_text = cfg.tower_final_text
        self._last_break_vt = self.vt

    def _start_balls(self) -> int:
        return 1

    def _build_bricks(self) -> None:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        n = c.tower_floors
        top = y0 + (y1 - y0) * 0.14
        bottom = y1 - (y1 - y0) * 0.06
        th = c.tower_floor_height
        step = (bottom - top) / max(1, n - 1) if n > 1 else 0
        self.bricks = []
        for r in range(n):
            y = top + r * step
            b = Brick(r, 0, (x0 + x1) / 2, y, x1 - x0, th, c.tower_hp, c.tower_hp)
            b.cracks = []                                  # where it was hit (fraction of the width)
            verts = [(x0, y - th / 2), (x1, y - th / 2), (x1, y + th / 2), (x0, y + th / 2)]
            shape = pymunk.Poly(self.space.static_body, verts, radius=1.0)
            shape.elasticity, shape.friction, shape.collision_type = 0.95, 0.0, 3
            self.space.add(shape)
            b.shape = shape
            self._by_shape[id(shape)] = b
            self.bricks.append(b)
        self.total = len(self.bricks)

    def _add_ball(self, pos=None, from_vel=None) -> BBall:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        r = c.breaker_ball_radius
        ball = super()._add_ball((self.rng.uniform(x0 + 2 * r, x1 - 2 * r), y0 + 2.2 * r))
        ball.shape.elasticity = 0.97
        ball.shape.filter = pymunk.ShapeFilter(group=1)
        sgn = 1 if self.rng.random() < 0.5 else -1
        ball.shape.body.velocity = (sgn * self.rng.uniform(260, 520), 0)
        self._spawned += 1
        return ball

    def _on_brick(self, arbiter, space, data) -> None:
        brick = self._by_shape.get(id(arbiter.shapes[1]))
        if brick is not None and brick.broken_vt is None and brick not in self._to_remove:
            try:
                px = arbiter.contact_point_set.points[0].point_a.x
            except Exception:
                px = arbiter.shapes[0].body.position.x
            brick.cracks.append(min(0.97, max(0.03, (px - (brick.x - brick.w / 2)) / brick.w)))
        super()._on_brick(arbiter, space, data)

    def _after_break(self, brick: Brick) -> None:
        pass

    def step(self, dt: float) -> None:
        c = self.cfg
        # more balls join every second until all are in
        while self._spawned < c.tower_balls and self.vt >= self._spawned * c.tower_ball_interval and self.finished_at is None:
            self._add_ball()
        super().step(dt)
        for ball in self.balls:
            body = ball.shape.body
            vx, vy = body.velocity
            if abs(vx) < 160:                     # keep drifting sideways so balls cover the whole floor
                vx = math.copysign(160 + self.rng.random() * 120, vx or (1 if self.rng.random() < 0.5 else -1))
            if abs(vy) < 40 and self._on_floor(body):      # resting on glass: bounce again
                vy = -c.tower_gravity * 0.12
            body.velocity = (vx, vy)

    def _on_floor(self, body) -> bool:
        return any(b.broken_vt is None and abs(b.y - body.position.y) < self.cfg.tower_floor_height / 2 + self.cfg.breaker_ball_radius + 6
                   for b in self.bricks)

    def thumb_ready(self) -> bool:
        """Thumbnail: about half the tower is down, cracks and shards on screen, balls still falling."""
        return self.broken >= max(2, int(self.total * 0.55)) and self.finished_at is None

    def stats(self) -> dict:
        return {"floors": self.total, "broken": self.broken, "balls": len(self.balls)}
