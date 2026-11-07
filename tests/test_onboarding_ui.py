"""Regression test for the 'onboarding stuck' bug: drives the real index.html/app.js in headless
Chromium with a mocked pywebview API. Skips if playwright isn't installed."""
import json
from pathlib import Path

import base64

import pytest

from mm911 import audio

from mm911.config import MergeConfig, PALETTES, SHAPES, HOOKS, LENGTH_PRESETS, EMOJI_SETS

pw = pytest.importorskip("playwright.sync_api")
WEB = Path(__file__).resolve().parent.parent / "mm911" / "gui" / "web" / "index.html"


WAV = "data:audio/wav;base64," + base64.b64encode(audio.wav_bytes(audio.builtin_pop())).decode()


def _mock(onboarded):
    b = {"app": "x", "credit": "x", "version": "t", "config": MergeConfig().to_dict(), "palettes": PALETTES,
         "shapes": SHAPES, "hooks": HOOKS, "lengths": LENGTH_PRESETS, "emoji_sets": EMOJI_SETS,
         "onboarded": onboarded, "output_dir": "C:/out", "min_tiers": 3, "max_tiers": 15}
    return ("""window.__calls=[];const B=%s;
    window.pywebview={api:new Proxy({},{get:(t,k)=>async(...a)=>{__calls.push([k,a]);
      if(k==="bootstrap")return B; if(k==="set_config"){Object.assign(B.config,a[0]);return B.config}
      if(k==="tier_previews")return Array.from({length:B.config.tiers},(_,i)=>({i,png:"",name:"",color:"#ff0000",emoji:"",image:""}));
      if(k==="finish_onboarding"){B.onboarded=true;return true} if(k==="sound_sample")return a[0]==="music"&&!B.config.music_path?"":"WAV_PLACEHOLDER"; if(k==="get_frame")return null; return true}})};""" % json.dumps(b)).replace("WAV_PLACEHOLDER", WAV)


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception as e:  # no browser binary on this machine
            pytest.skip(f"chromium unavailable: {e}")
        yield br
        br.close()


def _open(browser, onboarded):
    pg = browser.new_page(viewport={"width": 1360, "height": 860})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.add_init_script(_mock(onboarded))
    pg.goto(WEB.as_uri())
    pg.wait_for_timeout(400)
    return pg, errs


def test_onboarding_completes_and_closes(browser):
    pg, errs = _open(browser, False)
    assert pg.is_visible("#onboard")
    assert not pg.is_visible("#prog")
    pg.click("#obnext"); pg.click("#obnext")
    pg.click("#obforms button[data-n='6']")
    pg.click("#obnext")
    assert pg.inner_text("#obnext") == "Get started"
    pg.click("#obnext"); pg.wait_for_timeout(300)
    assert not pg.is_visible("#onboard"), "onboarding overlay must close"
    fin = [c for c in pg.evaluate("__calls") if c[0] == "finish_onboarding"]
    assert len(fin) == 1 and fin[0][1][0]["tiers"] == 6
    assert errs == []


def test_onboarding_not_shown_when_done(browser):
    pg, errs = _open(browser, True)
    assert not pg.is_visible("#onboard")
    assert errs == []


def test_export_and_sound_controls(browser):
    pg, errs = _open(browser, True)
    pg.click("summary:has-text('Export')") if not pg.is_visible("select[data-k=fps]") else None
    pg.select_option("select[data-k=fps]", "30")
    pg.select_option("select[data-k=export_resolution]", "4k")
    pg.select_option("select[data-k=export_codec]", "h265")
    pg.select_option("select[data-k=export_format]", "mov")
    pg.uncheck("input[data-k=export_audio]")
    pg.wait_for_timeout(200)
    sets = {}
    for c in pg.evaluate("__calls"):
        if c[0] == "set_config":
            sets.update(c[1][0])
    assert sets["fps"] == 30 and sets["export_resolution"] == "4k" and sets["export_codec"] == "h265"
    assert sets["export_format"] == "mov" and sets["export_audio"] is False
    assert "2160×3840 · 30 fps · H265 · MOV · no audio" in pg.inner_text("#exportsum")
    pg.click("#playdemo"); pg.wait_for_timeout(200)
    assert any(c[0] == "sound_sample" and c[1][0] == "demo" for c in pg.evaluate("__calls"))
    pg.click("button[title='Listen to the music']"); pg.wait_for_timeout(200)
    assert "Add a music file first" in pg.inner_text("body")
    assert not pg.is_visible("#prog")
    assert errs == []
