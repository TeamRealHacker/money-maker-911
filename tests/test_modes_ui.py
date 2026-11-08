"""Mode picker in the app: Escape / Breaker are selectable, their settings show, Merge-only rows hide."""
import pytest

from test_onboarding_ui import _mock, WEB

pw = pytest.importorskip("playwright.sync_api")


def test_mode_picker_switches_sections():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # pragma: no cover
            pytest.skip(f"chromium unavailable: {e}")
        pg = b.new_page(viewport={"width": 1360, "height": 860})
        pg.add_init_script(_mock(True))
        pg.goto(WEB.as_uri())
        pg.wait_for_timeout(600)
        assert pg.evaluate("document.querySelector('details[data-modes=escape]').hidden")
        for mode, title in (("escape", "Escape"), ("breaker", "Breaker"), ("glass", "Glass Rush"), ("merge", "Merge Evolution")):
            pg.click(f"#modes a[data-mode={mode}]")
            pg.wait_for_timeout(300)
            assert pg.evaluate("window.__calls.some(c => c[0]==='set_config' && c[1][0].mode==='%s')" % mode)
            assert pg.text_content("#modetitle") == title
            shown = pg.evaluate("[...document.querySelectorAll('details[data-modes]')].filter(d=>!d.hidden).map(d=>d.dataset.modes)")
            assert shown == ([] if mode == "merge" else [mode])
            hidden = pg.evaluate("document.querySelector('[data-k=container_shape]').closest('.row').hidden")
            assert hidden == (mode != "merge")
        # switching mode swaps the default hook, but never a hook the user wrote
        pg.click("#modes a[data-mode=glass]")
        pg.wait_for_timeout(200)
        assert pg.evaluate("document.querySelector('[data-k=hook]').value") == "Will the glass hold?"
        pg.fill("[data-k=hook]", "my own hook"); pg.dispatch_event("[data-k=hook]", "change")
        pg.click("#modes a[data-mode=breaker]")
        pg.wait_for_timeout(200)
        assert pg.evaluate("document.querySelector('[data-k=hook]').value") == "my own hook"
        b.close()
