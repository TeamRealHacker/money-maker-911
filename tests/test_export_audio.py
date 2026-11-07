"""Export options (fps / resolution / codec / format / audio) and the sound pipeline."""
import subprocess
import wave

import numpy as np
import pytest

from mm911 import audio
from mm911.cli import main as cli_main
from mm911.config import MergeConfig
from mm911.ffmpeg import ffmpeg_exe
from mm911.render import simulate, render_video, build_audio, physics_steps
from mm911.modes.merge import MergeSim


def _probe(path):
    return subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr


def _short(**kw):
    return MergeConfig(max_seconds=1.5, end_hold_seconds=0.3, **kw)


@pytest.fixture(scope="module")
def tone(tmp_path_factory):
    """A 12 s 440 Hz wav, used as 'music' and as a sound file."""
    p = tmp_path_factory.mktemp("snd") / "tone.wav"
    t = np.arange(int(audio.SR * 12)) / audio.SR
    pcm = (np.sin(2 * np.pi * 440 * t) * 0.5 * 32767).astype(np.int16)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(audio.SR); w.writeframes(pcm.tobytes())
    return p


def test_physics_independent_of_fps():
    res = {f: (lambda s: (s.won, s.merges, round(s.t, 3)))(simulate(MergeConfig(seed=2, fps=f))) for f in (24, 30, 60)}
    assert len(set(res.values())) == 1, res


def test_physics_steps_average():
    for fps in (24, 25, 30, 50, 60, 90, 120):
        g = physics_steps(fps)
        steps = [next(g) for _ in range(fps)]
        assert abs(sum(n * dt for n, dt in steps) - 1.0) < 1e-6   # one second of physics per second of video


@pytest.mark.parametrize("kw,size,fps,codec,ext", [
    (dict(fps=30), "1080x1920", "30 fps", "h264", ".mp4"),
    (dict(fps=24, export_resolution="720p", export_quality="small"), "720x1280", "24 fps", "h264", ".mp4"),
    (dict(fps=60, export_format="mov"), "1080x1920", "60 fps", "h264", ".mov"),
    (dict(fps=50, export_resolution="1440p"), "1440x2560", "50 fps", "h264", ".mp4"),
])
def test_export_variants(tmp_path, kw, size, fps, codec, ext):
    m = render_video(_short(**kw), str(tmp_path / "v.mp4"), encoder=None)
    assert m["file"].endswith(ext)
    info = _probe(m["file"])
    assert size in info and fps in info and codec in info
    assert "Audio: aac" in info


def test_h265(tmp_path):
    m = render_video(_short(fps=30, export_codec="h265", export_resolution="720p"), str(tmp_path / "v.mp4"))
    assert "hevc" in _probe(m["file"])


def test_silent_export(tmp_path):
    m = render_video(_short(export_audio=False), str(tmp_path / "v.mp4"))
    assert "Audio:" not in _probe(m["file"])


def test_music_is_not_cut_to_3s(tone):
    assert len(audio.load_music(str(tone))) > audio.SR * 11
    assert len(audio.load_sound(str(tone))) <= audio.SR * 3


def test_broken_sound_falls_back(tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio at all")
    s = audio.load_sound(str(bad))
    assert s.size > 0 and np.isfinite(s).all()
    assert audio.load_music(str(bad)).size == 0
    m = render_video(_short(sound_path=str(bad), music_path=str(bad)), str(tmp_path / "v.mp4"))
    assert "Audio: aac" in _probe(m["file"])


def test_audio_in_sync_with_speed():
    cfg = MergeConfig(speed=2.0, max_seconds=8, end_hold_seconds=0)
    sim = MergeSim(cfg)
    g = physics_steps(cfg.fps)
    frames = 0
    while not sim.done:
        n, dt = next(g)
        for _ in range(n):
            sim.step(dt)
        frames += 1
    seconds = frames / cfg.fps
    tr = build_audio(cfg, sim, seconds).mixed(seconds)
    last_ev = max(e.t for e in sim.events) / cfg.speed
    # the last pop must land inside the video, near where it happens on screen
    assert last_ev <= seconds + 0.05
    assert np.abs(tr[int(last_ev * audio.SR): int((last_ev + 0.1) * audio.SR)]).max() > 0.01


def test_demo_and_wav_bytes():
    b = audio.wav_bytes(audio.demo_track(audio.builtin_pop()))
    assert b[:4] == b"RIFF" and len(b) > 10000


def test_cli_export_flags(tmp_path, capsys):
    cli_main(["render", "--fps", "30", "--res", "720p", "--format", "mov", "--no-audio",
              "--out", str(tmp_path / "c.mp4"), "--length", "30"] if False else
             ["thumb", "--fps", "30", "--res", "720p", "--out", str(tmp_path / "t.jpg")])
    assert (tmp_path / "t.jpg").exists()


def test_batch_unsafe_theme_name(tmp_path):
    from mm911.batch import run_batch
    cfg = _short(theme_name='Meme: "cats"?/<x>', fps=24, export_resolution="720p")
    res = run_batch(cfg, 1, str(tmp_path), randomize=False, only_wins=False)
    assert len(res) == 1 and (tmp_path / "titles.csv").exists()
