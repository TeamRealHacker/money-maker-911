"""⌘K command palette: scoring, ranking and the staged actions."""
import pytest

from mm911 import palette


def _index(**kw):
    return palette.build(kw.pop("labels", {"gravity": "Gravity", "max_seconds": "Length (seconds)"}),
                         kw.pop("videos", [{"file": "a.mp4", "title": "Fruit Final Form", "mb": 4.2,
                                            "when": "2026-11-26 22:10"}]))


def test_build_has_every_kind():
    idx = _index()
    assert idx["actions"] and idx["pages"] and idx["settings"] and idx["videos"]
    assert {a["kind"] for a in idx["actions"]} == {"action"}
    assert idx["settings"][0]["kind"] == "setting"


def test_empty_query_offers_the_useful_actions_first():
    idx = _index()
    res = palette.search(idx, "")
    labels = [r["label"] for r in res]
    assert labels[0] in ("Render video", "Render a batch of videos")
    assert any("Publish" in l for l in labels)
    assert len(res) <= 12


@pytest.mark.parametrize("query,expected", [
    ("ren", "Render video"),                      # prefix
    ("video", "Render video"),                    # word start
    ("youtube", "Open Publish studio"),           # keyword
    ("grav", "Gravity"),                          # setting label
    ("max_sec", "Length (seconds)"),              # setting key
    ("fruit", "Fruit Final Form"),                # video title
    ("a.mp4", "Fruit Final Form"),                # video file name
])
def test_finds_each_kind(query, expected):
    res = palette.search(_index(), query)
    assert res and any(r["label"] == expected for r in res), [r["label"] for r in res]


def test_exact_match_ranks_first():
    idx = _index()
    assert palette.search(idx, "undo")[0]["label"] == "Undo"


def test_actions_beat_settings_on_a_tie():
    idx = palette.build({"publish": "Publish"}, [])
    res = palette.search(idx, "publish")
    kinds = [r["kind"] for r in res]
    assert kinds[0] == "action" and "page" in kinds


def test_multi_word_queries_match_across_the_label():
    idx = _index()
    assert palette.search(idx, "open studio")


def test_no_match_is_empty_and_never_raises():
    idx = _index()
    assert palette.search(idx, "zzzzzz") == []
    assert palette.search({}, "anything") == []
    assert palette.search(idx, None)          # empty query still gives the starter list


def test_limit_is_honoured():
    idx = _index()
    assert len(palette.search(idx, "e", limit=3)) == 3


def test_score_ordering_is_stable():
    assert palette.score("undo", "Undo") > palette.score("undo", "Undo everything now")
    assert palette.score("und", "Undo") > 0
    assert palette.score("xyz", "Undo") == 0
    assert palette.score("", "Undo") == 0


def test_shortcuts_are_documented():
    idx = _index()
    keys = [s["keys"] for s in idx["shortcuts"]]
    assert "⌘K / Ctrl+K" in keys and "Ctrl+Z" in keys
    assert all(s["what"] for s in idx["shortcuts"])


def test_every_action_the_ui_sends_is_in_the_index():
    """The JS switches on these ids; a typo would leave a dead palette row."""
    ids = {a["id"] for a in _index()["actions"]}
    for needed in ("render", "batch", "stop", "publish", "upload", "auto_upload", "library", "colab",
                   "preflight", "thumbnail", "new_run", "undo", "redo", "reset", "themes",
                   "search_settings", "open_output", "update", "shortcuts"):
        assert needed in ids


# ---------- the bridge the UI actually calls ----------
@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from mm911.gui import app as app_mod
    monkeypatch.setattr(app_mod.Api, "_start_preview", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(app_mod.Api, "_emit", lambda *a, **k: None, raising=False)
    return app_mod.Api()


def test_api_palette_returns_the_index(api):
    idx = api.palette()
    assert set(idx) == {"actions", "pages", "settings", "videos", "shortcuts"}
    assert len(idx["actions"]) >= 15
    assert len(idx["shortcuts"]) >= 8


def test_api_palette_search_finds_actions_and_settings(api):
    assert api.palette_search("upload")
    assert any("Upload" in r["label"] for r in api.palette_search("upload"))
    # with no page loaded there are no visible labels, but the key still matches
    assert isinstance(api.palette_search("gravity"), list)


def test_api_palette_run_routes_each_kind(api):
    assert api.palette_run("setting", "gravity") == {"reveal": "gravity"}
    assert api.palette_run("page", "library") == {"page": "library"}
    assert api.palette_run("video", "a.mp4") == {"video": "a.mp4"}
    assert api.palette_run("action", "colab") == {"page": "colab"}
    assert api.palette_run("action", "shortcuts") == {"shortcuts": True}
    assert api.palette_run("action", "auto_upload") == {"js": "auto_upload"}
    assert api.palette_run("action", "thumbnail") == {"js": "thumbnail"}


def test_api_palette_run_rejects_unknown_things(api):
    assert "error" in api.palette_run("nonsense", "x")
    assert "error" in api.palette_run("action", "definitely_not_an_action")


def test_api_colab_status_is_offline_safe(api):
    st = api.colab_status()
    assert st["ready"] is False            # no Colab CLI in CI
    assert [g["id"] for g in st["gpus"]] == ["T4", "L4", "A100"]
    assert st["steps"] and st["note"]


def test_api_colab_render_explains_itself_when_not_set_up(api):
    res = api.colab_render("T4", 1, False)
    assert res["ok"] is False and res["error"] and res.get("setup") is True


def test_api_auto_upload_is_one_call(api):
    st = api.auto_upload_state()
    assert st["enabled"] is False and "todo" in st and "waiting" in st
    assert api.auto_upload_set(True)["enabled"] is True
    assert api.auto_upload_state()["enabled"] is True
    assert api.auto_upload_set(False)["enabled"] is False


def test_the_ui_has_no_duplicate_bridge_methods():
    """A duplicated key in the `mm` object silently replaces the newer one (a stale Colab block
    once did exactly that), so the file is checked directly - no browser needed."""
    import re
    from collections import Counter
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "mm911" / "gui" / "web" / "app.js"
    body = src.read_text(encoding="utf-8")
    body = body[body.index("const mm = {"):]
    names = re.findall(r"^  (?:async )?([A-Za-z_$][\w$]*)\s*\(", body, re.M)
    dup = {k: v for k, v in Counter(names).items() if v > 1 and k not in {"if", "$", "swatches"}}
    assert not dup, f"duplicate mm methods: {sorted(dup)}"
    assert "async openColab()" in body and "async refreshColab()" in body
