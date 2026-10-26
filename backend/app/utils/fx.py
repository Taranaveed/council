"""Live FX with timestamp; static RegionProfile.fx_to_usd_fallback when offline.

Primary: Frankfurter (ECB) — covers GBP, EUR, INR, USD; does NOT publish PKR.
Secondary: open.er-api.com (exchangerate-api.com free tier) — covers PKR, INR, GBP, USD.
Fallback: static table / RegionProfile.fx_to_usd_fallback.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx

# In-memory cache: (pair) -> {rate, as_of, source}
_CACHE: dict[str, dict[str, Any]] = {}
_TTL_SEC = 3600

# Currencies Frankfurter/ECB typically omits (need secondary source).
_FRANKFURTER_UNSUPPORTED = frozenset({"PKR", "AED", "SAR", "CNY"})


def _static_to_usd(currency: str, profile_fallback: float | None) -> float | None:
    cur = (currency or "").upper()
    if cur == "USD":
        return 1.0
    if profile_fallback and profile_fallback > 0:
        return float(profile_fallback)
    # Hard safety net matching historical table (fallback of fallback)
    legacy = {
        "PKR": 1 / 278,
        "INR": 1 / 83,
        "AED": 1 / 3.67,
        "SAR": 1 / 3.75,
        "GBP": 1.27,
        "EUR": 1.08,
        "CAD": 0.74,
        "AUD": 0.65,
        "SGD": 0.74,
    }
    return legacy.get(cur)


def _from_frankfurter(cur: str) -> dict[str, Any] | None:
    if cur in _FRANKFURTER_UNSUPPORTED:
        return None
    url = f"https://api.frankfurter.app/latest?from=USD&to={cur}"
    with httpx.Client(timeout=3.0, follow_redirects=True) as client:
        resp = client.get(url)
        if resp.status_code != 200:
            return None
        data = resp.json()
        per_usd = float((data.get("rates") or {}).get(cur) or 0)
        if per_usd <= 0:
            return None
        return {
            "rate_to_usd": 1.0 / per_usd,
            "as_of": str(data.get("date") or datetime.now(timezone.utc).date()),
            "source": "frankfurter.app",
            "used_fallback": False,
        }


def _from_er_api(cur: str) -> dict[str, Any] | None:
    """open.er-api.com — free, no key; rates are CUR per 1 USD."""
    url = "https://open.er-api.com/v6/latest/USD"
    with httpx.Client(timeout=4.0, follow_redirects=True) as client:
        resp = client.get(url)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if str(data.get("result") or "").lower() != "success":
            return None
        per_usd = float((data.get("rates") or {}).get(cur) or 0)
        if per_usd <= 0:
            return None
        as_of = str(
            data.get("time_last_update_utc")
            or data.get("time_last_update_unix")
            or datetime.now(timezone.utc).date()
        )
        return {
            "rate_to_usd": 1.0 / per_usd,
            "as_of": as_of,
            "source": "open.er-api.com",
            "used_fallback": False,
        }


def fetch_usd_rate(currency: str, *, fallback_to_usd: float | None = None) -> dict[str, Any]:
    """
    Return {rate_to_usd, as_of, source, used_fallback}.
    rate_to_usd = units of USD per 1 unit of currency (same as old _TO_USD).
    """
    cur = (currency or "USD").upper()
    if cur == "USD":
        return {
            "rate_to_usd": 1.0,
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "identity",
            "used_fallback": False,
        }

    key = f"USD:{cur}"
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - float(hit.get("_cached_at") or 0) < _TTL_SEC:
        return {k: v for k, v in hit.items() if not k.startswith("_")}

    live: dict[str, Any] | None = None
    for fetcher in (_from_frankfurter, _from_er_api):
        try:
            live = fetcher(cur)
        except Exception:
            live = None
        if live:
            break

    if live:
        live["_cached_at"] = now
        _CACHE[key] = live
        return {k: v for k, v in live.items() if not k.startswith("_")}

    fb = _static_to_usd(cur, fallback_to_usd)
    out = {
        "rate_to_usd": float(fb) if fb else None,
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "static_fallback",
        "used_fallback": True,
    }
    if out["rate_to_usd"]:
        out["_cached_at"] = now
        _CACHE[key] = out
    return {k: v for k, v in out.items() if not k.startswith("_")}


def convert_amount(
    amount: float,
    from_cur: str,
    to_cur: str,
    *,
    from_fallback: float | None = None,
    to_fallback: float | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """Convert using live FX when possible. Returns (amount, meta)."""
    if amount is None or amount <= 0:
        return None, {"error": "bad_amount"}
    fr = (from_cur or "").upper()
    to = (to_cur or "").upper()
    if fr == to:
        return float(amount), {"source": "same_currency", "used_fallback": False}

    a = fetch_usd_rate(fr, fallback_to_usd=from_fallback)
    b = fetch_usd_rate(to, fallback_to_usd=to_fallback)
    if not a.get("rate_to_usd") or not b.get("rate_to_usd"):
        return None, {"error": "missing_rate", "from": a, "to": b}
    usd = float(amount) * float(a["rate_to_usd"])
    local = usd / float(b["rate_to_usd"])
    return local, {
        "from": a,
        "to": b,
        "used_fallback": bool(a.get("used_fallback") or b.get("used_fallback")),
    }
