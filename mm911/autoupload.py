"""📤 Auto-upload policy: which finished videos go to YouTube, with what metadata.

The decision logic lives here, away from the network, so it can be tested offline and the
GUI/CLI can share it. Two things happen after a render:

  after_render()  - take the batch's titles.csv (or the rendered files) and turn it into a
                    queue of uploads, honouring the user's auto-upload settings
  settings()      - the user's choice, persisted next to the app's other settings

Safety: auto-upload only ever runs when it was switched on, and a video that already has a
receipt in `.mm911_uploads.json` is never uploaded twice - re-running a batch can't spam a
channel with duplicates.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .publish import video_metadata

RECEIPT = ".mm911_uploads.json"
VIDEO_EXTS = (".mp4", ".mov")

DEFAULTS = {
    "enabled": False,          # never upload unless the user turned it on
    "privacy": "private",      # start private; the user reviews before going public
    "after_batch": True,       # auto-upload when a batch finishes
    "spread_days": 1,          # schedule over N days
    "times": "10:00,17:30",    # upload slots per day
    "only_wins": False,        # skip videos that did not reach the ending
}


def settings(raw: dict | None = None) -> dict:
    """The auto-upload settings, with every missing field filled from DEFAULTS."""
    out = dict(DEFAULTS)
    for k, v in (raw or {}).items():
        if k in out and isinstance(v, type(out[k])) or k in out and isinstance(out[k], (int, float)):
            try:
                out[k] = type(out[k])(v) if not isinstance(out[k], bool) else bool(v)
            except (TypeError, ValueError):
                continue
    return out


# ---------- receipts: never upload the same file twice ----------
def _receipt_path(folder: str) -> Path:
    return Path(folder) / RECEIPT


def load_receipts(folder: str) -> dict:
    p = _receipt_path(folder)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def save_receipt(folder: str, video: str, result: dict) -> None:
    """Remember that `video` was uploaded (keyed by name, so a re-encode is still not a dupe)."""
    p = _receipt_path(folder)
    data = load_receipts(folder)
    data[Path(video).name] = {"uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "video_id": result.get("video_id", ""), "url": result.get("url", ""),
                              "publish_at": result.get("publish_at", "")}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError:
        pass


def already_uploaded(folder: str, video: str) -> bool:
    rec = load_receipts(folder).get(Path(video).name) or {}
    return bool(rec.get("video_id"))


# ---------- planning ----------
def videos_in(folder: str) -> list[str]:
    """Rendered videos in a folder, newest last (titles.csv order matches the batch order)."""
    base = Path(folder)
    if not base.is_dir():
        return []
    files = [p for p in base.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    return [str(p) for p in sorted(files, key=lambda p: p.name.lower())]


def rows_from_folder(folder: str) -> list[dict]:
    """titles.csv when the batch wrote one, otherwise one row per video file."""
    import csv
    csv_path = Path(folder) / "titles.csv"
    if csv_path.exists():
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                rows = [{ (k or "").strip().lower(): (v or "").strip() for k, v in r.items() }
                        for r in csv.DictReader(f)]
            if rows:
                return rows
        except (OSError, ValueError):
            pass
    return [{"file": Path(v).name} for v in videos_in(folder)]


def after_render(folder: str, settings_raw: dict | None = None,
                 only_wins: bool = False, schedule: bool = True) -> dict:
    """The queue auto-upload would run for a finished render.

    Returns {"enabled", "plan": [{video,title,description,tags,privacy,publish_at}], "skipped": [...]}
    and never touches the network - the caller uploads.
    """
    from .publish import plan_schedule
    s = settings(settings_raw)
    out = {"enabled": bool(s["enabled"]), "plan": [], "skipped": [], "settings": s}
    if not out["enabled"]:
        return out
    rows = rows_from_folder(folder)
    if s["only_wins"] or only_wins:
        rows = [r for r in rows if str(r.get("won", "")).strip().lower() in ("1", "true", "yes", "won")]
    when = plan_schedule(len(rows), spread_days=int(s["spread_days"]), times=str(s["times"])) \
        if schedule else []
    base = Path(folder)
    for i, row in enumerate(rows):
        name = row.get("file") or ""
        path = base / Path(name).name if name else None
        if path is None or not path.exists():
            cand = sorted(base.glob(Path(name).stem + ".*")) if name else []
            path = cand[0] if cand else path
        if path is None or not path.exists():
            out["skipped"].append({"file": name, "reason": "file missing"})
            continue
        if already_uploaded(folder, str(path)):
            out["skipped"].append({"file": Path(path).name, "reason": "already uploaded"})
            continue
        meta = video_metadata(row)
        meta.update({"video": str(path), "privacy": s["privacy"],
                     "publish_at": when[i] if i < len(when) else ""})
        out["plan"].append(meta)
    return out


def uploaded_today(folder: str) -> int:
    """How many uploads the receipts record for today (UTC) - used for the quota line."""
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(1 for rec in load_receipts(folder).values()
               if str(rec.get("uploaded_at", "")).startswith(today))


def summary(plan: dict) -> str:
    """One line for the UI after a batch."""
    if not plan.get("enabled"):
        return "Auto-upload is off"
    n, sk = len(plan.get("plan") or []), len(plan.get("skipped") or [])
    if not n:
        return f"Nothing to upload ({sk} skipped)" if sk else "Nothing to upload"
    first = (plan["plan"][0] or {}).get("publish_at", "")
    return f"{n} video(s) queued" + (f", first at {first}" if first else "") + (f", {sk} skipped" if sk else "")
