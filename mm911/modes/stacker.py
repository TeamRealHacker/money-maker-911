"""🏗️ Tower Stack: a crane swings a block over the tower and drops it; every block that lands is
a note higher and the counter climbs. Too many sloppy drops in a row and the tower topples
(TOPPLED!), stack the target height and you are the TOWER KING!

Blocks are real pymunk boxes that fall, land and are frozen into the tower when they settle,
so the tower visibly wobbles and leans. Shares the Breaker renderer machinery (arena, cached
block layer, particles, banners, sounds, slow-mo, export) via StackerRenderer."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pymunk

from .breaker import Brick, pitch_ladder
from .merge import Particle, Popup, SoundEvent, Banner


@dataclass
class FallingBlock:
    body: pymunk.Body
    shape: pymunk.Poly
    index: int                # which picture / colour this block wears
    born_vt: float
    calm: float = 0.0         # seconds it has been nearly still


class StackerSim:
    GRAVITY = 2600.0

    def __init__(self, cfg, seed: int | None = None):
        cfg.clamp()
        self.cfg = cfg
        s = cfg.seed if seed is None else seed
        self.rng = random.Random(s)
        self.fx = random.Random(s * 4093 + 7)
        self.space = pymunk.Space()
        self.space.gravity = (0, self.GRAVITY)
        self.space.iterations = 14
        self.t = 0.0
        self.vt = 0.0
        self.particles: list[Particle] = []
        self.events: list[SoundEvent] = []
        self.banners: list[Banner] = []
        self.popups: list[Popup] = []
        self.balls: list = []                 # BreakerRenderer draws sim.balls (none here)
        self.bricks: list[Brick] = []         # settled blocks (drawn on the cached layer)
        self.falling: FallingBlock | None = None
        self.stacked = 0
        self.broken = 0                       # same counter as the other modes (blocks stacked)
        self.miss_streak = 0
        self.toppled = False
        self.finished_at: float | None = None
        self.final_pos = None
        self.shake = 0.0
        self.tension = False
        self._slow_until = -1.0
        self._slow_len = 1.0
        self._slow_factor = 1.0
        self._last_break_vt = 0.0
        self._next_drop = 0.6
        self._dead_blocks: list[FallingBlock] = []
        self.counter_text = cfg.stacker_counter_text
        self.final_text = cfg.stacker_final_text
        self.total = max(2, int(cfg.stacker_target))
        W, H = cfg.width, cfg.height
        m = cfg.breaker_arena_margin
        self.arena = (m, H * cfg.breaker_arena_top, W - m, H * cfg.breaker_arena_bottom)
        self.cx = (self.arena[0] + self.arena[2]) / 2
        self._build_walls()

    # ---------- setup ----------
    def _build_walls(self) -> None:
        x0, y0, x1, y1 = self.arena
        body = self.space.static_body
        segs = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
        for a, b in segs:
            seg = pymunk.Segment(body, a, b, 0.5)
            seg.elasticity, seg.friction, seg.collision_type = 0.0, 0.9, 2
            self.space.add(seg)

    def _spawn_offset(self) -> float:
        """Where the crane holds the block: a smooth sway. Spawns stay well inside the clean-drop
        window (the tower leans but every drop lands), so every seed finishes; the tower's own
        wobble and extreme settings can still push a block out for a real miss."""
        c = self.cfg
        off = math.sin(2 * math.pi * self.vt / max(0.5, c.stacker_swing_period)) * c.stacker_swing
        lim = max(0.1, min(c.stacker_swing, c.stacker_tolerance * 0.55))
        return max(-lim, min(lim, off)) * c.stacker_block_w

    def _drop_block(self) -> None:
        c = self.cfg
        w, h = c.stacker_block_w, c.stacker_block_h
        # the crane lowers the block to just above the tower (never higher than the arena top)
        y = max(self.tower_top() - h * 2.6, self.arena[1] + h * 1.6)
        body = pymunk.Body(1.0, pymunk.moment_for_box(1.0, (w, h)))
        body.position = (self.cx + self._spawn_offset(), y)
        shape = pymunk.Poly.create_box(body, (w, h), radius=2.0)
        shape.elasticity, shape.friction, shape.collision_type = 0.0, 0.85, 1
        self.space.add(body, shape)
        self.falling = FallingBlock(body, shape, self.stacked, self.vt)

    def tower_top(self) -> float:
        """y of the highest settled surface (the arena floor before the first block)."""
        if not self.bricks:
            return self.arena[3]
        return min(b.y - b.h / 2 for b in self.bricks)

    def below_center(self) -> float:
        if not self.bricks:
            return self.cx
        top = min(self.bricks, key=lambda b: b.y)
        return top.x

    # ---------- settling ----------
    def _settle(self, fb: FallingBlock, clean: bool) -> None:
        c = self.cfg
        body, shape = fb.body, fb.shape
        x, y = body.position.x, body.position.y
        ang = body.angle
        self.falling = None                      # cleared first: _finish() must not re-remove it
        self.space.remove(body, shape)
        if clean:
            verts = self._box_verts(x, y, ang, c.stacker_block_w, c.stacker_block_h)
            poly = pymunk.Poly(self.space.static_body, verts, radius=2.0)
            poly.friction, poly.collision_type = 0.9, 3
            self.space.add(poly)
            b = Brick(self.stacked, 0, x, y, c.stacker_block_w, c.stacker_block_h, 1, 1, shape=poly)
            self.bricks.append(b)
            self.stacked += 1
            self.broken = self.stacked
            self._last_break_vt = self.vt
            self.miss_streak = 0
            i = self.stacked
            self.events.append(SoundEvent(self.t, min(self.stacked, c.tiers - 1), "merge", vt=self.vt,
                                          pitch=pitch_ladder(c, i - 1, self.total)))
            self._burst(x, y, 8, fb.index)
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 0.5)
            if self.stacked >= self.total:
                self._finish(won=True, pos=(x, y))
            else:
                self._next_drop = max(0.15, c.stacker_interval)
        else:
            self.miss_streak += 1
            self.popups.append(Popup(x, y, "MISS", self.vt, max(0, fb.index % max(1, c.tiers))))
            self._burst(x, y, 5, fb.index)
            self._dead_blocks.append(fb)
            if self.miss_streak >= max(1, c.stacker_miss_limit):
                self._topple()

    def _topple(self) -> None:
        c = self.cfg
        self.toppled = True
        for b in self.bricks:                      # the tower comes alive and falls over
            verts = [(b.x - b.w / 2, b.y - b.h / 2), (b.x + b.w / 2, b.y - b.h / 2),
                     (b.x + b.w / 2, b.y + b.h / 2), (b.x - b.w / 2, b.y + b.h / 2)]
            body = pymunk.Body(1.0, pymunk.moment_for_box(1.0, (b.w, b.h)))
            body.position = (b.x, b.y)
            shape = pymunk.Poly(body, verts, radius=2.0)
            shape.elasticity, shape.friction, shape.collision_type = 0.05, 0.85, 3
            self.space.add(body, shape)
            self._dead_blocks.append(FallingBlock(body, shape, 0, self.vt))
        self.bricks.clear()
        self._finish(won=False, pos=(self.cx, self.tower_top()))
        self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt, pitch=-8.0))
        if c.shake_strength > 0:
            self.shake = max(self.shake, c.shake_strength * 2.4)

    def _finish(self, won: bool, pos) -> None:
        c = self.cfg
        self.finished_at = self.vt
        self.final_pos = pos
        if won:
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 2.2)
            self._burst(pos[0], pos[1], 40, max(0, c.tiers - 1))
        if self.falling is not None:
            try:
                self.space.remove(self.falling.body, self.falling.shape)
            except AssertionError:
                pass
            self.falling = None

    # ---------- helpers ----------
    @staticmethod
    def _box_verts(x, y, ang, w, h):
        ca, sa = math.cos(ang), math.sin(ang)
        pts = []
        for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
            pts.append((x + dx * ca - dy * sa, y + dx * sa + dy * ca))
        return pts

    def _burst(self, x: float, y: float, n: int, col_idx: int) -> None:
        c = self.cfg
        n = int(round(n * c.particle_amount))
        ncol = max(1, len(c.particle_colors))
        for _ in range(n):
            a = self.fx.uniform(0, 2 * math.pi)
            sp = self.fx.uniform(80, 420) * c.particle_speed
            life = self.fx.uniform(0.3, 0.7)
            self.particles.append(Particle(x, y, math.cos(a) * sp, math.sin(a) * sp, life,
                                           (col_idx % max(1, c.tiers), self.fx.randrange(ncol)),
                                           self.fx.uniform(3, 7),
                                           self.fx.uniform(0, 360), self.fx.uniform(-540, 540), life))

    def _slow(self, factor: float, seconds: float) -> None:
        self._slow_factor = factor
        self._slow_len = max(0.05, seconds)
        self._slow_until = self.vt + self._slow_len

    def time_scale(self) -> float:
        left = self._slow_until - self.vt
        if left <= 0:
            return 1.0
        k = min(1.0, left / (self._slow_len * 0.4))
        return 1.0 + (self._slow_factor - 1.0) * k

    def shake_offset(self) -> tuple[float, float]:
        if not self.shake:
            return 0.0, 0.0
        return self.shake * math.sin(self.vt * 93.0), self.shake * math.cos(self.vt * 71.0)

    # ---------- main step ----------
    def step(self, dt: float) -> None:
        real_dt = dt
        c = self.cfg
        dt *= c.speed * self.time_scale()
        self.space.step(dt)
        fb = self.falling
        if fb is not None and self.finished_at is None:
            v = fb.body.velocity.length
            w = abs(fb.body.angular_velocity)
            fb.calm = fb.calm + dt if (v < 60 and w < 1.0) else 0.0
            if fb.calm > 0.22 or self.vt - fb.born_vt > 6.0:
                off = abs(fb.body.position.x - self.below_center())
                clean = off <= c.stacker_tolerance * c.stacker_block_w \
                    and fb.body.position.y < self.arena[3] - c.stacker_block_h * 0.25
                self._settle(fb, clean)
        for db in list(self._dead_blocks):
            if self.vt - db.born_vt > 2.2 or db.body.position.y > self.arena[3] + 200:
                try:
                    self.space.remove(db.body, db.shape)
                except Exception:
                    pass
                self._dead_blocks.remove(db)
        if self.finished_at is None:
            if fb is None and self.falling is None:
                self._next_drop -= dt
                if self._next_drop <= 0:
                    self._drop_block()
            left = self.total - self.stacked
            self.tension = c.near_miss and 0 < left <= 2
        drag = 0.97 if c.particle_style != "confetti" else 0.94
        for pt in self.particles:
            pt.x += pt.vx * dt
            pt.y += pt.vy * dt
            pt.vy += c.particle_gravity * dt * (0.35 if c.particle_style == "confetti" else 1.0)
            pt.vx *= drag
            pt.rot += pt.spin * dt
            pt.life -= dt
        self.particles = [pt for pt in self.particles if pt.life > 0]
        self.banners = [b for b in self.banners if self.vt - b.born < b.life]
        self.popups = [p for p in self.popups if self.vt - p.born < p.life]
        self.shake *= math.exp(-real_dt * 9)
        if self.shake < 0.3:
            self.shake = 0.0
        self.t += dt
        self.vt += real_dt

    # ---------- interface used by the shared renderer / export ----------
    @property
    def done(self) -> bool:
        c = self.cfg
        if self.finished_at is not None:
            hold = c.end_hold_seconds + (c.slowmo_seconds * 0.5 if c.slowmo_final else 0.0)
            return self.vt >= self.finished_at + hold
        return self.vt >= (180.0 if c.until_finished else c.max_seconds)

    @property
    def won(self) -> bool:
        return self.finished_at is not None and not self.toppled

    @property
    def best_tier(self) -> int:
        return min(self.cfg.tiers - 1, self.stacked * self.cfg.tiers // max(1, self.total))

    @property
    def merges(self) -> int:
        return self.stacked

    @property
    def best_combo(self) -> int:
        return 0

    def stats(self) -> dict:
        return {"height": self.stacked, "target": self.total, "misses": self.miss_streak}

    def thumb_ready(self):
        return self.finished_at is not None and self.vt >= self.finished_at + 0.45
