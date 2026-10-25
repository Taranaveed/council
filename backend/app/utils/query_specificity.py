"""Detect vague single-word product queries and suggest a clearer search."""
from __future__ import annotations

import re
from typing import Any

from app.utils.relevance import detect_ambiguous_query

# Single tokens that are too broad for useful wholesale/retail ranking.
_VAGUE_SINGLES = {
    "mist",
    "mists",
    "spray",
    "sprays",
    "perfume",
    "perfumes",
    "cream",
    "creams",
    "oil",
    "oils",
    "soap",
    "soaps",
    "bag",
    "bags",
    "shirt",
    "shirts",
    "dress",
    "dresses",
    "shoes",
    "shoe",
    "phone",
    "phones",
    "cover",
    "covers",
    "case",
    "cases",
    "mug",
    "mugs",
    "bottle",
    "bottles",
    "watch",
    "watches",
    "light",
    "lights",
    "lamp",
    "lamps",
    "chair",
    "chairs",
    "table",
    "tables",
    "box",
    "boxes",
    "gift",
    "gifts",
    "toy",
    "toys",
    "kit",
    "kits",
    "set",
    "sets",
    "pack",
    "packs",
    "product",
    "products",
    "item",
    "items",
    "goods",
    "stuff",
    "thing",
    "things",
}

_NARROW_MAP = {
    "mist": "body mist 100ml wholesale",
    "mists": "body mist 100ml wholesale",
    "spray": "body spray fragrance wholesale",
    "perfume": "perfume body mist wholesale",
    "cream": "face cream jar wholesale",
    "oil": "essential oil bottle wholesale",
    "soap": "handmade soap bar wholesale",
    "bag": "tote bag wholesale",
    "shirt": "cotton t-shirt wholesale",
    "shoes": "casual sneakers wholesale",
    "phone": "smartphone accessories wholesale",
    "cover": "phone cover wholesale",
    "case": "phone case wholesale",
    "mug": "ceramic mug wholesale",
    "bottle": "water bottle wholesale",
    "watch": "wrist watch wholesale",
    "light": "LED bulb wholesale",
    "lamp": "desk lamp wholesale",
    "chair": "office chair wholesale",
    "table": "folding table wholesale",
    "toy": "kids toy wholesale",
    "kit": "starter kit wholesale",
    "gift": "gift set wholesale",
    "handsfree": "handsfree earphones wholesale",
    "handfree": "handsfree earphones wholesale",
}


def _normalize_handsfree(raw: str) -> str:
    text = str(raw or "").strip()
    text = re.sub(r"\bhand[\s-]*frees?\b", "handsfree", text, flags=re.I)
    text = re.sub(r"\bhands[\s-]*frees?\b", "handsfree", text, flags=re.I)
    text = re.sub(r"\bhandsfrees?\b", "handsfree", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def analyze_query_specificity(item_name: str) -> dict[str, Any]:
    raw = _normalize_handsfree(item_name)
    tokens = [t for t in re.split(r"\s+", raw) if t]
    letters_only = re.sub(r"[^a-zA-Z]", "", raw).lower()

    ambiguous = detect_ambiguous_query(raw)
    if ambiguous:
        return {
            "vague": True,
            "hard_vague": True,
            "reason": str(ambiguous.get("reason") or "ambiguous product type"),
            "suggestion": str(ambiguous.get("suggestion") or ""),
            "options": list(ambiguous.get("options") or []),
            "token_count": len(tokens),
            "ambiguous": True,
        }

    vague = False
    reason = ""
    if len(tokens) <= 1 and letters_only:
        if letters_only in _VAGUE_SINGLES or len(letters_only) <= 4:
            vague = True
            reason = "single vague word"
        elif len(tokens) == 1 and letters_only not in _NARROW_MAP and len(letters_only) < 8:
            vague = True
            reason = "single short word"

    soft = False
    joined = " ".join(t.lower() for t in tokens)
    audio_ok = bool(
        re.search(r"\b(earbuds?|earphones?|headphones?|headset|wired|wireless|bluetooth|tws)\b", joined)
    )
    if not vague and len(tokens) == 2:
        if re.search(
            r"\b(body mists?|face creams?|gift sets?|phone covers?|led lights?)\b",
            joined,
        ):
            soft = True
            reason = "broad category phrase"
    # Bare handsfree (or handsfree + wholesale only) needs an audio product word
    if re.search(r"\bhandsfree\b", joined) and not audio_ok:
        soft = True
        reason = "handsfree needs product type"

    suggestion = ""
    key = letters_only if len(tokens) <= 1 else tokens[0].lower()
    if vague or soft:
        suggestion = _NARROW_MAP.get(key) or _NARROW_MAP.get(tokens[0].lower() if tokens else "")
        if not suggestion and soft and "mist" in raw.lower():
            suggestion = "body mist 100ml floral wholesale"
        if not suggestion and "handsfree" in raw.lower():
            if re.search(r"\bwired\b", raw, re.I):
                suggestion = "wired handsfree earphones 3.5mm wholesale"
            else:
                suggestion = "handsfree earphones wholesale"
        if not suggestion and tokens:
            suggestion = f"{raw} wholesale pack size"

    # Don't "suggest" the same string the user already typed
    if suggestion and suggestion.strip().lower() == raw.strip().lower():
        suggestion = ""
        soft = False
        vague = False

    hard_vague = vague
    if re.search(r"\bhandsfree\b", raw, re.I) and soft and not audio_ok:
        hard_vague = True

    return {
        "vague": vague or soft,
        "hard_vague": hard_vague,
        "reason": reason,
        "suggestion": suggestion,
        "token_count": len(tokens),
    }


def maybe_narrow_query(item_name: str, *, auto: bool = True) -> tuple[str, dict[str, Any]]:
    """
    Return (search_query, meta). Always normalizes handfrees→handsfree.
    Wired+handsfree gains earphones/3.5mm so search does not drift to TWS.
    When auto and hard-vague, replace with suggestion.
    """
    original = str(item_name or "").strip()
    normalized = _normalize_handsfree(original)
    meta = analyze_query_specificity(normalized)
    meta["original"] = original
    used = normalized

    if re.search(r"\bwired\b", used, re.I) and re.search(r"\bhandsfree\b", used, re.I):
        if not re.search(r"\b(earphones?|headphones?|headset)\b", used, re.I):
            used = f"{used} earphones".strip()
        if not re.search(r"\b3\.5", used, re.I):
            used = f"{used} 3.5mm".strip()
        used = re.sub(r"\s+", " ", used).strip()
        if used.lower() != normalized.lower():
            return used, {
                **meta,
                "used_query": used,
                "auto_narrowed": True,
                "reason": meta.get("reason") or "wired handsfree needs earphones/3.5mm",
                "suggestion": meta.get("suggestion")
                or "wired handsfree earphones 3.5mm wholesale",
            }

    if not meta.get("vague"):
        return used, {**meta, "used_query": used, "auto_narrowed": False}
    suggestion = str(meta.get("suggestion") or "").strip()
    if auto and meta.get("hard_vague") and suggestion:
        return suggestion, {
            **meta,
            "used_query": suggestion,
            "auto_narrowed": True,
        }
    return used, {
        **meta,
        "used_query": used,
        "auto_narrowed": False,
    }
