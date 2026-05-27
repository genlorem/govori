"""Per-device token registry — paid-access licensing (1 token = 1 device).

Two tiers:
- MASTER token (env GOVORI_TOKEN): the owner/seller. Full access, no device
  binding, can reach /review. Existing personal setup keeps working unchanged.
- CUSTOMER tokens (this registry): issued per seat. Bound to the FIRST device
  that uses them; a different device with the same token is rejected. A second
  device needs a separately-issued token (controlled = billable).

Storage: ~/.config/govori/tokens.json
  { "gv_<hex>": {owner, label, device, bound_at, created, expires, active} }

CLI:  python -m govori.tokens issue --owner X --label Y [--days N]
      python -m govori.tokens list | revoke <tok> | rebind <tok>
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOKENS_FILE = Path.home() / ".config" / "govori" / "tokens.json"

_cache: dict | None = None
_cache_mtime: float = 0.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(use_cache: bool = True) -> dict:
    """Load registry; cached and invalidated by file mtime (zero-cost on hits)."""
    global _cache, _cache_mtime
    if not TOKENS_FILE.exists():
        return {}
    mtime = TOKENS_FILE.stat().st_mtime
    if use_cache and _cache is not None and mtime <= _cache_mtime:
        return _cache
    try:
        data = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    _cache, _cache_mtime = data, mtime
    return data


def _save(data: dict) -> None:
    global _cache, _cache_mtime
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKENS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(TOKENS_FILE)
    _cache, _cache_mtime = data, TOKENS_FILE.stat().st_mtime


def check(token: str, device_id: str | None) -> tuple[bool, str]:
    """Validate a customer token + enforce 1-token-1-device.

    Returns (allowed, reason). Binds the token to `device_id` on first use.
    Pure in-memory comparison after a cached load → no measurable latency.
    """
    if not token:
        return False, "missing"
    rec = _load().get(token)
    if not rec:
        return False, "unknown"
    if not rec.get("active", True):
        return False, "revoked"
    exp = rec.get("expires")
    if exp and _now() > exp:
        return False, "expired"
    bound = rec.get("device")
    if not bound:
        if not device_id:
            return False, "no_device_id"
        # first use → bind (reload uncached to avoid racing a concurrent bind)
        data = _load(use_cache=False)
        data[token]["device"] = device_id
        data[token]["bound_at"] = _now()
        _save(data)
        return True, "bound"
    if device_id != bound:
        return False, "device_mismatch"
    return True, "ok"


def issue(owner: str, label: str, days: int | None = None) -> str:
    data = _load(use_cache=False)
    tok = "gv_" + secrets.token_hex(20)
    rec = {"owner": owner, "label": label, "device": None,
           "created": _now(), "active": True}
    if days:
        rec["expires"] = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    data[tok] = rec
    _save(data)
    return tok


def register(key: str, owner: str, subscription_id: str | None = None,
             label: str = "Lemon Squeezy") -> None:
    """Register an externally-issued key (Lemon Squeezy license) as a live token.

    Idempotent: re-registering an existing key re-activates it and refreshes
    owner/subscription without dropping its device binding.
    """
    if not key:
        return
    data = _load(use_cache=False)
    rec = data.get(key, {"device": None, "created": _now()})
    rec.update({"owner": owner, "label": label, "active": True})
    if subscription_id:
        rec["subscription_id"] = str(subscription_id)
    rec.pop("expires", None)
    data[key] = rec
    _save(data)


def revoke_by_subscription(subscription_id: str) -> int:
    """Deactivate every token tied to a Lemon Squeezy subscription. Returns count."""
    data = _load(use_cache=False)
    n = 0
    for rec in data.values():
        if str(rec.get("subscription_id", "")) == str(subscription_id) and rec.get("active", True):
            rec["active"] = False
            n += 1
    if n:
        _save(data)
    return n


def revoke(token: str) -> bool:
    data = _load(use_cache=False)
    if token in data:
        data[token]["active"] = False
        _save(data)
        return True
    return False


def rebind(token: str) -> bool:
    """Clear the device binding so the token can attach to a new device (controlled)."""
    data = _load(use_cache=False)
    if token in data:
        data[token]["device"] = None
        data[token].pop("bound_at", None)
        _save(data)
        return True
    return False


def _main() -> None:
    import argparse

    p = argparse.ArgumentParser(prog="govori.tokens")
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("issue")
    pi.add_argument("--owner", required=True)
    pi.add_argument("--label", default="")
    pi.add_argument("--days", type=int, default=None)
    sub.add_parser("list")
    pr = sub.add_parser("revoke"); pr.add_argument("token")
    pb = sub.add_parser("rebind"); pb.add_argument("token")
    a = p.parse_args()

    if a.cmd == "issue":
        tok = issue(a.owner, a.label, a.days)
        print(tok)
    elif a.cmd == "list":
        data = _load(use_cache=False)
        if not data:
            print("(пусто)")
        for tok, r in data.items():
            dev = r.get("device") or "—"
            st = "active" if r.get("active", True) else "REVOKED"
            exp = r.get("expires", "")
            print(f"{tok}  {st}  owner={r.get('owner')}  label={r.get('label')}  device={dev}  exp={exp}")
    elif a.cmd == "revoke":
        print("revoked" if revoke(a.token) else "not found")
    elif a.cmd == "rebind":
        print("rebound (device cleared)" if rebind(a.token) else "not found")


if __name__ == "__main__":
    _main()
