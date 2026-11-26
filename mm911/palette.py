"""⌘K command palette: one search box for everything the app can do.

Typing "up" should not require knowing that auto-upload lives behind a checkbox in the publish
studio. The palette searches four kinds of thing at once and answers with a flat, ranked list:

  action  - do something now (render, batch, publish, open the studio, undo, check updates…)
  page    - go somewhere (My videos, Publish studio, Colab, a specific settings section)
  setting - jump to a control and highlight it (every `data-k` in the page, with its label)
  video   - open or reveal a render from the library

Scoring is deliberately simple and predictable (prefix > word-start > substring), because a
palette that reorders unpredictably is worse than no palette. Everything here is offline.
"""
from __future__ import annotations

import re
from pathlib import Path

# ---------- the fixed part: actions ----------
ACTIONS = [
    # (id, label, group, keywords, shortcut)
    ("render", "Render video", "Render", "make video render now single", ""),
    ("batch", "Render a batch of videos", "Render", "batch many queue factory", ""),
    ("stop", "Stop rendering", "Render", "cancel stop abort", ""),
    ("publish", "Open Publish studio", "Publish", "youtube upload publish studio", ""),
    ("upload", "Upload the queue to YouTube", "Publish", "youtube upload queue auto", ""),
    ("auto_upload", "Toggle auto-upload after a batch", "Publish", "auto upload youtube automatic", ""),
    ("library", "Open My videos", "Library", "library videos gallery renders", ""),
    ("colab", "Open Colab GPU rendering", "Render", "colab cloud gpu render remote", ""),
    ("preflight", "Check settings before rendering", "Render", "preflight check problems validate", ""),
    ("thumbnail", "Save a thumbnail", "Render", "thumbnail thumb jpg cover", ""),
    ("new_run", "Start a new run", "Render", "restart new run preview", ""),
    ("undo", "Undo", "Edit", "undo back revert", "Ctrl+Z"),
    ("redo", "Redo", "Edit", "redo forward", "Ctrl+Shift+Z"),
    ("reset", "Reset all settings to defaults", "Edit", "reset defaults clear", ""),
    ("themes", "Save / load a theme", "Edit", "theme save load preset look", ""),
    ("search_settings", "Search settings", "Go to", "settings find search control", "/"),
    ("open_output", "Open the output folder", "Go to", "folder explorer output files", ""),
    ("update", "Check for updates", "App", "update upgrade version new", ""),
    ("shortcuts", "Keyboard shortcuts", "App", "shortcuts keys help", "?"),
]

PAGES = [
    ("library", "My videos", "Library"),
    ("publish", "Publish studio", "Publish"),
    ("colab", "Colab GPU rendering", "Render"),
    ("sec-tiers", "Settings · Tiers & pictures", "Settings"),
    ("sec-sounds", "Settings · Sounds", "Settings"),
    ("sec-export", "Settings · Export", "Settings"),
    ("sec-gameplay", "Settings · Gameplay", "Settings"),
    ("sec-themes", "Settings · Themes & look", "Settings"),
    ("sec-balls", "Settings · Balls", "Settings"),
    ("sec-bg", "Settings · Background", "Settings"),
    ("sec-effects", "Settings · Effects", "Settings"),
    ("sec-text", "Settings · Text", "Settings"),
    ("sec-batch", "Settings · Batch", "Settings"),
]

SHORTCUTS = [
    ("⌘K / Ctrl+K", "Search everything (this palette)"),
    ("/", "Focus the settings search"),
    ("Ctrl+Z", "Undo"),
    ("Ctrl+Shift+Z", "Redo"),
    ("Ctrl+R", "Render video"),
    ("Ctrl+Shift+R", "Render a batch"),
    ("Ctrl+P", "Upload the queue to YouTube"),
    ("Ctrl+L", "My videos"),
    ("Esc", "Close the palette / a page"),
    ("?", "Keyboard shortcuts"),
]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower()).strip()


# curated items (actions, pages) win ties against the thousands of raw settings
KIND_BONUS = {"action": 12, "page": 9, "setting": 0, "video": 3}


def score(query: str, label: str, keywords: str = "") -> int:
    """Rank one candidate: exact > prefix > word-start > substring. 0 means "no match".

    A keyword that matches exactly ("publish" -> "publish studio" keywords) scores just under an
    exact label, so `publish` still surfaces the action before a setting that merely contains it.
    """
    q = _norm(query)
    if not q:
        return 0
    lab, kw = _norm(label), _norm(keywords)
    if lab == q:
        return 100
    if lab.startswith(q):
        return 90
    if any(w.startswith(q) for w in lab.split()):
        return 80
    if q in lab:
        return 65
    if kw == q:
        return 85
    if any(w.startswith(q) for w in kw.split()):
        return 55
    if q in kw:
        return 35
    # every typed word must appear somewhere ("up lo" -> "upload ...")
    parts = q.split()
    hay = f"{lab} {kw}"
    if len(parts) > 1 and all(p in hay for p in parts):
        return 25
    return 0


def build(settings_labels: dict | None = None, videos: list | None = None) -> dict:
    """The palette's index. `settings_labels` maps data-k -> visible label (from the page)."""
    actions = [{"id": i, "label": l, "group": g, "keywords": k, "shortcut": s, "kind": "action"}
               for i, l, g, k, s in ACTIONS]
    pages = [{"id": i, "label": l, "group": g, "keywords": l, "kind": "page"} for i, l, g in PAGES]
    settings = []
    for key, label in (settings_labels or {}).items():
        if not key:
            continue
        settings.append({"id": key, "label": label or key.replace("_", " ").title(),
                         "group": "Setting", "keywords": key.replace("_", " "), "kind": "setting"})
    vids = []
    for v in videos or []:
        name = v.get("file") or ""
        if not name:
            continue
        vids.append({"id": name, "label": v.get("title") or Path(name).stem,
                     "group": "Video", "keywords": name, "kind": "video",
                     "meta": f"{v.get('mb', 0)} MB · {v.get('when', '')}"})
    return {"actions": actions, "pages": pages, "settings": settings, "videos": vids,
            "shortcuts": [{"keys": k, "what": w} for k, w in SHORTCUTS]}


def search(index: dict, query: str, limit: int = 12) -> list[dict]:
    """Ranked results across every kind. Empty query returns the most useful actions."""
    q = (query or "").strip()
    if not q:
        first = [a for a in index.get("actions", []) if a["id"] in
                 ("render", "batch", "publish", "library", "colab", "upload", "undo", "update")]
        return first[:limit]
    out = []
    for kind, key in (("action", "actions"), ("page", "pages"), ("setting", "settings"),
                      ("video", "videos")):
        for item in index.get(key, []) or []:
            s = score(q, item["label"], item.get("keywords", ""))
            if s:
                out.append({**item, "score": s + KIND_BONUS.get(kind, 0)})
    # curated first (actions, pages), then settings and videos — each by score.
    # A setting key that happens to contain the word must not bury the action the user meant.
    order = {"action": 0, "page": 1, "setting": 2, "video": 3}
    out.sort(key=lambda r: (order.get(r["kind"], 9), -r["score"], r["label"].lower()))
    return out[:limit]
