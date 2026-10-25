"""RegionProfile loader — shared JSON under shared/region_profiles/.

Pakistan (pk) is the golden regression fixture (region_pk_v1). Shopping for pk stays off.
Unsupported countries raise RegionNotSupportedError — no silent UK/PK fallback.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

TRADE_ZONES = frozenset({"UK", "EU", "US", "PK", "EFTA-CH", "EFTA-NO"})
SUPPORTED_PROFILE_IDS = frozenset({"pk", "uk"})

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROFILES_DIR = _REPO_ROOT / "shared" / "region_profiles"

# Location keywords → profile id
_LOCATION_TO_ID: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(pakistan|lahore|karachi|islamabad|rawalpindi|faisalabad|multan|peshawar)\b", re.I), "pk"),
    (re.compile(r"\b(united kingdom|england|scotland|wales|london|manchester|edinburgh|birmingham|glasgow|uk)\b", re.I), "uk"),
    (re.compile(r"\b(united states|usa|new york|california|texas|chicago|seattle|los angeles)\b", re.I), "us"),
    (re.compile(r"\b(india|mumbai|delhi|bangalore|bengaluru)\b", re.I), "in"),
    (re.compile(r"\b(switzerland|zurich|geneva)\b", re.I), "efta-ch"),
    (re.compile(r"\b(norway|oslo)\b", re.I), "efta-no"),
    (re.compile(
        r"\b(germany|france|spain|italy|netherlands|belgium|ireland|eu|europe|"
        r"berlin|paris|madrid|rome|amsterdam|dublin)\b",
        re.I,
    ), "eu"),
]

_CODE_ALIASES = {
    "pk": "pk",
    "pakistan": "pk",
    "uk": "uk",
    "gb": "uk",
    "united kingdom": "uk",
    "us": "us",
    "usa": "us",
    "in": "in",
    "india": "in",
    "eu": "eu",
    "de": "eu",
    "fr": "eu",
    "efta-ch": "efta-ch",
    "ch": "efta-ch",
    "efta-no": "efta-no",
    "no": "efta-no",
}


class RegionNotSupportedError(LookupError):
    """Raised when the requested country/region has no RegionProfile JSON."""

    def __init__(self, profile_id: str, *, detail: str | None = None):
        self.profile_id = (profile_id or "").strip().lower() or "unknown"
        self.detail = detail or (
            f"Region not supported: '{self.profile_id}'. "
            f"Supported regions: {', '.join(sorted(SUPPORTED_PROFILE_IDS))}."
        )
        super().__init__(self.detail)


def _env_default_id() -> str:
    raw = (os.getenv("DEFAULT_REGION") or os.getenv("DEFAULT_COUNTRY_CODE") or "uk").strip().lower()
    return _CODE_ALIASES.get(raw, raw if raw in ("pk", "uk", "us", "in", "eu") else "uk")


def profiles_dir() -> Path:
    override = (os.getenv("REGION_PROFILES_DIR") or "").strip()
    if override:
        return Path(override)
    return _PROFILES_DIR


def profile_available(profile_id: str) -> bool:
    pid = _CODE_ALIASES.get((profile_id or "").strip().lower(), (profile_id or "").strip().lower())
    return (profiles_dir() / f"{pid}.json").is_file()


@lru_cache(maxsize=16)
def load_profile(profile_id: str) -> dict[str, Any]:
    pid = _CODE_ALIASES.get((profile_id or "").strip().lower(), (profile_id or "").strip().lower())
    path = profiles_dir() / f"{pid}.json"
    if not path.is_file():
        raise RegionNotSupportedError(pid)
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate_profile(data)
    return data


def _validate_profile(data: dict[str, Any]) -> None:
    tz = str(data.get("trade_zone") or "")
    if tz and tz not in TRADE_ZONES:
        raise ValueError(f"Invalid trade_zone {tz!r}; expected one of {sorted(TRADE_ZONES)}")
    if not data.get("currency"):
        raise ValueError("RegionProfile.currency is required")
    duty = data.get("duty") or {}
    if not isinstance(duty.get("fallback"), dict):
        raise ValueError("RegionProfile.duty.fallback is required")


def resolve_profile_id(
    *,
    location: str | None = None,
    country_code: str | None = None,
    currency: str | None = None,
) -> str:
    code = (country_code or "").strip().lower()
    if code:
        return _CODE_ALIASES.get(code, code)
    loc = (location or "").strip()
    if loc:
        for pattern, pid in _LOCATION_TO_ID:
            if pattern.search(loc):
                return pid
    cur = (currency or "").strip().upper()
    if cur == "PKR":
        return "pk"
    if cur == "GBP":
        return "uk"
    if cur == "USD":
        return "us"
    return _env_default_id()


def get_profile(
    *,
    location: str | None = None,
    country_code: str | None = None,
    currency: str | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Load the RegionProfile for the request. Raises RegionNotSupportedError if missing."""
    pid = (profile_id or "").strip() or resolve_profile_id(
        location=location, country_code=country_code, currency=currency
    )
    return load_profile(pid)


def require_supported_profile(
    *,
    location: str | None = None,
    country_code: str | None = None,
    currency: str | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Resolve + load; same as get_profile (explicit name for API call sites)."""
    return get_profile(
        location=location,
        country_code=country_code,
        currency=currency,
        profile_id=profile_id,
    )


def local_host_regex(profile: dict[str, Any]) -> re.Pattern[str]:
    parts = [str(p) for p in (profile.get("local_host_patterns") or []) if p]
    if not parts:
        return re.compile(r"a^")  # never matches
    return re.compile("|".join(f"(?:{p})" for p in parts), re.I)


def is_local_host(url_or_host: str, profile: dict[str, Any]) -> bool:
    return bool(local_host_regex(profile).search(str(url_or_host or "")))


def lookup_duty(
    profile: dict[str, Any],
    *,
    commodity_code: str | None = None,
    origin_country: str | None = None,
) -> dict[str, Any]:
    """
    Duty keyed by (destination, commodity_code, origin_country).
    Exact → wildcard commodity → wildcard origin → flat fallback (labeled).
    """
    duty = profile.get("duty") if isinstance(profile.get("duty"), dict) else {}
    fallback = dict(duty.get("fallback") or {})
    dest = str(profile.get("country_code") or "").upper()
    if dest == "GB":
        dest = "UK"
    cc = (commodity_code or "*").strip().upper() or "*"
    origin = (origin_country or "*").strip().upper() or "*"
    rows = duty.get("lookup") if isinstance(duty.get("lookup"), list) else []

    def score(row: dict[str, Any]) -> int:
        rd = str(row.get("destination") or "*").upper()
        rc = str(row.get("commodity_code") or "*").upper()
        ro = str(row.get("origin_country") or "*").upper()
        if rd not in ("*", dest):
            return -1
        s = 0
        if rd == dest:
            s += 4
        if rc == cc:
            s += 2
        elif rc == "*":
            s += 0
        else:
            return -1
        if ro == origin:
            s += 1
        elif ro == "*":
            s += 0
        else:
            return -1
        return s

    best: Optional[dict[str, Any]] = None
    best_s = -1
    for row in rows:
        if not isinstance(row, dict):
            continue
        s = score(row)
        if s > best_s:
            best_s = s
            best = row
    if best and best_s >= 0:
        out = dict(best)
        out["matched"] = True
        out.setdefault("label", "HS/origin duty lookup")
        return out
    out = dict(fallback)
    out["matched"] = False
    out["used_fallback"] = True
    out.setdefault(
        "label",
        "Flat currency fallback (not HS-coded) — assumption, not official customs",
    )
    return out


def import_origin_group(profile: dict[str, Any], origin_country: str | None) -> str:
    """Return 'domestic' or 'import' using profile.import_origin_groups."""
    groups = profile.get("import_origin_groups") if isinstance(profile.get("import_origin_groups"), dict) else {}
    origin = (origin_country or "").strip().upper()
    if not origin:
        return "import"
    for name, codes in groups.items():
        if origin in {str(c).upper() for c in (codes or [])}:
            return str(name)
    # ROW catch-all
    for name, codes in groups.items():
        if "ROW" in {str(c).upper() for c in (codes or [])}:
            return str(name)
    return "import"


def assert_pk_golden_parity() -> dict[str, Any]:
    """Freeze checks for region_pk_v1 — fail CI if PK rates drift."""
    pk = load_profile("pk")
    assert pk.get("version") == "region_pk_v1"
    assert pk.get("trade_zone") == "PK"
    assert pk.get("currency") == "PKR"
    assert pk.get("serp", {}).get("shopping_gl_supported") is False
    assert pk.get("serp", {}).get("preferred_engine") == "google"
    assert abs(float(pk["fx_to_usd_fallback"]) - (1 / 278)) < 1e-12
    assert float(pk["sales_tax"]["rate"]) == 0.18
    assert float(pk["duty"]["fallback"]["rate_mid"]) == 0.25
    assert float(pk["shipping_flat_local"]["amount"]) == 8500
    assert float(pk["freight_usd_per_kg"]["mid"]) == 10.0
    assert pk.get("min_plausible_price_retail") == 1000
    assert pk.get("min_plausible_price_bulk") == 150
    assert "daraz\\." in (pk.get("local_host_patterns") or [])
    assert "daraz_pk" in (pk.get("direct_adapters") or [])
    return pk
