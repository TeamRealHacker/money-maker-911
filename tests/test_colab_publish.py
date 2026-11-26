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
    """A fake `colab` executable that logs its calls, so no network is needed.
    Windows needs a .bat (shutil.which only finds PATHEXT extensions, and only
    cmd.exe can run batch files); everything else gets a #!/bin/sh script."""
    log = tmp_path / "calls.log"
    win = os.name == "nt"
    stub = tmp_path / "bin" / ("colab.bat" if win else "colab")
    stub.parent.mkdir()
    if win:
        body = "\r\n".join([
            "@echo off",
            f'>>"{log}" echo %*',
            'if /i "%~1"=="new" echo session created',
            'if /i "%~1"=="upload" echo uploaded',
            'if /i "%~1"=="exec" echo executed',
            'if /i "%~1"=="download" echo downloaded',
            'if /i "%~1"=="stop" echo stopped',
            'if /i "%~1"=="usage" echo compute units: 42.5',
            'if /i "%~1"=="config" echo project: test',
            "",
        ])
    else:
        body = (
            "#!/bin/sh\n"
            f'echo "$@" >> "{log}"\n'
            'case "$1" in new) echo "session created";; upload) echo uploaded;; exec) echo executed;;'
            ' download) echo downloaded;; stop) echo stopped;; usage) echo "compute units: 42.5";;'
            ' config) echo "project: test";; esac\n')
    stub.write_text(body, encoding="utf-8", newline="")
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


def test_cli_is_resolved_to_a_full_path(stub_colab):
    """The prefix must be the resolved path, not the bare name: on Windows a bare name only
    resolves through PATH for .exe, so a .bat/.cmd console script would never be launched."""
    prefix = colab.colab_cmd()
    assert prefix and prefix[0] == colab._resolve("colab")
    assert os.path.isabs(prefix[0]) and Path(prefix[0]).exists()


def test_windows_batch_cli_runs_through_cmd(monkeypatch):
    """.bat/.cmd wrappers can only be started by cmd.exe, so they get a `cmd /c` argv."""
    monkeypatch.setattr(colab, "_windows", lambda: True)
    argv = colab._argv([r"C:\tools\colab.bat"], ["colab", "usage"])
    assert argv == ["cmd", "/c", r"C:\tools\colab.bat", "usage"]


def test_posix_cli_runs_directly(monkeypatch, tmp_path):
    """On POSIX the resolved path replaces the bare program name, and no shell is involved."""
    monkeypatch.setattr(colab, "_windows", lambda: False)
    argv = colab._argv([str(tmp_path / "colab")], ["colab", "usage"])
    assert argv == [str(tmp_path / "colab"), "usage"]


def test_batch_is_found_even_without_pathext(monkeypatch, tmp_path):
    """A stripped PATHEXT makes shutil.which ignore .bat/.cmd (the Windows console script)."""
    d = tmp_path / "bin"
    d.mkdir()
    bat = d / "colab.bat"
    bat.write_text("@echo off\n", encoding="utf-8", newline="")
    bat.chmod(0o755)          # POSIX `which` also requires X_OK (Windows ignores it)
    monkeypatch.setattr(colab, "_windows", lambda: True)
    monkeypatch.setenv("PATH", str(d) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("PATHEXT", "")
    found = colab._resolve("colab")
    # Windows returns the on-disk casing (colab.BAT), so compare case-insensitively there
    assert found and (found == str(bat) or (os.name == "nt" and found.lower() == str(bat).lower()))


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


# ---------- one-click install / sign-in (the Windows path included) ----------
def test_status_guides_a_fresh_machine(monkeypatch):
    monkeypatch.setattr(colab, "colab_cmd", lambda: None)
    st = colab.status()
    ids = [s["id"] for s in st["steps"]]
    assert ids == ["wsl", "pipx", "cli", "login"]      # pipx, not system pip (PEP 668)
    assert st["manual"]["note"] and st["manual"]               # paste-able fallback always present
    assert st["can_install"] is True                            # a shell exists to run it with
    assert [g["id"] for g in st["gpus"]] == ["T4", "L4", "A100"]


def test_install_plan_shows_every_command_before_running(monkeypatch):
    plan = colab.install(dry_run=True)
    assert plan["dry_run"] is True and plan["steps"]
    assert all(s["cmd"] for s in plan["steps"])


def test_install_runs_the_steps_and_reports_them(monkeypatch, tmp_path):
    ran = []

    def fake_run(argv, **kw):
        ran.append(argv[-1])

        class R:
            returncode = 0
            stdout = "Successfully installed google-colab-cli"
            stderr = ""
        return R()

    monkeypatch.setattr(colab, "_runner", lambda: ["bash", "-lc"])
    monkeypatch.setattr(colab.subprocess, "run", fake_run)
    seen = []
    res = colab.install(on_step=lambda i, t, state, out: seen.append((i, state)))
    assert res["ok"] is True and res["needs_login"] is True
    assert [s for s in ran if "google-colab-cli" in s]
    assert seen[0] == (0, "start") and (0, "done") in seen       # live per-step status


def test_install_treats_already_installed_as_success(monkeypatch):
    class R:
        returncode = 1
        stdout = ""
        stderr = "pipx: 'google-colab-cli' is already installed"
    monkeypatch.setattr(colab, "_runner", lambda: ["bash", "-lc"])
    monkeypatch.setattr(colab.subprocess, "run", lambda *a, **k: R())
    assert colab.install()["ok"] is True


def test_install_reports_a_failure_with_manual_steps(monkeypatch):
    class R:
        returncode = 1
        stdout = ""
        stderr = "sudo: a password is required"
    monkeypatch.setattr(colab, "_runner", lambda: ["bash", "-lc"])
    monkeypatch.setattr(colab.subprocess, "run", lambda *a, **k: R())
    res = colab.install()
    assert res["ok"] is False and "step failed" in res["error"]
    assert "password" in res["steps"][0]["output"]      # the real reason is never hidden
    assert res["manual"]["note"]


def test_install_without_a_shell_says_so(monkeypatch):
    monkeypatch.setattr(colab, "_runner", lambda: None)
    res = colab.install()
    assert res["ok"] is False and "No shell" in res["error"]


def test_login_refuses_before_the_cli_exists(monkeypatch):
    monkeypatch.setattr(colab, "colab_cmd", lambda: None)
    res = colab.login_start()
    assert res["needs_install"] is True and res["manual"]


def test_login_picks_the_consent_url_out_of_the_cli_output(monkeypatch):
    import io

    class FakeProc:
        def __init__(self):
            self.stdout = io.StringIO("visit https://accounts.google.com/o/oauth2/auth?client=1 now\n")
            self._done = False

        def poll(self):
            return 0                          # the CLI exits once the consent page is printed
        
    monkeypatch.setattr(colab, "colab_cmd", lambda: ["/usr/bin/colab"])
    got = []
    res = colab.login_watch(FakeProc(), on_url=got.append)
    assert res["url"].startswith("https://accounts.google.com/")
    assert got == [res["url"]]


def test_find_url_ignores_plain_text():
    assert colab.find_url("no link here") == ""
    assert colab.find_url("see (https://colab.example/x).").startswith("https://colab.example/x")


def test_windows_install_goes_through_wsl(monkeypatch):
    monkeypatch.setattr(colab, "_windows", lambda: True)
    steps = colab.install_commands()
    assert steps[0]["cmd"].startswith("wsl --install")
    assert any("wsl -d Ubuntu" in s["cmd"] and "pipx" in s["cmd"] for s in steps)
    manual = colab.manual_commands()
    assert manual["powershell"][0].startswith("wsl --install")


def test_preflight_says_what_to_fix(monkeypatch):
    monkeypatch.setattr(colab, "colab_cmd", lambda: None)
    pf = colab.preflight("T4")
    assert pf["ok"] is False and pf["errors"] >= 1
    assert "Install" in pf["fix"]
    titles = [i["title"] for i in pf["items"]]
    assert "Colab CLI" in titles and "Render notebook" in titles


def test_preflight_is_green_when_everything_is_there(monkeypatch):
    monkeypatch.setattr(colab, "colab_cmd", lambda: ["/usr/bin/colab"])
    monkeypatch.setattr(colab, "check", lambda: {"cli": True, "wsl": True, "notebook": True,
                                                 "gpu": None, "ready": True, "needs_login": False,
                                                 "note": "ok", "version": "colab 0.5"})
    pf = colab.preflight("L4")
    assert pf["ok"] is True and pf["errors"] == 0
    assert "L4" in [i["detail"] for i in pf["items"]]


def test_render_uploads_with_the_real_cli_syntax(stub_colab, tmp_path):
    """The CLI takes `upload LOCAL REMOTE` and `download REMOTE LOCAL` (no --path flag), and only
    the videos from this run are reported back."""
    cfg = MergeConfig(mode="merge", max_seconds=2, fps=15, export_resolution="720p")
    out = tmp_path / "out"
    out.mkdir()
    (out / "older.mp4").write_bytes(b"old")            # an earlier render must not be reported
    res = colab.render_on_colab(cfg, str(out), gpu="T4", batch_count=0)
    calls = [c for c in stub_colab.read_text(encoding="utf-8").splitlines() if c.strip()]
    ups = [c for c in calls if c.startswith("upload")]
    downs = [c for c in calls if c.startswith("download")]
    assert ups and all("--path" not in c for c in ups)
    assert ups[0].split()[1] == "-s" and ups[0].split()[3].endswith("job.zip")
    assert downs and downs[0].split()[1] == "-s" and "--path" not in downs[0]
    assert res["videos"] == []
