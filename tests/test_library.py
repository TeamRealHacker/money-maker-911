"""📚 Library + undo history, offline."""
import json
import os
import time
from pathlib import Path

import pytest

from mm911 import library
from mm911.config import MergeConfig


def _render(tmp_path, name="meme_merge_001_7.mp4", thumb=True, size=2048):
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    if thumb:
        (tmp_path / (p.stem + ".jpg")).write_bytes(b"jpg")
    return p


def _csv(tmp_path, rows):
    head = "file,title,seed,mode,palette,shape,won\n"
    (tmp_path / "titles.csv").write_text(
        head + "".join(f"{f},{t},{s},{m},{p},{sh},{w}\n" for f, t, s, m, p, sh, w in rows),
        encoding="utf-8")


# ---------- library ----------
def test_empty_folder(tmp_path):
    out = library.library(str(tmp_path / "nope"))
    assert out["videos"] == [] and out["count"] == 0


def test_lists_videos_with_metadata(tmp_path):
    _render(tmp_path)
    _csv(tmp_path, [("meme_merge_001_7.mp4", "Fruit Final Form", "7", "merge", "Candy", "circle", "1")])
    out = library.library(str(tmp_path))
    v = out["videos"][0]
    assert out["count"] == 1 and v["title"] == "Fruit Final Form"
    assert v["seed"] == "7" and v["mode"] == "merge" and v["palette"] == "Candy"
    assert v["won"] is True and v["thumb"].endswith(".jpg")
    assert v["bytes"] > 0 and v["mb"] >= 0 and v["when"]


def test_newest_first(tmp_path):
    old = _render(tmp_path, "a.mp4")
    new = _render(tmp_path, "b.mp4")
    os.utime(old, (time.time() - 500, time.time() - 500))
    out = library.library(str(tmp_path))
    assert [v["file"] for v in out["videos"]] == ["b.mp4", "a.mp4"]


def test_upload_receipts_are_reflected(tmp_path):
    _render(tmp_path)
    (tmp_path / ".mm911_uploads.json").write_text(json.dumps(
        {"meme_merge_001_7.mp4": {"video_id": "abc", "url": "https://youtu.be/abc"}}), encoding="utf-8")
    v = library.library(str(tmp_path))["videos"][0]
    assert v["uploaded"] is True and v["url"] == "https://youtu.be/abc"


def test_corrupt_metadata_never_breaks_the_library(tmp_path):
    _render(tmp_path)
    (tmp_path / "titles.csv").write_text("not,a,real\ncsv?", encoding="utf-8")
    (tmp_path / "looks.json").write_text("{oops", encoding="utf-8")
    out = library.library(str(tmp_path))
    assert out["count"] == 1 and out["videos"][0]["title"].startswith("meme_merge")


def test_limit_is_honoured(tmp_path):
    for i in range(5):
        _render(tmp_path, f"v{i}.mp4")
    out = library.library(str(tmp_path), limit=3)
    assert len(out["videos"]) == 3 and out["count"] == 5


# ---------- looks ----------
def test_save_and_read_the_look_of_a_video(tmp_path):
    cfg = MergeConfig(palette="Neon", container_shape="heart", seed=42).to_dict()
    library.save_look(str(tmp_path), "a.mp4", cfg)
    look = library.look_of(str(tmp_path), "a.mp4")
    assert look["palette"] == "Neon" and look["container_shape"] == "heart" and look["seed"] == 42
    assert "export_audio" not in look           # only the look travels, not every setting


def test_look_of_an_unknown_video_is_empty(tmp_path):
    assert library.look_of(str(tmp_path), "nope.mp4") == {}


def test_look_is_saved_from_the_batch_metadata_when_available(tmp_path):
    _render(tmp_path)
    library.save_look(str(tmp_path), "meme_merge_001_7.mp4",
                      MergeConfig(palette="Space", seed=9).to_dict())
    v = library.library(str(tmp_path))["videos"][0]
    assert v["has_look"] is True and v["palette"] == "Space"


# ---------- delete ----------
def test_delete_removes_video_thumbnail_and_metadata(tmp_path):
    _render(tmp_path)
    library.save_look(str(tmp_path), "meme_merge_001_7.mp4", MergeConfig().to_dict())
    res = library.delete_video(str(tmp_path), "meme_merge_001_7.mp4")
    assert res["ok"]
    assert not (tmp_path / "meme_merge_001_7.mp4").exists()
    assert not (tmp_path / "meme_merge_001_7.jpg").exists()
    assert "meme_merge_001_7.mp4" not in json.loads((tmp_path / "looks.json").read_text())


def test_delete_refuses_paths_outside_the_folder(tmp_path):
    outside = tmp_path.parent / "precious.mp4"
    outside.write_bytes(b"keep me")
    res = library.delete_video(str(tmp_path / "out"), "../precious.mp4")
    assert res["error"] == "outside the output folder" and outside.exists()


def test_delete_of_a_missing_file_is_not_an_error(tmp_path):
    assert library.delete_video(str(tmp_path), "gone.mp4")["error"] == "already gone"


# ---------- history ----------
def test_history_undo_redo_roundtrip():
    """push(snapshot) remembers a state; undo(current) hands back the state to restore."""
    h = library.History()
    a, b = {"v": 1}, {"v": 2}
    h.push(a, "gravity")             # a is the state before the edit that produced b
    assert h.undo(b) == a            # undo: back to a, keeping b for redo
    assert h.redo(a) == b            # redo: forward to b again
    assert h.undo({"v": 3}) == a     # and undo still works from a new state


def test_history_is_bounded():
    h = library.History(limit=3)
    for i in range(10):
        h.push({"v": i})
    assert h.status()["undo"] == 3


def test_history_collapses_identical_pushes():
    h = library.History()
    h.push({"v": 1})
    h.push({"v": 1})
    h.push({"v": 1})
    assert h.status()["undo"] == 1


def test_new_edit_clears_redo():
    h = library.History()
    h.push({"v": 1})
    h.undo({"v": 2})
    assert h.status()["redo"] == 1
    h.push({"v": 9})
    assert h.status()["redo"] == 0


def test_history_empty_is_safe():
    h = library.History()
    assert h.undo({}) is None and h.redo({}) is None
    assert h.status() == {"undo": 0, "redo": 0, "next": "", "redo_next": ""}


def test_history_labels_are_reported():
    h = library.History()
    h.push({"v": 1}, "gravity")
    assert h.status()["next"] == "gravity"
