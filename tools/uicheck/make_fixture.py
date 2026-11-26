"""Regenerate `fixture.json` — the bridge answers the jsdom checks run against.

The fixture is generated from the real `Api` (so a bootstrap key that the page needs can never
drift out of sync), then a couple of settings and one rendered video are added, because a
headless run has no page labels and no renders on disk.

    python tools/uicheck/make_fixture.py && (cd tools/uicheck && node check.mjs)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))          # run from anywhere: import the repo package


def main() -> None:
    home = tempfile.mkdtemp()
    for var in ("APPDATA", "HOME", "USERPROFILE", "XDG_CONFIG_HOME"):
        os.environ[var] = home          # never touch the developer's real settings
    from mm911.gui import app as app_mod

    app_mod.Api._start_preview = lambda *a, **k: None
    app_mod.Api._emit = lambda *a, **k: None
    api = app_mod.Api()

    boot = api.bootstrap()
    boot["onboarded"] = True            # the checks want the main UI, not the wizard
    boot["themes"] = ["Fruit"]

    index = api.palette()
    index["settings"] = [
        {"id": "gravity", "label": "Gravity", "group": "Setting", "keywords": "gravity strength",
         "kind": "setting"},
        {"id": "max_seconds", "label": "Length (seconds)", "group": "Setting", "keywords": "max seconds",
         "kind": "setting"},
    ]
    video = {"file": "meme_merge_001.mp4", "title": "Fruit Merge 🍉 Final Form", "mb": 4.2,
             "bytes": 4_400_000, "when": "2026-11-26 21:10", "mode": "Meme Merge", "palette": "Fruit",
             "shape": "Circle", "won": True, "uploaded": False, "url": "", "has_look": False,
             "thumb": "", "path": "/out/meme_merge_001.mp4", "modified": 1_764_000_000.0, "seed": 7}
    index["videos"] = [{**video, "id": video["file"], "label": video["title"],
                        "group": "Video", "keywords": video["file"], "kind": "video",
                        "meta": "4.2 MB · 2026-11-26 21:10"}]

    library = api.library()
    library.update(folder="/out", count=1, videos=[video], total_mb=4.2, error="")

    upload = api.auto_upload_state()
    upload.update(enabled=False, deps=True, signed_in=True, todo=2, waiting=2, folder="/out")

    history = api.history_status()
    history.update(undo=2, redo=0, next="gravity", redo_next="")   # one edit to undo, none to redo

    fixture = {
        "bootstrap": boot,
        "palette": index,
        "colab": api.colab_status(),
        "upload": upload,
        "library": library,
        "preflight": api.preflight(),
        "history": history,
        "publish": api.publish_status(),
        "plan": {"plan": [], "summary": "2 ready to upload", "todo": 2,
                 "quota": {"used": 0, "limit": 6, "left": 6}},
    }
    (HERE / "fixture.json").write_text(json.dumps(fixture, indent=1), encoding="utf-8")
    print(f"wrote {HERE / 'fixture.json'} "
          f"({len(index['actions'])} actions, {len(index['pages'])} pages, {len(boot['config'])} config keys)")


if __name__ == "__main__":
    main()
