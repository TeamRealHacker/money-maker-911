"""🎳 Bowling Strike: a lane with a triangle of pins at the top; your meme ball is thrown from the
bottom, pins fly with a note higher for every one knocked down, and the ball is re-thrown until
every pin is down: STRIKE!

Built on the Breaker arena (shares its renderer machinery, sounds, particles, slow-mo, export)."""
from __future__ import annotations

import math

import pymunk

from .breaker import BBall, BreakerSim, Brick


class BowlingSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        self._pending_throw = 0.0
        self.throws = 1
        self._end_vt: float | None = None
        self._throw_in = False
        super().__init__(cfg, seed)
        self.counter_text = cfg.bowling_counter_text
        self.final_text = cfg.bowling_final_text

    # ---------- setup ----------
    def _build_bricks(self) -> None:
        """Pins in a triangle at the top of the lane (front row = 1 pin, back row = full)."""
        c = self.cfg
        x0, y0, x1, _y1 = self.arena
        self.bricks = []
        self._by_shape = {}
        spacing = c.bowling_pin_radius * 2.6 * c.bowling_pin_spread
        rows = max(1, min(c.bowling_rows, 8))
        cx = (x0 + x1) / 2
        top = y0 + c.bowling_pin_radius * 2.2
        want = max(1, min(c.bowling_pins, rows * (rows + 1) // 2))
        placed = 0
        for r in range(rows):                    # r = 0 is the front row (closest to the ball)
            n = r + 1
            if placed + n > want:
                n = want - placed
            if n <= 0:
                break
            y = top + (rows - 1 - r) * spacing
            for i in range(n):
                x = cx + (i - (n - 1) / 2) * spacing
                b = Brick(r, i, x, y, c.bowling_pin_radius * 2, c.bowling_pin_radius * 2,
                          c.bowling_pin_hp, c.bowling_pin_hp)
                rad = c.bowling_pin_radius * 0.9
                shape = pymunk.Poly(self.space.static_body,
                                    [(x - rad, y - rad), (x + rad, y - rad),
                                     (x + rad, y + rad), (x - rad, y + rad)], radius=1.0)
                shape.elasticity, shape.friction, shape.collision_type = 0.05, 0.0, 3
                self.space.add(shape)
                b.shape = shape
                self._by_shape[id(shape)] = b
                self.bricks.append(b)
                placed += 1
        self.total = placed

    def _radius(self) -> float:
        return self.cfg.bowling_ball_radius

    def _start_balls(self) -> int:
        return 1

    def _add_ball(self, pos=None, from_vel=None) -> BBall:
        c = self.cfg
        r = self._radius()
        x0, _y0, x1, y1 = self.arena
        body = pymunk.Body(1.0, pymunk.moment_for_circle(1.0, 0, r))
        # spawn directly below a standing pin so the throw plows its whole column (the arena code's
        # minimum-sideways-speed rule widens steep throws, which only helps cover the column)
        alive = self.alive_bricks()
        tx = alive[self.rng.randrange(len(alive))].x if alive else (x0 + x1) / 2
        a = math.radians(-90 + self.rng.uniform(-4, 4))
        body.position = (min(max(tx + self.rng.uniform(-12, 12), x0 + r * 1.5), x1 - r * 1.5), y1 - r * 2.4)
        body.velocity = (math.cos(a) * c.bowling_speed, math.sin(a) * c.bowling_speed)
        shape = pymunk.Circle(body, r)
        shape.elasticity, shape.friction, shape.collision_type = 1.0, 0.0, 1
        self.space.add(body, shape)
        ball = BBall(shape, len(self.balls), self.vt, [])
        self.balls.append(ball)
        return ball

    def _deck_bottom(self) -> float:
        c = self.cfg
        return self.arena[1] + c.bowling_pin_radius * (2.2 + c.bowling_rows * 2.6 * c.bowling_pin_spread)

    # ---------- events ----------
    def _after_break(self, brick: Brick) -> None:
        """No extra balls in bowling: pins just fall."""
        return

    def _on_brick(self, arbiter, space, data) -> None:
        super()._on_brick(arbiter, space, data)
        brick = self._by_shape.get(id(arbiter.shapes[1]))
        if brick is not None and brick.hp <= 0 and self.cfg.shake_strength > 0:
            self.shake = max(self.shake, self.cfg.shake_strength * 0.55)

    def _break(self, brick: Brick) -> None:
        super()._break(brick)
        if self.broken >= self.total and self.finished_at is not None:
            # winning throw: the ball flies off, STRIKE!
            if self.balls:
                b = self.balls.pop(0)
                self.space.remove(b.shape, b.shape.body)
            self._pending_throw = 0.0

    # ---------- main step ----------
    def step(self, dt: float) -> None:
        super().step(dt)
        c = self.cfg
        sp = c.bowling_speed                           # the arena code normalises to breaker_speed;
        if self.finished_at is None or self._end_vt is not None:
            for b in self.balls:                       # re-normalise to the bowling throw speed
                v = b.shape.body.velocity
                n = math.hypot(v.x, v.y) or 1.0
                b.shape.body.velocity = (v.x / n * sp, v.y / n * sp)
        if self.finished_at is not None or self._end_vt is not None:
            return
        if self.balls:
            body = self.balls[0].shape.body
            deck = self._deck_bottom()
            if body.position.y < deck:
                self._throw_in = True
            # the ball homes in on the nearest standing pin wherever it is (stronger than the
            # arena code's minimum-sideways-speed drift), except while it is falling back out of
            # the pin deck - then the throw ends instead
            alive = self.alive_bricks()
            falling_out = self._throw_in and body.position.y > deck + self._radius() * 6.0 \
                and body.velocity.y > 0
            if alive and not falling_out:
                tgt = min(alive, key=lambda bk: (bk.x - body.position.x) ** 2 + (bk.y - body.position.y) ** 2)
                dx, dy = tgt.x - body.position.x, tgt.y - body.position.y
                dl = math.hypot(dx, dy) or 1.0
                v = body.velocity
                k = min(1.0, 5.0 * dt)
                vx, vy = v.x / sp + (dx / dl - v.x / sp) * k, v.y / sp + (dy / dl - v.y / sp) * k
                n = math.hypot(vx, vy) or 1.0
                body.velocity = (vx / n * sp, vy / n * sp)
            # the throw ends when the ball falls back out of the pin deck (or after a rally)
            if falling_out or self.vt - self.balls[0].born_vt > 4.5:
                self._throw_in = False
                b = self.balls.pop(0)
                self.space.remove(b.shape, b.shape.body)
                self._pending_throw = 0.45
        elif self._pending_throw > 0:
            self._pending_throw -= dt
            if self._pending_throw <= 0:
                self._pending_throw = 0.0
                if self.broken < self.total:
                    if self.throws >= self.cfg.bowling_max_throws:
                        self._end_vt = self.vt      # out of throws: end without a STRIKE
                    else:
                        self.throws += 1
                        self._add_ball()

    @property
    def done(self) -> bool:
        c = self.cfg
        if self._end_vt is not None:
            return self.vt >= self._end_vt + 1.4
        if self.finished_at is not None:
            hold = c.end_hold_seconds + (c.slowmo_seconds * 0.5 if c.slowmo_final else 0.0)
            return self.vt >= self.finished_at + hold
        return self.vt >= (180.0 if c.until_finished else c.max_seconds)

    @property
    def best_tier(self) -> int:
        return min(self.cfg.tiers - 1, self.broken * self.cfg.tiers // max(1, self.total))

    def stats(self) -> dict:
        return {"pins": self.total, "down": self.broken, "throws": self.throws}
