"""Draws Merge frames with pygame (offscreen) and exports MP4 with FFmpeg."""
from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

from .audio import AudioTrack, load_sound  # noqa: E402
from .config import MergeConfig, PALETTES, CREDIT, hex_to_rgb  # noqa: E402
from .ffmpeg import ffmpeg_exe, best_encoder  # noqa: E402
from .modes.merge import MergeSim  # noqa: E402

if not pygame.get_init():
    pygame.init()


def asset_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "mm911" / "assets" / Path(*parts)
    if p.exists():
        return p
    return Path(__file__).resolve().parent / "assets" / Path(*parts)


def _font(cfg: MergeConfig, size: int, bold: bool = True) -> pygame.font.Font:
    path = cfg.font_path if cfg.font_path and Path(cfg.font_path).exists() else \
        asset_path("fonts", "Poppins-Bold.ttf" if bold else "Poppins-SemiBold.ttf")
    try:
        return pygame.font.Font(str(path), size)
    except Exception:
        return pygame.font.Font(None, size)


def _shade(c: tuple, f: float) -> tuple:
    if f < 1:
        return tuple(max(0, int(v * f)) for v in c)
    return tuple(min(255, int(v + (255 - v) * (f - 1))) for v in c)


def _luma(c) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


class Renderer:
    def __init__(self, cfg: MergeConfig, scale: float = 1.0):
        self.cfg = cfg
        self.scale = scale
        self.W, self.H = int(cfg.width * scale), int(cfg.height * scale)
        self.pal = PALETTES.get(cfg.palette, PALETTES["Candy"])
        self.surface = pygame.Surface((self.W, self.H))
        self.bg = self._make_bg()
        self.sprites = [self._make_sprite(t) for t in range(cfg.tiers)]
        self.f_hook = _font(cfg, int(64 * scale))
        self.f_small = _font(cfg, int(34 * scale), bold=False)
        self.f_big = _font(cfg, int(120 * scale))
        self.f_label = _font(cfg, int(30 * scale))

    # ---------- prebuilt layers ----------
    def _make_bg(self) -> pygame.Surface:
        s = pygame.Surface((self.W, self.H))
        if self.cfg.background_image and Path(self.cfg.background_image).exists():
            img = pygame.image.load(self.cfg.background_image).convert() if pygame.display.get_init() and pygame.display.get_surface() else pygame.image.load(self.cfg.background_image)
            iw, ih = img.get_size()
            k = max(self.W / iw, self.H / ih)
            img = pygame.transform.smoothscale(img, (int(iw * k) + 1, int(ih * k) + 1))
            s.blit(img, ((self.W - img.get_width()) // 2, (self.H - img.get_height()) // 2))
            dim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 70))
            s.blit(dim, (0, 0))
            return s
        top, bot = hex_to_rgb(self.pal["bg_top"]), hex_to_rgb(self.pal["bg_bottom"])
        for y in range(self.H):
            k = y / max(1, self.H - 1)
            pygame.draw.line(s, tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3)), (0, y), (self.W, y))
        return s

    def _tier_color(self, t: int) -> tuple:
        tiers = self.pal["tiers"]
        return hex_to_rgb(tiers[t % len(tiers)])

    def _make_sprite(self, t: int) -> pygame.Surface:
        """Supersampled ball sprite: fill, rim, soft highlight, label or image."""
        cfg = self.cfg
        r = cfg.tier_radius(t) * self.scale
        ss = 3
        R = max(2, int(r * ss))
        big = pygame.Surface((R * 2 + 4, R * 2 + 4), pygame.SRCALPHA)
        c = (R + 2, R + 2)
        col = self._tier_color(t)
        img_path = cfg.tier_images[t] if t < len(cfg.tier_images) else ""
        if img_path and Path(img_path).exists():
            img = pygame.image.load(img_path)
            iw, ih = img.get_size()
            k = (2 * R) / max(iw, ih)
            img = pygame.transform.smoothscale(img, (max(1, int(iw * k)), max(1, int(ih * k))))
            has_alpha = img.get_flags() & pygame.SRCALPHA or img.get_alpha() is not None
            if has_alpha:
                big.blit(img, (c[0] - img.get_width() // 2, c[1] - img.get_height() // 2))
            else:  # circle-mask photos
                mask = pygame.Surface(big.get_size(), pygame.SRCALPHA)
                pygame.draw.circle(mask, (255, 255, 255, 255), c, R)
                tmp = pygame.Surface(big.get_size(), pygame.SRCALPHA)
                tmp.blit(img, (c[0] - img.get_width() // 2, c[1] - img.get_height() // 2))
                tmp.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
                big.blit(tmp, (0, 0))
                pygame.draw.circle(big, _shade(col, 0.7), c, R, max(2, R // 14))
        else:
            pygame.draw.circle(big, _shade(col, 0.72), c, R)
            pygame.draw.circle(big, col, c, int(R * 0.9))
            hl = pygame.Surface(big.get_size(), pygame.SRCALPHA)
            pygame.draw.ellipse(hl, (255, 255, 255, 70),
                                (c[0] - R * 0.55, c[1] - R * 0.7, R * 0.8, R * 0.5))
            big.blit(hl, (0, 0))
            if cfg.show_tier_labels:
                label = cfg.tier_names[t] if t < len(cfg.tier_names) and cfg.tier_names[t] else str(t + 1)
                f = _font(cfg, max(10, int(R * (0.9 if len(label) <= 2 else 0.5))))
                txt_col = (30, 30, 40) if _luma(col) > 140 else (250, 250, 250)
                ts = f.render(label, True, txt_col)
                big.blit(ts, (c[0] - ts.get_width() // 2, c[1] - ts.get_height() // 2))
        size = (max(1, big.get_width() // ss), max(1, big.get_height() // ss))
        return pygame.transform.smoothscale(big, size)

    # ---------- drawing ----------
    def _text_center(self, font, text, y, color, shadow=True):
        s = font.render(text, True, color)
        x = (self.W - s.get_width()) // 2
        if shadow:
            sh = font.render(text, True, (0, 0, 0))
            sh.set_alpha(70)
            self.surface.blit(sh, (x + 3 * self.scale, y + 4 * self.scale))
        self.surface.blit(s, (x, y))
        return s.get_height()

    def _wrap(self, font, text, max_w):
        words, lines, cur = text.split(), [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if font.size(test)[0] <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines[:3]

    def draw(self, sim: MergeSim) -> pygame.Surface:
        cfg, sc, S = self.cfg, self.scale, self.surface
        S.blit(self.bg, (0, 0))
        text_col = hex_to_rgb(self.pal["text"])
        cont_col = hex_to_rgb(self.pal["container"])

        # hook text
        y = int(150 * sc)
        for line in self._wrap(self.f_hook, cfg.hook, self.W * 0.86):
            y += self._text_center(self.f_hook, line, y, text_col)

        # tier progress strip
        if cfg.show_progress:
            n = cfg.tiers
            dot = int(min(70, (self.W * 0.8) / n) * sc / sc)
            gap = dot * 0.2
            total = n * dot + (n - 1) * gap
            x0 = (self.W - total) / 2
            yy = y + int(30 * sc)
            for t in range(n):
                spr = self.sprites[t]
                k = dot / max(spr.get_width(), 1)
                small = pygame.transform.smoothscale(spr, (dot, dot))
                if t > sim.best_tier:
                    small.set_alpha(60)
                S.blit(small, (x0 + t * (dot + gap), yy))
                _ = k

        # container shadow + walls
        pts = [(x * sc, y_ * sc) for x, y_ in sim.outline_world()]
        th = max(2, int(cfg.container_thickness * sc))
        shadow = [(x + 6 * sc, y_ + 10 * sc) for x, y_ in pts]
        sh = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
        pygame.draw.lines(sh, (0, 0, 0, 55), True, shadow, th)
        S.blit(sh, (0, 0))
        pygame.draw.lines(S, cont_col, True, pts, th)
        for p in pts:
            pygame.draw.circle(S, cont_col, p, th / 2)

        # balls
        for b in sim.balls:
            spr = self.sprites[b.tier]
            pos = b.shape.body.position
            ang = -math.degrees(b.shape.body.angle) if (cfg.tier_images and b.tier < len(cfg.tier_images) and cfg.tier_images[b.tier]) else 0
            if b.pop < 1 or ang:
                e = 1 - (1 - b.pop) ** 3
                k = 0.6 + 0.4 * e + 0.12 * math.sin(e * math.pi)
                spr = pygame.transform.rotozoom(spr, ang, k)
            S.blit(spr, (pos.x * sc - spr.get_width() / 2, pos.y * sc - spr.get_height() / 2))

        # particles
        for p in sim.particles:
            col = self._tier_color(p.color[0])
            pygame.draw.circle(S, col, (p.x * sc, p.y * sc), max(1, p.size * sc * min(1, p.life * 2)))

        # watermark / credit
        wm = cfg.watermark or ""
        if wm:
            s = self.f_small.render(wm, True, text_col)
            s.set_alpha(150)
            S.blit(s, ((self.W - s.get_width()) // 2, self.H - int(170 * sc)))

        # ending
        if sim.finished_at is not None:
            k = min(1.0, (sim.t - sim.finished_at) / 0.4)
            scale = 0.5 + 0.5 * (1 - (1 - k) ** 3) + 0.08 * math.sin(k * math.pi)
            s = self.f_big.render("FINAL FORM!", True, text_col)
            s = pygame.transform.rotozoom(s, 0, scale)
            S.blit(s, ((self.W - s.get_width()) // 2, int(self.H * 0.83)))
        elif sim.t > cfg.max_seconds - 2.0:
            s = self.f_hook.render("So close...", True, text_col)
            S.blit(s, ((self.W - s.get_width()) // 2, int(self.H * 0.84)))
        return S


def _pitch_for(event_tier: int, kind: str) -> float:
    base = {"drop": -4.0, "merge": 0.0, "final": 7.0}[kind]
    return base + event_tier * 1.6


def simulate(cfg: MergeConfig) -> MergeSim:
    """Run the physics only (fast) — used to find winning seeds."""
    sim = MergeSim(cfg)
    dt = 1 / cfg.fps
    while not sim.done:
        sim.step(dt)
    return sim


def render_video(cfg: MergeConfig, out_path: str, progress: Callable[[float], None] | None = None,
                 encoder: list[str] | None = None) -> dict:
    """Render one Merge video to MP4. Returns metadata."""
    t0 = time.time()
    sim = MergeSim(cfg)
    rend = Renderer(cfg)
    dt = 1 / cfg.fps
    est_frames = int((cfg.max_seconds + cfg.end_hold_seconds) * cfg.fps)
    out_path = str(out_path)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    tmpdir = tempfile.mkdtemp(prefix="mm911_")
    silent = os.path.join(tmpdir, "video.mp4")
    enc = encoder or best_encoder()
    cmd = [ffmpeg_exe(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{rend.W}x{rend.H}", "-r", str(cfg.fps), "-i", "-",
           *enc, "-pix_fmt", "yuv420p", "-movflags", "+faststart", silent]
    creation = 0x08000000 if os.name == "nt" else 0  # no console window on Windows
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=creation)
    frames = 0
    try:
        while not sim.done:
            sim.step(dt)
            surf = rend.draw(sim)
            proc.stdin.write(pygame.image.tobytes(surf, "RGB"))
            frames += 1
            if progress and frames % 15 == 0:
                progress(min(0.97, frames / est_frames))
    finally:
        proc.stdin.close()
        proc.wait()
    seconds = frames / cfg.fps
    # audio
    track = AudioTrack(seconds)
    snd = load_sound(cfg.sound_path)
    last_t = -1.0
    for ev in sim.events:
        if ev.kind == "drop" and ev.t - last_t < 0.05:
            continue
        vol = cfg.sound_volume * (0.35 if ev.kind == "drop" else 1.0 if ev.kind == "merge" else 1.3)
        track.add(snd, ev.t, _pitch_for(ev.tier, ev.kind), vol)
        last_t = ev.t
    if cfg.music_path:
        track.add_music(load_sound(cfg.music_path), cfg.music_volume)
    wav = os.path.join(tmpdir, "audio.wav")
    track.write(wav, seconds)
    subprocess.run([ffmpeg_exe(), "-y", "-v", "error", "-i", silent, "-i", wav, "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "160k", "-shortest", out_path], check=True, creationflags=creation)
    for f in (silent, wav):
        try:
            os.remove(f)
        except OSError:
            pass
    if progress:
        progress(1.0)
    return {"file": out_path, "seed": cfg.seed, "won": sim.won, "best_tier": sim.best_tier + 1,
            "seconds": round(seconds, 2), "merges": sim.merges, "render_seconds": round(time.time() - t0, 1)}


def render_preview_frame(cfg: MergeConfig, sim: MergeSim, rend: Renderer) -> bytes:
    """JPEG bytes of the current frame (for the live preview in the app)."""
    import io
    surf = rend.draw(sim)
    buf = io.BytesIO()
    pygame.image.save(surf, buf, "preview.jpg")
    return buf.getvalue()


__all__ = ["Renderer", "render_video", "simulate", "render_preview_frame", "CREDIT"]
