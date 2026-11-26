"""🚦 Preflight: everything that would make a render fail, checked BEFORE it starts.

A batch of 200 videos that dies on video 180 because one picture is broken (or because the
output folder is not writable, or the sound file was moved) wastes an hour. `check()` looks at
the config and the machine and returns a list of problems, each with a severity:

  error    - the render will almost certainly fail or produce nothing usable
  warning  - it will probably work, but something looks wrong (missing picture, no sound)
  ok/info  - worth knowing (CPU-only encoding, no AI models installed)

Everything here is offline and side-effect free (no rendering, no downloads), so the app can run
it on every settings change; `docs/PREFLIGHT.md` has the list of checks.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import MergeConfig, MODES, MIN_TIERS, MAX_TIERS

MAX_SECONDS = 180.0          # render.py caps the sim length; longer requests are clamped
FFMPEG_HINT = "FFmpeg is bundled with the app; a source install needs imageio-ffmpeg or ffmpeg on PATH"


def _exists(path: str) -> bool:
    return bool(path) and Path(path).expanduser().exists()


def _writable(folder: str) -> tuple[bool, str]:
    p = Path(folder).expanduser() if folder else Path.cwd()
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".mm911_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, str(p)
    except OSError as e:
        return False, f"{p} ({e.strerror or e})"


def _item(level: str, area: str, message: str, fix: str = "", key: str = "") -> dict:
    return {"level": level, "area": area, "message": message, "fix": fix, "key": key}


def check(cfg: MergeConfig, output_dir: str = "", ffmpeg_ok: bool | None = None) -> dict:
    """Run every check; returns {"items": [...], "errors": n, "warnings": n, "ready": bool}."""
    items: list[dict] = []
    c = cfg

    # ---- mode / length ----
    if c.mode not in MODES:
        items.append(_item("error", "Mode", f"unknown mode '{c.mode}'",
                           "pick a mode in the left rail", "mode"))
    if c.until_finished and c.max_seconds and c.max_seconds > MAX_SECONDS:
        items.append(_item("warning", "Length",
                           f"runs until finished but requests {c.max_seconds:.0f}s",
                           f"anything past {MAX_SECONDS:.0f}s is ignored", "max_seconds"))
    elif not c.until_finished and c.max_seconds and c.max_seconds > MAX_SECONDS:
        items.append(_item("warning", "Length", f"{c.max_seconds:.0f}s is longer than the "
                           f"{MAX_SECONDS:.0f}s cap", "shorten it or turn on until finished",
                           "max_seconds"))

    # ---- forms / pictures ----
    if not (MIN_TIERS <= int(c.tiers) <= MAX_TIERS):
        items.append(_item("error", "Forms", f"{c.tiers} forms is outside {MIN_TIERS}-{MAX_TIERS}",
                           f"use {MIN_TIERS}-{MAX_TIERS} forms", "tiers"))
    folder = getattr(c, "tier_image_folder", "") or ""
    images = list(getattr(c, "tier_images", []) or [])
    if folder:
        p = Path(folder).expanduser()
        if not p.is_dir():
            items.append(_item("error", "Pictures", f"picture folder not found: {p.name}",
                               "pick the folder again", "tier_image_folder"))
        else:
            n = len([f for f in p.iterdir()
                     if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")])
            if n == 0:
                items.append(_item("error", "Pictures", f"no pictures in {p.name}",
                                   "add png/jpg files", "tier_image_folder"))
            elif n < int(c.tiers):
                items.append(_item("warning", "Pictures",
                                   f"{n} picture(s) for {c.tiers} forms",
                                   "the extra forms fall back to emoji", "tier_image_folder"))
    elif images:
        missing = [Path(i).name for i in images if not _exists(i)]
        if missing:
            items.append(_item("error", "Pictures",
                               f"{len(missing)} picture(s) moved or deleted: {', '.join(missing[:3])}"
                               + ("…" if len(missing) > 3 else ""),
                               "pick the pictures again", "tier_images"))
    else:
        items.append(_item("info", "Pictures", "no pictures loaded - emoji tiers are used",
                           "add your own pictures for a personal look", "tier_images"))

    # ---- sounds / music ----
    for key, label in (("sound_path", "Sound"), ("music_path", "Music")):
        value = getattr(c, key, "") or ""
        if value and not _exists(value):
            items.append(_item("warning", label, f"{label.lower()} file not found: "
                               f"{Path(value).name}", "pick it again or clear it", key))
    tier_sounds = [s for s in (getattr(c, "tier_sounds", None) or []) if s]
    gone = [Path(s).name for s in tier_sounds if not _exists(s)]
    if gone:
        items.append(_item("warning", "Sounds", f"{len(gone)} tier sound(s) missing: "
                           f"{', '.join(gone[:3])}", "re-pick them in Sounds", "tier_sounds"))
    if not (getattr(c, "auto_sounds", False) or tier_sounds or _exists(c.sound_path or "")):
        items.append(_item("info", "Sounds", "using the built-in pop",
                           "search Myinstants for a satisfying sound", "sound_path"))

    # ---- output folder ----
    ok, where = _writable(output_dir)
    if not ok:
        items.append(_item("error", "Output", f"cannot write to {where}",
                           "choose another output folder", "output_dir"))

    # ---- export settings ----
    if c.export_resolution == "4k" and c.fps > 60:
        items.append(_item("warning", "Export", f"4K at {c.fps} fps is very slow",
                           "60 fps or 2K renders ~4x faster", "fps"))
    if c.export_encoder in ("nvidia", "intel", "amd") and not ffmpeg_ok:
        items.append(_item("warning", "Export", "hardware encoder requested",
                           "renders fall back to the CPU if it is unavailable", "export_encoder"))

    # ---- environment ----
    if ffmpeg_ok is False:
        items.append(_item("error", "FFmpeg", "FFmpeg was not found", FFMPEG_HINT, "ffmpeg"))
    free_gb = None
    try:
        usage = shutil.disk_usage(where if ok else os.getcwd())
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 2:
            items.append(_item("error", "Disk", f"only {free_gb:.1f} GB free",
                               "free some space - a 1080p short is ~10-30 MB", "disk"))
        elif free_gb < 8:
            items.append(_item("warning", "Disk", f"{free_gb:.1f} GB free",
                               "batches of 100+ videos need a few GB", "disk"))
    except OSError:
        pass

    errors = sum(1 for i in items if i["level"] == "error")
    warnings = sum(1 for i in items if i["level"] == "warning")
    return {"items": items, "errors": errors, "warnings": warnings,
            "ready": errors == 0, "free_gb": round(free_gb, 1) if free_gb else None,
            "output_dir": where}


def summary(result: dict) -> str:
    """One line for the status bar."""
    if result.get("errors"):
        return f"{result['errors']} problem(s) to fix before rendering"
    if result.get("warnings"):
        return f"Ready · {result['warnings']} warning(s)"
    return "Ready to render"
