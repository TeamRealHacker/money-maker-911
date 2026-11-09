"""🐍 Snake Grow: a snake of your pictures glides around the arena, eats food, and grows one segment per bite.
Every bite plays a note higher than the last; at the target length: LONGEST SNAKE!
Built on the Breaker arena (food = one-hit bricks, the head is the ball, segments follow its path)."""
from __future__ import annotations

import math

import pymunk

from .breaker import BreakerSim, BBall, Brick


class SnakeSim(BreakerSim):
    def __init__(self, cfg, seed: int | None = None):
        self.segs: list[BBall] = []
        self._path: list[tuple[float, float, float]] = []      # (x, y, distance travelled)
        self._dist = 0.0
        self._food_n = 0
        super().__init__(cfg, seed)
        self.constant_speed = False
        self.space.gravity = (0, 0)
        self.counter_text = cfg.snake_counter_text
        self.final_text = cfg.snake_final_text
        self.head = self.balls[0]
        self.head.index = cfg.tiers - 1
        self.head.shape.body.position = (self.cx, self.cy)
        a = self.rng.uniform(0, 2 * math.pi)
        self._ang = a
        self.head.shape.body.velocity = (math.cos(a) * cfg.snake_speed, math.sin(a) * cfg.snake_speed)
        self._last_break_vt = self.vt
        for _ in range(3):
            self._grow(silent=True)
        self._new_food()

    def _radius(self) -> float:
        return self.cfg.snake_ball_radius

    def _start_balls(self) -> int:
        return 1

    def _build_bricks(self) -> None:
        self.bricks = []
        self.total = max(2, int(self.cfg.snake_target))

    # ---------- snake ----------
    def _grow(self, silent: bool = False) -> None:
        r = self._radius()
        body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        hp = self.head.shape.body.position
        body.position = (hp.x, hp.y)
        shape = pymunk.Circle(body, r)
        shape.filter = pymunk.ShapeFilter(mask=0)
        shape.collision_type = 9
        self.space.add(body, shape)
        seg = BBall(shape, len(self.segs) % max(1, self.cfg.tiers - 1 or 1), self.vt - (9 if silent else 0), [])
        self.segs.append(seg)
        self.balls.insert(0, seg)                 # drawn under the head
        self._taper()

    def _taper(self) -> None:
        n = len(self.segs)
        for k, s in enumerate(self.segs):             # segs[0] = thickest, next to the head
            s.scale_k = 1.0 - 0.38 * (k / max(1, n - 1)) if n > 1 else 1.0
        self.head.scale_k = 1.12

    def _new_food(self) -> None:
        c = self.cfg
        x0, y0, x1, y1 = self.arena
        fs = c.snake_food_size
        m = fs + self._radius() * 1.2
        hp = self.head.shape.body.position
        for _ in range(30):
            x, y = self.rng.uniform(x0 + m, x1 - m), self.rng.uniform(y0 + m, y1 - m)
            if math.hypot(x - hp.x, y - hp.y) > 260:
                break
        b = Brick(self._food_n % max(1, c.tiers), 0, x, y, fs, fs, 1, 1)
        verts = [(x - fs / 2, y - fs / 2), (x + fs / 2, y - fs / 2), (x + fs / 2, y + fs / 2), (x - fs / 2, y + fs / 2)]
        shape = pymunk.Poly(self.space.static_body, verts, radius=fs * 0.2)
        shape.elasticity, shape.friction, shape.collision_type = 1.0, 0.0, 3
        shape.sensor = True                         # the head eats it, never bounces off
        self.space.add(shape)
        b.shape = shape
        self._by_shape[id(shape)] = b
        self.bricks.append(b)
        self._food_n += 1
        self._food = b

    def _after_break(self, brick) -> None:
        self._grow()
        self._last_break_vt = self.vt
        c = self.cfg
        if self.finished_at is None:
            self._new_food()

    def _break(self, brick) -> None:
        super()._break(brick)
        if self.finished_at is not None:
            self._grow(silent=True)

    # ---------- motion ----------
    def _steer(self, dt: float) -> None:
        c = self.cfg
        body = self.head.shape.body
        p = body.position
        v = body.velocity
        if v.length > 1:
            self._ang = math.atan2(v.y, v.x)             # follows wall bounces
        if self.finished_at is None:
            dx, dy = self._food.x - p.x, self._food.y - p.y
            dist = math.hypot(dx, dy) or 1.0
            want = math.atan2(dy, dx)
            diff = (want - self._ang + math.pi) % (2 * math.pi) - math.pi
            rate = min(10.0, max(c.snake_turn, c.snake_speed / max(dist * 0.5, 1.0)))
            self._ang += max(-rate * dt, min(rate * dt, diff))
            wob = math.sin(self.vt * 5.0) * 0.9 * dt
            self._ang += wob
        sp = c.snake_speed if self.finished_at is None else c.snake_speed * 0.5
        body.velocity = (math.cos(self._ang) * sp, math.sin(self._ang) * sp)

    def _follow(self) -> None:
        hp = self.head.shape.body.position
        if self._path:
            lx, ly, ld = self._path[-1]
            self._dist = ld + math.hypot(hp.x - lx, hp.y - ly)
        self._path.append((hp.x, hp.y, self._dist))
        gap = self._radius() * self.cfg.snake_gap
        need = gap * (len(self.segs) + 2)
        while len(self._path) > 2 and self._path[1][2] < self._dist - need:
            self._path.pop(0)
        pts = self._path
        j = len(pts) - 2
        for k, s in enumerate(self.segs):             # segs[0] sits right behind the head
            tgt = self._dist - gap * (k + 1)
            while j > 0 and pts[j][2] > tgt:
                j -= 1
            a = pts[max(j, 0)]
            b = pts[min(j + 1, len(pts) - 1)]
            span = b[2] - a[2]
            u = 0.0 if span <= 1e-6 else max(0.0, min(1.0, (tgt - a[2]) / span))
            s.shape.body.position = (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
            s.trail = []

    def step(self, dt: float) -> None:
        self._steer(dt * self.cfg.speed * self.time_scale())
        super().step(dt)
        self._follow()

    @property
    def best_tier(self) -> int:
        return self.cfg.tiers - 1 if self.won else min(self.cfg.tiers - 1, self.broken * self.cfg.tiers // self.total)

    def stats(self) -> dict:
        return {"length": len(self.segs), "eaten": self.broken, "target": self.total}
