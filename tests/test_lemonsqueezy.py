"""Tests for govori.lemonsqueezy — webhook signature verification and event handling."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from unittest.mock import MagicMock, patch

import pytest

import govori.lemonsqueezy as ls


SECRET = "test-webhook-secret-xyz"


def _make_sig(body: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 hex digest (what verify_signature expects as raw hex)."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# verify_signature tests
# ---------------------------------------------------------------------------

def test_verify_correct_signature(monkeypatch):
    monkeypatch.setenv("GOVORI_LS_SECRET", SECRET)
    body = b'{"event":"test"}'
    sig = _make_sig(body, SECRET)
    assert ls.verify_signature(body, sig) is True


def test_verify_wrong_signature(monkeypatch):
    monkeypatch.setenv("GOVORI_LS_SECRET", SECRET)
    body = b'{"event":"test"}'
    assert ls.verify_signature(body, "badhex") is False


def test_verify_no_secret(monkeypatch):
    monkeypatch.delenv("GOVORI_LS_SECRET", raising=False)
    body = b'{"event":"test"}'
    sig = _make_sig(body, SECRET)
    assert ls.verify_signature(body, sig) is False


def test_verify_no_signature(monkeypatch):
    monkeypatch.setenv("GOVORI_LS_SECRET", SECRET)
    body = b'{"event":"test"}'
    assert ls.verify_signature(body, None) is False


def test_verify_empty_signature(monkeypatch):
    monkeypatch.setenv("GOVORI_LS_SECRET", SECRET)
    body = b'{"event":"test"}'
    assert ls.verify_signature(body, "") is False


# ---------------------------------------------------------------------------
# handle() tests — mock tokens module to avoid file I/O
# ---------------------------------------------------------------------------

def _make_payload(event: str, **attrs) -> dict:
    return {
        "meta": {"event_name": event},
        "data": {"id": "sub123", "attributes": attrs},
    }


def test_handle_subscription_created_with_key():
    payload = _make_payload(
        "subscription_created",
        key="gv_abc", user_email="buyer@test.com"
    )
    with patch.object(ls, "tokens") as mock_tok:
        result = ls.handle(payload)
    mock_tok.register.assert_called_once()
    call_args = mock_tok.register.call_args
    # First positional arg should be the license key
    assert "gv_abc" in call_args[0] or call_args[1].get("key") == "gv_abc" or call_args[0][0] == "gv_abc"
    assert result["ok"] is True
    assert result["action"] == "granted"


def test_handle_subscription_created_no_key():
    """subscription_created without a key → noop (key comes separately)."""
    payload = _make_payload("subscription_created", user_email="buyer@test.com")
    with patch.object(ls, "tokens") as mock_tok:
        result = ls.handle(payload)
    mock_tok.register.assert_not_called()
    assert result["action"] == "noop_no_key"


def test_handle_license_key_created():
    payload = _make_payload("license_key_created", key="gv_def", user_email="x@y.com")
    with patch.object(ls, "tokens") as mock_tok:
        result = ls.handle(payload)
    mock_tok.register.assert_called_once()
    assert result["action"] == "granted"


def test_handle_subscription_cancelled():
    payload = _make_payload("subscription_cancelled", user_email="x@y.com")
    payload["data"]["id"] = "sub_to_revoke"
    with patch.object(ls, "tokens") as mock_tok:
        mock_tok.revoke_by_subscription.return_value = 1
        result = ls.handle(payload)
    mock_tok.revoke_by_subscription.assert_called_once_with("sub_to_revoke")
    assert result["action"] == "revoked"


def test_handle_unknown_event():
    """Unhandled event → no exception, returns ok=True action=ignored."""
    payload = _make_payload("totally_unknown_event_xyz")
    with patch.object(ls, "tokens"):
        result = ls.handle(payload)
    assert result["ok"] is True
    assert result["action"] == "ignored"


# ---------------------------------------------------------------------------
# /lemonsqueezy/webhook endpoint tests
# ---------------------------------------------------------------------------

def test_webhook_endpoint_bad_sig(client, monkeypatch):
    monkeypatch.setenv("GOVORI_LS_SECRET", SECRET)
    body = json.dumps({"meta": {"event_name": "subscription_created"}, "data": {}}).encode()
    r = client.post(
        "/lemonsqueezy/webhook",
        content=body,
        headers={"X-Signature": "badhex", "Content-Type": "application/json"},
    )
    assert r.status_code == 401


def test_webhook_endpoint_good_sig(client, monkeypatch):
    monkeypatch.setenv("GOVORI_LS_SECRET", SECRET)
    payload = {
        "meta": {"event_name": "subscription_created"},
        "data": {
            "id": "sub1",
            "attributes": {"key": "gv_test_key", "user_email": "test@example.com"},
        },
    }
    body = json.dumps(payload).encode()
    sig = _make_sig(body, SECRET)
    with patch("govori.tokens.register"):
        r = client.post(
            "/lemonsqueezy/webhook",
            content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
