"""Playwright tests for /setup onboarding page."""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright not installed")

from playwright.sync_api import sync_playwright  # noqa: E402


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        yield br
        br.close()


@pytest.fixture()
def page(browser):
    pg = browser.new_page()
    yield pg
    pg.close()


def test_setup_page_loads(page, live_server):
    resp = page.goto(f"{live_server}/setup?key=gv_test")
    assert resp.status >= 200 and resp.status < 500


def test_setup_shows_key(page, live_server):
    page.goto(f"{live_server}/setup?key=gv_test")
    content = page.content()
    assert "gv_test" in content, f"Key not found in page: {content[:500]}"


def test_setup_has_install_button(page, live_server):
    page.goto(f"{live_server}/setup?key=gv_test")
    content = page.content().lower()
    has_button = any(
        kw in content for kw in ["добавить", "govori", "install", "add", "open"]
    )
    assert has_button, f"No install button found in: {content[:500]}"
