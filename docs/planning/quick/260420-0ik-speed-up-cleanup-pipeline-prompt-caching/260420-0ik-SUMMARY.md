---
phase: 260420-0ik
plan: 01
subsystem: cleanup-pipeline
tags: [perf, cleanup, anthropic, prompt-caching]
type: quick
requirements:
  - QUICK-260420-0ik
dependency_graph:
  requires:
    - _load_cleanup_vocabulary (existing)
    - _get_anthropic_client (existing)
    - NOTES_CFG (existing)
  provides:
    - _WHISPER_CORRECTIONS (module-level constant, list of (compiled_regex, str))
    - _apply_whisper_corrections(text) -> str
    - clean_transcription control flow — regex fast-path + prompt caching
  affects:
    - fn→paste latency on short utterances (insta-paste path)
    - Haiku TTFT + input token cost on repeated cleanup calls within 5 min
tech_stack:
  added: []
  patterns:
    - Local regex fast-path before network call (skip Haiku when safe)
    - Anthropic ephemeral prompt caching via cache_control on system prompt
key_files:
  created: []
  modified:
    - govori.py (one new constant, one new helper, three edits in clean_transcription)
decisions:
  - Bypass raised <3 → <6 words; regex fast-path compensates for the missed 3-5 word range
  - <8 word threshold for regex-only short-circuit: balances confidence (regex is context-free
    and always correct) against the risk of missing a Haiku-only fix (БИОС→VPS, etc.)
  - Rebind `text = cleaned_local` before Haiku so length-delta sanity check operates on the
    post-regex baseline — preserves guardrail intent
  - Ephemeral cache_control (not persistent) — 5 min TTL matches typical dictation session
metrics:
  duration_minutes: 8
  completed_date: "2026-04-20"
  tasks_completed: 2
  files_changed: 1
  lines_added: 68
  lines_removed: 5
  commits: 1
---

# Phase 260420-0ik Plan 01: Speed Up Cleanup Pipeline + Prompt Caching Summary

Latency optimization of `clean_transcription()` via a local regex fast-path for known Whisper errors, Anthropic ephemeral prompt caching on the ~1500-token system prompt, and a raised short-utterance bypass — three independent wins, one atomic commit.

## What Changed

Single commit `49ce794` touches only `govori.py`. Two additions + three control-flow edits.

### 1. New module-level constant + helper (above `clean_transcription`)

- `_WHISPER_CORRECTIONS` — list of `(compiled_regex, replacement)` tuples for context-free substitutions:
  - `\bсофтра\b` → `завтра`
  - `\bMark\s*Visa\b`, `\bМарк\s*Виз\b`, `\bМаркиз\b` → `Marquiz`
  - `\bТр[ае]йл[\-\s]*Март(?:ом|а|у|е|ами|ах)?\b` → `Travelmart`
- `_apply_whisper_corrections(text)` — iterates the table, returns corrected text. Idempotent.

Compiled once at import time; `re` was already imported at line 21. No new dependency.

### 2. Three edits inside `clean_transcription()`

**Edit 1 — bypass raised from `<3` to `<6` words.** Docstring updated accordingly. Trades missed corrections on rare 3-5 word utterances for consistent sub-200ms latency; regex fast-path below still fires on longer utterances.

**Edit 2 — regex fast-path inserted after client guards.** Runs `_apply_whisper_corrections(text)`. If the regex pass changed the text AND `word_count < 8`, we skip Haiku entirely with a `[cleanup] regex-only:` log line. Otherwise we rebind `text = cleaned_local` so the downstream Haiku call sees the already-normalized input, and the 0.8–1.3 length-delta sanity check operates on the correct (post-regex) baseline.

**Edit 3 — Haiku `system` parameter switched to cache_control list form.** The ~1500-token system prompt is wrapped as:

```python
system=[
    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
]
```

System prompt string literal (lines 1748–1792) is byte-identical to pre-change; only its wrapping changes. Ephemeral cache has a 5-minute TTL — first call of a session still pays full price, subsequent calls within 5 min get −30–50% TTFT and −90% input token cost on cache hits.

## Observed Latency Improvement

No live dictation was run in this executor context (daemon requires Accessibility permission and an interactive macOS session). The three changes are expected to produce:

- **Short utterances (<6 words):** ~1.5s → <10ms. Entire Haiku roundtrip eliminated.
- **Known-error utterances (6–7 words, regex changes text):** ~1.5s → <20ms. Regex handles it; Haiku call skipped.
- **Longer utterances on repeat (within 5 min):** ~1.5s → ~0.7–1.0s TTFT. Prompt caching on system input.
- **First longer utterance of a session:** unchanged (no cache hit yet).

User can verify per plan's manual checks: dictate «софтра встреча» → no `[cleanup]` output; dictate «софтра встреча с Маркиз у Травел-Март» → `[cleanup] regex-only:` line; dictate a 10+ word sentence twice within 5 min and watch TTFT.

## Verification Results

All plan-level checks passed:

1. **Syntax:** `python3 -m py_compile govori.py` → exit 0
2. **Function surface:** `_apply_whisper_corrections` added; no functions removed (verified via `ast`)
3. **Regex sanity:** `«софтра встреча с Маркиз и Трейл-Мартом»` → `«завтра встреча с Marquiz и Travelmart»` (matches plan's expected output exactly)
4. **Idempotence:** running `_apply_whisper_corrections` twice produces identical output
5. **Helper unit tests (isolated exec of the new block):** empty string, case-insensitive, MarkVisa/Mark Visa/Марк Виз/Маркиз variants, Трайл-Март/Трейл-Мартом/Трейл Март all normalize correctly; unchanged text remains untouched
6. **Control flow greps inside `clean_transcription`:** `< 6` (bypass), `< 8` (regex short-skip), no remaining `< 3`
7. **`cache_control` grep:** exactly one hit, inside the `messages.create` call at line 1861
8. **Length-delta check preserved:** both `0.8` and `1.3` bounds still present
9. **No prompt drift:** `git diff` shows zero changes inside the system prompt f-string; only wrapping changed
10. **Single atomic commit:** `git log -1 --stat` shows `govori.py` as the only modified file

## Deviations from Plan

None — plan executed exactly as written.

## Notes

- Worktree base mismatch: this worktree (`worktree-agent-a6fc02ec`) was rooted at `ecebbeb`, not the plan's target base `077e298`. A reset was requested but denied by the sandbox. The plan's pre-state code (govori.py at 2966 lines with `clean_transcription` at line 1721, `<3 word` bypass, no `_apply_whisper_corrections`) was verified to match this worktree exactly before editing, so the plan applied cleanly. The commit is on this worktree's `main`; the orchestrator handles merging.
- No new imports needed (`re` already imported at line 21).
- No behavioral regression for longer utterances that still reach Haiku — the only change they see is `system` wrapped as a list (Anthropic SDK accepts both forms; cache is applied when the list form is used).

## Self-Check: PASSED

- FOUND: govori.py (modified)
- FOUND: commit 49ce794 (`git log --oneline -1` confirms `perf(cleanup): speed up clean_transcription...`)
- FOUND: `_apply_whisper_corrections` function in govori.py (via ast walk)
- FOUND: `_WHISPER_CORRECTIONS` constant (via grep, line ~1723)
- FOUND: `cache_control` exactly once in govori.py (line 1861)
- FOUND: `word_count < 6` and `word_count < 8` in `clean_transcription`; no `< 3` remaining
- FOUND: length-delta `0.8` and `1.3` bounds still in place
