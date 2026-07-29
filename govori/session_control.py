"""HTTP client for session-manager (localhost:3007) — voice-driven session control.

Relay and session-manager run co-located on the same VPS, so this talks to
the loopback API directly (the same endpoints the `poke` skill uses) rather
than going through Agent Mailbox delegation.
"""
from __future__ import annotations

import os

import httpx
from loguru import logger

_DEFAULT_BASE_URL = "http://localhost:3007"


def _base_url() -> str:
    return os.environ.get("GOVORI_SM_URL", _DEFAULT_BASE_URL)


def list_sessions(timeout: float = 5.0) -> list[dict]:
    """Live tmux sessions known to session-manager, e.g. [{"id": ..., "status": ...}].

    Returns [] on any failure (unreachable, bad response) — callers treat
    that the same as "no sessions to route to".
    """
    try:
        resp = httpx.get(f"{_base_url()}/api/sessions", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.warning(f"session-manager list_sessions failed: {exc}")
        return []


def ask_session(target: str, question: str, timeout: float = 10.0) -> dict:
    """Inject `question` into the target session's pane immediately (poke-style).

    Fire-and-forget: this returns as soon as the text is injected, it does
    NOT wait for the target session to reply.
    """
    try:
        resp = httpx.post(
            f"{_base_url()}/api/bus/ask",
            json={"target": target, "question": question},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning(f"session-manager ask_session failed target={target!r}: {exc}")
        return {"ok": False, "error": str(exc)}
