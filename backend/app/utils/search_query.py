"""Helpers to turn long product specs into short market-search queries."""
from __future__ import annotations

import re

_STOP = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "with",
    "for",
    "from",
    "that",
    "this",
    "high",
    "quality",
    "premium",
    "look",
    "looks",
    "best",
    "new",
    "our",
    "product",
    "item",
    "features",
    "feature",
    "battery",
    "lasts",
    "hours",
    "hour",
    "sleek",
    "design",
    "superior",
    "very",
    "good",
    "great",
    "preminum",
    "amazing",
    "excellent",
    "super",
    "ultra",
}

# Accessory types before bare "leather" so "leather mobile covers" ≠ "leather"
_PRODUCT_NOUNS = [
    "earbuds",
    "earbud",
    "earphones",
    "earphone",
    "headphones",
    "headphone",
    "headset",
    "buds",
    "airpods",
    "speaker",
    "speakers",
    "watch",
    "smartwatch",
    "covers",
    "cover",
    "cases",
    "case",
    "phonecase",
    "phone",
    "smartphone",
    "iphone",
    "laptop",
    "tablet",
    "camera",
    "charger",
    "powerbank",
    "keyboard",
    "mouse",
    "monitor",
    "tv",
    "router",
    "console",
    "jacket",
    "coat",
    "shoes",
    "sneakers",
    "bag",
    "backpack",
    "wallet",
    "belt",
    "leather",
]

_KEEP = {
    "wireless",
    "bluetooth",
    "noise",
    "cancelling",
    "cancellation",
    "canceling",
    "anc",
    "tws",
    "true",
    "gaming",
    "sports",
    "waterproof",
    "water",
    "resistant",
    "pro",
    "max",
    "mini",
    "plus",
    "active",
    "bass",
    "stereo",
    "over",
    "ear",
    "on",
    "in",
    "neckband",
    "bone",
    "conduction",
    "leather",
    "mobile",
    "phone",
    "cover",
    "covers",
    "case",
    "cases",
    "flip",
    "folio",
}

_COMPOUNDS = [
    (
        re.compile(
            r"\bleather\b.+\b(mobile|phone)\b.+\b(cover|covers)\b|"
            r"\b(mobile|phone)\b.+\bleather\b.+\b(cover|covers)\b|"
            r"\bleather\b.+\b(cover|covers)\b",
            re.I,
        ),
        "leather phone cover",
    ),
    (
        re.compile(
            r"\bleather\b.+\b(mobile|phone)\b.+\b(case|cases)\b|"
            r"\b(mobile|phone)\b.+\bleather\b.+\b(case|cases)\b|"
            r"\bleather\b.+\b(case|cases)\b",
            re.I,
        ),
        "leather phone case",
    ),
    (re.compile(r"\bleather\b.+\bjacket\b|\bjacket\b.+\bleather\b", re.I), "leather jacket"),
    (re.compile(r"\bleather\b.+\bbag\b|\bbag\b.+\bleather\b", re.I), "leather bag"),
    (re.compile(r"\bleather\b.+\bwallet\b|\bwallet\b.+\bleather\b", re.I), "leather wallet"),
]


def shorten_product_query(raw: str | None, max_len: int = 55) -> str:
    original = re.sub(r"[\r\n]+", " ", str(raw or ""))
    original = re.sub(r"\s+", " ", original).strip()
    if not original:
        return "product"

    cleaned = re.sub(r"[^\w\s.+%-]", " ", original)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()

    for pattern, out in _COMPOUNDS:
        if pattern.search(cleaned):
            return out if len(out) <= max_len else out[:max_len].strip()

    words = [w for w in cleaned.split(" ") if w]

    noun = next((n for n in _PRODUCT_NOUNS if n in words or n in cleaned), None)
    modifiers = [w for w in words if w in _KEEP]

    parts: list[str] = []
    for m in modifiers:
        if m not in parts:
            parts.append(m)
    if noun and noun not in parts:
        parts.append(noun)

    built = " ".join(parts).strip()
    built = re.sub(r"\bnoise cancellation\b", "noise cancelling", built)
    built = re.sub(r"\bnoise canceling\b", "noise cancelling", built)
    built = re.sub(r"\btrue wireless\b", "wireless", built)
    built = re.sub(r"\s+", " ", built).strip()

    if re.search(r"\bleather\b", cleaned) and re.search(r"\b(cover|covers)\b", cleaned):
        built = "leather phone cover"
    elif (
        re.search(r"\bleather\b", cleaned)
        and re.search(r"\b(case|cases)\b", cleaned)
        and not re.search(r"\b(cover|covers)\b", cleaned)
    ):
        built = "leather phone case"

    if len(built) >= 6:
        return built if len(built) <= max_len else built[:max_len].strip()

    head = re.split(r"[,.;|]", original, maxsplit=1)[0].strip()
    fallback_words: list[str] = []
    for w in re.sub(r"[^\w\s.+%-]", " ", head).split():
        lower = w.lower()
        if lower in _STOP:
            continue
        if re.match(r"^\d+\+?(h|hr|hrs|hours)?$", w, re.I):
            continue
        if len(w) <= 1:
            continue
        fallback_words.append(w)

    out = " ".join(fallback_words).strip() or head or "product"
    if len(out) <= 3 and noun:
        out = noun
    return out if len(out) <= max_len else out[:max_len].strip()
