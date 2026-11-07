import time


def test_api_sound_and_preview_events(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    from mm911.gui import app
    api = app.Api()
    assert api.sound_sample("sound").startswith("data:audio/wav;base64,")
    assert api.sound_sample("demo").startswith("data:audio/wav;base64,")
    assert api.sound_sample("music") == ""          # no music set
    api.set_config({"fps": "30", "export_resolution": "8k", "audio_bitrate": "999", "export_codec": "x"})
    c = api._cfg
    assert (c.fps, c.export_resolution, c.audio_bitrate, c.export_codec) == (30, "1080p", 320, "h264")
    api.set_config({"speed": 3.0})
    api.preview(True)
    got, last, t0 = [], 0, time.time()
    while time.time() - t0 < 6 and not got:
        f = api.get_frame(last)
        if f:
            last = f["id"]
            got += f["snd"]
        time.sleep(0.05)
    api.preview(False)
    assert got and got[0][0] in ("drop", "merge", "final")
