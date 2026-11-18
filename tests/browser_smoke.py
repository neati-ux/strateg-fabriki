"""Local Chromium fixture only: no external network or model calls."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / '.browser-runtime')]
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.browser-runtime' / 'browsers')
from playwright.sync_api import sync_playwright
import ux_capture as ux

with sync_playwright() as engine, tempfile.TemporaryDirectory() as folder:
    browser = engine.chromium.launch(headless=True, timeout=15000)
    try:
        page = browser.new_page()
        html = '''<main><h1>Fixture</h1><button onclick='document.querySelector("h1").textContent="Changed"'>Open</button></main>'''
        page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=html))
        with patch.object(ux, 'validate_url'):
            result = ux.capture_steps(page, [{'action': 'goto', 'url': 'https://fixture.invalid/'},
                {'action': 'click', 'selector': 'button'}], Path(folder))
        assert len(result) == 2
        assert 'Changed' in (Path(folder) / 'content.md').read_text(encoding='utf-8')
        assert (Path(folder) / '02.png').stat().st_size > 100
        print('Chromium local fixture: 2 screens, DOM change, accessibility, PNG: OK')
    finally:
        browser.close()
