"""Duplicate checker: identical / re-encoded videos are flagged, different seeds are not."""
import os
import subprocess
import tempfile

os.environ.setdefault("APPDATA", os.path.join(tempfile.gettempdir(), "mm911_test_appdata"))

from mm911 import dedupe  # noqa: E402
from mm911.batch import run_batch  # noqa: E402
from mm911.config import MergeConfig  # noqa: E402
from mm911.ffmpeg import ffmpeg_exe  # noqa: E402
from mm911.render import render_video  # noqa: E402

FAST = dict(max_seconds=5, fps=24, export_resolution="720p", export_audio=False, export_thumbnail=False,
            export_encoder="cpu", export_quality="small", near_miss=False)


def test_phash_similarity(tmp_path):
    a = render_video(MergeConfig(seed=1, **FAST), str(tmp_path / "a.mp4"))["file"]
    b = render_video(MergeConfig(seed=2, **FAST), str(tmp_path / "b.mp4"))["file"]
    c = str(tmp_path / "c.mp4")   # a re-encoded, slightly brighter, smaller copy of a
    subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-i", a, "-vf", "scale=540:-2,eq=brightness=0.03",
                    "-c:v", "libx264", "-crf", "30", c], check=True)
    sa, sb, sc = (dedupe.signature(p) for p in (a, b, c))
    assert len(sa) == dedupe.SAMPLES
    assert dedupe.similarity(sa, sa) == 1.0
    assert dedupe.similarity(sa, sc) >= dedupe.DEFAULT_THRESHOLD
    assert dedupe.similarity(sa, sb) < dedupe.DEFAULT_THRESHOLD
    pairs = dedupe.scan_folder(str(tmp_path))
    assert [(p["a"], p["b"]) for p in pairs] == [("a.mp4", "c.mp4")]


def test_batch_flags_duplicates(tmp_path):
    # the same settings + seed again = the same video: the second batch must flag it
    base = MergeConfig(seed=5, dedupe_action="flag", **FAST)
    first = run_batch(base, 1, str(tmp_path), randomize=False, only_wins=False)
    assert first[0]["similar_to"] == ""
    os.replace(first[0]["file"], tmp_path / "earlier.mp4")      # an older video in the folder
    book = dedupe.HashBook(tmp_path)
    book.add("earlier.mp4", dedupe.signature(str(tmp_path / "earlier.mp4")))
    second = run_batch(base, 1, str(tmp_path), randomize=False, only_wins=False)
    assert second[0]["similar_to"] == "earlier.mp4" and second[0]["similarity"] >= 0.99
