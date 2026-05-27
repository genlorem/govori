#!/usr/bin/env python3
"""Throwaway benchmark — measures transcription latency for Groq vs OpenAI
on pre-recorded .opus files. Spike 001-latency-benchmark.

Run:
    python3 bench/latency_bench.py

Reads .opus files from ~/life/state/govori-audio/ and runs each through
both providers N times. Prints p50/p95 table + transcript divergence.
"""
import io
import json
import os
import statistics
import sys
import time
from pathlib import Path

from openai import OpenAI

AUDIO_DIR = Path.home() / "life" / "state" / "govori-audio"
N_ITERATIONS = 5
LANGUAGE = "ru"
WHISPER_PROMPT = (
    "Транскрипция русской речи с английскими терминами. "
    "Govori, Whisper, Groq, OpenAI, Anthropic, Claude, Marquiz, Travelmart, MCP, GSD."
)


def load_env():
    env_file = Path.home() / ".config" / "govori" / "env"
    if not env_file.exists():
        return
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:]
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


load_env()

PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": os.environ.get("GROQ_API_KEY"),
        "model": "whisper-large-v3-turbo",
    },
    "groq_full": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": os.environ.get("GROQ_API_KEY"),
        "model": "whisper-large-v3",
    },
    "openai": {
        "base_url": None,
        "api_key": os.environ.get("OPENAI_API_KEY"),
        "model": "whisper-1",
    },
}


def percentile(data, p):
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def transcribe_once(client, model, audio_bytes, filename):
    buf = io.BytesIO(audio_bytes)
    # OpenAI rejects .opus extension even though OGG/Opus container is supported;
    # rename to .ogg (the actual container format) for cross-provider compatibility.
    buf.name = filename.replace(".opus", ".ogg")
    t0 = time.perf_counter()
    result = client.with_options(timeout=60.0, max_retries=0).audio.transcriptions.create(
        model=model,
        file=buf,
        language=LANGUAGE,
        temperature=0,
        prompt=WHISPER_PROMPT,
    )
    elapsed = time.perf_counter() - t0
    return elapsed, result.text.strip()


def bench_file(file_path, providers, iterations):
    audio_bytes = file_path.read_bytes()
    try:
        duration = float(file_path.stem.split("_")[-1].rstrip("s"))
    except ValueError:
        duration = -1
    size_kb = len(audio_bytes) / 1024
    print(f"\n→ {file_path.name} ({duration:.0f}s, {size_kb:.1f}KB)")

    results = {}
    for name, cfg in providers.items():
        if not cfg["api_key"]:
            print(f"  [{name}] SKIP — no API key")
            continue
        kwargs = {"api_key": cfg["api_key"]}
        if cfg["base_url"]:
            kwargs["base_url"] = cfg["base_url"]
        client = OpenAI(**kwargs)

        latencies = []
        transcripts = []
        for i in range(iterations):
            try:
                t, text = transcribe_once(client, cfg["model"], audio_bytes, file_path.name)
                latencies.append(t)
                transcripts.append(text)
                print(f"  [{name}] iter {i+1}/{iterations}: {t*1000:6.0f}ms")
            except Exception as e:
                print(f"  [{name}] iter {i+1}: ERROR {type(e).__name__}: {e}")
                # Backoff briefly to avoid hammering on 429
                time.sleep(1.5)

        if latencies:
            results[name] = {
                "model": cfg["model"],
                "duration": duration,
                "size_kb": size_kb,
                "latencies": latencies,
                "p50_ms": percentile(latencies, 50) * 1000,
                "p95_ms": percentile(latencies, 95) * 1000,
                "mean_ms": statistics.mean(latencies) * 1000,
                "first_transcript": transcripts[0] if transcripts else "",
                "transcripts_match": len(set(transcripts)) == 1,
            }
    return results


def print_summary(all_results):
    print("\n" + "=" * 88)
    print("LATENCY PER FILE")
    print("=" * 88)
    print(f"{'File':<30} {'Dur':>5} {'Provider':<8} {'p50':>8} {'p95':>8} {'mean':>8}")
    print("-" * 88)
    for file_name, res in all_results.items():
        for prov, d in res.items():
            print(
                f"{file_name:<30} {d['duration']:>4.0f}s {prov:<8} "
                f"{d['p50_ms']:>6.0f}ms {d['p95_ms']:>6.0f}ms {d['mean_ms']:>6.0f}ms"
            )

    print("\n" + "=" * 88)
    print("AGGREGATE BY PROVIDER (all files, all iterations)")
    print("=" * 88)
    for prov in PROVIDERS:
        all_lat = [t for res in all_results.values() if prov in res for t in res[prov]["latencies"]]
        if not all_lat:
            continue
        p50 = percentile(all_lat, 50) * 1000
        p95 = percentile(all_lat, 95) * 1000
        mean = statistics.mean(all_lat) * 1000
        print(f"  {prov:<8} n={len(all_lat):>3}  p50={p50:>6.0f}ms  p95={p95:>6.0f}ms  mean={mean:>6.0f}ms")

    pairs = [
        ("groq", "groq_full", "turbo vs full (same provider)"),
        ("groq", "openai", "turbo vs whisper-1"),
        ("groq_full", "openai", "full vs whisper-1"),
    ]
    for a, b, label in pairs:
        print("\n" + "=" * 88)
        print(f"TRANSCRIPT DIVERGENCE — {label}, first iteration")
        print("=" * 88)
        diverges = 0
        compared = 0
        for file_name, res in all_results.items():
            if a in res and b in res:
                compared += 1
                ta = res[a]["first_transcript"]
                tb = res[b]["first_transcript"]
                if ta == tb:
                    print(f"  ✓ {file_name}: identical")
                else:
                    diverges += 1
                    print(f"  ✗ {file_name}: differ")
                    print(f"      {a:<10}: {ta[:140]}{'…' if len(ta) > 140 else ''}")
                    print(f"      {b:<10}: {tb[:140]}{'…' if len(tb) > 140 else ''}")
        print(f"\n  Total: {diverges} / {compared} files diverge")


def main():
    files = sorted(AUDIO_DIR.rglob("*.opus"))
    if not files:
        print(f"No .opus files in {AUDIO_DIR}", file=sys.stderr)
        sys.exit(1)

    iterations = int(os.environ.get("BENCH_ITER", N_ITERATIONS))
    print(f"Found {len(files)} files, running {iterations} iterations per provider")
    print(f"Providers: {list(PROVIDERS.keys())}")

    all_results = {}
    for f in files:
        all_results[f.name] = bench_file(f, PROVIDERS, iterations)

    print_summary(all_results)

    out_path = Path(__file__).parent / "results.json"
    compact = {}
    for fname, res in all_results.items():
        compact[fname] = {}
        for prov, d in res.items():
            compact[fname][prov] = {
                "model": d["model"],
                "duration": d["duration"],
                "size_kb": d["size_kb"],
                "latencies_ms": [round(l * 1000, 1) for l in d["latencies"]],
                "p50_ms": round(d["p50_ms"], 1),
                "p95_ms": round(d["p95_ms"], 1),
                "mean_ms": round(d["mean_ms"], 1),
                "transcripts_match": d["transcripts_match"],
                "first_transcript_preview": d["first_transcript"][:200],
            }
    out_path.write_text(json.dumps(compact, indent=2, ensure_ascii=False))
    print(f"\nResults saved → {out_path}")


if __name__ == "__main__":
    main()
