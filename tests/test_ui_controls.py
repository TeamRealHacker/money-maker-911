"""Drives EVERY control of the real page in headless Chromium (mocked pywebview API), in every mode:
no JS errors, every changed setting is sent to Python, buttons never throw, the progress bar stays hidden."""
import pytest

import json

from test_onboarding_ui import WEB, WAV
from mm911.config import MergeConfig, PALETTES, SHAPES, HOOKS, LENGTH_PRESETS, EMOJI_SETS

pw = pytest.importorskip("playwright.sync_api")



def _mock(onboarded=True):
    """A pywebview API stand-in that answers every method with the shape the real one returns."""
    b = {"app": "x", "credit": "x", "version": "t", "config": MergeConfig().to_dict(), "palettes": PALETTES,
         "shapes": SHAPES, "hooks": HOOKS, "lengths": LENGTH_PRESETS, "emoji_sets": EMOJI_SETS, "themes": [],
         "onboarded": onboarded, "output_dir": "C:/out", "min_tiers": 3, "max_tiers": 15,
         "export": {"fps": [24, 30, 60], "resolutions": ["720p", "1080p"], "qualities": ["high"], "codecs": ["h264"],
                    "encoders": ["auto"], "formats": ["mp4"], "audio_bitrates": [192]},
         "bg_modes": ["palette", "solid", "gradient", "image", "video"], "size_curves": ["exponential", "linear", "custom"],
         "particle_styles": ["sparks", "confetti"], "sound_strategies": ["pitch_up"], "keywords": ["pop"],
         "random_knobs": {"palette": "Palette"}, "cutout": {"onnx": False, "models": []}}
    js = """window.__calls=[];const B=%s;const DEF=JSON.parse(JSON.stringify(B.config));
    const rows=()=>Array.from({length:B.config.tiers},(_,i)=>({i,png:"",name:"",color:"#ff0000",emoji:"",image:""}));
    const obj=()=>({error:"",config:B.config,results:[],sounds:[],rows:[],picked:[]});
    window.pywebview={api:new Proxy({},{get:(t,k)=>async(...a)=>{__calls.push([k,a]);
      if(k==="bootstrap")return B;
      if(k==="set_config"){Object.assign(B.config,a[0]);return B.config}
      if(k==="reset_config"||k==="load_theme"){Object.assign(B.config,DEF);return B.config}
      if(["tier_previews","pick_tier_image","clear_tier_image","pick_image_folder","set_tier","apply_emoji_set","clear_tiers"].includes(k))return rows();
      if(["pick_images","sound_rows","set_sound_pitch","list_themes","save_theme","delete_theme"].includes(k))return [];
      if(["pick_file","pick_folder","export_theme","save_thumbnail","preview_sound"].includes(k))return "";
      if(["import_theme","sound_auto_fill","sound_use","pick_sound_for","clear_sound","sound_search"].includes(k))return obj();
      if(k==="prep_status")return {busy:false,note:""}; if(k==="prepare_images")return {images:0,skipped:[],cut:0,errors:[],status:{}};
      if(k==="finish_onboarding"){B.onboarded=true;return true}
      if(k==="sound_sample")return a[0]==="music"&&!B.config.music_path?"":"WAV_PLACEHOLDER";
      if(k==="get_frame")return null; return true}})};""" % json.dumps(b)
    return js.replace("WAV_PLACEHOLDER", WAV)


MODES = ["merge", "escape", "breaker", "glass"]

POKE = """() => {
  const sent = [];
  document.querySelectorAll('[data-k]').forEach((el) => {
    if (el.closest('[hidden]') || el.offsetParent === null && el.type !== 'range') return;
    const ev = (n) => el.dispatchEvent(new Event(n, {bubbles: true}));
    const both = () => { ev('input'); ev('change'); };
    if (el.type === 'checkbox') { el.checked = !el.checked; both(); }
    else if (el.type === 'range') { const lo = +el.min, hi = +el.max; el.value = lo + (hi - lo) * 0.4; ev('input'); ev('change'); }
    else if (el.type === 'color') { el.value = '#3366cc'; ev('input'); ev('change'); }
    else if (el.tagName === 'SELECT') { el.selectedIndex = el.options.length - 1; both(); }
    else if (el.type === 'number') { el.value = el.min ? el.min : 5; ev('input'); ev('change'); }
    else { el.value = 'x'; ev('input'); ev('change'); }
    sent.push(el.dataset.k);
  });
  return sent;
}"""


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception as e:  # pragma: no cover
            pytest.skip(f"chromium unavailable: {e}")
        yield br
        br.close()


@pytest.mark.parametrize("mode", MODES)
def test_every_control_in_every_mode(browser, mode):
    pg = browser.new_page(viewport={"width": 1360, "height": 860})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.add_init_script(_mock(True))
    pg.goto(WEB.as_uri())
    pg.wait_for_timeout(500)
    pg.click(f"#modes a[data-mode={mode}]")
    pg.wait_for_timeout(300)
    # open every section so its controls are laid out
    pg.evaluate("document.querySelectorAll('details').forEach(d => { if (!d.hidden) d.open = true; })")
    keys = pg.evaluate(POKE)
    pg.wait_for_timeout(700)               # debounce
    sent = set()
    for c in pg.evaluate("__calls"):
        if c[0] == "set_config":
            sent.update(c[1][0].keys())
    assert keys, "no controls found"
    missing = [k for k in set(keys) if k not in sent and k not in ("tier_image_folder",)]
    assert not missing, f"controls that never reached Python in {mode}: {missing}"
    assert not pg.is_visible("#prog")
    assert errs == []
    pg.close()


def test_every_button_click_is_safe(browser):
    pg = browser.new_page(viewport={"width": 1360, "height": 860})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.add_init_script(_mock(True))
    pg.goto(WEB.as_uri())
    pg.wait_for_timeout(500)
    pg.evaluate("document.querySelectorAll('details').forEach(d => { d.open = true; })")
    n = pg.evaluate("document.querySelectorAll('button').length")
    for i in range(n):
        pg.evaluate("(i) => { const b = document.querySelectorAll('button')[i]; if (b && !b.closest('[hidden]')) b.click(); }", i)
    pg.wait_for_timeout(600)
    assert errs == [], errs
    assert pg.is_visible("body")
    pg.close()
