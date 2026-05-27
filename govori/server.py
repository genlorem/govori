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
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
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

        plugins = load_plugins(PLUGINS_DIR)
    except (ImportError, AttributeError):
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
    yield


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


@app.post("/dict")
async def dict_endpoint(audio: UploadFile = File(...)) -> JSONResponse:
    t0 = time.monotonic()
    file_bytes = await audio.read()
    logger.debug("/dict received {} bytes filename={}", len(file_bytes), audio.filename)

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

    latency = (time.monotonic() - t0) * 1000
    logger.info(
        "/dict size={}B dur={:.2f}s latency={:.0f}ms -> ok",
        len(file_bytes),
        duration,
        latency,
    )
    return JSONResponse({"ok": True, "text": text, "duration_sec": round(duration, 2)})


@app.post("/note")
async def note_endpoint(audio: UploadFile = File(...)) -> JSONResponse:
    t0 = time.monotonic()
    file_bytes = await audio.read()
    logger.debug("/note received {} bytes filename={}", len(file_bytes), audio.filename)

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

    try:
        meta = save_or_merge_note(text, duration)
    except Exception as exc:
        logger.exception("/note save_failed: {}", exc)
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "error": str(exc), "reason": "save_failed"},
        ) from exc

    contexts = meta.get("contexts") or []
    context = contexts[0] if contexts else "default"
    latency = (time.monotonic() - t0) * 1000
    logger.info(
        "/note size={}B dur={:.2f}s latency={:.0f}ms -> ok ctx={}",
        len(file_bytes),
        duration,
        latency,
        context,
    )
    return JSONResponse(
        {
            "ok": True,
            "text": text,
            "saved_to": meta.get("path"),
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
