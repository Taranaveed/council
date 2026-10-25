"""Extract must-have specs implied by the buyer query and check listings."""
from __future__ import annotations

import re
from typing import Any

# Ordered patterns: (id, display label, match regex on query, match regex on listing blob)
_SPEC_PATTERNS: list[tuple[str, str, re.Pattern[str], re.Pattern[str]]] = [
    (
        "capacity_ml",
        "capacity (ml)",
        re.compile(r"\b(\d+)\s*ml\b", re.I),
        re.compile(r"\b{n}\s*ml\b", re.I),  # placeholder — filled per extract
    ),
    (
        "bluetooth",
        "Bluetooth",
        re.compile(r"\bbluetooth\b", re.I),
        re.compile(r"\bbluetooth\b|\bbt\b|\btws\b", re.I),
    ),
    (
        "wired",
        "wired / 3.5mm",
        # Only explicit wired / jack — "handsfree" alone is often Bluetooth
        re.compile(r"\bwired\b|\b3\.5\s*mm\b|\b3\.5mm\b|\baux\s*jack\b", re.I),
        re.compile(r"\bwired\b|\b3\.5\s*mm\b|\b3\.5mm\b|\baux\b|\bjack\b", re.I),
    ),
    (
        "wireless",
        "wireless",
        re.compile(r"\bwireless\b|\btws\b", re.I),
        re.compile(r"\bwireless\b|\btws\b|\bbluetooth\b", re.I),
    ),
    (
        "usb_c",
        "USB-C",
        re.compile(r"\busb[\s\-]?c\b|\btype[\s\-]?c\b", re.I),
        re.compile(r"\busb[\s\-]?c\b|\btype[\s\-]?c\b", re.I),
    ),
    (
        "sterling_925",
        "925 sterling silver",
        re.compile(r"\b925\b|\bsterling\b", re.I),
        re.compile(r"\b925\b|\bsterling\b", re.I),
    ),
    (
        "gold_18k",
        "18K gold",
        re.compile(r"\b18\s*k\b|\b18ct\b", re.I),
        re.compile(r"\b18\s*k\b|\b18ct\b|\b18\s*karat\b", re.I),
    ),
    (
        "ceramic",
        "ceramic",
        re.compile(r"\bceramic\b", re.I),
        re.compile(r"\bceramic\b", re.I),
    ),
    (
        "organic",
        "organic",
        re.compile(r"\borganic\b", re.I),
        re.compile(r"\borganic\b", re.I),
    ),
    (
        "waterproof",
        "waterproof / IP",
        re.compile(r"\bwaterproof\b|\bip\d{2}\b", re.I),
        re.compile(r"\bwaterproof\b|\bip\d{2}\b|\bwater[\s\-]?resist", re.I),
    ),
    (
        "pack_count",
        "pack / multipack count",
        re.compile(r"\b(\d+)\s*(?:pcs?|pieces?|pack|pair)\b", re.I),
        re.compile(r"\b{n}\s*(?:pcs?|pieces?|pack|pair)\b", re.I),
    ),
]


def extract_must_haves(query: str | None) -> list[dict[str, str]]:
    """
    Return [{id, label, query_token}] for must-haves implied by the query.
    Capacity/pack counts capture the numeric token from the query.
    """
    q = str(query or "").strip()
    if not q:
        return []
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    # Capacity ml
    for m in re.finditer(r"\b(\d+)\s*ml\b", q, re.I):
        n = m.group(1)
        sid = f"capacity_{n}ml"
        if sid not in seen:
            seen.add(sid)
            found.append({"id": sid, "label": f"{n} ml", "query_token": m.group(0), "match": n})

    # Pack counts (skip tiny 1)
    for m in re.finditer(r"\b(\d+)\s*(?:pcs?|pieces?|pack|pairs?)\b", q, re.I):
        n = m.group(1)
        if int(n) < 2:
            continue
        sid = f"pack_{n}"
        if sid not in seen:
            seen.add(sid)
            found.append({"id": sid, "label": f"{n}-pack", "query_token": m.group(0), "match": n})

    for sid, label, q_re, _ in _SPEC_PATTERNS:
        if sid in ("capacity_ml", "pack_count"):
            continue
        if sid in seen:
            continue
        if q_re.search(q):
            # Avoid double-counting wired+wireless if both appear — keep both; buyer asked
            seen.add(sid)
            found.append({"id": sid, "label": label, "query_token": label, "match": ""})

    return found


def _listing_blob(listing: dict[str, Any]) -> str:
    parts = [
        str(listing.get("title") or ""),
        str(listing.get("snippet") or ""),
        str(listing.get("note") or ""),
        str(listing.get("warranty") or ""),
    ]
    for v in listing.get("variants") or []:
        if isinstance(v, dict):
            parts.append(str(v.get("label") or ""))
        else:
            parts.append(str(v))
    return " ".join(parts).lower()


def check_listing_specs(
    listing: dict[str, Any],
    must_haves: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Return list of failed must-haves for this listing."""
    if not must_haves:
        return []
    blob = _listing_blob(listing)
    misses: list[dict[str, str]] = []
    must_ids = {str(s.get("id") or "") for s in must_haves}
    for spec in must_haves:
        sid = spec.get("id") or ""
        label = spec.get("label") or sid
        token = str(spec.get("match") or "")
        ok = False
        if sid.startswith("capacity_") and token:
            ok = bool(re.search(rf"\b{re.escape(token)}\s*ml\b", blob, re.I))
        elif sid.startswith("pack_") and token:
            ok = bool(re.search(rf"\b{re.escape(token)}\s*(?:pcs?|pieces?|pack|pairs?)\b", blob, re.I))
        else:
            for psid, _, _, list_re in _SPEC_PATTERNS:
                if psid == sid or (sid.startswith(psid)):
                    ok = bool(list_re.search(blob))
                    break
            if not ok:
                # Fuzzy: label words in blob (skip slash labels like "wired / 3.5mm")
                words = [
                    w
                    for w in re.split(r"\W+", label.lower())
                    if len(w) > 2 and w not in ("wired",)
                ]
                if "wired" in sid:
                    ok = bool(re.search(r"\bwired\b|\b3\.5\s*mm\b|\baux\b|\bjack\b", blob, re.I))
                else:
                    ok = all(w in blob for w in words) if words else False
        # Wired required + clearly wireless/TWS → always a miss
        if sid == "wired" and re.search(
            r"\b(wireless|bluetooth|tws|true\s*wireless)\b", blob, re.I
        ):
            if not re.search(r"\bwired\b|\b3\.5\s*mm\b|\baux\b", blob, re.I):
                ok = False
        # Ceramic required + stainless/steel/thermos without ceramic → miss (already)
        # plus hard contradiction when steel/thermos dominates
        if sid == "ceramic" and not ok:
            if re.search(r"\b(stainless|steel|thermos|flask)\b", blob, re.I):
                ok = False
        if not ok:
            misses.append({"id": sid, "label": label})
    return misses


def listing_satisfies_wired_intent(listing: dict[str, Any], query: str | None) -> bool:
    """When query asks for wired, require an explicit wired/jack cue; reject TWS/BT."""
    q = str(query or "").lower()
    if not re.search(r"\bwired\b|\b3\.5\s*mm\b", q):
        return True
    blob = _listing_blob(listing)
    wired = bool(re.search(r"\bwired\b|\b3\.5\s*mm\b|\baux\b|\bjack\b", blob, re.I))
    if wired:
        return True
    # No wired cue on a wired query → not a match (even vague "handsfree earphones")
    return False


def annotate_listings_with_spec_check(
    listings: list[dict[str, Any]],
    query: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    must = extract_must_haves(query)
    # If buyer said wired, drop conflicting wireless must-have extracted from "earbuds" etc.
    if any(m.get("id") == "wired" for m in must):
        must = [m for m in must if m.get("id") != "wireless"]
    out: list[dict[str, Any]] = []
    for row in listings or []:
        item = dict(row)
        if not listing_satisfies_wired_intent(item, query):
            item["spec_misses"] = [{"id": "wired", "label": "wired / 3.5mm"}]
            item["must_haves"] = must
            item["spec_ok"] = False
            item["wired_conflict"] = True
            out.append(item)
            continue
        misses = check_listing_specs(item, must)
        item["must_haves"] = must
        item["spec_misses"] = misses
        item["spec_ok"] = len(misses) == 0
        out.append(item)
    return out, must
