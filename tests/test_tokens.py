"""Unit tests for govori.tokens — per-device licensing."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import govori.tokens as tok


@pytest.fixture(autouse=True)
def _reset(tmp_config):
    """Each test gets a fresh empty tokens file and cleared cache."""
    yield


def test_issue_and_load(tmp_config):
    """issue() creates a token; _load() sees it immediately."""
    token_str = tok.issue("owner1", "label1")
    assert token_str.startswith("gv_")
    data = json.loads(tmp_config["tokens_file"].read_text())
    assert token_str in data
    assert data[token_str]["active"] is True


def test_check_unknown():
    result = tok.check("doesnotexist", None)
    assert result == (False, "unknown")


def test_check_revoked(tmp_config):
    ts = tok.issue("o", "l")
    tok.revoke(ts)
    assert tok.check(ts, None) == (False, "revoked")


def test_check_expired(tmp_config):
    """Manually write an expired token and verify check returns 'expired'."""
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    ts = "gv_expired_test_token"
    data = {"active": True, "device": None, "expires": past, "owner": "o", "label": "l"}
    tokens_data = json.loads(tmp_config["tokens_file"].read_text())
    tokens_data[ts] = data
    tmp_config["tokens_file"].write_text(json.dumps(tokens_data))
    # Clear cache so fresh read happens
    tok._cache = None
    tok._cache_mtime = 0.0
    assert tok.check(ts, None) == (False, "expired")


def test_device_binding_first_call(tmp_config):
    """First check with device_id binds the device."""
    ts = tok.issue("o", "l")
    result = tok.check(ts, "dev1")
    assert result == (True, "bound")
    data = json.loads(tmp_config["tokens_file"].read_text())
    assert data[ts]["device"] == "dev1"


def test_device_binding_same_device(tmp_config):
    ts = tok.issue("o", "l")
    tok.check(ts, "dev1")  # bind
    assert tok.check(ts, "dev1") == (True, "ok")


def test_device_binding_different_device(tmp_config):
    ts = tok.issue("o", "l")
    tok.check(ts, "dev1")
    assert tok.check(ts, "dev2") == (False, "device_mismatch")


def test_device_no_device_id_unbound(tmp_config):
    """Unbound token + no device_id → no_device_id (token cannot be used without device)."""
    ts = tok.issue("o", "l")
    # Do NOT bind yet — call without device_id
    assert tok.check(ts, None) == (False, "no_device_id")


def test_device_mismatch_after_binding(tmp_config):
    """After binding to dev1, calling with device_id=None or dev2 → device_mismatch."""
    ts = tok.issue("o", "l")
    tok.check(ts, "dev1")  # bind
    # None is treated as a different device_id (not equal to "dev1") → device_mismatch
    assert tok.check(ts, None) == (False, "device_mismatch")


def test_revoke(tmp_config):
    ts = tok.issue("o", "l")
    tok.revoke(ts)
    ok, reason = tok.check(ts, None)
    assert ok is False
    assert reason == "revoked"


def test_rebind_allows_new_device(tmp_config):
    """rebind() clears device; new device can bind."""
    ts = tok.issue("o", "l")
    tok.check(ts, "dev1")  # bind to dev1
    tok.rebind(ts)
    result = tok.check(ts, "dev2")
    assert result == (True, "bound")


def test_register_idempotent(tmp_config):
    """register() twice with same key = no error, token stays active."""
    tok.register("gv_key1", "owner@test.com", "sub1")
    tok.register("gv_key1", "owner@test.com", "sub1")
    ok, _ = tok.check("gv_key1", "d1")
    assert ok is True


def test_register_saves_subscription_id(tmp_config):
    tok.register("gv_key2", "owner@test.com", "sub_abc")
    data = json.loads(tmp_config["tokens_file"].read_text())
    assert data["gv_key2"]["subscription_id"] == "sub_abc"


def test_register_reactivates_revoked(tmp_config):
    """register() re-activates a previously revoked token."""
    tok.register("gv_key3", "o@t.com", "sub3")
    tok.revoke("gv_key3")
    tok._cache = None  # force fresh load
    tok.register("gv_key3", "o@t.com", "sub3")
    data = json.loads(tmp_config["tokens_file"].read_text())
    assert data["gv_key3"]["active"] is True


def test_register_keeps_device_binding(tmp_config):
    """register() must not drop existing device binding."""
    tok.register("gv_key4", "o@t.com", "sub4")
    tok.check("gv_key4", "orig_dev")  # bind
    tok.register("gv_key4", "o@t.com", "sub4")  # re-register
    data = json.loads(tmp_config["tokens_file"].read_text())
    assert data["gv_key4"]["device"] == "orig_dev"


def test_revoke_by_subscription(tmp_config):
    """revoke_by_subscription() deactivates all tokens with that sub_id."""
    tok.register("gv_a", "a@t.com", "sub99")
    tok.register("gv_b", "b@t.com", "sub99")
    tok.register("gv_c", "c@t.com", "sub_other")  # different sub

    count = tok.revoke_by_subscription("sub99")
    assert count == 2

    data = json.loads(tmp_config["tokens_file"].read_text())
    assert data["gv_a"]["active"] is False
    assert data["gv_b"]["active"] is False
    assert data["gv_c"]["active"] is True  # unaffected
