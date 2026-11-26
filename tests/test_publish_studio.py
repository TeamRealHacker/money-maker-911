"""📤 Publish studio: auto-upload policy, receipts, sign-in plumbing - all offline.

The Google client libraries are NOT installed in CI, which is exactly the state most users
start in, so the tests cover the "no deps" path as hard as the happy path.
"""
import json
from pathlib import Path

import pytest

from mm911 import autoupload, publish


# ---------- helpers ----------
def _folder(tmp_path, names=("v1.mp4", "v2.mp4"), csv_rows=None):
    for n in names:
        (tmp_path / n).write_bytes(b"x")
    if csv_rows is not None:
        head = "file,title,description,hashtags\n"
        body = "".join(f"{f},{t},,{h}\n" for f, t, h in csv_rows)
        (tmp_path / "titles.csv").write_text(head + body, encoding="utf-8")
    return str(tmp_path)


# ---------- settings ----------
def test_settings_defaults_are_safe():
    s = autoupload.settings()
    assert s["enabled"] is False            # never upload unless switched on
    assert s["privacy"] == "private"        # and start private
    assert s["after_batch"] is True


def test_settings_keeps_valid_values():
    s = autoupload.settings({"enabled": True, "privacy": "unlisted", "spread_days": 3})
    assert s["enabled"] is True and s["privacy"] == "unlisted" and s["spread_days"] == 3


def test_settings_ignores_unknown_and_bad_values():
    s = autoupload.settings({"nonsense": 1, "spread_days": "not a number"})
    assert "nonsense" not in s
    assert s["spread_days"] == autoupload.DEFAULTS["spread_days"]


# ---------- planning ----------
def test_after_render_is_inert_when_disabled(tmp_path):
    folder = _folder(tmp_path, csv_rows=[("v1.mp4", "One", "#shorts")])
    plan = autoupload.after_render(folder, {})
    assert plan["enabled"] is False and plan["plan"] == []


def test_after_render_plans_every_video_once(tmp_path):
    folder = _folder(tmp_path, csv_rows=[("v1.mp4", "One", "#shorts"), ("v2.mp4", "Two", "#shorts")])
    plan = autoupload.after_render(folder, {"enabled": True, "privacy": "private"})
    assert len(plan["plan"]) == 2
    first = plan["plan"][0]
    assert first["title"] == "One" and first["privacy"] == "private"
    assert first["publish_at"]                       # scheduled
    assert Path(first["video"]).exists()


def test_after_render_makes_rows_without_a_titles_csv(tmp_path):
    folder = _folder(tmp_path)
    plan = autoupload.after_render(folder, {"enabled": True})
    assert {Path(p["video"]).name for p in plan["plan"]} == {"v1.mp4", "v2.mp4"}
    assert all(p["title"] for p in plan["plan"])


def test_after_render_skips_missing_files(tmp_path):
    folder = _folder(tmp_path, names=("v1.mp4",))
    (tmp_path / "titles.csv").write_text("file,title\nv1.mp4,One\ngone.mp4,Gone\n", encoding="utf-8")
    plan = autoupload.after_render(folder, {"enabled": True})
    assert [Path(p["video"]).name for p in plan["plan"]] == ["v1.mp4"]
    assert plan["skipped"][0]["reason"] == "file missing"


def test_only_wins_filters_on_the_won_column(tmp_path):
    for n in ("a.mp4", "b.mp4"):
        (tmp_path / n).write_bytes(b"x")
    (tmp_path / "titles.csv").write_text("file,title,won\na.mp4,Winner,1\nb.mp4,Loser,0\n", encoding="utf-8")
    plan = autoupload.after_render(str(tmp_path), {"enabled": True, "only_wins": True})
    assert [Path(p["video"]).name for p in plan["plan"]] == ["a.mp4"]


def test_schedule_is_opt_out(tmp_path):
    folder = _folder(tmp_path)
    plan = autoupload.after_render(folder, {"enabled": True}, schedule=False)
    assert all(p["publish_at"] == "" for p in plan["plan"])


# ---------- receipts: no double uploads ----------
def test_receipt_roundtrip_and_no_double_upload(tmp_path):
    folder = _folder(tmp_path, names=("v1.mp4",))
    autoupload.save_receipt(folder, str(tmp_path / "v1.mp4"),
                            {"video_id": "abc123", "url": "https://youtu.be/abc123"})
    assert autoupload.already_uploaded(folder, str(tmp_path / "v1.mp4")) is True
    rec = json.loads((tmp_path / autoupload.RECEIPT).read_text())["v1.mp4"]
    assert rec["video_id"] == "abc123" and rec["uploaded_at"].endswith("+00:00")
    plan = autoupload.after_render(folder, {"enabled": True})
    assert plan["plan"] == []
    assert plan["skipped"][0]["reason"] == "already uploaded"


def test_receipts_survive_a_broken_file(tmp_path):
    _folder(tmp_path, names=("v1.mp4",))
    (tmp_path / autoupload.RECEIPT).write_text("{not json", encoding="utf-8")
    assert autoupload.load_receipts(str(tmp_path)) == {}
    assert autoupload.already_uploaded(str(tmp_path), str(tmp_path / "v1.mp4")) is False


def test_failed_upload_leaves_no_receipt(tmp_path):
    folder = _folder(tmp_path, names=("v1.mp4",))
    autoupload.save_receipt(folder, str(tmp_path / "v1.mp4"), {"error": "quota"})
    assert autoupload.already_uploaded(folder, str(tmp_path / "v1.mp4")) is False


# ---------- summaries ----------
def test_summary_lines():
    assert autoupload.summary({"enabled": False}) == "Auto-upload is off"
    assert autoupload.summary({"enabled": True, "plan": [], "skipped": []}) == "Nothing to upload"
    assert "2 skipped" in autoupload.summary({"enabled": True, "plan": [], "skipped": [1, 2]})
    line = autoupload.summary({"enabled": True, "plan": [{"publish_at": "2027-01-01T10:00:00Z"}],
                               "skipped": []})
    assert line.startswith("1 video(s) queued") and "2027-01-01" in line


# ---------- publish plumbing (no Google libs installed) ----------
def test_has_google_deps_reports_a_bool():
    assert isinstance(publish.has_google_deps(), bool)


def test_token_file_is_outside_the_repo():
    tok = publish.token_file()
    assert tok.name == "token.json"
    assert "MoneyMaker911" in str(tok)


def test_sign_out_without_a_token_is_harmless(tmp_path):
    res = publish.sign_out(str(tmp_path / "nope.json"))
    assert res["ok"] is True and res["revoked"] is False


def test_sign_out_deletes_the_token(tmp_path):
    tok = tmp_path / "token.json"
    tok.write_text("{}", encoding="utf-8")
    res = publish.sign_out(str(tok))
    assert res["ok"] and not tok.exists()


def test_account_info_without_a_token_is_signed_out(tmp_path):
    info = publish.account_info(token_path=str(tmp_path / "none.json"))
    assert info == {"signed_in": False, "channel": "", "thumb": "", "error": ""}


def test_account_info_with_a_token_but_no_deps_explains_itself(tmp_path, monkeypatch):
    tok = tmp_path / "token.json"
    tok.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(publish, "has_google_deps", lambda: False)
    info = publish.account_info(token_path=str(tok))
    assert info["signed_in"] is False and "google-api-python-client" in info["error"]


def test_account_info_reads_the_channel_name(tmp_path, monkeypatch):
    tok = tmp_path / "token.json"
    tok.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(publish, "has_google_deps", lambda: True)

    class Svc:
        def channels(self):
            return self

        def list(self, **kw):
            return self

        def execute(self):
            return {"items": [{"snippet": {"title": "My Shorts",
                                           "thumbnails": {"default": {"url": "https://i/x.jpg"}}}}]}
    info = publish.account_info(service=Svc(), token_path=str(tok))
    assert info["signed_in"] is True and info["channel"] == "My Shorts"
    assert info["thumb"] == "https://i/x.jpg"


def test_account_info_reports_a_dead_token(tmp_path, monkeypatch):
    tok = tmp_path / "token.json"
    tok.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(publish, "has_google_deps", lambda: True)

    class Svc:
        def channels(self):
            return self

        def list(self, **kw):
            return self

        def execute(self):
            raise RuntimeError("Token has been expired or revoked.")
    info = publish.account_info(service=Svc(), token_path=str(tok))
    assert info["signed_in"] is False and "revoked" in info["error"]


def test_sign_in_without_a_client_secret_says_what_to_do(monkeypatch, tmp_path):
    monkeypatch.setattr(publish, "has_google_deps", lambda: True)
    monkeypatch.setattr(publish, "find_client_secret", lambda: "")
    monkeypatch.setattr(publish, "_google_imports", lambda: (None, None, None, None, None))
    with pytest.raises(SystemExit) as e:
        publish.sign_in(token_path=str(tmp_path / "t.json"))
    assert "client_secret.json" in str(e.value)
    assert "Desktop app" in str(e.value)          # the exact console setting to pick


def test_find_client_secret_looks_in_the_app_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "_app_dir", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)                    # nothing in the cwd
    assert publish.find_client_secret() == ""
    (tmp_path / "client_secret.json").write_text("{}", encoding="utf-8")
    assert publish.find_client_secret().endswith("client_secret.json")


def test_scopes_cover_upload_and_channel_read():
    assert any("youtube.upload" in s for s in publish.SCOPES)
    assert any("youtube.readonly" in s for s in publish.SCOPES)


# ---------- CLI ----------
def test_cli_publish_whoami_offline(tmp_path, monkeypatch, capsys):
    from mm911.cli import main as cli_main
    monkeypatch.setattr(publish, "token_file", lambda: tmp_path / "token.json")
    cli_main(["publish", "whoami"])
    out = json.loads(capsys.readouterr().out)
    assert out["signed_in"] is False


def test_cli_publish_auto_dry_run_plans_without_uploading(tmp_path, monkeypatch, capsys):
    from mm911.cli import main as cli_main
    for n in ("v1.mp4", "v2.mp4"):
        (tmp_path / n).write_bytes(b"x")
    (tmp_path / "titles.csv").write_text("file,title,won\nv1.mp4,One,1\nv2.mp4,Two,0\n", encoding="utf-8")
    called = []
    monkeypatch.setattr(publish, "upload_queue", lambda *a, **k: called.append(1) or [])
    cli_main(["publish", "auto", "--folder", str(tmp_path), "--enable", "on",
              "--only-wins", "--dry-run"])
    out = json.loads(capsys.readouterr().out)
    assert out["enabled"] is True and len(out["plan"]) == 1   # only the winner
    assert called == []                                       # a dry run never uploads


def test_cli_publish_auto_saves_a_receipt_per_upload(tmp_path, monkeypatch, capsys):
    from mm911.cli import main as cli_main
    (tmp_path / "v1.mp4").write_bytes(b"x")
    monkeypatch.setattr(publish, "upload_queue",
                        lambda plan, **k: [{"video": p["video"], "video_id": "id1", "url": "u"} for p in plan])
    cli_main(["publish", "auto", "--folder", str(tmp_path), "--enable", "on"])
    capsys.readouterr()
    assert autoupload.already_uploaded(str(tmp_path), str(tmp_path / "v1.mp4")) is True


# ---------- YouTube quota ----------
def test_upload_quota_math():
    q = publish.quota(0)
    assert q["per_day"] == 6 and q["left"] == 6
    assert publish.quota(2)["left"] == 4
    assert publish.quota(6)["left"] == 0          # the API refuses after ~6 uploads a day
    assert publish.quota(99)["left"] == 0         # never negative


def test_uploaded_today_counts_only_todays_receipts(tmp_path):
    from datetime import datetime, timedelta, timezone
    folder = _folder(tmp_path, names=("v1.mp4", "v2.mp4"))
    today = datetime.now(timezone.utc)
    autoupload.save_receipt(folder, str(tmp_path / "v1.mp4"), {"video_id": "a"})
    # rewrite one receipt to yesterday
    path = tmp_path / autoupload.RECEIPT
    data = json.loads(path.read_text())
    data["v2.mp4"] = {"uploaded_at": (today - timedelta(days=1)).isoformat(timespec="seconds"),
                      "video_id": "b"}
    path.write_text(json.dumps(data), encoding="utf-8")
    assert autoupload.uploaded_today(folder) == 1
