# Spike Manifest

## Idea

Optimize Govori's post-release dictation latency (user reports ~2s pause
between releasing the fn key and text appearing at cursor). Investigate where
the latency actually lives before committing to a multi-phase implementation.

## Spikes

| # | Name | Validates | Verdict | Tags |
|---|------|-----------|---------|------|
| 001 | [latency-benchmark](001-latency-benchmark/README.md) | Groq vs OpenAI on 8 real .opus files — measures API latency and transcript divergence | ✓ VALIDATED | latency, transcription, groq, openai |
