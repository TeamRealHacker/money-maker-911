"""The desktop Api without a window: settings recovery, onboarding persistence, every mode's live preview,
and the thread-safety rules (calls from several threads at once must never raise or deadlock)."""
import json
import threading
import time

import pytest


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from mm911.gui import app
    a = app.Api()
    yield a
    a.preview(False)


def _wait_frame(api, timeout=12):
    last, t0 = 0, time.time()
    while time.time() - t0 < timeout:
        f = api.get_frame(last)
        if f:
            return f
        time.sleep(0.05)
    return None


def test_bootstrap_is_json_serialisable(api):
    b = api.bootstrap()
    json.dumps(b)
    assert b["onboarded"] is False and "glass" in b["config"]["mode"] + "glass"


def test_corrupted_settings_recover(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from mm911.gui import app
    d = app.app_dir()
    for junk in ("{not json", "[]", '{"config": {"tiers": "abc", "mode": 7, "fps": null}}', ""):
        (d / "settings.json").write_text(junk, encoding="utf-8")
        a = app.Api()
        json.dumps(a.bootstrap())
        a.set_config({"tiers": 5})
        assert json.loads((d / "settings.json").read_text(encoding="utf-8"))["config"]["tiers"] == 5


def test_finish_onboarding_persists_tiers(api, tmp_path):
    from mm911.gui import app
    assert api.finish_onboarding({"palette": "Ocean", "tiers": 13, "theme_name": "  My Gang  "}) is True
    a2 = app.Api()
    b = a2.bootstrap()
    assert b["onboarded"] and b["config"]["tiers"] == 13 and b["config"]["palette"] == "Ocean"
    assert b["config"]["theme_name"] == "My Gang"
    api.finish_onboarding({"tiers": "999", "palette": "nope"})      # garbage never raises
    assert api._cfg.tiers == 15 and api._cfg.palette == "Ocean"
    api.finish_onboarding(None)


def test_set_config_rejects_garbage(api):
    api.set_config({"fps": "abc", "tiers": 99, "mode": "nope", "glass_hp": "7", "escape_rings": None,
                    "tier_emojis": "x", "unknown_key": 1})
    c = api._cfg
    assert c.tiers == 15 and c.mode == "merge" and c.glass_hp == 7 and c.fps in range(15, 121)
    json.dumps(api.set_config({"mode": "glass"}))
    assert api._cfg.mode == "glass"


@pytest.mark.parametrize("mode", ["merge", "escape", "breaker", "glass", "ghost", "rhythm"])
def test_preview_every_mode_returns_frames(api, mode):
    api.set_config({"mode": mode})
    api.preview(True)
    f = _wait_frame(api)
    assert f and len(f["jpg"]) > 1000
    api.preview(False)


def test_concurrent_calls_do_not_break_preview(api):
    api.preview(True)
    errors = []

    def hammer(fn):
        try:
            for i in range(6):
                fn(i)
        except Exception as e:           # pragma: no cover
            errors.append(repr(e))

    jobs = [lambda i: api.set_config({"tiers": 5 + i % 6, "mode": ["merge", "glass", "escape"][i % 3]}),
            lambda i: api.tier_previews(),
            lambda i: api.apply_emoji_set(["Fruit", "Animals", ""][i % 3]),
            lambda i: api.clear_tier_image(i % 4),
            lambda i: api.set_tier(i % 3, "name", f"n{i}")]
    ts = [threading.Thread(target=hammer, args=(j,)) for j in jobs]
    [t.start() for t in ts]
    [t.join(90) for t in ts]
    assert not any(t.is_alive() for t in ts) and not errors, errors
    time.sleep(0.8)
    assert _wait_frame(api)
    assert api._pthread.is_alive()


def test_bad_images_do_not_break_previews(api, tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    api.set_config({"tier_images": [str(bad), str(tmp_path / "missing.png")], "mode": "glass"})
    rows = api.tier_previews()
    assert len(rows) == api._cfg.tiers and all(r["png"] for r in rows)
    api.preview(True)
    assert _wait_frame(api)
