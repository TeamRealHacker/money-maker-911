"""🪐 Orbit 3D: a ball flying down a tunnel of hoops, in real perspective.

The look is a proper 3D vanishing point: every hoop is the same size in the world and they sit at
increasing depth, so they nest into a tunnel that shrinks toward the horizon, while the ball weaves
along the rim and pops them one at a time as it reaches each one.

It is pure pygame - no OpenGL, no GPU, no per-pixel work - and it is built to cost about the same
as any 2D mode:

* one axis-aligned pinhole projection (`K / depth`) for every point: a frame is one multiply and
  one divide per point, no matrices,
* nothing is allocated per frame: hoops are drawn with `pygame.draw.ellipse` and colours are
  pre-mixed against the background (no per-frame SRCALPHA surfaces, which is what makes "3D" slow
  in pygame),
* the whole scene is one short list sorted back-to-front (no depth buffer needed),
* the hoop the ball is about to clear is always the *same distance ahead of it*, so the shot is
  framed identically all the way down the tunnel - no camera surprises, no giant near-plane hoop.

The mechanic stays the familiar one, so sounds, slow-mo, the batch factory and the export pipeline
work unchanged: hoops clear one by one, every clear plays a note, the last one is FINAL FORM.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

from .breaker import BreakerSim
from .merge import Particle, SoundEvent

# ---- the shot ---------------------------------------------------------------------------------
YAW = math.radians(7.0)          # slight side-on look: hoops become ellipses that fan out
OUT_X = 0.10                     # eye offset sideways, as a fraction of the hoop radius
OUT_Y = -0.07                   # ... and slightly above, so the rings are seen at an angle
BACK = 1.55                      # how far behind the ball the eye rides (× camera distance)


@dataclass
class OrbitRing:
    """One hoop of the tunnel. Same world radius for all of them: perspective does the rest."""

    z: float                       # depth along the tunnel (negative = in front of the eye)
    radius: float                  # world radius
    index: int = 0                 # place in the run (drives the tier colour)
    cleared_vt: float | None = None


class Orbit3DSim(BreakerSim):
    """Hoops down a tunnel; the ball flies through them in order."""

    def __init__(self, cfg, seed: int | None = None):
        self.orbit_rings: list[OrbitRing] = []
        self.orbit_travel = 0.0
        self.orbit_angle = 0.0
        self.near_z = 1.0
        self.ring_radius = 1.0
        self.tunnel_len = 1.0
        self.back = 1.0
        self.ball_z = 0.0
        self._trail: list[tuple] = []
        super().__init__(cfg, seed)
        self.counter_text = getattr(cfg, "orbit_counter_text", "{cleared} / {total} rings")
        self.final_text = getattr(cfg, "orbit_final_text", "FINAL FORM 3D!")

    # ---------- setup ----------
    def _build_bricks(self) -> None:
        """No brick wall: the tunnel is scenery, so `self.bricks` stays empty. Nothing collides and
        nothing can ever be shoved out of frame by the physics engine."""
        cfg = self.cfg
        self.total = max(2, int(getattr(cfg, "orbit_rings", 8)))
        cam = max(260.0, min(2400.0, float(getattr(cfg, "orbit_camera_dist", 760.0))))
        self.cam = cam
        self.near_z = cam * 0.62                      # how far ahead of the ball the next hoop is
        self.ring_radius = cam * 0.52                 # every hoop is this big in the world
        self.back = cam * BACK                        # the eye trails the ball by this much
        self.tunnel_len = self.near_z * (self.total + 1.5)
        self.orbit_rings = [OrbitRing(z=-self.near_z, radius=self.ring_radius, index=i)
                            for i in range(self.total)]
        self.bricks = []
        self.orbit_angle = math.pi * 0.5
        self.orbit_travel = 0.0
        self._trail.clear()
        self.ball_z = -self.near_z
        self._layout()

    def alive_bricks(self):
        """The base step asks what is left to hit; hoops are cleared by flying through them."""
        return []

    def _start_balls(self) -> int:
        return 1

    def _radius(self) -> float:
        return float(getattr(self.cfg, "orbit_ball_radius", 92.0))

    def _layout(self) -> None:
        """Put the live hoops on a *harmonic* depth curve ahead of the ball.

        Projected radius is `K·R/z`, so harmonic depths (`z ∝ 1/j`) make the hoops evenly spaced on
        screen instead of collapsing into a clump at the vanishing point - that even spacing is
        what makes the tunnel read as depth at a glance. The nearest hoop always sits exactly
        `near_z` ahead of the ball, so the shot is framed the same for the whole run."""
        live = [r for r in self.orbit_rings if r.cleared_vt is None]
        n = len(live)
        for j, ring in enumerate(live):
            ring.z = self.ball_z - self.near_z * n / max(0.55, n - j)

    # ---------- the ball's path ----------
    @property
    def orbit_speed(self) -> float:
        return math.radians(max(8.0, min(400.0, float(getattr(self.cfg, "orbit_speed_deg", 105.0)))))

    def ball_pos3(self) -> tuple[float, float, float]:
        a = self.orbit_angle
        r = self.ring_radius * 0.40                   # rides the rim: it flies through the hoop
        return (r * math.cos(a), r * math.sin(a) * 0.85, self.ball_z)

    def _place_ball(self) -> None:
        """Keep the real physics body on the ball's 2D spot, so anything that reads `balls[0]`
        (trails, popups, the export pipeline) stays coherent."""
        if not self.balls:
            return
        x, y, _ = self.ball_pos3()
        body = self.balls[0].shape.body
        body.position = (x, y)
        body.velocity = (0.0, 0.0)

    # ---------- clearing ----------
    def _clear(self, ring: OrbitRing, i: int) -> None:
        c = self.cfg
        ring.cleared_vt = self.vt
        self.broken += 1
        self._last_break_vt = self.vt
        self.events.append(SoundEvent(self.t, min(i * c.tiers // max(1, self.total), c.tiers - 1),
                                      "merge", vt=self.vt, pitch=self._pitch(i)))
        x, y, z = self.ball_pos3()
        self._burst(x, y, z - self.near_z * 0.2, 16, i)
        self._layout()                                # the rest of the tunnel inhales, forwards
        if self.broken >= self.total and self.finished_at is None:
            self.finished_at = self.vt
            self.final_pos = (x, y)
            self.events.append(SoundEvent(self.t, c.tiers - 1, "final", vt=self.vt))
            if c.slowmo_final:
                self._slow(c.slowmo_factor, c.slowmo_seconds)
            if c.shake_strength > 0:
                self.shake = max(self.shake, c.shake_strength * 2.0)
            self._burst(x, y, z, 46, i)

    def _pitch(self, i: int) -> float:
        c = self.cfg
        k = (i - 1) / max(1, self.total - 1)
        return c.breaker_pitch_low + (c.breaker_pitch_high - c.breaker_pitch_low) * k

    def _burst(self, x: float, y: float, z: float, n: int, i: int) -> None:
        """Particles carry their own depth (`z`, `vz`) and are projected with everything else."""
        c = self.cfg
        n = int(round(n * c.particle_amount))
        ncol = max(1, len(c.particle_colors))
        for _ in range(n):
            a = self.fx.uniform(0, math.tau)
            sp = self.fx.uniform(30, 190) * c.particle_speed
            life = self.fx.uniform(0.4, 0.9)
            p = Particle(x, y, math.cos(a) * sp, math.sin(a) * sp, life,
                         (i % max(1, c.tiers), self.fx.randrange(ncol)),
                         self.fx.uniform(700, 1600), self.fx.uniform(0, 360),
                         self.fx.uniform(-540, 540), life)
            p.z = z                                              # type: ignore[attr-defined]
            p.vz = self.fx.uniform(-150, 90) * c.particle_speed  # type: ignore[attr-defined]
            self.particles.append(p)

    # ---------- main step ----------
    def step(self, dt: float) -> None:
        c = self.cfg
        scaled = dt * self.time_scale()
        # the run down the tunnel always finishes inside the video
        span = max(2.0, float(getattr(c, "max_seconds", 12.0)) * 0.80)
        speed = (self.near_z * (self.total + 0.6)) / span          # world units per second
        self.orbit_travel += speed * scaled
        self.orbit_angle = (self.orbit_angle + self.orbit_speed * scaled) % math.tau
        self.ball_z = -self.near_z - self.orbit_travel
        self._layout()                           # the tunnel keeps its constant framing as we fly
        self._place_ball()

        if self.finished_at is None:
            # the ball reaches a hoop once it has travelled a full `near_z` since the last one
            want = int(self.orbit_travel // self.near_z) + 1
            while self.broken < min(want, self.total) and self.finished_at is None:
                live = [r for r in self.orbit_rings if r.cleared_vt is None]
                near = min(live, key=lambda r: -r.z) if live else None
                if near is None:
                    break
                self._clear(near, self.broken + 1)

        keep = max(0, int(getattr(c, "orbit_trail", 14)))
        self._trail.append((self.ball_pos3(), self.vt))
        if len(self._trail) > keep:
            del self._trail[:len(self._trail) - keep]

        for p in self.particles:                                   # particles keep their own depth
            p.z = getattr(p, "z", 0.0) + getattr(p, "vz", 0.0) * dt  # type: ignore[attr-defined]
        super().step(dt)
        if self.balls:
            self._place_ball()                                     # base step moves bodies: re-pin
        self.popups = [p for p in self.popups if self.vt - p.born < p.life]

    @property
    def best_tier(self) -> int:
        return min(self.cfg.tiers - 1, self.broken * self.cfg.tiers // max(1, self.total))

    def stats(self) -> dict:
        return {"cleared": self.broken, "rings": self.total,
                "travel": round(self.orbit_travel / max(1.0, self.near_z), 2),
                "angle": round(math.degrees(self.orbit_angle), 1)}


class Orbit3DRenderer:
    """Perspective renderer for Orbit 3D.

    Duck-types the surface `BreakerRenderer` exposes (it borrows its fonts, palette, background,
    ball sprites and text helpers) and replaces the 2D frame with a projected one.
    """

    def __init__(self, cfg, scale: float = 1.0):
        from ..render_modes import BreakerRenderer
        self._base = BreakerRenderer(cfg, scale)
        self.cfg, self.scale = cfg, scale
        self.surface = self._base.surface
        self.bg = self._base.bg
        self.W, self.H = self._base.W, self._base.H
        self.f_hook, self.f_count, self.f_big = self._base.f_hook, self._base.f_count, self._base.f_big
        self.f_small, self.f_tension = self._base.f_small, self._base.f_tension
        self._sprite: dict = {}
        self._cam_cache = None
        self._bg_cache: dict = {}
        self.ring_wander = 0.0

    # ---- helpers borrowed from the 2D renderer ----
    def _radius(self) -> float:
        return float(getattr(self.cfg, "orbit_ball_radius", 92.0))

    def _tc(self, h):
        return self._base._tc(h)

    def _tier_color(self, t):
        return self._base._tier_color(t)

    def _text_center(self, *a, **k):
        return self._base._text_center(*a, **k)

    def _wrap(self, *a, **k):
        return self._base._wrap(*a, **k)

    # ---- camera ----
    def _cam(self, sim):
        """An axis-aligned pinhole camera looking down the tunnel.

        `K` is solved from the frame (not from a fixed focal length), so the same shot frames a
        Short, a square post or 4K landscape: the hoop ahead of the ball always fills ~78% of the
        width and the tunnel always runs to a vanishing point inside the frame."""
        key = (self.W, self.H, round(float(getattr(sim, "near_z", 1.0)), 1),
               round(float(getattr(sim, "ring_radius", 1.0)), 1),
               round(float(getattr(sim, "back", 1.0)), 1))
        if self._cam_cache is not None and self._cam_cache[0] == key:
            return self._cam_cache[1]
        R = max(1.0, float(getattr(sim, "ring_radius", 1.0)))
        near = max(1.0, float(getattr(sim, "near_z", 1.0)))
        back = max(1.0, float(getattr(sim, "back", 1.0)))
        near_depth = near + back                          # first hoop's depth from the eye
        K = (self.W * 0.42) * near_depth / R              # → the hoop is ~78% of the frame wide
        ox, oy = R * OUT_X, R * OUT_Y
        lift = float(getattr(self.cfg, "orbit_ball_y", 70.0)) / 400.0
        cx, cy = self.W * 0.5, self.H * (0.52 + 0.16 * lift)
        state = (K, cx, cy, near_depth, back, ox, oy, R)

        def project(x: float, y: float, z: float, ball_z: float):
            # the eye rides with the ball: bigger z = closer to the viewer, so depth is the gap
            depth = max(40.0, (ball_z + back) - z)
            return (cx + K * (x - ox) / depth, cy - K * (y - oy) / depth, depth)

        state = state + (project,)
        self._cam_cache = (key, state)
        return state

    # ---- cached surfaces ----
    def _dot_sprite(self, r: int, col: tuple, alpha: int) -> pygame.Surface:
        key = ("dot", r, col, alpha // 24)
        d = self._sprite.get(key)
        if d is not None:
            return d
        d = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        pygame.draw.circle(d, (*col, max(0, min(255, alpha))), (r, r), r)
        if len(self._sprite) > 400:
            self._sprite.clear()
        self._sprite[key] = d
        return d

    def _bg_at(self, x: float, y: float) -> tuple:
        """The cached background's colour at a pixel (quantised to 16 px, so it is a dict hit and
        never a per-frame surface read)."""
        gx = max(0, min(self.W - 1, int(x))) // 16
        gy = max(0, min(self.H - 1, int(y))) // 16
        c = self._bg_cache.get((gx, gy))
        if c is None:
            px = self.bg.get_at((gx * 16, gy * 16))
            c = (px[0], px[1], px[2])
            self._bg_cache[(gx, gy)] = c
        return c

    @staticmethod
    def _mix(col: tuple, other: tuple, k: float) -> tuple:
        """Linear blend. Used instead of per-surface alpha: drawing with a pre-mixed colour costs
        nothing, while a full-screen SRCALPHA surface per hoop costs everything."""
        k = max(0.0, min(1.0, k))
        return (int(col[0] + (other[0] - col[0]) * k),
                int(col[1] + (other[1] - col[1]) * k),
                int(col[2] + (other[2] - col[2]) * k))

    # ---- the frame ----
    def draw(self, sim) -> pygame.Surface:
        cfg, sc, S = self.cfg, self.scale, self.surface
        S.blit(self.bg, (0, 0))
        K, cx, cy, near_depth, back, ox, oy, R, project = self._cam(sim)
        sx, sy = sim.shake_offset()
        dx, dy = int(round(sx * sc)), int(round(sy * sc))
        ball_z = getattr(sim, "ball_z", 0.0)

        fog = max(0.0, min(0.85, float(getattr(cfg, "orbit_fog", 0.45))))
        # line weight tracks the frame, not the scale factor: 6 px on a 1080-wide shot is a hair
        thick = max(2, int(getattr(cfg, "orbit_ring_thickness", 8) * sc * self.W / 540))
        ball_tier = min(cfg.tiers - 1, sim.best_tier)
        ball_info = self._base._ball(ball_tier)
        bx, by, bz = sim.ball_pos3()

        # the hoops: the eye looks down the axis from a little off to one side, so a hoop's circle
        # is seen as an ellipse. The tilt is fixed, so the squash is one constant per frame.
        squash = max(0.70, min(0.96, 1.0 - math.hypot(OUT_X, OUT_Y) * 1.15))
        self.ring_wander = R * 0.13
        ball_px, ball_py, ball_d = project(bx, by, bz, ball_z)

        # ---- the tunnel itself: faint spokes from the vanishing point to the near hoop ----
        # Six converging streaks cost six lines and they are what makes the depth read in motion:
        # without them a nested set of rings looks like a static bullseye.
        spokes = 6
        vpx, vpy, vp_depth = project(0.0, 0.0, sim.orbit_rings[-1].z if sim.orbit_rings else -1e9, ball_z)
        spoke_col = self._mix(self._tier_color(0), self._bg_at(self.W * 0.5, self.H * 0.5), 0.90)
        near_ring = min((r for r in sim.orbit_rings if r.cleared_vt is None),
                        key=lambda r: -r.z, default=None)
        if near_ring is not None:
            _, _, nd = project(0.0, 0.0, near_ring.z, ball_z)
            rad_n = K * near_ring.radius / nd
            spin = sim.vt * 0.25
            for k in range(spokes):
                a = spin + k * math.tau / spokes
                ex = cx + rad_n * math.cos(a) * 1.15
                ey = cy - rad_n * math.sin(a) * 1.15 * squash
                pygame.draw.line(S, spoke_col, (vpx + dx, vpy + dy), (ex + dx, ey + dy),
                                 max(1, int(2 * sc)))

        # ---- one painter's pass, far to near ----
        scene: list[tuple] = []
        for ring in sim.orbit_rings:
            age = None
            if ring.cleared_vt is not None:
                age = sim.vt - ring.cleared_vt
                if age > 0.55:
                    continue
            wob = ring.index * 1.15 + sim.vt * 0.9
            ox3 = self.ring_wander * math.cos(wob) + ox
            oy3 = self.ring_wander * 0.75 * math.sin(wob * 1.3) + oy
            rpx, rpy, depth = project(ox3, oy3, ring.z, ball_z)
            if depth < back * 0.9:                      # already behind the eye
                continue
            scene.append((depth, "ring", (ring, rpx, rpy, age)))
        for pt, vt in sim._trail:
            age = sim.vt - vt
            if age <= 0.4:
                tx, ty, td = project(*pt, ball_z)
                if td > back * 0.5:
                    scene.append((td, "trail", (tx, ty, age, td)))
        scene.append((ball_d, "ball", (ball_px, ball_py, ball_d)))
        for p in sim.particles:
            ppx, ppy, pdep = project(p.x, p.y, getattr(p, "z", 0.0), ball_z)
            if pdep > back * 0.5:
                scene.append((pdep, "spark", (p, ppx, ppy, pdep)))
        scene.sort(key=lambda it: -it[0])

        for depth, kind, payload in scene:
            if kind == "ring":
                ring, rpx, rpy, age = payload
                radius_px = int(K * ring.radius / depth)
                if radius_px < 2 or radius_px > self.W * 0.62:
                    continue                              # small as a dot, or flying past the eye
                bright = 1.0 - fog * min(1.0, depth / max(1.0, near_depth * 2.4))
                if age is not None:                       # the flash as it pops
                    bright *= max(0.0, 1 - age / 0.55)
                    radius_px = int(radius_px * (1 + 0.9 * age))
                if bright <= 0.05:
                    continue
                col = self._tier_color(min(cfg.tiers - 1, ring.index * cfg.tiers // max(1, sim.total)))
                bgc = self._bg_at(rpx + dx, rpy + dy)
                # contrast follows the background: on a light theme a pastel ring vanishes into
                # the paper, on a dark one it has to glow. One luminance test, no theme guessing.
                near = max(0.0, 1.0 - depth / max(1.0, near_depth * 2.0))
                if (bgc[0] * 299 + bgc[1] * 587 + bgc[2] * 114) // 1000 > 150:
                    col = self._mix(col, (18, 16, 38), 0.20 + 0.40 * near)      # darker = visible
                else:
                    col = self._mix(col, (255, 255, 255), 0.10 + 0.45 * near)   # brighter = visible
                w = max(8, radius_px * 2)
                h = max(6, int(w * squash))
                rect = pygame.Rect(0, 0, w, h)
                rect.center = (int(rpx + dx), int(rpy + dy))
                glow = rect.inflate(thick * 10, thick * 10)
                pygame.draw.ellipse(S, self._mix(col, bgc, 0.90 / max(0.25, bright)), glow,
                                    max(2, thick * 3))
                pygame.draw.ellipse(S, self._mix(col, bgc, (1.0 - bright) * 0.85), rect,
                                    max(2, thick + int(2 * near * sc)))
                inner = rect.inflate(-max(3, thick), -max(3, int(thick * squash)))
                if inner.width > 6 and inner.height > 4:
                    pygame.draw.ellipse(S, self._mix((255, 255, 255),
                                                     self._mix(col, bgc, 1 - bright), 0.5),
                                        inner, max(1, thick // 3))
            elif kind == "trail":
                tx, ty, age, td = payload
                k = max(0.0, 1 - age / 0.4)
                rr = max(1, int(K * self._radius() / td * (0.22 + 0.5 * k)))
                dot = self._dot_sprite(rr, ball_info["look"].color, int(170 * k))
                S.blit(dot, (round(tx + dx - rr), round(ty + dy - rr)))
            elif kind == "ball":
                r_ball = max(4, int(K * self._radius() / depth))
                spr = ball_info["sprite"]
                if abs(spr.get_width() - 2 * r_ball) > 2:
                    spr = pygame.transform.smoothscale(spr, (2 * r_ball, 2 * r_ball))
                S.blit(spr, (round(payload[0] + dx - spr.get_width() / 2),
                             round(payload[1] + dy - spr.get_height() / 2)))
            else:                                          # spark
                p, ppx, ppy, pdep = payload
                size = max(1.0, p.size * 0.012 * (K / pdep))
                pcols = self._base.p_cols
                col = pcols[p.color[1] % len(pcols)] if pcols else self._tier_color(p.color[0])
                pygame.draw.circle(S, col, (round(ppx + dx), round(ppy + dy)), max(1, int(size)))

        # hook
        y = int(cfg.hook_y * self.H)
        hook_col = self._tc(cfg.hook_color)
        for line in self._wrap(self.f_hook, cfg.hook, self.W * 0.86):
            y += self._text_center(self.f_hook, line, y, hook_col)

        # counter
        ctext = getattr(sim, "counter_text", None) or cfg.breaker_counter_text
        if ctext:
            left = max(0, sim.total - sim.broken)
            txt = (ctext.replace("{left}", str(left)).replace("{cleared}", str(sim.broken))
                   .replace("{broken}", str(sim.broken)).replace("{total}", str(sim.total))
                   .replace("{balls}", "1").replace("{time}", f"{sim.vt:.1f}"))
            pulse = max(0.0, 1 - (sim.vt - sim._last_break_vt) / 0.22) if sim.broken else 0.0
            t = self.f_count.render(txt, True, self._tc(cfg.counter_color))
            if pulse > 0:
                t = pygame.transform.rotozoom(t, 0, 1 + 0.09 * pulse)
            S.blit(t, ((self.W - t.get_width()) // 2, max(int(self.H * 0.135), y + int(10 * sc))))

        # ---- endings ----
        final_col = self._tc(cfg.final_text_color)
        if sim.finished_at is not None:
            kk = min(1.0, (sim.vt - sim.finished_at) / 0.4)
            grow = 0.55 + 0.45 * (1 - (1 - kk) ** 3) + 0.07 * math.sin(kk * math.pi)
            s = self.f_big.render((getattr(sim, "final_text", None) or cfg.breaker_final_text)
                                  .replace("{total}", str(sim.total)), True, final_col)
            s = pygame.transform.rotozoom(s, 0, grow)
            S.blit(s, ((self.W - s.get_width()) // 2, int(self.H * 0.40)))
        elif not cfg.until_finished and sim.vt > cfg.max_seconds - 2.0:
            s = self.f_hook.render(cfg.fail_text, True, final_col)
            S.blit(s, ((self.W - s.get_width()) // 2, int(self.H * 0.905)))
        if cfg.watermark:
            self._base._text_at(self.f_small, cfg.watermark, cfg.watermark_y,
                                self._tc(cfg.watermark_color),
                                max(0, min(255, cfg.watermark_opacity)))
        return S
