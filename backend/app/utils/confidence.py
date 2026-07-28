"""Deterministic confidence score for pricing advice (0–100)."""
from __future__ import annotations

import re
import statistics
from typing import Any

from app.utils.price_classifier import extract_price_value


def normalize_confidence_value(raw: Any) -> float | None:
    """Accept 0–1 or 0–100 and return 0–100, or None if invalid."""
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if 0 <= v <= 1:
        return round(v * 100, 1)
    if 0 <= v <= 100:
        return round(v, 1)
    return None


def _listing_prices(listings: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for item in listings:
        raw = item.get("price")
        if raw is None:
            continue
        val = extract_price_value(str(raw))
        if val is not None and val > 0:
            values.append(val)
    return values


def _prices_from_text(text: str) -> list[float]:
    if not text:
        return []
    # Prefer currency-ish amounts; fall back to larger numbers
    found = re.findall(
        r"(?:Rs\.?|PKR|USD|\$|€|£|INR|AED|SAR)\s*([\d,]+(?:\.\d+)?)"
        r"|([\d,]{3,}(?:\.\d+)?)",
        text,
        flags=re.I,
    )
    values: list[float] = []
    for a, b in found:
        token = a or b
        val = extract_price_value(token)
        if val is not None and val > 0:
            values.append(val)
    return values


def _coeff_of_variation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = statistics.mean(values)
    if mean <= 0:
        return None
    return statistics.pstdev(values) / mean


def _near_median(value: float, median: float, tol: float = 0.15) -> bool:
    if median <= 0:
        return False
    return abs(value - median) / median <= tol


def _mid_from_price_range(price_range: Any) -> float | None:
    if not isinstance(price_range, dict):
        return None
    lo = extract_price_value(str(price_range.get("min"))) if price_range.get("min") is not None else None
    hi = extract_price_value(str(price_range.get("max"))) if price_range.get("max") is not None else None
    if lo is not None and hi is not None and lo > 0 and hi > 0:
        return (lo + hi) / 2.0
    if lo is not None and lo > 0:
        return lo
    if hi is not None and hi > 0:
        return hi
    return None


def compute_price_confidence(
    listings: list[dict[str, Any]] | None,
    verdict: dict[str, Any] | None = None,
    transcript: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Score how trustworthy a pricing recommendation is from evidence, not LLM vibes.

    Components (approx max ~108 before clamp):
      - listing_volume   up to 42
      - price_quality    up to 28  (parseable prices + tight spread + page prices)
      - vendor_quality   up to 20  (Verified share, floor 8 if any verified)
      - agent_agreement  up to 18  (rec / range mid vs market + agent cluster)
    Soft-blend up to 20% of a normalized LLM confidence when n >= 3.
    """
    listings = listings or []
    verdict = verdict or {}
    transcript = transcript or {}

    n = len(listings)
    foreign = sum(1 for item in listings if item.get("currency_mismatch"))
    local_listings = [i for i in listings if not i.get("currency_mismatch")]
    # Prefer local-currency comps for price statistics; fall back to all if none local
    price_source_listings = local_listings if local_listings else listings

    if n == 0:
        listing_volume = 0.0
    elif n <= 2:
        listing_volume = 18.0
    elif n <= 4:
        listing_volume = 30.0
    elif n <= 7:
        listing_volume = 38.0
    else:
        listing_volume = 42.0
    # Foreign-only sample is thin evidence for a local price
    if n > 0 and not local_listings:
        listing_volume = min(listing_volume, 18.0)

    prices = _listing_prices(price_source_listings)
    parse_ratio = (len(prices) / n) if n else 0.0
    price_quality = parse_ratio * 16.0
    cv = _coeff_of_variation(prices)
    if cv is None:
        spread_bonus = 5.0 if len(prices) == 1 else 0.0
    elif cv < 0.2:
        spread_bonus = 12.0
    elif cv < 0.35:
        spread_bonus = 8.0
    elif cv < 0.5:
        spread_bonus = 4.0
    else:
        spread_bonus = 0.0
    if any(str(item.get("price_source") or "").lower() == "page" for item in listings):
        price_quality += 3.0
    price_quality = min(28.0, price_quality + spread_bonus)

    verified = sum(
        1
        for item in listings
        if str(item.get("vendor_status") or "").lower() == "verified"
    )
    if n and verified > 0:
        vendor_quality = max(8.0, verified / n * 20.0)
    else:
        vendor_quality = 0.0

    agent_agreement = 0.0
    # Don't score "agreement" against a foreign-currency median when seller is local-currency
    median = None
    if local_listings:
        median = statistics.median(prices) if prices else None
    rec_raw = verdict.get("recommended_price")
    rec_val = extract_price_value(str(rec_raw)) if rec_raw is not None else None
    range_mid = _mid_from_price_range(verdict.get("price_range"))

    if median is not None:
        if rec_val is not None and _near_median(rec_val, median, 0.2):
            agent_agreement += 10.0
        elif range_mid is not None and _near_median(range_mid, median, 0.2):
            agent_agreement += 8.0

    agent_prices: list[float] = []
    for name in ("premium_maximizer", "volume_discounter", "market_benchmark", "market_skeptic"):
        agent_prices.extend(_prices_from_text(transcript.get(name, "")))
    if len(agent_prices) >= 2:
        agent_cv = _coeff_of_variation(agent_prices)
        if agent_cv is not None and agent_cv < 0.25:
            agent_agreement += 8.0
        elif agent_cv is not None and agent_cv < 0.35:
            agent_agreement += 5.0
        elif agent_cv is not None and agent_cv < 0.4:
            agent_agreement += 3.0
    elif median is not None and rec_val is not None and _near_median(rec_val, median, 0.1):
        agent_agreement += 3.0
    agent_agreement = min(18.0, agent_agreement)

    computed = listing_volume + price_quality + vendor_quality + agent_agreement

    # Soft blend with judge self-score when evidence exists (does not rescue empty markets).
    llm = normalize_confidence_value(verdict.get("confidence"))
    if llm is not None and n >= 3 and local_listings:
        score = 0.8 * computed + 0.2 * llm
    elif llm is not None and n > 0:
        score = 0.85 * computed + 0.15 * llm
    else:
        score = computed

    # Hard rules from evidence quality
    if n == 0:
        score = min(score, 30.0)
    elif not local_listings and n > 0:
        # Foreign-only comps cannot support a high local-market confidence
        score = min(score, 55.0)
    elif len(local_listings) >= 5 and parse_ratio >= 0.6 and (cv is None or cv < 0.35):
        score = max(score, 78.0)
        if verified >= 1:
            score = max(score, 85.0)
    if verified == 0 and 0 < n < 5:
        score = min(score, 88.0)

    score = int(round(max(0.0, min(100.0, score))))

    return {
        "confidence": score,
        "confidence_breakdown": {
            "listing_volume": round(listing_volume, 1),
            "price_quality": round(price_quality, 1),
            "vendor_quality": round(vendor_quality, 1),
            "agent_agreement": round(agent_agreement, 1),
            "llm_hint": llm,
            "listing_count": n,
            "local_listing_count": len(local_listings),
            "foreign_listing_count": foreign,
            "parseable_prices": len(prices),
            "verified_vendors": verified,
            "price_spread_cv": round(cv, 3) if cv is not None else None,
        },
    }


_GENERIC_CHANNELS = re.compile(
    r"^(social media|online advertising|digital marketing|internet|online|"
    r"ads|advertising|marketing)$",
    re.I,
)


def compute_audience_confidence(
    *,
    product_name: str,
    problem_solved: str,
    location: str | None,
    currency: str | None,
    price_min: str | None,
    price_max: str | None,
    verdict: dict[str, Any],
    listing_count: int = 0,
) -> dict[str, Any]:
    """Score audience advice from input detail + persona/channel quality (0–100)."""
    input_detail = 0.0
    name_len = len((product_name or "").strip())
    problem_len = len((problem_solved or "").strip())
    if name_len >= 4:
        input_detail += 8.0
    if name_len >= 12:
        input_detail += 4.0
    if problem_len >= 20:
        input_detail += 10.0
    if problem_len >= 60:
        input_detail += 6.0
    if (location or "").strip():
        input_detail += 10.0
    if (currency or "").strip() and (currency or "").upper() != "USD":
        input_detail += 4.0
    elif (currency or "").strip():
        input_detail += 2.0
    if (price_min or "").strip() and (price_max or "").strip():
        input_detail += 10.0
    input_detail = min(40.0, input_detail)

    personas = verdict.get("personas") if isinstance(verdict.get("personas"), list) else []
    persona_quality = 0.0
    if len(personas) >= 3:
        persona_quality += 12.0
    elif len(personas) >= 2:
        persona_quality += 6.0

    ages = {
        str(p.get("age_range") or "").strip().lower()
        for p in personas
        if isinstance(p, dict) and str(p.get("age_range") or "").strip()
    }
    jobs = {
        str(p.get("job_or_role") or "").strip().lower()
        for p in personas
        if isinstance(p, dict) and str(p.get("job_or_role") or "").strip()
    }
    if len(ages) >= 3:
        persona_quality += 10.0
    elif len(ages) >= 2:
        persona_quality += 5.0
    if len(jobs) >= 3:
        persona_quality += 8.0
    elif len(jobs) >= 2:
        persona_quality += 4.0

    objections = sum(
        1
        for p in personas
        if isinstance(p, dict) and str(p.get("main_objection") or "").strip()
    )
    if objections >= 3:
        persona_quality += 5.0
    elif objections >= 1:
        persona_quality += 2.0
    persona_quality = min(35.0, persona_quality)

    channel_quality = 0.0
    top = str(verdict.get("top_channel_recommendation") or "").strip()
    if top and not _GENERIC_CHANNELS.match(top):
        channel_quality += 8.0
        if len(top) >= 12:
            channel_quality += 4.0
    plan = verdict.get("channel_plan") if isinstance(verdict.get("channel_plan"), list) else []
    specific_steps = 0
    for item in plan:
        if not isinstance(item, dict):
            continue
        ch = str(item.get("channel") or "").strip()
        action = str(item.get("example_action") or "").strip()
        if ch and not _GENERIC_CHANNELS.match(ch):
            specific_steps += 1
        if len(action) >= 20:
            specific_steps += 1
    channel_quality += min(8.0, specific_steps * 2.0)
    channel_quality = min(20.0, channel_quality)

    market_bonus = 0.0
    if listing_count >= 5:
        market_bonus = 8.0
    elif listing_count >= 1:
        market_bonus = 5.0

    computed = input_detail + persona_quality + channel_quality + market_bonus
    llm = normalize_confidence_value(verdict.get("confidence"))
    if llm is not None and len(personas) >= 3:
        score = 0.75 * computed + 0.25 * llm
    elif llm is not None:
        score = 0.8 * computed + 0.2 * llm
    else:
        score = computed

    if not (location or "").strip():
        score = min(score, 72.0)
    if len(ages) <= 1 and len(personas) >= 2:
        score = min(score, 72.0)
    if not top or _GENERIC_CHANNELS.match(top):
        score = min(score, 78.0)

    score = int(round(max(0.0, min(100.0, score))))
    return {
        "confidence": score,
        "confidence_breakdown": {
            "input_detail": round(input_detail, 1),
            "persona_quality": round(persona_quality, 1),
            "channel_quality": round(channel_quality, 1),
            "market_bonus": round(market_bonus, 1),
            "llm_hint": llm,
            "persona_count": len(personas),
            "distinct_age_bands": len(ages),
            "listing_count": listing_count,
        },
    }
