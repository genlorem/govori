"""Playwright tests for /review web page.

Skipped automatically if playwright is not installed.
Run: .venv/bin/playwright install chromium && pytest tests/web -v
"""
from __future__ import annotations

import pytest

# Skip entire module if playwright not installed
playwright_mod = pytest.importorskip("playwright", reason="playwright not installed")

from playwright.sync_api import sync_playwright  # noqa: E402


MASTER = "test-master-token-abc123"


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


def test_review_page_loads(page, live_server):
    """/review?token=<master> loads and contains expected content."""
    page.goto(f"{live_server}/review?token={MASTER}")
    content = page.content()
    assert any(
        kw in content.lower()
        for kw in ["ревью", "review", "словарь", "dictionary", "govori"]
    ), f"Expected review page content, got: {content[:500]}"


def test_review_page_has_dict_section(page, live_server):
    page.goto(f"{live_server}/review?token={MASTER}")
    content = page.content().lower()
    assert "словарь" in content or "dict" in content


def test_review_data_without_token(live_server):
    """/review/data without token → 401 (uses httpx, not browser)."""
    import httpx
    r = httpx.get(f"{live_server}/review/data", follow_redirects=False)
    assert r.status_code == 401


def test_setup_accessible(page, live_server):
    """/setup page loads without crashing."""
    resp = page.goto(f"{live_server}/setup?key=gv_test")
    assert resp.status < 500
