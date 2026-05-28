# Govori Test Suite

## Non-browser tests (unit + integration)

```bash
cd /Users/genlorem/Projects/govori
.venv/bin/python -m pytest tests/ --ignore=tests/web -v
```

All external API calls (Anthropic, Groq/Whisper) are mocked. No real credentials needed.
Real `~/.config/govori/` files are **never touched** — tests use `tmp_path`.

## Browser (Playwright) tests

Install Chromium first (one-time):

```bash
.venv/bin/playwright install chromium
```

Then run:

```bash
.venv/bin/python -m pytest tests/web -v
```

Playwright tests are skipped automatically if `playwright` is not installed.

## Individual test files

| File | What it tests |
|------|---------------|
| `test_tokens.py` | Per-device licensing: issue, check, revoke, rebind, register, revoke_by_subscription |
| `test_auth.py` | `_auth` middleware: master vs customer tokens, open paths, 401/403 codes |
| `test_correct.py` | Deterministic glossary replacement, stem/word-exact modes, no-false-positives |
| `test_lemonsqueezy.py` | HMAC signature verification, webhook event dispatch, `/lemonsqueezy/webhook` endpoint |
| `test_endpoints.py` | All FastAPI endpoints via TestClient with mocked transcription |
| `test_audio.py` | `_decode_audio` (garbage → exception, valid WAV), `_check_audio_quality` (silence/short) |
| `test_review.py` | `pending_edits`, `dictionary_entries`, `accept_correction`, `remove_correction`, `mark_reviewed` |
| `web/test_review_page.py` | Playwright: /review page loads, auth gating, /review/data 401 |
| `web/test_setup_page.py` | Playwright: /setup page loads, key displayed, install button present |

## Markers

- `@pytest.mark.live` — requires real external APIs (Groq, Anthropic, govori.io). Skipped by default.
  Run with: `pytest -m live`

## Notes

- PyAV is required for `test_decode_valid_wav` in `test_audio.py`. If not installed, that test is skipped.
- `soundfile` is not required — WAV synthesis uses stdlib `wave`.
