---
spike: 001
name: latency-benchmark
validates: "Given 8 pre-recorded .opus files (4–52s real dictation), when transcribed N=5 times via Groq whisper-large-v3-turbo vs OpenAI whisper-1, then we can locate the dominant latency source and decide whether further pipeline optimization (parallel encoding, modular refactor) is worth the cost"
verdict: VALIDATED
related: []
tags: [latency, transcription, groq, openai, benchmark, throwaway]
---

# Spike 001: Latency Benchmark

## What This Validates

**Given** 8 pre-recorded `.opus` files in `~/life/state/govori-audio/` (real
user dictation, 4s–52s, OGG/Opus 16kHz mono — same format Govori sends to Whisper),

**when** each file is transcribed N=5 times through both Groq
(`whisper-large-v3-turbo`) and OpenAI (`whisper-1`) using the same
`language=ru`, `temperature=0`, and a trimmed `prompt`,

**then** we can answer:
1. What is the true p50/p95 API latency per provider?
2. Is Groq actually 5–10× faster for our payloads, as claimed in marketing?
3. Do transcripts diverge between providers (quality regression risk if we
   migrate / use fallback)?
4. Does API latency dominate the perceived 2s pause, or is encoding /
   paste / something else the real bottleneck?

Answers drive the scope of Phase 1 (Groq + OpenAI fallback + modular
refactor) and Phase 2 (parallel encoding during recording).

## How to Run

```bash
cd ~/Projects/govori
source .venv/bin/activate
python3 bench/latency_bench.py
```

Override iteration count for a quick check:

```bash
BENCH_ITER=2 python3 bench/latency_bench.py
```

The script reads `GROQ_API_KEY` and `OPENAI_API_KEY` from
`~/.config/govori/env` (same file Govori uses). Output is printed to stdout;
machine-readable results saved to `bench/results.json` (gitignored).

## What to Expect

- 8 files × 2 providers × 5 iterations = 80 API calls. Total run time
  ~2–4 minutes depending on network and longest file (52s).
- A per-file latency table (p50/p95/mean per provider).
- An aggregate table averaged across all files.
- A transcript divergence section: identical / differing per file.

**Concrete signals to watch:**

- If Groq p50 < 500ms and OpenAI p50 > 1500ms → API is the bottleneck;
  Phase 1 (Groq + fallback) gives the bulk of the 2s win.
- If both providers > 1000ms → network or local encoding is the real
  problem; need to instrument the live pipeline before Phase 2.
- If transcripts diverge significantly → fallback strategy needs UX
  consideration (which transcript wins on retry?).

## Results

Run: 2026-05-13, 5 iterations × 8 files × 2 providers = 80 API calls.
Network: home Wi-Fi (Алматы). Hardware: MacBook Pro M-series.

### Verdict
**VALIDATED** — benchmark cleanly answered all four questions.

### Aggregate latency (all files, all iterations)

| Provider | n | p50 | p95 | mean |
|----------|---|-----|-----|------|
| groq (whisper-large-v3-turbo) | 39 | **386 ms** | **705 ms** | **441 ms** |
| openai (whisper-1)            | 40 | 1476 ms    | 3416 ms    | 1704 ms     |

**Groq is ~3.8× faster on p50 and ~4.8× faster on p95.**

### Per-file (mean ms, sorted by duration)

| File         | Audio | Groq mean | OpenAI mean | Ratio |
|--------------|-------|-----------|-------------|-------|
| 193649_4s    | 4s    | 350       | 815         | 2.3×  |
| 120141_6s    | 6s    | 321       | 1168        | 3.6×  |
| 112748_7s    | 7s    | 328       | 1394        | 4.3×  |
| 040312_10s   | 10s   | 377       | 1229        | 3.3×  |
| 180526_22s   | 22s   | 485       | 1457        | 3.0×  |
| 112846_24s   | 24s   | 443       | 1940        | 4.4×  |
| 165437_25s   | 25s   | 502       | 2294        | 4.6×  |
| 171317_52s   | 52s   | 694       | 3337        | 4.8×  |

Groq latency grows **sub-linearly** with audio length (1.9× growth for 13× length).
OpenAI grows **almost linearly** (4× growth for 13× length).

### Transcript divergence

6/8 files (75%) produced different transcripts between providers. Differences are
mostly minor (case, declension, homophones — "Наде" vs "надо", "VPO" vs "ПО",
"Память" vs "Пометь"). Both providers occasionally win on specific words.
**Quality is comparable** — neither systematically better.

### Surprises

1. **OpenAI Whisper API rejects `.opus` extension** (HTTP 400 — invalid file format)
   even though `ogg`/`oga` is in the supported list. Fix: rename `buf.name` to
   `.ogg` before upload. govori.py already does this; the bench script initially
   didn't and burned the first run.
2. **Groq latency for short clips is remarkably flat** (~320–390ms regardless
   of file size from 4s to 22s). Looks like a fixed network/processing floor.
3. **OpenAI p95 reaches 3.4s on long files** — meaning some single API calls
   alone exceed the 2s pause budget. Migrating away from OpenAI is justified
   on tail latency alone.
4. **Groq throwing ~5% transient errors** in one run (1 missing iteration out
   of 40). Could be rate-limiting (free tier) or transient API issues — argues
   for OpenAI fallback as a reliability net, even though Groq is faster overall.

### Signal for the build

**Phase 1 (Groq + OpenAI fallback + modular refactor)** — still worth doing but
the *latency* angle is small. Groq is already used; the fallback is for
**reliability** (handle the ~5% transient errors), not raw speed. Refactor stands
on its own architectural merit.

**Phase 2 (parallel encoding during recording)** — **critical**. If Groq API
takes ~440ms but user perceives 2s, the missing ~1500ms is somewhere else:
- PyAV OGG/Opus encoding of multi-second audio (likely 200–800ms for long
  recordings — bench skips this since files are already OGG)
- TLS handshake / cold connection setup (no connection pooling visible in code)
- `_transcribe_with_auto_retries` thread spawn + busy-loop overhead
- HUD updates / clipboard restore / paste

Parallel encoding alone could save the entire encoding step from post-release
latency. **Phase 2 is the highest-ROI next move.**

**New diagnostic recommendation:** before Phase 2, add `time.perf_counter()`
instrumentation to the live `stop_and_transcribe → _encode_and_transcribe →
paste_text` chain. Bench measures API only; we need ground truth on the other
~1.5s. This should be Plan 1 of Phase 1 (or a quick task before phases start).

