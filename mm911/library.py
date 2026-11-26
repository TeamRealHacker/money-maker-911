"""📚 Studio comfort: the render library and the undo history.

Two small, offline pieces that make the app comfortable to live in:

  library()   - every finished video in the output folder, with its thumbnail, size, the seed and
                the palette/shape that made it, and whether it was uploaded - so the app can show
                a gallery instead of asking you to open Explorer.
  history     - an undo/redo stack over the config, so a slider you regret is one Ctrl+Z away.

Nothing here renders, uploads or touches the network.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

VIDEO_EXTS = (".mp4", ".mov")


# ---------- settings that are worth remembering per video (and re-applying) ----------
LOOK_KEYS = ("mode", "palette", "container_shape", "tiers", "seed", "hook", "fps",
             "export_resolution", "export_codec", "bg_mode", "bg_colors", "ball_scale",
             "particle_style", "gravity", "speed", "max_seconds", "until_finished",
             "tier_names", "tier_emojis", "tier_colors", "sound_path", "music_path")


def look_from_config(cfg_dict: dict) -> dict:
    """The part of a config that makes a video look the way it does (travels with it)."""
    return {k: cfg_dict[k] for k in LOOK_KEYS if k in cfg_dict}


# ---------- library ----------
def _rows(folder: Path) -> dict:
    """titles.csv rows keyed by file name (the batch factory's own metadata)."""
    csv_path = folder / "titles.csv"
    if not csv_path.exists():
        return {}
    import csv
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            rows = [{ (k or "").strip().lower(): (v or "").strip() for k, v in r.items() }
                    for r in csv.DictReader(f)]
    except (OSError, ValueError):
        return {}
    return {Path(r.get("file", "")).name: r for r in rows if r.get("file")}


def _sidecar(folder: Path) -> dict:
    """`looks.json`: the look each video was rendered with (written by the app after a render)."""
    p = folder / "looks.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def save_look(folder: str, video: str, cfg_dict: dict) -> None:
    """Remember the look a video was made with, so it can be reproduced or varied later."""
    base = Path(folder)
    data = _sidecar(base)
    data[Path(video).name] = {"look": look_from_config(cfg_dict), "saved": time.time()}
    try:
        base.mkdir(parents=True, exist_ok=True)
        (base / "looks.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass


def _uploads(folder: Path) -> dict:
    from .autoupload import load_receipts
    return load_receipts(str(folder))


def library(folder: str, limit: int = 400) -> dict:
    """Every video in the output folder, newest first, with what the app needs to show it."""
    base = Path(folder)
    if not base.is_dir():
        return {"folder": str(base), "videos": [], "count": 0, "total_mb": 0.0, "error": ""}
    rows, looks, uploads = _rows(base), _sidecar(base), _uploads(base)
    thumbs = {p.stem: p for p in base.iterdir() if p.is_file() and p.suffix.lower() in (".jpg", ".png")}
    videos = []
    for p in base.iterdir():
        if not (p.is_file() and p.suffix.lower() in VIDEO_EXTS):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        row = rows.get(p.name, {})
        look = (looks.get(p.name) or {}).get("look") or {}
        thumb = thumbs.get(p.stem)
        videos.append({
            "file": p.name, "path": str(p), "mb": round(st.st_size / (1024 * 1024), 3),
            "bytes": st.st_size,
            "modified": st.st_mtime, "when": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
            "title": row.get("title") or p.stem, "seed": row.get("seed") or look.get("seed") or "",
            "mode": row.get("mode") or look.get("mode") or "",
            "palette": row.get("palette") or look.get("palette") or "",
            "shape": row.get("shape") or look.get("container_shape") or "",
            "won": str(row.get("won", look.get("won", ""))).lower() in ("1", "true", "yes"),
            "thumb": str(thumb) if thumb else "",
            "uploaded": bool((uploads.get(p.name) or {}).get("video_id")),
            "url": (uploads.get(p.name) or {}).get("url", ""),
            "has_look": bool(look),
        })
    videos.sort(key=lambda v: v["modified"], reverse=True)
    total = sum(v["mb"] for v in videos)
    return {"folder": str(base), "videos": videos[:max(1, int(limit))], "count": len(videos),
            "total_mb": round(total, 1), "error": ""}


def delete_video(folder: str, name: str) -> dict:
    """Delete one render (and its thumbnail) - only ever inside the given folder."""
    base = Path(folder).resolve()
    target = (base / Path(name).name).resolve()
    if base not in target.parents and target.parent != base:
        return {"error": "outside the output folder"}
    if not target.name or Path(name).name != name or target.parent != base:
        # `../x` or a nested path: never let a delete escape the output folder
        return {"error": "outside the output folder"}
    if not target.exists():
        return {"error": "already gone"}
    removed = []
    for p in (target, target.with_suffix(".jpg"), target.with_suffix(".png")):
        try:
            if p.exists():
                p.unlink()
                removed.append(p.name)
        except OSError as e:
            return {"error": f"could not delete {p.name} ({e})"}
    for meta in (base / "looks.json", base / ".mm911_uploads.json"):
        try:
            if not meta.exists():
                continue
            data = json.loads(meta.read_text(encoding="utf-8")) or {}
            if data.pop(Path(name).name, None) is not None:
                meta.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except (OSError, ValueError):
            pass
    return {"ok": True, "removed": removed}


def look_of(folder: str, name: str) -> dict:
    """The saved look for one video ({} when it was rendered before looks were recorded)."""
    return ((_sidecar(Path(folder)).get(Path(name).name) or {}).get("look")) or {}


# ---------- undo / redo ----------
@dataclass
class History:
    """A bounded undo stack over config snapshots.

    Deliberately simple: the app pushes the config *before* a change, and undo/redo swap the
    current one in. Bounded so a long session cannot grow without limit.
    """
    limit: int = 60
    _undo: list = field(default_factory=list)
    _redo: list = field(default_factory=list)

    def push(self, snapshot: dict, label: str = "") -> None:
        """Remember a state. Consecutive identical states are collapsed (slider spam)."""
        if self._undo and self._undo[-1]["config"] == snapshot:
            return
        self._undo.append({"config": snapshot, "label": label, "at": time.time()})
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self, current: dict) -> dict | None:
        if not self._undo:
            return None
        step = self._undo.pop()
        self._redo.append({"config": current, "label": step.get("label", ""), "at": time.time()})
        return step["config"]

    def redo(self, current: dict) -> dict | None:
        if not self._redo:
            return None
        step = self._redo.pop()
        self._undo.append({"config": current, "label": step.get("label", ""), "at": time.time()})
        return step["config"]

    def status(self) -> dict:
        return {"undo": len(self._undo), "redo": len(self._redo),
                "next": (self._undo[-1]["label"] if self._undo else ""),
                "redo_next": (self._redo[-1]["label"] if self._redo else "")}
