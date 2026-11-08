"""🥛 Glass Rush: a ball bounces inside nested rings of glass. Every hit cracks the ring it touched;
when a ring has taken all its hits it shatters and the ball rushes on to the next one, a little faster
and a note higher. Break every ring for the ending.

Rings, ball, trail, glow and sounds share the escape_* settings with Escape (rings without gaps here);
glass_* adds toughness, cracks and the ending. Every seed is winnable: each bounce is a hit."""
from __future__ import annotations

import math

import pymunk

from .escape import EscapeSim, Ring, ring_layout, pitch_ladder
from .merge import SoundEvent


def glass_ball_radius(cfg, broken: int = 0) -> float:
    """Ball size: escape_ball_radius grown per broken ring, never bigger than the ring it is inside."""
    radii = ring_layout(cfg)
    th = cfg.escape_ring_thickness
    r = cfg.escape_ball_radius * (cfg.escape_ball_growth ** broken)
    if broken < len(radii):
        r = min(r, (radii[broken] - th / 2 - 4) * 0.8)
    return max(4.0, r)


def ring_hp(cfg, i: int) -> int:
    return max(1, int(round(cfg.glass_hp + cfg.glass_hp_growth * i)))


class GlassSim(EscapeSim):
    ASSIST = False

    def __init__(self, cfg, seed: int | None = None):
        self.hp: dict[int, int] = {}
        self.max_hp: dict[int, int] = {}
        self.cracks: dict[int, list] = {}      # ring index -> list of polylines [(angle_off, radial_off)]
        self.hit_vt: dict[int, float] = {}
        self.hit_angle: dict[int, float] = {}
        self._pending: list[Ring] = []
        self._ring_of: dict[int, Ring] = {}
        self.hits = 0
        super().__init__(cfg, seed)

    # ---------- setup ----------
    def _ball_radius(self, escaped: int) -> float:
        return glass_ball_radius(self.cfg, escaped)

    def _build_rings(self) -> None:
        c = self.cfg
        for i, R in enumerate(ring_layout(c)):
            gap0 = self.rng.uniform(0, 2 * math.pi)
            body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
            body.position = (self.cx, self.cy)
            spin = c.glass_spin * (1 + i * c.escape_spin_step)
            if c.escape_alternate and i % 2 == 1:
                spin = -spin
            body.angular_velocity = math.radians(spin)
            ring = Ring(i, R, 0.0, gap0, body, [])
            self.space.add(body)
            ring.shapes = self._segments(ring)
            for s in ring.shapes:
                self._ring_of[id(s)] = ring
            self.hp[i] = self.max_hp[i] = ring_hp(c, i)
            self.cracks[i] = []
            self.rings.append(ring)

    # ---------- hits ----------
    def _on_bounce(self, arbiter, space, data) -> None:
        super()._on_bounce(arbiter, space, data)     # bounce sound + sparks
        ring = self._ring_of.get(id(arbiter.shapes[1]))
        if ring is None or ring.escaped_vt is not None or ring in self._pending:
            return
        i = ring.index
        self.hits += 1
        self.hp[i] -= 1
        self.hit_vt[i] = self.vt
        pts = arbiter.contact_point_set.points
        p = pts[0].point_a if pts else self.ball.body.position
        ang = math.atan2(p[1] - self.cy, p[0] - self.cx)
        self.hit_angle[i] = ang
        if self.cfg.glass_cracks and self.hp[i] > 0:
            self.cracks[i].extend(self._make_crack(ring, ang - ring.angle, 1 - self.hp[i] / self.max_hp[i]))
        if self.hp[i] <= 0:
            self._pending.append(ring)

    def _make_crack(self, ring: Ring, local_ang: float, damage: float) -> list:
        """A jagged crack across the glass with two branches along it (ring-local polar offsets)."""
        th = self.cfg.escape_ring_thickness
        R = ring.radius
        f = self.fx
        pts = [(0.0, -th / 2 - 1)]
        for k, rr in enumerate((-th / 6, th / 6, th / 2 + 1)):
            pts.append((f.uniform(-0.5, 0.5) * th / R * (k + 1), rr))
        lines = [pts]
        for sign in (-1, 1):
            a, r = pts[2][0], pts[2][1]
            branch = [(a, r)]
            n = 2 + int(damage * 3)
            for _ in range(n):
                a += sign * f.uniform(8, 22) * (0.7 + damage) / R
                r = max(-th / 2 - 1, min(th / 2 + 1, r + f.uniform(-th * 0.5, th * 0.5)))
                branch.append((a, r))
            lines.append(branch)
        return [[(local_ang + da, dr) for da, dr in line] for line in lines]

    def _progress(self, body) -> None:
        pending, self._pending = self._pending, []
        for ring in pending:
            if ring.escaped_vt is None:
                self._escape(ring)
                v = body.velocity
                gain = 1.0 + self.cfg.glass_speed_gain
                body.velocity = (v.x * gain, v.y * gain)

    def stats(self) -> dict:
        return {"broken": self.escaped, "rings": len(self.rings), "hits": self.hits}
