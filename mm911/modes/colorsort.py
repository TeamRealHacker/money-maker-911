"""🎨 Color Sort: pictures drift around the arena and each one is pulled toward the goal ring that wears its own picture.
Touch the right ring and it is sorted (note climbs each time); every ring has its own colour. SORTED! when all are home.
Built on the Chain Reaction arena (shares its renderer, sounds, particles, slow-mo and export)."""
from __future__ import annotations

import math

from .chain import ChainSim


class ColorSortSim(ChainSim):
    def __init__(self, cfg, seed: int | None = None):
        self.k = max(2, min(8, int(cfg.colorsort_zones), max(2, int(cfg.tiers))))
        super().__init__(cfg, seed)
        self.counter_text = cfg.colorsort_counter_text
        self.final_text = cfg.colorsort_final_text
        self.total = max(2, int(cfg.colorsort_balls))
        self.zones = self._make_zones()

    def _make_zones(self) -> list[tuple[float, float, float]]:
        x0, y0, x1, y1 = self.arena
        rad = self.cfg.colorsort_zone_radius
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = (x1 - x0) / 2 - rad - 14, (y1 - y0) / 2 - rad - 14
        out = []
        for i in range(self.k):
            a = -math.pi / 2 + 2 * math.pi * i / self.k
            out.append((cx + rx * math.cos(a) * (1 if self.k > 2 else 0.0) + (rx * (1 if i == 0 else -1) if self.k == 2 else 0),
                        cy + ry * math.sin(a) * (1 if self.k > 2 else 0.0), rad))
        return out

    def _radius(self) -> float:
        return self.cfg.colorsort_ball_radius

    def _start_balls(self) -> int:
        return self.cfg.colorsort_balls

    def _build_bricks(self) -> None:
        self.bricks = []
        self.total = max(2, int(self.cfg.colorsort_balls))

    def _add_ball(self, pos=None):
        b = super()._add_ball(pos)
        b.index = self.rng.randrange(self.k)
        sp = self.cfg.colorsort_speed
        v = b.shape.body.velocity
        n = v.length or 1.0
        b.shape.body.velocity = (v.x / n * sp, v.y / n * sp)
        return b

    def step(self, dt: float) -> None:
        c = self.cfg
        sp = c.colorsort_speed
        if self.finished_at is None and self.vt > 0.6:
            for b in list(self.balls):
                p = b.shape.body.position
                zx, zy, zr = self.zones[b.index % self.k]
                d = math.hypot(zx - p.x, zy - p.y)
                if d <= zr * 0.8 and self.finished_at is None:
                    self._pop(b)
                    continue
                v = b.shape.body.velocity
                ang = math.atan2(v.y, v.x)
                want = math.atan2(zy - p.y, zx - p.x)
                diff = (want - ang + math.pi) % (2 * math.pi) - math.pi
                ang += max(-1, min(1, diff)) * min(abs(diff), c.colorsort_pull * max(1.0, sp / 230.0) * dt)
                b.shape.body.velocity = (math.cos(ang) * sp, math.sin(ang) * sp)
        for b in self.balls:
            v = b.shape.body.velocity
            n = v.length or 1.0
            b.shape.body.velocity = (v.x / n * sp, v.y / n * sp)
        super(ChainSim, self).step(dt)

    def stats(self) -> dict:
        return {"left": len(self.balls), "target": self.total}
