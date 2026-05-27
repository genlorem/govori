"""Lemon Squeezy webhook handling — turns subscription lifecycle into token grants.

LS is the merchant-of-record (handles payment, tax, customer email, license key
generation). This module verifies the signed webhook and maps events onto the
token registry:

  subscription_created / subscription_resumed / subscription_unpaused
      → register the LS license key as an active token (owner = buyer email)
  subscription_cancelled / subscription_expired / subscription_paused
      → revoke every token for that subscription

Set the signing secret in env GOVORI_LS_SECRET (Lemon Squeezy → Settings →
Webhooks → Signing secret). The webhook URL is https://govori.io/lemonsqueezy/webhook.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os

from loguru import logger

from . import tokens

GRANT_EVENTS = {"subscription_created", "subscription_resumed", "subscription_unpaused",
                "subscription_payment_success", "order_created"}
REVOKE_EVENTS = {"subscription_cancelled", "subscription_expired", "subscription_paused"}


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """Constant-time HMAC-SHA256 check against GOVORI_LS_SECRET."""
    secret = os.environ.get("GOVORI_LS_SECRET")
    if not secret:
        logger.warning("GOVORI_LS_SECRET not set — rejecting webhook")
        return False
    if not signature:
        return False
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def _extract(payload: dict) -> tuple[str, str, str | None, str | None]:
    """Pull (event, email, subscription_id, license_key) from an LS webhook body."""
    event = (payload.get("meta") or {}).get("event_name", "")
    data = payload.get("data") or {}
    attrs = data.get("attributes") or {}
    email = attrs.get("user_email") or attrs.get("email") or ""
    # subscription_id: for subscription events it's data.id; for order events it
    # may live in attributes.first_subscription_item or be absent.
    sub_id = None
    if "subscription" in event:
        sub_id = str(data.get("id")) if data.get("id") is not None else None
    sub_id = sub_id or attrs.get("subscription_id")
    # license key: present on license_key_created, or carried in custom data /
    # attributes depending on product config.
    key = attrs.get("key") or (payload.get("meta") or {}).get("custom_data", {}).get("license_key")
    return event, email, (str(sub_id) if sub_id else None), key


def handle(payload: dict) -> dict:
    """Apply a verified webhook payload to the token registry."""
    event, email, sub_id, key = _extract(payload)
    logger.info("LS webhook: event={} email={} sub={} key={}", event, email, sub_id,
                (key[:6] + "…") if key else None)

    if event in GRANT_EVENTS:
        if not key:
            # No license key in this event — LS sends a separate
            # license_key_created we also accept below. Nothing to grant yet.
            logger.info("LS grant event without key — waiting for license_key_created")
            return {"ok": True, "action": "noop_no_key", "event": event}
        tokens.register(key, owner=email or "unknown", subscription_id=sub_id)
        return {"ok": True, "action": "granted", "event": event}

    if event == "license_key_created":
        if key:
            tokens.register(key, owner=email or "unknown", subscription_id=sub_id)
            return {"ok": True, "action": "granted", "event": event}
        return {"ok": True, "action": "noop_no_key", "event": event}

    if event in REVOKE_EVENTS:
        if sub_id:
            n = tokens.revoke_by_subscription(sub_id)
            return {"ok": True, "action": "revoked", "count": n, "event": event}
        return {"ok": True, "action": "noop_no_sub", "event": event}

    logger.debug("LS webhook: unhandled event {} (raw kept in log)", event)
    logger.debug("LS raw: {}", json.dumps(payload)[:1000])
    return {"ok": True, "action": "ignored", "event": event}
