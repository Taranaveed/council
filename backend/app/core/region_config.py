"""Regional defaults for global deployments (no Pakistan hardcode)."""
from __future__ import annotations

import os
import re
from typing import Optional


def _env(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip()


# Logical region for CDN / routing (us | eu | uk | asia | pk | ...)
DEFAULT_REGION = _env("DEFAULT_REGION", "us").lower()
# ISO-ish country code for locale / geo (e.g. PK, US).
# Note: Google Shopping does not support every country (Pakistan `pk` is excluded).
# market-service falls back to engine=google for unsupported shopping `gl` codes.
DEFAULT_COUNTRY_CODE = _env("DEFAULT_COUNTRY_CODE", "us").upper()
# Human-readable fallback location label
DEFAULT_LOCATION = _env("DEFAULT_LOCATION", "United States")
DEFAULT_LANGUAGE = _env("DEFAULT_LANGUAGE", "en")

_LOCATION_TO_GL: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(pakistan|lahore|karachi|islamabad|rawalpindi)\b", re.I), "pk"),
    (re.compile(r"\b(united kingdom|england|scotland|wales|london|manchester|edinburgh|uk)\b", re.I), "uk"),
    (re.compile(r"\b(united states|usa|new york|california|texas|chicago|seattle|los angeles)\b", re.I), "us"),
    (re.compile(r"\b(france|paris|lyon|marseille)\b", re.I), "fr"),
    (re.compile(r"\b(germany|berlin|munich|hamburg)\b", re.I), "de"),
    (re.compile(r"\b(canada|toronto|vancouver)\b", re.I), "ca"),
    (re.compile(r"\b(india|mumbai|delhi|bangalore)\b", re.I), "in"),
    (re.compile(r"\b(uae|dubai|abu dhabi)\b", re.I), "ae"),
    (re.compile(r"\b(singapore)\b", re.I), "sg"),
    (re.compile(r"\b(netherlands|amsterdam)\b", re.I), "nl"),
    (re.compile(r"\b(spain|madrid|barcelona)\b", re.I), "es"),
    (re.compile(r"\b(italy|rome|milan)\b", re.I), "it"),
    (re.compile(r"\b(ireland|dublin)\b", re.I), "ie"),
]

_REGION_TO_GL = {
    "us": "us",
    "eu": "de",
    "uk": "uk",
    "asia": "sg",
    "pk": "pk",
    "pakistan": "pk",
}


def country_code_from_location(location: str | None) -> str:
    loc = (location or "").strip()
    if loc:
        for pattern, gl in _LOCATION_TO_GL:
            if pattern.search(loc):
                return gl.upper()
    mapped = _REGION_TO_GL.get(DEFAULT_REGION)
    if mapped:
        return mapped.upper()
    return DEFAULT_COUNTRY_CODE


def resolve_market_locale(
    location: str | None = None,
    country_code: str | None = None,
) -> dict[str, str]:
    gl = (country_code or "").strip().lower() or country_code_from_location(location).lower()
    search_location = (location or "").strip() or DEFAULT_LOCATION
    return {
        "location": search_location,
        "gl": gl,
        "hl": DEFAULT_LANGUAGE,
        "default_region": DEFAULT_REGION,
        "country_code": gl.upper(),
    }
