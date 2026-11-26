"""☁️ Colab bridge + 📤 YouTube uploader: packing, notebook validity, command sequences,
metadata and scheduling - all offline (the google-colab-cli binary is stubbed)."""
import json
import os
import zipfile
from pathlib import Path

import pytest

from mm911 import colab, publish
from mm911.config import MergeConfig


@pytest.fixture()
def stub_colab(tmp_path, monkeypatch):
    """A fake `colab` executable that logs its calls, so no network is needed."""
    log = tmp_path / "calls.log"
    stub = tmp_path / "bin" / "colab"
    stub.parent.mkdir()
    stub.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'case "$1" in new) echo "session created";; upload) echo uploaded;; exec) echo executed;;'
        ' download) echo downloaded;; stop) echo stopped;; usage) echo "compute units: 42.5";;'
        ' config) echo "project: test";; esac\n')
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(stub.parent) + os.pathsep + os.environ.get("PATH", ""))
    return log


def test_check_shape_and_friendly_note(stub_colab):
    out = colab.check()
    assert out["cli"] is True and out["ready"] is True and out["notebook"] is True


def test_check_without_cli(monkeypatch):
    monkeypatch.setattr(colab, "colab_cmd", lambda: None)
    out = colab.check()
    assert out["cli"] is False and "google-colab-cli" in out["note"]


def test_quota_uses_the_cli(stub_colab):
    out = colab.quota()
    assert "compute units" in out.get("output", "")


def test_pack_job_rewrites_media_paths(tmp_path):
    img = tmp_path / "1.png"
    img.write_bytes(b"png")
    snd = tmp_path / "pop.mp3"
    snd.write_bytes(b"mp3")
    folder = tmp_path / "memes"
    folder.mkdir()
    (folder / "2.png").write_bytes(b"png2")
    cfg = MergeConfig(mode="merge", tier_images=[str(img)], sound_path=str(snd),
                      tier_image_folder=str(folder))
    out = tmp_path / "job.zip"
    info = colab.pack_job(cfg, str(out), batch_count=7)
    assert info["media"] >= 3
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "job/preset.json" in names and "job/job.json" in names
        assert "job/main.py" in names
        assert any(n.startswith("job/mm911/") for n in names)
        assert any(n.startswith("job/media/") for n in names)
        d = json.loads(z.read("job/preset.json"))
        job = json.loads(z.read("job/job.json"))
    assert job == {"action": "batch", "count": 7}
    assert d["sound_path"] == "media/pop.mp3"
    assert d["tier_images"][0] == "media/1.png"
    assert d["tier_image_folder"] == "media"


def test_notebook_is_valid_and_renders_a_job():
    nb = json.loads(colab.REPO_NOTEBOOK.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4 and nb["cells"]
    src = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    for needed in ("job.zip", "preset.json", "main.py", "output.zip"):
        assert needed in src


def test_render_on_colab_command_sequence(stub_colab, tmp_path):
    cfg = MergeConfig(mode="merge", max_seconds=2, fps=15, export_resolution="720p")
    out = colab.render_on_colab(cfg, str(tmp_path / "out"), gpu="L4", session="mm911", batch_count=2)
    calls = stub_colab.read_text(encoding="utf-8").splitlines()
    actions = [c.split()[0] for c in calls if c.strip()]
    assert actions[0] == "new" and actions[-1] == "stop"
    assert "upload" in actions and "exec" in actions and "download" in actions
    assert any("--gpu" in c and "L4" in c for c in calls)
    assert out["gpu"] == "L4"


# ---------- 📤 publish ----------
def test_read_titles_and_metadata(tmp_path):
    csvp = tmp_path / "titles.csv"
    csvp.write_text("file,title,description,hashtags\n"
                    "v1.mp4,My Merge,An epic run,#shorts #merge\n", encoding="utf-8")
    rows = publish.read_titles(str(csvp))
    meta = publish.video_metadata(rows[0])
    assert meta["title"] == "My Merge"
    assert "#shorts" in meta["description"] and "shorts" in [t.lower() for t in meta["tags"]]


def test_metadata_defaults_when_columns_missing():
    meta = publish.video_metadata({"file": "some_clip.mp4"})
    assert meta["title"] == "some_clip" and meta["description"]


def test_plan_schedule_spreads_and_is_iso():
    when = publish.plan_schedule(5, spread_days=2, times="09:00,18:00")
    assert len(when) == 5 and len(set(when)) == 5
    for t in when:
        assert t.endswith("Z") and "T" in t


def test_queue_plan_matches_files(tmp_path):
    (tmp_path / "v1.mp4").write_bytes(b"x")
    csvp = tmp_path / "titles.csv"
    csvp.write_text("file,title\nv1.mp4,Hello\nv2.mp4,Gone\n", encoding="utf-8")
    plan = publish.queue_plan(str(csvp), folder=str(tmp_path), spread_days=3)
    assert plan[0]["video"] == str(tmp_path / "v1.mp4")
    assert plan[0]["title"] == "Hello" and plan[0]["publish_at"]
    assert "v2" in plan[1]["video"]      # missing file still gets a (failing) plan entry


def test_upload_queue_dry_run(tmp_path, capsys):
    (tmp_path / "v1.mp4").write_bytes(b"x")
    plan = [{"video": str(tmp_path / "v1.mp4"), "title": "T", "description": "D", "tags": ["shorts"],
             "privacy": "public", "publish_at": "2027-01-01T09:00:00Z"}]
    out = publish.upload_queue(plan, dry_run=True)
    assert out[0]["dry"] is True and "dry" in capsys.readouterr().out.lower()


def test_check_api_reports_what_is_missing():
    out = publish.check_api()
    assert set(out) == {"deps", "client_secret", "token", "pip"}
