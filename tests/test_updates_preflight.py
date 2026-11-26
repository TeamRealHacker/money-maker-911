"""🔄 Update center + 🚦 preflight, offline (no network, no rendering)."""
import json
import os
from pathlib import Path

import pytest

from mm911 import preflight, updates
from mm911.config import VERSION, MergeConfig


# ---------- versions ----------
@pytest.mark.parametrize("text,want", [
    ("1.2.3", (1, 2, 3, 1, "")),
    ("v1.2.3", (1, 2, 3, 1, "")),
    ("V0.24", (0, 24, 1, "")),
    ("1.2.3-rc1", (1, 2, 3, 0, "rc1")),
    ("", ()),
    ("nightly", ()),
])
def test_parse_version(text, want):
    assert updates.parse_version(text) == want


@pytest.mark.parametrize("candidate,current,newer", [
    ("0.24.0", "0.23.0", True),
    ("0.23.0", "0.23.0", False),
    ("0.23.0", "0.23", False),          # 0.23 == 0.23.0
    ("0.23.0", "0.24.0", False),
    ("1.0.0", "0.99.99", True),
    ("1.0.0-rc1", "1.0.0", False),      # a pre-release never beats its release
    ("1.0.0", "1.0.0-rc1", True),
    ("", "1.0.0", False),
])
def test_is_newer(candidate, current, newer):
    assert updates.is_newer(candidate, current) is newer


def test_current_version_is_the_build_version():
    assert updates.current_version() == VERSION


# ---------- checking (offline: `latest` is injected) ----------
def test_check_offline_with_payload():
    payload = {"tag_name": "v9.9.9", "name": "Big update", "body": "## Notes\n- new modes\n- faster",
               "html_url": "https://example.test/rel", "published_at": "2026-11-01T10:00:00Z",
               "prerelease": False,
               "assets": [{"name": "MoneyMaker911.exe", "browser_download_url": "https://x/a.exe", "size": 42},
                          {"name": "notes.txt", "browser_download_url": "https://x/n.txt", "size": 1}]}
    out = updates.check(latest=payload, current="0.23.0")
    assert out["checked"] and not out["error"]
    assert out["newer"] is True and out["latest"] == "9.9.9"
    assert [a["name"] for a in out["assets"]] == ["MoneyMaker911.exe"]     # only downloadable app files
    assert out["url"] == "https://example.test/rel"


def test_check_says_no_when_current_is_newest():
    out = updates.check(latest={"tag_name": "v0.1.0"}, current="0.23.0")
    assert out["newer"] is False and out["checked"]


def test_check_network_failure_is_reported_not_raised(monkeypatch):
    def boom(*a, **k):
        raise OSError("no internet")
    monkeypatch.setattr(updates, "_get_json", boom)
    out = updates.check()
    assert "could not reach GitHub" in out["error"] and out["newer"] is False


def test_check_prefers_non_draft_prerelease(monkeypatch):
    """The portable build ships as the `nightly` pre-release, so drafts are skipped."""
    seen = []

    def fake(url, timeout=0):
        seen.append(url)
        return [{"draft": True, "tag_name": "v9.0.0"}, {"draft": False, "tag_name": "v0.24.0"}]
    monkeypatch.setattr(updates, "_get_json", fake)
    out = updates.check(current="0.23.0")
    assert out["latest"] == "0.24.0" and out["newer"] is True
    assert "releases?per_page=10" in seen[0]


def test_changelog_cleans_markdown():
    lines = updates.changelog("# v1\n\n- **Added** the thing\n* second\n| table | x |\n```\n- code\n```\n- last")
    assert lines[0].startswith("**Added**") or lines[0] == "**Added** the thing"
    assert "second" in lines and "table" not in lines
    assert all(not ln.startswith(("-", "#", "```")) for ln in lines)


def test_changelog_limit():
    assert len(updates.changelog("\n".join(f"- item {i}" for i in range(50)), limit=5)) == 5


# ---------- install guards ----------
def test_install_refuses_outside_the_portable_exe(monkeypatch):
    monkeypatch.setattr(updates, "is_frozen", lambda: False)
    res = updates.install("whatever.exe")
    assert "portable .exe" in res["error"] and res["url"].startswith("https://github.com")


def test_download_reports_bad_url(tmp_path):
    res = updates.download("https://127.0.0.1:1/nothing.exe", str(tmp_path / "a.exe"), timeout=2)
    assert "error" in res and not (tmp_path / "a.exe").exists()


def test_install_swaps_and_keeps_the_old_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "is_frozen", lambda: True)
    target = tmp_path / "MoneyMaker911.exe"
    target.write_bytes(b"old build")
    new = tmp_path / "update.exe"
    new.write_bytes(b"new build")
    res = updates.install(str(new), target=str(target), restart=False)
    assert res["ok"] and target.read_bytes() == b"new build"
    assert Path(res["old"]).read_bytes() == b"old build"      # kept: an update can be undone
    assert res["restarted"] is False


def test_install_missing_update_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "is_frozen", lambda: True)
    res = updates.install(str(tmp_path / "nope.exe"), target=str(tmp_path / "app.exe"), restart=False)
    assert "missing" in res["error"]


def test_status_shape():
    assert set(updates.status()) == {"current", "repo", "releases", "frozen"}


# ---------- preflight ----------
def _items(res, level=None):
    return [i for i in res["items"] if level is None or i["level"] == level]


def test_preflight_clean_config_is_ready(tmp_path):
    res = preflight.check(MergeConfig(max_seconds=15), str(tmp_path), ffmpeg_ok=True)
    assert res["ready"] is True and res["errors"] == 0
    assert preflight.summary(res).startswith("Ready")


def test_preflight_catches_missing_picture_folder(tmp_path):
    cfg = MergeConfig(tier_image_folder=str(tmp_path / "gone"))
    res = preflight.check(cfg, str(tmp_path), ffmpeg_ok=True)
    assert not res["ready"]
    assert any("picture folder not found" in i["message"] for i in _items(res, "error"))


def test_preflight_catches_missing_picture_files(tmp_path):
    missing = [str(tmp_path / "a.png"), str(tmp_path / "b.png")]
    res = preflight.check(MergeConfig(tier_images=missing), str(tmp_path), ffmpeg_ok=True)
    errs = _items(res, "error")
    assert errs and "moved or deleted" in errs[0]["message"]
    assert errs[0]["key"] == "tier_images"


def test_preflight_warns_when_folder_has_too_few_pictures(tmp_path):
    folder = tmp_path / "pics"
    folder.mkdir()
    (folder / "1.png").write_bytes(b"png")
    cfg = MergeConfig(tier_image_folder=str(folder), tiers=9)
    res = preflight.check(cfg, str(tmp_path), ffmpeg_ok=True)
    assert res["ready"] and any("1 picture(s) for 9 forms" in i["message"] for i in _items(res, "warning"))


def test_preflight_catches_unwritable_output(tmp_path):
    blocker = tmp_path / "file-not-a-folder"
    blocker.write_text("x")
    res = preflight.check(MergeConfig(), str(blocker / "sub"), ffmpeg_ok=True)
    errs = [i for i in _items(res, "error") if i["area"] == "Output"]
    assert errs, res["items"]


def test_preflight_reports_missing_ffmpeg():
    res = preflight.check(MergeConfig(), "", ffmpeg_ok=False)
    assert any(i["area"] == "FFmpeg" for i in _items(res, "error"))


def test_preflight_flags_too_long_a_render():
    res = preflight.check(MergeConfig(max_seconds=900, until_finished=False), "", ffmpeg_ok=True)
    assert any("cap" in i["message"] for i in _items(res, "warning"))


def test_preflight_warns_about_missing_sound_file(tmp_path):
    res = preflight.check(MergeConfig(sound_path=str(tmp_path / "pop.mp3")), str(tmp_path), ffmpeg_ok=True)
    assert any(i["area"] == "Sound" for i in _items(res, "warning"))


def test_preflight_summary_counts():
    res = {"errors": 2, "warnings": 0}
    assert preflight.summary(res) == "2 problem(s) to fix before rendering"
    assert preflight.summary({"errors": 0, "warnings": 3}) == "Ready · 3 warning(s)"
    assert preflight.summary({"errors": 0, "warnings": 0}) == "Ready to render"


def test_preflight_never_touches_the_config(tmp_path):
    cfg = MergeConfig(tiers=5)
    before = cfg.to_dict()
    preflight.check(cfg, str(tmp_path), ffmpeg_ok=True)
    assert cfg.to_dict() == before


# ---------- CLI + entry point wiring ----------
def test_main_py_routes_the_new_commands_to_the_cli():
    """main.py has an allowlist; a command missing from it silently opens the GUI instead."""
    import main as entry
    for cmd in ("update", "preflight"):
        assert cmd in entry.CLI_COMMANDS, f"{cmd} would open the desktop app instead of the CLI"
    for cmd in ("render", "batch", "thumb", "cutout", "sounds", "dedupe", "colab", "publish"):
        assert cmd in entry.CLI_COMMANDS


def test_cli_preflight_prints_json_and_exits_zero(tmp_path, capsys):
    from mm911.cli import main as cli_main
    cli_main(["preflight", "--out", str(tmp_path)])
    out = json.loads(capsys.readouterr().out)
    assert out["ready"] is True and "summary" in out


def test_cli_preflight_fails_on_a_broken_preset(tmp_path, capsys):
    from mm911.cli import main as cli_main
    with pytest.raises(SystemExit) as e:
        cli_main(["preflight", "--out", str(tmp_path), "--image-folder", str(tmp_path / "gone")])
    assert e.value.code == 1


def test_cli_update_check_offline_reports_the_error(monkeypatch, capsys):
    from mm911.cli import main as cli_main

    def boom(*a, **k):
        raise OSError("no internet")
    monkeypatch.setattr(updates, "_get_json", boom)
    with pytest.raises(SystemExit):
        cli_main(["update", "check"])
    out = json.loads(capsys.readouterr().out)
    assert "could not reach GitHub" in out["error"]
