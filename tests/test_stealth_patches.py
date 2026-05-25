"""Tests for stealth patches — validates anti-detection properties."""
import pytest
from playwright.sync_api import sync_playwright
from tools.screenshot_runner.stealth.loader import load_stealth_script


@pytest.fixture(scope="module")
def browser_context():
    """Shared Playwright browser for all stealth tests."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        ctx.add_init_script(load_stealth_script(session_seed=1234))
        yield ctx
        browser.close()


def test_webdriver_undefined(browser_context):
    """navigator.webdriver must be undefined after patching."""
    page = browser_context.new_page()
    result = page.evaluate("navigator.webdriver")
    assert result is None, f"Expected undefined, got {result}"
    page.close()


def test_chrome_runtime_present(browser_context):
    """window.chrome.runtime must exist."""
    page = browser_context.new_page()
    result = page.evaluate(
        "typeof window.chrome !== 'undefined' && typeof window.chrome.runtime !== 'undefined'"
    )
    assert result is True
    page.close()


def test_plugins_not_empty(browser_context):
    """navigator.plugins must have at least 1 entry."""
    page = browser_context.new_page()
    count = page.evaluate("navigator.plugins.length")
    assert count >= 1, f"Expected plugins, got {count}"
    page.close()


def test_languages_set(browser_context):
    """navigator.languages must be a non-empty array."""
    page = browser_context.new_page()
    langs = page.evaluate("navigator.languages")
    assert isinstance(langs, list) and len(langs) > 0
    page.close()


@pytest.mark.xfail(strict=False, reason="Canvas API limited in headless environments")
def test_canvas_noise_applied(browser_context):
    """Two sessions with different seeds must produce different canvas fingerprints."""
    page1 = browser_context.new_page()
    fp1 = page1.evaluate("""() => {
        const c = document.createElement('canvas');
        c.width = 200; c.height = 50;
        const ctx = c.getContext('2d');
        ctx.fillText('chimera test', 10, 25);
        return c.toDataURL();
    }""")
    page1.close()

    with sync_playwright() as p:
        b2 = p.chromium.launch(headless=True)
        ctx2 = b2.new_context()
        from tools.screenshot_runner.stealth.loader import load_stealth_script
        ctx2.add_init_script(load_stealth_script(session_seed=9999))
        page2 = ctx2.new_page()
        fp2 = page2.evaluate("""() => {
            const c = document.createElement('canvas');
            c.width = 200; c.height = 50;
            const ctx = c.getContext('2d');
            ctx.fillText('chimera test', 10, 25);
            return c.toDataURL();
        }""")
        page2.close()
        b2.close()

    assert fp1 != fp2, "Canvas fingerprints should differ between sessions"


def test_webgl_vendor_patched(browser_context):
    """WebGL vendor should return Intel Inc. if WebGL is available."""
    page = browser_context.new_page()
    page.goto("about:blank")
    vendor = page.evaluate("""() => {
        const canvas = document.createElement('canvas');
        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
        if (!gl) return null;
        const ext = gl.getExtension('WEBGL_debug_renderer_info');
        if (!ext) return null;
        return gl.getParameter(ext.UNMASKED_VENDOR_WEBGL);
    }""")
    if vendor is not None:
        assert vendor == "Intel Inc.", f"Expected Intel Inc., got {vendor}"
    page.close()
