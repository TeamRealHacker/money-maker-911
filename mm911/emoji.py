"""Emoji tiers: crisp colour emoji from Twemoji SVGs (CC-BY 4.0, (c) Twitter/jdecked).
Common ones ship inside the app; any other emoji is downloaded once and cached."""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

import pygame

TWEMOJI_CDN = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@15.1.0/assets/svg/{}.svg"


def emoji_code(ch: str) -> str:
    cps = [ord(c) for c in ch.strip()]
    if 0x200D not in cps:
        cps = [c for c in cps if c != 0xFE0F]
    return "-".join(f"{c:x}" for c in cps)


def _bundled_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "mm911" / "assets" / "emoji"
    return p if p.exists() else Path(__file__).resolve().parent / "assets" / "emoji"


def _cache_dir() -> Path:
    d = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "MoneyMaker911" / "emoji"
    d.mkdir(parents=True, exist_ok=True)
    return d


def emoji_svg(ch: str) -> Path | None:
    if not ch or not ch.strip():
        return None
    code = emoji_code(ch)
    for d in (_bundled_dir(), _cache_dir()):
        p = d / f"{code}.svg"
        if p.exists():
            return p
    try:  # one-time download, then offline forever
        req = urllib.request.Request(TWEMOJI_CDN.format(code), headers={"User-Agent": "MoneyMaker911"})
        with urllib.request.urlopen(req, timeout=6) as r:
            data = r.read()
        if b"<svg" not in data[:400]:
            return None
        p = _cache_dir() / f"{code}.svg"
        p.write_bytes(data)
        return p
    except Exception:
        return None


def render_emoji(ch: str, size: int) -> pygame.Surface | None:
    """Emoji as an RGBA surface of size x size, or None if it can't be found."""
    p = emoji_svg(ch)
    if p is None:
        return None
    size = max(4, int(size))
    try:
        return pygame.image.load_sized_svg(str(p), (size, size))
    except Exception:
        try:
            return pygame.transform.smoothscale(pygame.image.load(str(p)), (size, size))
        except Exception:
            return None
