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
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# upload + read-only, so the studio can greet you with your own channel name after sign-in
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]
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


def token_file() -> Path:
    """Where the OAuth token lives (the app's own folder, never the repo)."""
    return _app_dir() / "token.json"


def _app_dir() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "MoneyMaker911"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = Path.home() / ".mm911"
        base.mkdir(parents=True, exist_ok=True)
    return base


def sign_out(token_path: str = "") -> dict:
    """Forget the cached token (and tell Google to revoke it when we can)."""
    path = Path(token_path) if token_path else token_file()
    revoked = False
    try:
        if path.exists():
            try:
                from google.oauth2.credentials import Credentials
                from google.auth.transport.requests import Request
                Credentials.from_authorized_user_file(str(path), SCOPES).revoke(Request())
                revoked = True
            except Exception:
                pass                     # offline / no deps: deleting the file is enough
            path.unlink()
    except OSError as e:
        return {"error": f"could not delete the token ({e})"}
    return {"ok": True, "revoked": revoked}


def account_info(service=None, client_secret: str = "", token_path: str = "") -> dict:
    """Who is signed in: the channel name / thumbnail (best effort, offline-safe)."""
    info = {"signed_in": False, "channel": "", "thumb": "", "error": ""}
    path = Path(token_path) if token_path else token_file()
    if not path.exists():
        return info
    if not has_google_deps():
        info["error"] = "google-api-python-client is not installed"
        return info
    try:
        svc = service or youtube_service(client_secret or find_client_secret() or "client_secret.json",
                                        str(path))
        res = svc.channels().list(part="snippet", mine=True).execute()
        items = res.get("items") or []
        if items:
            snip = items[0].get("snippet", {}) or {}
            info.update(signed_in=True, channel=snip.get("title", ""),
                        thumb=((snip.get("thumbnails") or {}).get("default") or {}).get("url", ""))
        else:
            info["signed_in"] = True
    except Exception as e:                  # network / expired token / revoked: just report it
        info["error"] = str(e)[:300]
    return info


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


def sign_in(client_secret: str = "", token_path: str = "", on_url=None,
            open_browser: bool = True, timeout: int = 300):
    """Sign in from the app: run Google's installed-app flow with console + local server disabled.

    We print Google's URL via `on_url` so the UI can show (and copy) it, then wait for the
    redirect on a fixed loopback port. The token is cached in the app folder, so the next
    sign-in - and every upload - is silent.
    """
    InstalledAppFlow, _Request, Credentials, _build, _media = _google_imports()
    secret = client_secret or find_client_secret()
    if not secret:
        raise SystemExit(
            "No client_secret.json yet. Create one in Google Cloud Console: "
            "APIs & Services ▸ Credentials ▸ Create credentials ▸ OAuth client ID ▸ Desktop app, "
            "then use 'Add client secret…' in the Publish studio.")
    flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
    auth_url, _state = flow.authorization_url(prompt="consent", access_type="offline")
    if on_url:
        try:
            on_url(auth_url)
        except Exception:
            pass
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(auth_url)
        except Exception:
            pass
    creds = flow.run_local_server(port=0, timeout_seconds=timeout,
                                 authorization_prompt_message="Finish sign-in in your browser…",
                                 success_message="Signed in - you can close this tab.")
    path = Path(token_path) if token_path else token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def find_client_secret() -> str:
    """The OAuth client secret: next to the app, in the app folder, or in the current folder."""
    for cand in (Path.cwd() / CLIENT_SECRET_CANDIDATES[0], _app_dir() / CLIENT_SECRET_CANDIDATES[0]):
        if cand.exists():
            return str(cand)
    for folder in (Path.cwd(), _app_dir()):
        hits = sorted(folder.glob(CLIENT_SECRET_CANDIDATES[1]))
        if hits:
            return str(hits[0])
    return ""


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


# YouTube Data API v3: the free daily allowance, and what one upload costs (1,600 units),
# which means about 6 uploads per day before the API refuses until the quota resets at midnight PT.
DAILY_QUOTA_UNITS = 10000
UPLOAD_COST_UNITS = 1600
UPLOADS_PER_DAY = DAILY_QUOTA_UNITS // UPLOAD_COST_UNITS


def quota(daily_uploads: int = 0) -> dict:
    """How many uploads today's quota still allows (best effort: Google does not expose usage)."""
    used = max(0, min(DAILY_QUOTA_UNITS, int(daily_uploads) * UPLOAD_COST_UNITS))
    return {"per_day": UPLOADS_PER_DAY, "used": int(daily_uploads), "limit": UPLOADS_PER_DAY,
            "left": max(0, (DAILY_QUOTA_UNITS - used) // UPLOAD_COST_UNITS)}


def has_google_deps() -> bool:
    """Are the optional Google client libraries importable?"""
    try:
        import googleapiclient  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
        return True
    except ImportError:
        return False


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
