"""📤 YouTube uploader (v0.23.0): turn the batch's titles.csv into scheduled YouTube uploads.

Pure helpers (offline-testable):
  read_titles()   - parse a titles.csv from the batch factory
  video_metadata()- title / description / tags for one row ( Shorts defaults)
  plan_schedule() - spread N videos over M days at fixed hours

The actual upload uses the official YouTube Data API v3 (google-api-python-client). Those
imports are lazy, so the rest of the app never needs the dependency:
    pip install google-api-python-client google-auth-oauthlib

CLI:
  python main.py publish check
  python main.py publish upload output/video.mp4 --title "..." --tags "shorts,cats" --privacy public
  python main.py publish queue output/titles.csv --folder output --spread-days 3 --times "10:00,17:30"
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRET_CANDIDATES = ("client_secret.json", "client_secret_*.json")


# ---------- titles.csv ----------
def read_titles(path: str) -> list[dict]:
    """Rows of a batch's titles.csv (the batch factory writes file,title,description,hashtags...)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        out.append({(k or "").strip().lower(): (v or "").strip() for k, v in r.items()})
    return out


def video_metadata(row: dict, default_tags: str = "#shorts") -> dict:
    """Title / description / tags for one titles.csv row (missing fields get sensible defaults)."""
    title = row.get("title") or Path(row.get("file") or "video.mp4").stem
    hashtags = [h.strip() for h in (row.get("hashtags") or "").replace(",", " ").split() if h.strip()]
    desc_lines = [ln for ln in (row.get("description") or "").splitlines() if ln.strip()]
    desc = "\n".join(desc_lines)
    tags = [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()]
    if not tags:
        tags = [h.lstrip("#").lower() for h in hashtags]
    if hashtags:
        tail = " ".join(hashtags)
        if tail.lower() not in desc.lower():
            desc = (desc + "\n\n" + tail).strip()
    if "#shorts" not in " ".join(hashtags).lower() and "shorts" not in [t.lower() for t in tags]:
        tags = tags + ["shorts"]
    if not desc:
        desc = title + "\n\n" + default_tags
    return {"title": title[:100], "description": desc[:5000], "tags": tags[:15]}


# ---------- schedule ----------
def _parse_times(times: str) -> list[tuple[int, int]]:
    out = []
    for part in (times or "10:00,17:30").split(","):
        part = part.strip()
        if not part:
            continue
        h, _, m = part.partition(":")
        out.append((int(h), int(m or 0)))
    return out or [(10, 0)]


def plan_schedule(count: int, spread_days: int = 1, times: str = "10:00,17:30",
                  start: datetime | None = None) -> list[str]:
    """publishAt timestamps (ISO, UTC) that spread `count` videos over the given daily slots.
    Slots that would be in the past (or already taken) are pushed to the next free day, so every
    video gets a unique slot."""
    now = datetime.now(timezone.utc)
    start = start or now + timedelta(minutes=10)
    slots = _parse_times(times)
    used: set[str] = set()
    out = []
    for i in range(max(0, count)):
        day = i // max(1, len(slots))
        h, m = slots[i % len(slots)]
        t = (start + timedelta(days=day)).replace(hour=h, minute=m, second=0, microsecond=0)
        while t <= now or t.strftime("%Y-%m-%dT%H:%M:%SZ") in used:
            t += timedelta(days=1)
        stamp = t.strftime("%Y-%m-%dT%H:%M:%SZ")
        used.add(stamp)
        out.append(stamp)
    return out


def queue_plan(csv_path: str, folder: str = "", spread_days: int = 1,
               times: str = "10:00,17:30", privacy: str = "public") -> list[dict]:
    """Everything the queue needs: video file + metadata + publishAt for every row."""
    rows = read_titles(csv_path)
    when = plan_schedule(len(rows), spread_days=spread_days, times=times)
    folder = folder or str(Path(csv_path).parent)
    out = []
    for row, at in zip(rows, when):
        f = row.get("file") or ""
        p = Path(folder) / Path(f).name if f and not Path(f).is_absolute() else Path(f)
        if not p.exists():
            cand = sorted(Path(folder).glob(Path(f).stem + ".*")) if f else []
            p = cand[0] if cand else p
        meta = video_metadata(row)
        meta.update({"video": str(p), "privacy": privacy, "publish_at": at})
        out.append(meta)
    return out


# ---------- the actual API (lazy imports) ----------
def _google_imports():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        import google.auth.exceptions
    except ImportError as e:
        raise SystemExit("Missing dependency: pip install google-api-python-client google-auth-oauthlib\n"
                         f"({e})")
    return InstalledAppFlow, Request, Credentials, build, MediaFileUpload


def get_credentials(client_secret: str = "client_secret.json", token_path: str = "token.json"):
    """OAuth installed-app flow; the token is cached in token.json (next runs are silent)."""
    InstalledAppFlow, Request, Credentials, _build, _media = _google_imports()
    creds = None
    if Path(token_path).exists():
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not Path(client_secret).exists():
            cands = [str(p) for pat in CLIENT_SECRET_CANDIDATES[1:] for p in Path(".").glob(pat)]
            raise SystemExit(f"Put your OAuth client secret at {client_secret} "
                             f"(Google Cloud Console ▸ APIs & Services ▸ OAuth client ▸ Desktop app). "
                             f"Found: {cands or 'none'}")
        flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
        creds = flow.run_local_server(port=0)
        Path(token_path).write_text(creds.to_json(), encoding="utf-8")
    return creds


def youtube_service(client_secret: str = "client_secret.json", token_path: str = "token.json"):
    _i, _r, _c, build, _m = _google_imports()
    return build("youtube", "v3", credentials=get_credentials(client_secret, token_path))


def upload_video(video: str, title: str = "", description: str = "", tags: list | None = None,
                 privacy: str = "public", publish_at: str = "",
                 client_secret: str = "client_secret.json", token_path: str = "token.json") -> dict:
    """Resumable upload of one video; with publish_at it is scheduled (privacyStatus=private)."""
    yt = youtube_service(client_secret, token_path)
    body = {"snippet": {"title": title or Path(video).stem, "description": description or "",
                        "tags": tags or [], "categoryId": "24"},
            "status": {"privacyStatus": "private" if publish_at else privacy,
                       "selfDeclaredMadeForKids": False}}
    if publish_at:
        body["status"]["publishAt"] = publish_at
    media = MediaFileUpload(video, chunksize=8 * 1024 * 1024, resumable=True,
                            mimetype="video/mp4" if video.lower().endswith(".mp4") else "video/quicktime")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = req.next_chunk(num_retries=3)
        if status:
            print(f"\r  uploading {status.progress() * 100:5.1f}%", end="", flush=True)
    print()
    vid = response.get("id", "")
    return {"video_id": vid, "url": f"https://youtu.be/{vid}" if vid else "", "publish_at": publish_at}


def upload_queue(plan: list[dict], client_secret: str = "client_secret.json",
                 token_path: str = "token.json", dry_run: bool = False) -> list[dict]:
    """Upload a whole queue plan (from queue_plan) sequentially."""
    results = []
    for item in plan:
        if not Path(item["video"]).exists():
            results.append({"video": item["video"], "error": "file missing"})
            continue
        if dry_run:
            print(f"[dry] {Path(item['video']).name} at {item['publish_at']}: {item['title']}")
            results.append({"video": item["video"], "publish_at": item["publish_at"], "dry": True})
            continue
        print(f"▶ {Path(item['video']).name} → {item['publish_at']}")
        results.append({"video": item["video"],
                        **upload_video(item["video"], item["title"], item["description"],
                                       item.get("tags"), item.get("privacy", "public"),
                                       item.get("publish_at", ""), client_secret, token_path)})
    return results


def check_api() -> dict:
    """Is the Google API client installed? Is there a client secret / token in the folder?"""
    try:
        import googleapiclient  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
        deps = True
    except ImportError:
        deps = False
    here = Path(".")
    secret = (here / CLIENT_SECRET_CANDIDATES[0]).exists() or \
        any(here.glob(CLIENT_SECRET_CANDIDATES[1]))
    return {"deps": deps, "client_secret": secret, "token": (here / "token.json").exists(),
            "pip": "pip install google-api-python-client google-auth-oauthlib"}
