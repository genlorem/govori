"""FastAPI relay server — receives audio from iPhone Shortcuts via Tailscale."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from loguru import logger

import govori.config as cfg
from govori.config import (
    CONFIG_FILE,  # noqa: F401
    PLUGINS_DIR,
    install_runtime_config,
    load_config,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger.remove()
logger.add(sys.stdout, level="INFO")
_log_file = Path.home() / ".config" / "govori" / "relay.log"
_log_file.parent.mkdir(parents=True, exist_ok=True)
logger.add(str(_log_file), rotation="10 MB", retention=5, level="DEBUG")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_uptime_start: float = 0.0
_bound_host: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_bind_host() -> str:
    env = os.environ.get("GOVORI_RELAY_HOST")
    if env:
        return env
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            ip = result.stdout.strip().splitlines()[0].strip()
            if ip:
                return ip
    except Exception:
        pass
    return "127.0.0.1"


def _decode_audio(file_bytes: bytes) -> tuple[np.ndarray, float]:
    """Decode any audio format → mono float32 numpy array at 16 kHz."""
    import av  # noqa: PLC0415

    try:
        container = av.open(BytesIO(file_bytes))
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        samples: list[np.ndarray] = []
        for frame in container.decode(audio=0):
            for resampled in resampler.resample(frame):
                arr = resampled.to_ndarray()  # shape (1, N) int16
                samples.append(arr.flatten().astype(np.float32) / 32768.0)
        # flush
        for resampled in resampler.resample(None):
            arr = resampled.to_ndarray()
            samples.append(arr.flatten().astype(np.float32) / 32768.0)
        if not samples:
            raise ValueError("No audio samples decoded")
        audio = np.concatenate(samples)
        duration_sec = len(audio) / 16000.0
        logger.debug("Decoded audio: samples={} dur={:.2f}s", len(audio), duration_sec)
        return audio, duration_sec
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "error": str(exc), "reason": "bad_format"},
        ) from exc


async def _extract_audio_bytes(request: Request) -> tuple[bytes, str]:
    """Get audio bytes from either multipart form-data or a raw request body.

    iPhone Shortcuts can POST audio two ways:
      - "Request Body = Form" → multipart, file in field `audio`
      - "Request Body = File" → raw bytes, no field name (simpler to wire,
        no magic-variable form item needed in the shortcut)
    Returns (bytes, source_label).
    """
    ctype = request.headers.get("content-type", "")
    logger.debug("_extract: content-type={!r} len-hdr={}", ctype, request.headers.get("content-length"))
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        logger.debug("_extract: multipart fields={}", list(form.keys()))
        upload = form.get("audio") or (next(iter(form.values()), None))
        if upload is None or isinstance(upload, str):
            raise HTTPException(
                status_code=400,
                detail={"ok": False, "error": f"no file in form (fields={list(form.keys())})", "reason": "bad_format"},
            )
        return await upload.read(), f"form:{getattr(upload, 'filename', '?')}"
    # Raw body (application/octet-stream, audio/*, or anything non-multipart)
    body = await request.body()
    logger.debug("_extract: raw body len={}", len(body))
    if not body:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "error": "empty request body", "reason": "bad_format"},
        )
    return body, f"raw:{ctype or 'no-ctype'}"


def _check_audio_quality(audio: np.ndarray, duration_sec: float) -> None:
    if duration_sec < 0.5:
        raise HTTPException(
            status_code=400,
            detail={
                "ok": False,
                "error": f"Audio too short: {duration_sec:.2f}s",
                "reason": "too_short",
            },
        )
    rms = float(np.sqrt(np.mean(audio**2)))
    if rms < 0.0001:
        raise HTTPException(
            status_code=400,
            detail={
                "ok": False,
                "error": f"Audio is silent: RMS={rms:.6f}",
                "reason": "too_short",
            },
        )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    global _uptime_start, _bound_host
    _uptime_start = time.monotonic()
    config = load_config()
    try:
        from govori.config import load_plugins  # noqa: PLC0415

        plugins = load_plugins()
    except (ImportError, AttributeError, TypeError):
        plugins = {}
    install_runtime_config(config, plugins)
    _bound_host = _resolve_bind_host()
    logger.info(
        "Relay started: model={} note_model={} lang={} base_url={}",
        config.model,
        config.note_model,
        config.language,
        config.base_url,
    )
    _warmup()
    yield


def _warmup() -> None:
    """Eliminate first-request cold start.

    The first real request used to pay ~2s extra: lazy imports (transcribe,
    notes→anthropic) loaded on demand, and PyAV's first decode/encode JIT-warmed
    its codecs. Pre-pay all of that at startup against a tiny synthetic clip so
    the user's first dictation is as fast as steady-state (~1s vs ~3.3s).
    """
    t0 = time.monotonic()
    try:
        # 1. Force the lazy imports the endpoints use
        import govori.notes  # noqa: F401,PLC0415
        import govori.transcribe  # noqa: F401,PLC0415
        from govori.notes import _is_hallucination  # noqa: PLC0415

        _is_hallucination("warmup")
        # 2. Warm PyAV: encode+decode a 0.1s silent mono clip (no network)
        silent = np.zeros(int(cfg.SAMPLE_RATE * 0.1), dtype=np.float32)
        buf = BytesIO()
        import av  # noqa: PLC0415

        container = av.open(buf, mode="w", format="ogg")
        stream = container.add_stream("libopus", rate=cfg.SAMPLE_RATE, layout="mono")
        frame = av.AudioFrame.from_ndarray(
            (silent * 32767).astype("int16").reshape(1, -1), format="s16", layout="mono"
        )
        frame.rate = cfg.SAMPLE_RATE
        for pkt in stream.encode(frame):
            container.mux(pkt)
        for pkt in stream.encode(None):
            container.mux(pkt)
        container.close()
        buf.seek(0)
        _decode_audio(buf.read())
        logger.info("Warmup done in {:.0f}ms", (time.monotonic() - t0) * 1000)
    except Exception as exc:  # never block startup on warmup
        logger.warning("Warmup skipped ({})", exc)


app = FastAPI(title="govori-relay", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> JSONResponse:
    try:
        import importlib.metadata as _meta  # noqa: PLC0415

        version = _meta.version("govori")
    except Exception:
        version = "dev"
    return JSONResponse(
        {
            "ok": True,
            "version": version,
            "uptime_s": round(time.monotonic() - _uptime_start, 2),
            "tailscale_ip": _bound_host,
        }
    )


@app.post("/dict-test")
async def dict_test_endpoint(request: Request) -> JSONResponse:
    """Test endpoint: returns a fixed canned transcript without touching audio.

    Used to verify the iPhone Shortcut UX end-to-end (Record → POST → Clipboard
    → Notification) when the user can't speak or wants to validate pipeline
    plumbing without burning Groq calls. Accepts any body (form or raw) and
    never reads it.
    """
    canned = (
        "Тестовая транскрипция Govori. Если ты видишь этот текст в буфере "
        "обмена и в нотификации — значит pipeline iPhone→Tailscale→VPS→Shortcut "
        "работает целиком."
    )
    logger.info("/dict-test -> canned response")
    if request.query_params.get("text"):
        return PlainTextResponse(canned)
    return JSONResponse({"ok": True, "text": canned, "duration_sec": 0.0, "test": True})


@app.post("/dict")
async def dict_endpoint(request: Request) -> JSONResponse:
    t0 = time.monotonic()
    file_bytes, src = await _extract_audio_bytes(request)
    logger.debug("/dict received {} bytes source={}", len(file_bytes), src)

    arr, duration = _decode_audio(file_bytes)
    _check_audio_quality(arr, duration)

    # Lazy imports so tests can mock them via sys.modules
    from govori.state import PERMANENT_API_ERROR  # noqa: PLC0415
    from govori.transcribe import transcribe_with_fallback  # noqa: PLC0415

    text = transcribe_with_fallback(arr, duration)
    if text is PERMANENT_API_ERROR or text is None:
        logger.error("/dict transcribe_failed")
        raise HTTPException(
            status_code=500,
            detail={
                "ok": False,
                "error": "Transcription failed",
                "reason": "transcribe_failed",
            },
        )

    from govori.notes import _is_hallucination  # noqa: PLC0415

    if not text or not text.strip() or _is_hallucination(text):
        raise HTTPException(
            status_code=400,
            detail={
                "ok": False,
                "error": "Hallucination or empty result",
                "reason": "hallucination",
            },
        )

    # Layer 1: glossary post-correction. Default = instant deterministic map
    # (zero added latency). ?ai=1 also runs the Haiku long-tail pass (~+1s).
    from govori.correct import correct_transcript  # noqa: PLC0415

    use_ai = bool(request.query_params.get("ai"))
    text, _edits = correct_transcript(text, source="dict", use_ai=use_ai)

    latency = (time.monotonic() - t0) * 1000
    logger.info(
        "/dict size={}B dur={:.2f}s latency={:.0f}ms -> ok",
        len(file_bytes),
        duration,
        latency,
    )
    # iPhone Shortcuts use ?text=1 → plain text, so the response itself IS the
    # transcript and auto-chains straight into Set Clipboard (no JSON parsing,
    # no magic-variable key extraction needed).
    if request.query_params.get("text"):
        return PlainTextResponse(text)
    return JSONResponse({"ok": True, "text": text, "duration_sec": round(duration, 2)})


@app.post("/note")
async def note_endpoint(request: Request) -> JSONResponse:
    t0 = time.monotonic()
    file_bytes, src = await _extract_audio_bytes(request)
    logger.debug("/note received {} bytes source={}", len(file_bytes), src)

    arr, duration = _decode_audio(file_bytes)
    _check_audio_quality(arr, duration)

    from govori.state import PERMANENT_API_ERROR  # noqa: PLC0415
    from govori.transcribe import transcribe_with_fallback  # noqa: PLC0415

    note_model = getattr(cfg.CONFIG, "note_model", None)
    text = transcribe_with_fallback(arr, duration, model_override=note_model)
    if text is PERMANENT_API_ERROR or text is None:
        logger.error("/note transcribe_failed")
        raise HTTPException(
            status_code=500,
            detail={
                "ok": False,
                "error": "Transcription failed",
                "reason": "transcribe_failed",
            },
        )

    from govori.notes import _is_hallucination, save_or_merge_note  # noqa: PLC0415

    if not text or not text.strip() or _is_hallucination(text):
        raise HTTPException(
            status_code=400,
            detail={
                "ok": False,
                "error": "Hallucination or empty result",
                "reason": "hallucination",
            },
        )

    # Layer 1: glossary post-correction before classify+save. Notes run in the
    # background, so always use the full Haiku pass (latency is not user-facing).
    from govori.correct import correct_transcript  # noqa: PLC0415

    text, _edits = correct_transcript(text, source="note", use_ai=True)

    try:
        result = save_or_merge_note(text, duration)
    except Exception as exc:
        logger.exception("/note save_failed: {}", exc)
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "error": str(exc), "reason": "save_failed"},
        ) from exc

    if not result:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "error": "save_or_merge_note returned None", "reason": "save_failed"},
        )

    meta = result.get("meta") or {}
    contexts = meta.get("contexts") or []
    context = contexts[0] if contexts else "default"
    latency = (time.monotonic() - t0) * 1000
    logger.info(
        "/note size={}B dur={:.2f}s latency={:.0f}ms -> {} ctx={}",
        len(file_bytes),
        duration,
        latency,
        result.get("action", "saved"),
        context,
    )
    if request.query_params.get("text"):
        action_ru = "объединено" if result.get("action") == "merged" else "сохранено"
        return PlainTextResponse(f"[{context}] {action_ru}: {text}")
    return JSONResponse(
        {
            "ok": True,
            "text": text,
            "saved_to": result.get("path", ""),
            "action": result.get("action", "saved"),
            "note_id": result.get("note_id", ""),
            "context": context,
            "contexts": contexts,
            "type": meta.get("type"),
            "urgency": meta.get("urgency"),
            "tags": meta.get("tags", []),
            "title": meta.get("title"),
            "duration_sec": round(duration, 2),
        }
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    import uvicorn  # noqa: PLC0415

    host = _resolve_bind_host()
    port = int(os.environ.get("GOVORI_RELAY_PORT", "8765"))
    uvicorn.run("govori.server:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
