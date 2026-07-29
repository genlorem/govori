"""FastAPI relay server — receives audio from iPhone Shortcuts via Tailscale."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

import numpy as np
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
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
_INTENT_CACHE_TTL_SEC = 300.0
_intent_cache: dict[str, dict] = {}
_last_classification: dict[str, dict] = {}
_intent_cache_lock = threading.Lock()


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


def _container_duration_sec(data: bytes) -> float:
    """Read duration from any PyAV-readable container (OGG, WebM, MP4, etc.)."""
    try:
        import av  # noqa: PLC0415
        c = av.open(BytesIO(data))
        dur = float(c.duration) / 1_000_000 if c.duration and c.duration > 0 else 0.0
        c.close()
        return dur
    except Exception:
        return 0.0


def _is_preencoded(data: bytes) -> bool:
    """True if data is OGG/Opus or WebM/Opus — can be forwarded to Groq without re-encoding."""
    return data[:4] == b"OggS" or data[:4] == b"\x1a\x45\xdf\xa3"


def _preencoded_filename(data: bytes) -> str:
    """Return the appropriate filename for a pre-encoded audio buffer."""
    if data[:4] == b"OggS":
        return "audio.ogg"
    return "audio.webm"


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


def _evict_intent_cache_locked(now: float) -> None:
    expired = [token for token, item in _intent_cache.items()
               if now - item.get("timestamp", 0.0) > _INTENT_CACHE_TTL_SEC]
    for token in expired:
        _intent_cache.pop(token, None)


def _store_intent_cache(text: str, duration: float, meta: dict) -> str:
    token = uuid.uuid4().hex
    now = time.monotonic()
    with _intent_cache_lock:
        _evict_intent_cache_locked(now)
        _intent_cache[token] = {
            "timestamp": now,
            "text": text,
            "duration": duration,
            "meta": meta,
        }
    return token


def _get_intent_cache(token: str | None) -> dict | None:
    if not token:
        return None
    now = time.monotonic()
    with _intent_cache_lock:
        _evict_intent_cache_locked(now)
        item = _intent_cache.get(token)
        if item is None:
            return None
        if now - item.get("timestamp", 0.0) > _INTENT_CACHE_TTL_SEC:
            _intent_cache.pop(token, None)
            return None
        return dict(item)


def _store_last_classification(auth_token: str | None, text: str, duration: float, meta: dict) -> None:
    """Remember this device's most recent classify, keyed by its static auth token.

    Lets the execute call omit a per-request token: the shortcut sends only its
    static access token, and we resolve the last classification for it.
    """
    if not auth_token:
        return
    now = time.monotonic()
    with _intent_cache_lock:
        _last_classification[auth_token] = {
            "timestamp": now,
            "text": text,
            "duration": duration,
            "meta": meta,
        }


def _get_last_classification(auth_token: str | None) -> dict | None:
    if not auth_token:
        return None
    now = time.monotonic()
    with _intent_cache_lock:
        item = _last_classification.get(auth_token)
        if item is None:
            return None
        if now - item.get("timestamp", 0.0) > _INTENT_CACHE_TTL_SEC:
            _last_classification.pop(auth_token, None)
            return None
        return dict(item)


_INTENT_LINE_RU = {
    "note": ("📝", "Заметка"),
    "ask": ("🔍", "Вопрос"),
    "do": ("⚡", "Команда"),
}


def _intent_line(intent: str, summary: str | None) -> str:
    emoji, intent_ru = _INTENT_LINE_RU.get(intent, _INTENT_LINE_RU["note"])
    return f"{emoji} {intent_ru}: {summary or 'note'}"


def _normalize_intent(raw: str | None, cached_meta: dict) -> str | None:
    """Map a phone-menu choice to a canonical intent (note/ask/do).

    Accepts canonical codes, Russian menu labels (with optional emoji, e.g.
    "🔍 Вопрос"), and an "accept"/"принять"/empty value meaning "use the
    auto-detected intent". Returns None if unrecognised (→ caller 400s).
    """
    if not raw or not raw.strip():
        return cached_meta.get("intent") or "note"
    low = raw.strip().lower()
    if "принят" in low or low in ("accept", "✓"):
        return cached_meta.get("intent") or "note"
    if low in _INTENT_LINE_RU:
        return low
    if "вопрос" in low or "ask" in low:
        return "ask"
    if "команд" in low or "действ" in low or low == "do":
        return "do"
    if "заметк" in low or "note" in low:
        return "note"
    return None


async def _transcribe_correct_note_request(request: Request) -> tuple[str, float, int]:
    file_bytes, src = await _extract_audio_bytes(request)
    logger.debug("/note received {} bytes source={}", len(file_bytes), src)

    pre_encoded_buf: BytesIO | None = None
    if _is_preencoded(file_bytes):
        duration = _container_duration_sec(file_bytes)
        if duration >= 0.5:
            pre_encoded_buf = BytesIO(file_bytes)
            pre_encoded_buf.name = _preencoded_filename(file_bytes)
            arr = None
            logger.debug("/note preencoded-fast-path dur={:.2f}s", duration)
        else:
            arr, duration = _decode_audio(file_bytes)
            _check_audio_quality(arr, duration)
    else:
        arr, duration = _decode_audio(file_bytes)
        _check_audio_quality(arr, duration)

    from govori.state import PERMANENT_API_ERROR  # noqa: PLC0415
    from govori.transcribe import transcribe_with_fallback  # noqa: PLC0415

    note_model = getattr(cfg.CONFIG, "note_model", None)
    text = transcribe_with_fallback(arr, duration, model_override=note_model,
                                    pre_encoded=pre_encoded_buf)
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

    # Layer 1: glossary post-correction before classify+save. Notes run in the
    # background, so always use the full Haiku pass (latency is not user-facing).
    from govori.correct import correct_transcript  # noqa: PLC0415

    text, _edits = correct_transcript(text, source="note", use_ai=True)
    return text, duration, len(file_bytes)


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
# Auth — required only when GOVORI_TOKEN is set (i.e. exposed publicly via
# govori.io). On Tailscale-only deployments leave it unset and everything is
# open within the tailnet. /health is always open (for Traefik/uptime checks).
# Token accepted as header `X-Govori-Token` or query `?token=`.
# ---------------------------------------------------------------------------
_OPEN_PATHS = {"/", "/health", "/review/icon.png", "/lemonsqueezy/webhook", "/setup"}
# Owner pages — only the master token may reach them (customers can't).
_OWNER_PREFIXES = ("/review",)


@app.middleware("http")
async def _auth(request: Request, call_next):
    path = request.url.path
    if path in _OPEN_PATHS:
        return await call_next(request)

    master = os.environ.get("GOVORI_TOKEN")

    # In the two-stage note flow, ?token= is the short-lived intent-cache token,
    # not the relay auth token. The endpoint validates it and returns 410 if it
    # is missing or expired; stage=classify still goes through normal auth.
    if path == "/note" and request.query_params.get("stage") == "execute" and not request.headers.get("x-govori-token"):
        return await call_next(request)

    sent = request.headers.get("x-govori-token") or request.query_params.get("token")

    # No auth configured at all → open (Tailscale-only dev mode).
    if not master:
        return await call_next(request)

    # Master token = owner: full access, no device binding.
    if sent and sent == master:
        request.state.is_master = True
        return await call_next(request)

    # Otherwise treat as a customer token (per-device licensing).
    from govori.tokens import check  # noqa: PLC0415

    device_id = request.headers.get("x-device-id") or request.query_params.get("device")
    ok, reason = check(sent, device_id)
    if not ok:
        # 403 for device conflict (valid token, wrong device); 401 otherwise.
        code = 403 if reason in ("device_mismatch", "no_device_id") else 401
        return JSONResponse({"ok": False, "error": "unauthorized", "reason": reason}, status_code=code)
    # Customers may only dictate / take notes — not the owner review console.
    if any(path.startswith(p) for p in _OWNER_PREFIXES):
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)
    return await call_next(request)


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


@app.post("/lemonsqueezy/webhook")
async def lemonsqueezy_webhook(request: Request) -> JSONResponse:
    from govori import lemonsqueezy as ls  # noqa: PLC0415

    raw = await request.body()
    sig = request.headers.get("x-signature")
    if not ls.verify_signature(raw, sig):
        logger.warning("LS webhook: bad signature")
        return JSONResponse({"ok": False, "error": "bad signature"}, status_code=401)
    try:
        payload = json.loads(raw)
    except Exception as exc:
        logger.warning("LS webhook bad json: {} | len={} raw[:120]={!r}", exc, len(raw), raw[:120])
        return JSONResponse({"ok": False, "error": "bad json"}, status_code=400)
    return JSONResponse(ls.handle(payload))


@app.get("/", response_class=HTMLResponse)
async def landing_page() -> HTMLResponse:
    from govori.landing import render_landing  # noqa: PLC0415

    return HTMLResponse(render_landing())


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(key: str = "") -> HTMLResponse:
    from govori.onboarding_page import render_setup  # noqa: PLC0415

    return HTMLResponse(render_setup(key))


@app.get("/review", response_class=HTMLResponse)
async def review_page() -> HTMLResponse:
    from govori.review import render_page  # noqa: PLC0415

    return HTMLResponse(render_page())


@app.get("/review/icon.png")
async def review_icon():
    from fastapi.responses import Response  # noqa: PLC0415

    from govori.review import icon_bytes  # noqa: PLC0415

    return Response(content=icon_bytes(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=604800"})


@app.get("/review/data")
async def review_data() -> JSONResponse:
    from govori.review import pending_edits  # noqa: PLC0415

    return JSONResponse(pending_edits())


@app.get("/review/dict")
async def review_dict() -> JSONResponse:
    from govori.review import dictionary_entries  # noqa: PLC0415

    return JSONResponse(dictionary_entries())


@app.post("/review/action")
async def review_action(request: Request) -> JSONResponse:
    from govori.review import (  # noqa: PLC0415
        accept_correction,
        mark_reviewed,
        remove_correction,
    )

    body = await request.json()
    if body.get("remove"):
        remove_correction(body["remove"])
        return JSONResponse({"ok": True})
    added, reason = True, "added"
    if body.get("accept"):
        added, reason = accept_correction(body.get("from", ""), body.get("to", ""))
    mark_reviewed(body.get("ts", ""))
    return JSONResponse({"ok": True, "added": added, "reason": reason})


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


_TYPE_RU = {"idea": "идея", "commitment": "обязательство", "observation": "наблюдение",
            "todo": "дело", "decision": "решение", "question": "вопрос", "other": "прочее"}
_URGENCY_RU = {"low": "низкая", "medium": "средняя", "high": "высокая"}


def _category_line(context: str, meta: dict, *, saved: bool, merged: bool = False) -> str:
    """Human notification text focused on the CATEGORY, not the transcript."""
    type_ru = _TYPE_RU.get(meta.get("type", ""), meta.get("type", ""))
    urg_ru = _URGENCY_RU.get(meta.get("urgency", ""), meta.get("urgency", ""))
    ctxs = ", ".join(meta.get("contexts") or [context])
    tail = " · ".join(x for x in [type_ru, f"важность: {urg_ru}" if urg_ru else ""] if x)
    if not saved:  # preview
        head = f"→ {ctxs}"
    else:
        head = f"✓ {'объединено с' if merged else 'сохранено в'} {ctxs}"
    return f"{head}\n{tail}" if tail else head


def _learn_in_background(text: str) -> None:
    """Run the Haiku pass after the fast response is already sent.

    Fast /dict returns instantly (deterministic map only). This runs in the
    response background so the user pays no latency, yet Haiku still inspects
    the transcript for not-yet-learned term errors and logs them to the review
    queue — so the glossary keeps growing from everyday dictation.
    """
    try:
        from govori.correct import correct_transcript  # noqa: PLC0415

        correct_transcript(text, source="dict-bg", use_ai=True)
    except Exception as exc:  # never let background work surface
        logger.info("background learn skipped: {}", exc)


@app.post("/dict")
async def dict_endpoint(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    t0 = time.monotonic()
    file_bytes, src = await _extract_audio_bytes(request)
    logger.debug("/dict received {} bytes source={}", len(file_bytes), src)

    # Fast path: OGG/Opus or WebM/Opus received directly → skip decode+encode round-trip
    pre_encoded_buf: BytesIO | None = None
    if _is_preencoded(file_bytes):
        duration = _container_duration_sec(file_bytes)
        if duration >= 0.5:
            pre_encoded_buf = BytesIO(file_bytes)
            pre_encoded_buf.name = _preencoded_filename(file_bytes)
            arr = None
            logger.debug("/dict preencoded-fast-path dur={:.2f}s", duration)
        else:
            arr, duration = _decode_audio(file_bytes)
            _check_audio_quality(arr, duration)
    else:
        arr, duration = _decode_audio(file_bytes)
        _check_audio_quality(arr, duration)

    # Lazy imports so tests can mock them via sys.modules
    from govori.state import PERMANENT_API_ERROR  # noqa: PLC0415
    from govori.transcribe import transcribe_with_fallback  # noqa: PLC0415

    text = transcribe_with_fallback(arr, duration, pre_encoded=pre_encoded_buf)
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
    raw_text = text
    text, _edits = correct_transcript(text, source="dict", use_ai=use_ai)
    # Background learning only for the owner (master token): it costs an extra
    # Haiku call and logs the transcript — neither is acceptable for paying
    # customers. They get the curated map; the owner's usage grows it.
    is_master = getattr(request.state, "is_master", False)
    if not use_ai and is_master:
        background_tasks.add_task(_learn_in_background, raw_text)

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
    stage = request.query_params.get("stage")
    wants_text_stage = bool(request.query_params.get("text"))

    if stage == "classify":
        text, duration, size = await _transcribe_correct_note_request(request)
        from govori import intents  # noqa: PLC0415

        meta = intents.classify_intent(text)
        action = None
        session_message = None
        session_candidates: list[str] = []
        if meta.get("intent") == "do":
            action_info = intents.classify_do_action(text)
            action = action_info.get("action")
            session_message = action_info.get("message")
            session_candidates = action_info.get("candidates") or []
        meta["action"] = action
        meta["session_message"] = session_message
        meta["session_candidates"] = session_candidates
        token = _store_intent_cache(text, duration, meta)
        _store_last_classification(
            request.headers.get("x-govori-token") or request.query_params.get("token"),
            text, duration, meta,
        )
        intent = meta.get("intent", "note")
        summary = meta.get("summary") or meta.get("title") or "note"
        latency = (time.monotonic() - t0) * 1000
        logger.info(
            "/note stage=classify size={}B dur={:.2f}s latency={:.0f}ms -> intent={} target={} action={}",
            size,
            duration,
            latency,
            intent,
            meta.get("target"),
            action,
        )
        confidence = meta.get("confidence", "high")
        confirm = 0 if confidence == "high" else 1
        if action == "session_ask":
            # Side-effect action — menu is mandatory regardless of confidence,
            # and doubles as target picker (candidates list) + confirmation.
            confirm = 1
            line = f"Отправить «{session_message}»?" if session_message else "Отправить в сессию?"
        else:
            line = _intent_line(intent, summary)
        if wants_text_stage:
            # ?field=confirm → plain "1"/"0" for the shortcut's If gate (no JSON
            # parsing on the phone). Otherwise the human-readable category line.
            if request.query_params.get("field") == "confirm":
                return PlainTextResponse(str(confirm))
            return PlainTextResponse(line)
        return JSONResponse(
            {
                "ok": True,
                "stage": "classify",
                "token": token,
                "intent": intent,
                "target": meta.get("target"),
                "contexts": meta.get("contexts"),
                "note_kind": meta.get("type"),
                "urgency": meta.get("urgency"),
                "summary": summary,
                "title": meta.get("title"),
                "confidence": confidence,
                "confirm": confirm,
                "line": line,
                "action": action,
                "session_candidates": session_candidates,
            }
        )

    if stage == "execute":
        cached = _get_intent_cache(request.query_params.get("token"))
        if cached is None:
            cached = _get_last_classification(
                request.headers.get("x-govori-token") or request.query_params.get("token")
            )
        if cached is None:
            return JSONResponse({"ok": False, "reason": "token_expired"}, status_code=410)
        text = cached["text"]
        duration = cached["duration"]
        cached_meta = cached.get("meta") or {}
        intent = _normalize_intent(request.query_params.get("intent"), cached_meta)
        if intent not in _INTENT_LINE_RU:
            return JSONResponse({"ok": False, "reason": "bad_intent"}, status_code=400)

        from govori import intents  # noqa: PLC0415

        predicted_intent = cached_meta.get("intent")

        if intent == "note":
            from govori.notes import save_or_merge_note  # noqa: PLC0415

            try:
                result = save_or_merge_note(text, duration)
            except Exception as exc:
                logger.exception("/note stage=execute save_failed: {}", exc)
                raise HTTPException(
                    status_code=500,
                    detail={"ok": False, "error": str(exc), "reason": "save_failed"},
                ) from exc
            if not result:
                raise HTTPException(
                    status_code=500,
                    detail={"ok": False, "error": "save_or_merge_note returned None", "reason": "save_failed"},
                )
            result_meta = result.get("meta") or {}
            title = result_meta.get("title") or cached_meta.get("title") or "note"
            line = f"✓ сохранено: {title}"
            intents.log_intent_decision({
                "raw_text": text[:300], "predicted_intent": predicted_intent,
                "predicted_confidence": cached_meta.get("confidence"), "chosen_intent": "note",
            })
            if wants_text_stage:
                return PlainTextResponse(line)
            return JSONResponse({"ok": True, "stage": "execute", "intent": "note", "line": line})

        if intent == "ask":
            answer = intents.brain_answer(text)
            intents.log_intent_decision({
                "raw_text": text[:300], "predicted_intent": predicted_intent,
                "predicted_confidence": cached_meta.get("confidence"), "chosen_intent": "ask",
            })
            if wants_text_stage:
                return PlainTextResponse(answer)
            return JSONResponse({"ok": True, "stage": "execute", "intent": "ask", "answer": answer})

        # intent == "do"
        action = cached_meta.get("action")
        if action == "session_ask":
            candidates = cached_meta.get("session_candidates") or []
            message = cached_meta.get("session_message") or text
            session_choice = (request.query_params.get("session") or "").strip()
            cancelled = not session_choice or session_choice.lower() in ("отмена", "cancel", "❌ отмена", "❌")
            intents.log_intent_decision({
                "raw_text": text[:300], "predicted_intent": "do", "predicted_action": action,
                "predicted_target": candidates[0] if candidates else None,
                "predicted_confidence": cached_meta.get("confidence"),
                "chosen_intent": "do", "chosen_action": action,
                "chosen_target": None if cancelled else session_choice,
            })
            answer = "❌ отменено" if cancelled else intents.session_ask_execute(session_choice, message)
            if wants_text_stage:
                return PlainTextResponse(answer)
            return JSONResponse({"ok": True, "stage": "execute", "intent": "do", "action": action, "answer": answer})

        answer = intents.dispatch_command(text, cached_meta.get("target"))
        intents.log_intent_decision({
            "raw_text": text[:300], "predicted_intent": "do", "predicted_action": action,
            "predicted_confidence": cached_meta.get("confidence"), "chosen_intent": "do", "chosen_action": action,
        })
        if wants_text_stage:
            return PlainTextResponse(answer)
        return JSONResponse({"ok": True, "stage": "execute", "intent": "do", "answer": answer})

    if stage is not None:
        return JSONResponse({"ok": False, "reason": "bad_stage"}, status_code=400)

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

    # Preview mode (?preview=1): classify but DON'T save. Lets the shortcut show
    # an on-screen confirm ("→ marquiz · дело · высокая, сохранить?") before the
    # real save call. Returns the category, not the transcript.
    is_preview = bool(request.query_params.get("preview"))
    wants_text = bool(request.query_params.get("text"))

    if is_preview:
        from govori.notes import classify_note  # noqa: PLC0415

        meta = classify_note(text)
        contexts = meta.get("contexts") or []
        context = contexts[0] if contexts else "default"
        if wants_text:
            return PlainTextResponse(_category_line(context, meta, saved=False))
        return JSONResponse({"ok": True, "preview": True, "context": context,
                             "contexts": contexts, "type": meta.get("type"),
                             "urgency": meta.get("urgency"), "title": meta.get("title")})

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
    if wants_text:
        return PlainTextResponse(_category_line(context, meta, saved=True,
                                                merged=result.get("action") == "merged"))
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
