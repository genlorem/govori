# Testing Patterns

**Analysis Date:** 2026-04-15

## Test Framework

**Runner:** Not configured

No test framework, test runner, or test configuration file is present in the project. There are no `pytest.ini`, `setup.cfg`, `pyproject.toml`, `tox.ini`, `jest.config.*`, or equivalent files. No test files (`*.test.*`, `*.spec.*`, `test_*.py`, `*_test.py`) exist in the project root or any subdirectory.

**Run Commands:**
```bash
# No test commands defined
```

## Test File Organization

**Location:** None — no test files exist

**Naming:** N/A

## What Exists Instead

The codebase is a single-file macOS daemon (`govori.py`, 1912 lines). All logic is in one module with no separation between pure/testable logic and macOS-specific I/O. The following functions contain pure logic that could be unit tested without macOS APIs:

**Purely testable (no system I/O):**
- `_load_yaml(path)` — file parsing
- `_load_yaml_list(path)` — list extraction
- `load_config()` — config merging with defaults
- `build_whisper_prompt(config, plugins)` — string joining
- `build_notes_config(plugins)` — dict construction
- `_sanitize_slug(s, maxlen)` — string normalization
- `_validate_meta(data)` — dict coercion/validation
- `_is_hallucination(text)` — set membership check
- `_split_frontmatter(md)` — markdown parsing
- `_update_frontmatter_amended(fm_lines, timestamp)` — list mutation
- `_resolve_path(template, now)` — template substitution
- `_find_merge_candidates(contexts, hours)` — filtering logic

**Testable with mocking:**
- `classify_note(text)` — requires mocked `anthropic_client`
- `_decide_merge(new_text, candidates)` — requires mocked `anthropic_client`
- `save_as_note(text, duration_sec)` — requires mocked filesystem + `classify_note`
- `save_or_merge_note(text, duration_sec)` — orchestration function
- `_encode_and_transcribe(audio)` — requires mocked `client.audio.transcriptions`

**Untestable without macOS runtime:**
- `setup_hud()`, `set_hud()` — AppKit/NSPanel
- `paste_text()`, `_press_enter()` — Quartz CGEvent
- `install_monitor()` — CGEventTap
- `cg_event_callback()` — CGEvent handler
- `show_predict_menu()` — NSMenu

## Mocking

**Framework:** None established

If tests were added, the natural mocking targets would be:
```python
# Mock OpenAI client
from unittest.mock import MagicMock, patch

with patch("govori.client") as mock_client:
    mock_client.audio.transcriptions.create.return_value.text = "test text"
    result = _encode_and_transcribe(audio_array)

# Mock Anthropic client
with patch("govori._get_anthropic_client") as mock_get:
    mock_get.return_value = MagicMock()
    mock_get.return_value.messages.create.return_value.content[0].text = '{"title": "test"}'
    result = classify_note("some note text")
```

## Fixtures and Factories

**Test Data:** None defined

Example inputs for pure functions that could be tested immediately:
- `_sanitize_slug("Hello World!")` → `"hello-world"`
- `_is_hallucination("спасибо за просмотр")` → `True`
- `_split_frontmatter("---\nid: x\n---\nbody")` → `(["---","id: x","---"], "body")`
- `_validate_meta({"type": "invalid", "urgency": "invalid"})` → coerces to defaults

## Coverage

**Requirements:** None enforced

**View Coverage:** N/A

## Test Types

**Unit Tests:** Not present

**Integration Tests:** Not present

**E2E Tests:** Not present

## Adding Tests

If tests are introduced, recommended setup:

```bash
pip install pytest pytest-mock
```

Suggested `pytest.ini` or `pyproject.toml` section:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

Test file placement: `tests/test_govori.py` co-located at project root.

**Key isolation challenge:** `govori.py` runs side-effecting code at module scope (config loading, `cli_main()` execution, OpenAI client construction, env var check with `sys.exit`). To test individual functions, either:
1. Extract pure functions into a separate `govori_core.py` module
2. Mock `sys.argv`, `os.environ`, and `OpenAI` before importing
3. Import individual functions after patching the module-level exit paths

---

*Testing analysis: 2026-04-15*
