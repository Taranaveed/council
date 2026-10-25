from __future__ import annotations

import asyncio
import re
import time as _time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.agents.audience_discovery_prompts import (
    audience_judge_prompt,
    demographic_scout_prompt,
    psychographic_analyst_prompt,
    utility_specialist_prompt,
)
from app.agents.deal_finder_prompts import (
    NO_LIVE_LISTINGS_THRIFT_REPLY,
    apply_empty_listings_gate,
    contextual_persona_prompt,
    deal_judge_prompt,
    risk_analyst_prompt,
    thrift_advocate_prompt,
)
from app.agents.price_bargaining_prompts import (
    market_benchmark_prompt,
    market_skeptic_prompt,
    premium_maximizer_prompt,
    price_judge_prompt,
    volume_discounter_prompt,
)
from app.core.agent_orchestrator import AgentOrchestrator
from app.core.auth import get_current_user
from app.core.debate_runner import run_agent_debate, run_three_agent_debate
from app.utils.listing_channel import (
    annotate_listing_channels,
    bulk_quote_guidance,
)
from app.utils.spec_check import annotate_listings_with_spec_check
from app.core.market_client import (
    fetch_market_prices,
    fetch_page_facts_for_listings,
    format_market_block,
    listings_to_market_context,
)
from app.db.marketplaces import get_marketplace_by_slug, infer_location_context
from app.models.modes import (
    AudienceDiscoveryRequest,
    AudienceDiscoveryResponse,
    DealFinderRequest,
    DealFinderResponse,
    LaunchPackRequest,
    LaunchPackResponse,
    LaunchPackVariantResult,
    PriceBargainingRequest,
    PriceBargainingResponse,
)
from app.utils.confidence import compute_audience_confidence, compute_price_confidence
from app.utils.listing_links import (
    apply_high_risk_bulk_guard,
    coerce_verdict_when_listings_exist,
)
from app.utils.landed_cost import compute_landed_cost
from app.utils.listing_risk import build_listing_risk_flags, risk_score_from_flags
from app.utils.fact_sheet import build_listing_fact_sheet, fact_sheet_for_prompt
from app.utils.money import parse_money
from app.utils.price_stats import build_price_explanation, prepare_seller_comps
from app.utils.query_specificity import maybe_narrow_query
from app.utils.relevance import (
    filter_relevant_priced_listings,
    no_good_matches_verdict,
)
from app.utils.search_query import shorten_product_query
from app.utils.seller_pack import (
    build_action_pack,
    build_channel_creatives,
    build_export_text,
    empty_state_note,
)
from app.utils.vendor_check import enrich_listings_with_vendor_status
from app.utils.verdict_prose import apply_verified_prose
from app.utils.verdict_verify import clear_best_pick, verify_verdict_against_listings
from app.utils.claim_dispute import apply_disputed_to_listings
from app.utils.run_log import write_run_log
from app.utils.cost_assumptions import destination_prompt_block, shared_cost_assumptions
from app.utils.debate_gates import apply_risk_hard_signal
from app.utils.total_consistency import check_totals_consistency
from app.utils.verdict_hedge import hedge_verdict_confidence
from app.utils.sourced_facts import scrub_agent_texts, scrub_unsourced_coverage_brands

router = APIRouter(prefix="/api/modes", tags=["modes"])


def _public_agent_error() -> HTTPException:
    return HTTPException(
        status_code=502,
        detail="The agents could not finish this run. Wait a moment and try again.",
    )


def _no_comps_price_verdict(req_min: str, req_max: str, currency: str) -> dict[str, Any]:
    band = f"{req_min}–{req_max} {currency}".strip()
    return {
        "recommended_price": band,
        "promo_floor": req_min,
        "price_range": {"min": req_min, "max": req_max},
        "confidence": 8,
        "summary": (
            "No live comps were returned, so this is your stated range — not a verified market price."
        ),
        "why_this_price": (
            "Search did not return usable listings. Re-run with a clearer product name before locking a public list price."
        ),
        "key_argument_for": "",
        "key_argument_against": "Insufficient live listing data.",
        "market_context": [],
    }


def _no_comps_price_transcript() -> dict[str, str]:
    return {
        "market_benchmark": (
            "[NO LIVE COMPS] Search returned no usable listings. "
            "List price stays inside the seller's stated range and is not a market median."
        )
    }


def _economics_block(req: Any) -> str:
    parts: list[str] = []
    cogs = getattr(req, "cost_of_goods", None)
    margin = getattr(req, "target_margin_pct", None)
    condition = getattr(req, "condition", None)
    category = getattr(req, "category", None)
    comps = getattr(req, "competitor_links", None)
    if cogs:
        parts.append(f"Cost of goods: {cogs}")
    if margin:
        parts.append(f"Target margin %: {margin}")
    if condition:
        parts.append(f"Condition / make: {condition}")
    if category:
        parts.append(f"Category: {category}")
    if comps:
        parts.append(f"Competitor links / notes: {comps}")
    return ("\n".join(parts) + "\n") if parts else ""


async def _load_listings(
    product_name: str,
    location: str | None,
    currency: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    query = shorten_product_query(product_name)
    listings, warning = await fetch_market_prices(
        query,
        location,
        limit=14,
        preferred_currency=currency,
    )
    listings = await enrich_listings_with_vendor_status(listings)
    # Seller comps need live product prices in the seller's currency — not raw SERP junk
    listings = prepare_seller_comps(
        listings,
        query=query or product_name or "",
        currency=currency,
        limit=10,
    )
    return listings, warning


def _merge_warning(listings: list, fetch_warning: str | None, empty_msg: str) -> str | None:
    if not listings:
        return fetch_warning or empty_msg
    return fetch_warning if fetch_warning else None


async def _run_price_debate(
    *,
    context: str,
    lean: bool = False,
) -> tuple[dict[str, str], dict[str, Any], str | None]:
    if lean:
        agents = [
            ("premium_maximizer", premium_maximizer_prompt()),
            ("volume_discounter", volume_discounter_prompt()),
            ("market_benchmark", market_benchmark_prompt()),
        ]
        return await run_agent_debate(
            context=context,
            agents=agents,
            judge_prompt=price_judge_prompt(),
            agent_max_tokens=280,
            judge_max_tokens=1400,
        )
    return await run_agent_debate(
        context=context,
        agents=[
            ("premium_maximizer", premium_maximizer_prompt()),
            ("volume_discounter", volume_discounter_prompt()),
            ("market_skeptic", market_skeptic_prompt()),
            ("market_benchmark", market_benchmark_prompt()),
        ],
        judge_prompt=price_judge_prompt(),
    )


async def _run_audience_debate(
    *,
    context: str,
    lean: bool = False,
) -> tuple[dict[str, str], dict[str, Any], str | None]:
    return await run_three_agent_debate(
        context=context,
        agent1_prompt=demographic_scout_prompt(),
        agent1_name="demographic_scout",
        agent2_prompt=psychographic_analyst_prompt(),
        agent2_name="psychographic_analyst",
        agent3_prompt=utility_specialist_prompt(),
        agent3_name="utility_specialist",
        judge_prompt=audience_judge_prompt(),
        agent_max_tokens=280 if lean else 400,
        judge_max_tokens=1400 if lean else 1600,
    )


def _finalize_price_verdict(
    verdict: dict[str, Any],
    listings: list[dict[str, Any]],
    transcript: dict[str, str],
    req_min: str,
    req_max: str,
) -> dict[str, Any]:
    if not verdict:
        verdict = {
            "recommended_price": f"{req_min}–{req_max}",
            "price_range": {"min": req_min, "max": req_max},
            "confidence": 0,
            "summary": "Judge response could not be parsed.",
            "key_argument_for": "",
            "key_argument_against": "",
            "market_context": [],
        }
    verdict["market_context"] = listings_to_market_context(listings)
    conf = compute_price_confidence(listings, verdict, transcript)
    verdict["confidence"] = conf["confidence"]
    verdict["confidence_breakdown"] = conf["confidence_breakdown"]
    return verdict


def _finalize_audience_verdict(
    verdict: dict[str, Any],
    *,
    product_name: str,
    problem_solved: str,
    location: str | None,
    currency: str,
    price_min: str | None,
    price_max: str | None,
    listings: list[dict[str, Any]],
) -> dict[str, Any]:
    if not verdict:
        verdict = {
            "personas": [],
            "summary": "Judge response could not be parsed.",
            "top_channel_recommendation": "",
            "channel_plan": [],
            "confidence": 0,
        }
    conf = compute_audience_confidence(
        product_name=product_name,
        problem_solved=problem_solved,
        location=location,
        currency=currency,
        price_min=price_min,
        price_max=price_max,
        verdict=verdict,
        listing_count=len(listings),
    )
    verdict["confidence"] = conf["confidence"]
    verdict["confidence_breakdown"] = conf["confidence_breakdown"]
    if listings:
        verdict["market_context"] = listings_to_market_context(listings)
    return verdict


async def _build_variant_pack(
    *,
    label: str,
    product_name: str,
    product_specs: str,
    problem_solved: str,
    price_min: str,
    price_max: str,
    currency: str,
    location: str | None,
    economics: Any,
    listings: list[dict[str, Any]],
    market_warning: str | None,
    lean: bool = True,
) -> LaunchPackVariantResult:
    econ = _economics_block(economics)
    market_block = format_market_block(listings, preferred_currency=currency)
    price_context = (
        f"Product name: {product_name}\n"
        f"Product specs:\n{product_specs}\n\n"
        f"Problem solved: {problem_solved}\n"
        f"Estimated price range: {price_min} – {price_max} {currency}\n"
        f"Seller currency (REQUIRED for recommended_price): {currency}\n"
        f"Location hint: {location or 'not provided'}\n"
        f"{econ}\n"
        f"{market_block}"
    )
    location_context = infer_location_context(location) if location else {}
    region_notes = ""
    if location_context.get("currency"):
        region_notes = (
            f"Inferred regional currency: {location_context.get('currency')}. "
            "Prefer local income language and platforms for this market.\n"
        )
    audience_context = (
        f"Product name: {product_name}\n"
        f"Product specs:\n{product_specs}\n"
        f"Primary problem it solves: {problem_solved}\n"
        f"Seller location / market: {location or 'not provided'}\n"
        f"Currency for all prices and willingness-to-pay: {currency}\n"
        f"Seller price band: {price_min} – {price_max} {currency}\n"
        f"{econ}"
        f"{region_notes}"
        f"{market_block}"
    )

    try:
        if listings:
            price_result, audience_result = await asyncio.gather(
                _run_price_debate(context=price_context, lean=lean),
                _run_audience_debate(context=audience_context, lean=lean),
            )
            price_t, price_v, _price_raw = price_result
            aud_t, aud_v, _aud_raw = audience_result
        else:
            audience_result = await _run_audience_debate(context=audience_context, lean=lean)
            aud_t, aud_v, _aud_raw = audience_result
            price_t = _no_comps_price_transcript()
            price_v = _no_comps_price_verdict(price_min, price_max, currency)
    except HTTPException:
        raise
    except Exception:
        raise _public_agent_error()
    price_v = _finalize_price_verdict(price_v, listings, price_t, price_min, price_max)
    aud_v = _finalize_audience_verdict(
        aud_v,
        product_name=product_name,
        problem_solved=problem_solved,
        location=location,
        currency=currency,
        price_min=price_min,
        price_max=price_max,
        listings=listings,
    )
    explanation = build_price_explanation(
        listings=listings,
        currency=currency,
        price_min=price_min,
        price_max=price_max,
        recommended_price=str(price_v.get("recommended_price") or ""),
        cost_of_goods=getattr(economics, "cost_of_goods", None),
        target_margin_pct=getattr(economics, "target_margin_pct", None),
    )
    # Keep deterministic why when comps exist — LLM prose often invents
    # "verified" / "near cluster" claims that fight the numbers.
    if not explanation.get("why") and price_v.get("why_this_price"):
        explanation["why"] = str(price_v.get("why_this_price") or "").strip()

    action = build_action_pack(
        price_verdict=price_v,
        audience_verdict=aud_v,
        explanation=explanation,
        product_name=product_name,
        condition=getattr(economics, "condition", None),
    )
    creatives = build_channel_creatives(
        aud_v,
        product_name=product_name,
        problem_solved=problem_solved,
        list_price=action.get("list_price"),
        location=location,
    )
    note = empty_state_note(explanation, market_warning)
    export = build_export_text(
        product_name=product_name,
        location=location,
        action_pack=action,
        explanation=explanation,
        audience_verdict=aud_v,
        creatives=creatives,
    )
    return LaunchPackVariantResult(
        label=label,
        product_name=product_name,
        price_verdict=price_v,
        audience_verdict=aud_v,
        price_transcript=price_t,
        audience_transcript=aud_t,
        price_explanation=explanation,
        action_pack=action,
        channel_creatives=creatives,
        export_text=export,
        empty_state_note=note,
        market_listings=listings,
        market_warning=market_warning,
    )


@router.post("/price-bargaining", response_model=PriceBargainingResponse)
async def price_bargaining(
    req: PriceBargainingRequest,
    _user: dict = Depends(get_current_user),
):
    search_name = req.product_name or req.product_specs
    listings, fetch_warning = await _load_listings(search_name, req.location, req.currency)
    market_warning = _merge_warning(
        listings,
        fetch_warning,
        "Live market data unavailable; agents used form input only.",
    )
    market_block = format_market_block(listings, preferred_currency=req.currency)
    context = (
        f"Product specs:\n{req.product_specs}\n\n"
        f"Estimated price range: {req.price_range_min} – {req.price_range_max} {req.currency}\n"
        f"Seller currency (REQUIRED for recommended_price): {req.currency}\n"
        f"Location hint: {req.location or 'not provided'}\n"
        f"{_economics_block(req)}\n"
        f"{market_block}"
    )

    if not listings:
        transcript_raw = _no_comps_price_transcript()
        verdict = _no_comps_price_verdict(req.price_range_min, req.price_range_max, req.currency)
        raw = None
    else:
        try:
            transcript_raw, verdict, raw = await _run_price_debate(context=context, lean=False)
        except Exception:
            raise _public_agent_error()
    verdict = _finalize_price_verdict(
        verdict, listings, transcript_raw, req.price_range_min, req.price_range_max
    )
    explanation = build_price_explanation(
        listings=listings,
        currency=req.currency,
        price_min=req.price_range_min,
        price_max=req.price_range_max,
        recommended_price=str(verdict.get("recommended_price") or ""),
        cost_of_goods=req.cost_of_goods,
        target_margin_pct=req.target_margin_pct,
    )
    action = build_action_pack(
        price_verdict=verdict,
        audience_verdict={},
        explanation=explanation,
        product_name=req.product_name or shorten_product_query(req.product_specs),
        condition=req.condition,
    )
    return PriceBargainingResponse(
        transcript=transcript_raw,
        verdict=verdict,
        market_listings=listings,
        market_warning=market_warning,
        raw_verdict=raw,
        price_explanation=explanation,
        action_pack=action,
        empty_state_note=empty_state_note(explanation, market_warning),
    )


@router.post("/audience-discovery", response_model=AudienceDiscoveryResponse)
async def audience_discovery(
    req: AudienceDiscoveryRequest,
    _user: dict = Depends(get_current_user),
):
    location = (req.location or "").strip() or None
    location_context = infer_location_context(location) if location else {}
    currency = (req.currency or "").strip() or (location_context.get("currency") or "USD")
    price_min = (req.price_range_min or "").strip() or None
    price_max = (req.price_range_max or "").strip() or None

    listings, fetch_warning = await _load_listings(req.product_name, location, currency)
    market_warning = _merge_warning(
        listings,
        fetch_warning,
        (
            "Live local prices unavailable; audience advice used your form details only."
            if location
            else "Live market data unavailable; agents used form input only."
        ),
    )
    market_block = format_market_block(listings, preferred_currency=currency) if listings else ""
    price_band = (
        f"{price_min} – {price_max} {currency}"
        if price_min and price_max
        else f"not provided (currency for answers: {currency})"
    )
    region_notes = ""
    if location_context.get("currency"):
        region_notes = (
            f"Inferred regional currency: {location_context.get('currency')}. "
            "Prefer local income language and platforms for this market.\n"
        )
    specs = (req.product_specs or "").strip()
    context = (
        f"Product name: {req.product_name}\n"
        + (f"Product specs:\n{specs}\n" if specs else "")
        + f"Primary problem it solves: {req.problem_solved}\n"
        f"Seller location / market: {location or 'not provided'}\n"
        f"Currency for all prices and willingness-to-pay: {currency}\n"
        f"Seller price band: {price_band}\n"
        f"{_economics_block(req)}"
        f"{region_notes}"
        f"{market_block}"
    )

    try:
        transcript_raw, verdict, raw = await _run_audience_debate(context=context, lean=False)
    except Exception:
        raise _public_agent_error()
    verdict = _finalize_audience_verdict(
        verdict,
        product_name=req.product_name,
        problem_solved=req.problem_solved,
        location=location,
        currency=currency,
        price_min=price_min,
        price_max=price_max,
        listings=listings,
    )
    explanation = build_price_explanation(
        listings=listings,
        currency=currency,
        price_min=price_min,
        price_max=price_max,
        recommended_price=None,
        cost_of_goods=req.cost_of_goods,
        target_margin_pct=req.target_margin_pct,
    )
    creatives = build_channel_creatives(
        verdict,
        product_name=req.product_name,
        problem_solved=req.problem_solved,
        list_price=explanation.get("list_price_suggestion"),
        location=location,
    )
    action = build_action_pack(
        price_verdict={},
        audience_verdict=verdict,
        explanation=explanation,
        product_name=req.product_name,
        condition=req.condition,
    )
    return AudienceDiscoveryResponse(
        transcript=transcript_raw,
        verdict=verdict,
        market_listings=listings,
        market_warning=market_warning,
        raw_verdict=raw,
        channel_creatives=creatives,
        action_pack=action,
        empty_state_note=empty_state_note(explanation, market_warning),
    )


@router.post("/launch-pack", response_model=LaunchPackResponse)
async def launch_pack(
    req: LaunchPackRequest,
    _user: dict = Depends(get_current_user),
):
    location = (req.location or "").strip() or None
    currency = (req.currency or "USD").strip() or "USD"
    listings, fetch_warning = await _load_listings(req.product_name, location, currency)
    market_warning = _merge_warning(
        listings,
        fetch_warning,
        "Live market data unavailable; launch pack used your form details only.",
    )

    primary = await _build_variant_pack(
        label="Variant A",
        product_name=req.product_name,
        product_specs=req.product_specs,
        problem_solved=req.problem_solved,
        price_min=req.price_range_min,
        price_max=req.price_range_max,
        currency=currency,
        location=location,
        economics=req,
        listings=listings,
        market_warning=market_warning,
        lean=True,
    )

    variant_b = None
    comparison_note = None
    b_name = (req.variant_b_name or "").strip()
    b_specs = (req.variant_b_specs or "").strip()
    if b_name and b_specs:
        b_listings, b_warn = await _load_listings(b_name, location, currency)
        b_warning = _merge_warning(
            b_listings,
            b_warn or fetch_warning,
            "Live market data unavailable for variant B.",
        )
        variant_b = await _build_variant_pack(
            label="Variant B",
            product_name=b_name,
            product_specs=b_specs,
            problem_solved=req.problem_solved,
            price_min=req.price_range_min,
            price_max=req.price_range_max,
            currency=currency,
            location=location,
            economics=req,
            listings=b_listings or listings,
            market_warning=b_warning,
            lean=True,
        )
        a_price = primary.action_pack.get("list_price") or "—"
        b_price = variant_b.action_pack.get("list_price") or "—"
        a_ch = primary.action_pack.get("top_channel") or "—"
        b_ch = variant_b.action_pack.get("top_channel") or "—"
        comparison_note = (
            f"{req.product_name} suggested list {a_price} via {a_ch}. "
            f"{b_name} suggested list {b_price} via {b_ch}. "
            "Pick the SKU with clearer local comps and a tighter buyer objection."
        )

    return LaunchPackResponse(
        primary=primary,
        variant_b=variant_b,
        comparison_note=comparison_note,
        market_listings=listings,
        market_warning=market_warning,
    )


@router.post("/deal-finder", response_model=DealFinderResponse)
async def deal_finder(
    req: DealFinderRequest,
    _user: dict = Depends(get_current_user),
):
    from app.db.credits import assert_can_run

    credits = assert_can_run(int(_user["id"]))
    if credits.get("exhausted"):
        raise HTTPException(
            status_code=402,
            detail=(
                f"Free plan limit reached ({credits.get('used_this_month')}/"
                f"{credits.get('limit')} briefs this month). "
                "Upgrade or wait until next month."
            ),
        )

    marketplace = req.marketplace
    profile = get_marketplace_by_slug(marketplace) if marketplace else None
    location_context = infer_location_context(req.location)
    marketplace_label = (profile or {}).get("name") or marketplace or "unspecified"
    explicit_currency = (req.currency or "").strip().upper()
    inferred_currency = (location_context.get("currency") or "").strip()
    if inferred_currency.lower().startswith("local"):
        inferred_currency = ""
    local_currency = explicit_currency or inferred_currency
    if explicit_currency:
        location_context = {**location_context, "currency": explicit_currency}

    # RegionProfile gate — unsupported countries must not silently fall back to UK/PK rates
    from app.core.region_profile import RegionNotSupportedError, require_supported_profile

    try:
        region_profile = require_supported_profile(
            location=req.location,
            country_code=None,
            currency=local_currency or None,
        )
        location_context = {
            **location_context,
            "region_profile_id": str(region_profile.get("id") or ""),
            "trade_zone": str(region_profile.get("trade_zone") or location_context.get("trade_zone") or ""),
            "regulatory_focus": str(
                region_profile.get("regulatory_focus")
                or location_context.get("regulatory_focus")
                or ""
            ),
        }
        if not local_currency and region_profile.get("currency"):
            local_currency = str(region_profile["currency"]).upper()
            location_context = {**location_context, "currency": local_currency}
    except RegionNotSupportedError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "region_not_supported",
                "message": str(exc.detail),
                "profile_id": exc.profile_id,
                "supported": ["pk", "uk"],
            },
        ) from exc

    qty = req.quantity if isinstance(req.quantity, int) and req.quantity > 0 else None
    mode = (req.buying_mode or "retail").strip().lower()
    if mode not in ("retail", "bulk"):
        mode = "retail"
    is_bulk = mode == "bulk" or (qty is not None and qty >= 5)

    budget_hint = ""
    if req.max_budget:
        budget_hint = f"under {req.max_budget} {local_currency}".strip()

    product_query, query_meta = maybe_narrow_query(req.item_name, auto=True)
    bulk_terms = "wholesale bulk supplier MOQ" if is_bulk else ""
    qty_hint = f"{qty} units" if qty and qty > 1 else ""
    if is_bulk:
        search_query = product_query.strip()
    else:
        search_query = " ".join(
            part for part in [product_query, qty_hint, budget_hint, req.location] if part
        ).strip()
    fetch_limit = 16 if is_bulk else 12

    listings, fetch_warning = await fetch_market_prices(
        search_query or product_query,
        req.location,
        limit=fetch_limit,
        preferred_currency=local_currency or None,
        bulk_mode=is_bulk,
        quantity=qty,
        budget=req.max_budget,
        use_cache=True,
    )
    warn_l = (fetch_warning or "").lower()
    quota_hit = "run out of searches" in warn_l or "quota" in warn_l
    # Avoid burning more SerpApi when the account is exhausted
    if not listings and (req.max_budget or is_bulk) and not quota_hit:
        fallback_query = " ".join(
            part for part in [product_query, bulk_terms if is_bulk else "", req.location] if part
        ).strip()
        listings, fetch_warning2 = await fetch_market_prices(
            fallback_query or product_query,
            req.location,
            limit=fetch_limit,
            preferred_currency=local_currency or None,
            bulk_mode=is_bulk,
            quantity=qty,
            budget=req.max_budget,
            use_cache=True,
        )
        fetch_warning = fetch_warning or fetch_warning2
        warn_l = (fetch_warning or "").lower()
        quota_hit = "run out of searches" in warn_l or "quota" in warn_l

    if (is_bulk and not quota_hit):
        wholesale_hosts = (
            "alibaba.", "indiamart.", "made-in-china.", "dhgate.",
            "globalsources.", "tradeindia.", "aliexpress.", "europages.",
            "thomasnet.", "faire.",
        )
        wholesale_count = sum(
            1 for x in listings
            if any(h in str(x.get("link") or "").lower() for h in wholesale_hosts)
        )
        # Skip costly second Serp pass when we already have enough comps
        # (local-first market-service already searched wholesale when needed).
        enough_comps = len(listings) >= 6
        if wholesale_count < 2 and not enough_comps:
            extra, _ = await fetch_market_prices(
                f"{product_query} wholesale supplier".strip(),
                req.location,
                limit=fetch_limit,
                preferred_currency=local_currency or None,
                bulk_mode=True,
                quantity=qty,
                budget=req.max_budget,
                use_cache=True,
            )
            seen = {str(x.get("link") or "").strip() for x in listings}
            for row in extra:
                link = str(row.get("link") or "").strip()
                if link and link not in seen:
                    listings.append(row)
                    seen.add(link)
                if len(listings) >= fetch_limit:
                    break
    elif is_bulk and quota_hit:
        fetch_warning = (
            f"{fetch_warning or ''} SerpApi search quota exhausted — "
            "results may be thin until the key renews; try Alibaba catalog / local shops."
        ).strip()

    listings = await enrich_listings_with_vendor_status(listings)
    listings = annotate_listing_channels(listings, is_bulk=is_bulk)
    listings, must_haves = annotate_listings_with_spec_check(listings, product_query or req.item_name)

    # Page facts — only top pick, and only if market-service didn't already enrich it
    top = listings[:1]
    if top and any(not r.get("page_facts_fetched") for r in top):
        refreshed = await fetch_page_facts_for_listings(
            top,
            query=product_query or req.item_name,
            preferred_currency=local_currency or None,
            location=req.location,
        )
        by_link = {str(r.get("link") or ""): r for r in refreshed}
        listings = [
            {**row, **by_link[str(row.get("link") or "")]}
            if str(row.get("link") or "") in by_link
            else row
            for row in listings
        ]
        listings = annotate_listing_channels(listings, is_bulk=is_bulk)
        listings, must_haves = annotate_listings_with_spec_check(
            listings, product_query or req.item_name
        )

    bulk_quote = bulk_quote_guidance(listings, is_bulk=is_bulk)

    # Relevance gate: only product-detail pages with parseable unit prices count
    kept, dropped, rel_meta = filter_relevant_priced_listings(
        listings, product_query or req.item_name, is_bulk=is_bulk
    )
    # Receipt-friendly tallies for the buyer UI (why rows were excluded)
    drop_reasons: dict[str, int] = {}
    for row in dropped:
        key = str(row.get("drop_reason") or "other")
        drop_reasons[key] = drop_reasons.get(key, 0) + 1
    rel_meta = {**rel_meta, "drop_reasons": drop_reasons}
    if rel_meta.get("no_good_matches"):
        from app.utils.relevance import is_reviewable_product_listing, listing_relevant_to_query

        # Still surface product-detail seller links (even if price needs confirmation)
        reviewable = [
            dict(row)
            for row in listings
            if is_reviewable_product_listing(row)
            and listing_relevant_to_query(row, product_query or req.item_name)
        ]
        verdict = no_good_matches_verdict(
            product_query or req.item_name, dropped=len(dropped)
        )
        verdict = apply_verified_prose(verdict, landed=None, budget=None)
        if reviewable:
            verdict["summary"] = (
                f"Found {len(reviewable)} supplier page(s) for “{product_query or req.item_name}”, "
                "but fewer than 2 have a parseable unit price. Open the seller links to confirm MOQ and price."
            )
            if isinstance(verdict.get("winner"), dict):
                verdict["winner"]["reason"] = verdict["summary"]
                verdict["winner"]["title"] = str(reviewable[0].get("title") or "")[:120]
                verdict["winner"]["vendor"] = str(reviewable[0].get("vendor") or "")
                verdict["winner"]["link"] = str(reviewable[0].get("link") or "")
                verdict["winner"]["price"] = str(reviewable[0].get("price") or "See listing")
            verdict["agent_breakdown"] = {
                "thrift_advocate": "Supplier pages exist — confirm unit price and MOQ on each listing before buying.",
                "risk_analyst": "Do not treat missing snippet prices as zero cost; verify on the seller site.",
                "contextual_persona": "Open 2–3 links, note MOQ and shipping, then refine if needed.",
            }
        # Prefer priced kept rows; else show reviewable product pages (no Best-pick badge).
        display = clear_best_pick(kept if kept else reviewable[:12])
        for row in display:
            if row.get("wired_conflict") or any(
                isinstance(m, dict) and m.get("id") == "wired"
                for m in (row.get("spec_misses") or [])
            ):
                row["rank_reason"] = (
                    "Does not match wired / 3.5mm — shown only as a rejected result."
                )
            elif not kept and row.get("needs_price_confirm"):
                row["rank_reason"] = "Confirm unit price and MOQ on the seller page."
        warn_bits = [
            fetch_warning,
            f"Relevance: {rel_meta.get('relevant_priced_count', 0)} usable product-detail "
            f"listings after dropping {len(dropped)} off-category/storefront/wrong-spec rows.",
            (
                f"Showing {len(display)} supplier page(s) — confirm prices on-site."
                if display and not kept
                else "No good matches — refine your query (product type, connector, material)."
            ),
        ]
        q_low = (product_query or req.item_name or "").lower()
        checklist = [
            "Refine your query",
            "Search again with a specific product type",
        ]
        if re.search(r"\bwired\b", q_low):
            warn_bits.append(
                "Wired intent: results looked wireless/TWS or lacked a parseable unit price. "
                "Try “wired handsfree earphones 3.5mm wholesale”."
            )
            checklist = [
                "Try “wired handsfree earphones 3.5mm wholesale”",
                "Add 3.5mm / aux jack to the query",
                "Avoid “TWS / wireless / earbuds” results",
            ]
        elif query_meta.get("vague") and query_meta.get("suggestion"):
            warn_bits.append(
                f"Try a clearer query such as “{query_meta.get('suggestion')}”."
            )
            checklist.insert(0, f"Try “{query_meta.get('suggestion')}”")
            if query_meta.get("options"):
                warn_bits.append(
                    "Options: " + "; ".join(str(o) for o in query_meta["options"][:4])
                )
        market_warning = " ".join(b for b in warn_bits if b)
        fact_flags = build_listing_risk_flags(
            display, winner=None, query=req.item_name
        )
        risk_nm = risk_score_from_flags(fact_flags)
        brief_id_nm: int | None = None
        compare_nm: dict[str, Any] | None = None
        try:
            from app.db import briefs as briefs_db

            saved_nm = briefs_db.save_brief(
                user_id=int(_user["id"]),
                run_id=None,
                item_name=product_query or req.item_name,
                location=req.location,
                currency=local_currency or None,
                quantity=qty,
                buying_mode="bulk" if is_bulk else "retail",
                verdict=verdict if isinstance(verdict, dict) else {},
                market_listings=display if isinstance(display, list) else [],
                market_warning=market_warning,
                risk_score=risk_nm if isinstance(risk_nm, dict) else None,
                query_meta={**query_meta, "relevance": rel_meta},
                transcript={
                    "thrift_advocate": "Insufficient relevant product pages.",
                    "risk_analyst": "Off-category, wrong-spec, or storefront-only results are not usable.",
                    "contextual_persona": "Ask the buyer to clarify the exact product (e.g. wired 3.5mm).",
                },
            )
            brief_id_nm = int(saved_nm["id"]) if saved_nm and saved_nm.get("id") is not None else None
            if brief_id_nm is not None:
                verdict = dict(verdict)
                verdict["brief_id"] = brief_id_nm
                prior_nm = briefs_db.find_prior_brief(
                    int(_user["id"]),
                    item_name=product_query or req.item_name,
                    supplier_host=saved_nm.get("supplier_host"),
                    exclude_id=brief_id_nm,
                )
                if prior_nm:
                    compare_nm = briefs_db.compare_briefs(saved_nm, prior_nm)
        except Exception as exc:
            print(f"[briefs] save failed (no_match): {exc}")
        from app.db.credits import credit_status
        from app.utils.supplier_table import build_supplier_table, build_brief_export_text

        table_nm = build_supplier_table(
            display if isinstance(display, list) else [],
            verdict=verdict if isinstance(verdict, dict) else {},
            quantity=qty,
            is_bulk=is_bulk,
        )
        export_nm = build_brief_export_text(
            item_name=product_query or req.item_name,
            location=req.location,
            quantity=qty,
            buying_mode="bulk" if is_bulk else "retail",
            verdict=verdict if isinstance(verdict, dict) else {},
            supplier_table=table_nm,
            negotiation_message=None,
            brief_id=brief_id_nm,
        )
        return DealFinderResponse(
            transcript={
                "thrift_advocate": "Insufficient relevant product pages.",
                "risk_analyst": "Off-category, wrong-spec, or storefront-only results are not usable.",
                "contextual_persona": "Ask the buyer to clarify the exact product (e.g. wired 3.5mm).",
            },
            verdict=verdict,
            market_listings=display,
            market_warning=market_warning,
            raw_verdict="NO_MATCH",
            risk_score=risk_nm,
            negotiation_script=[],
            buy_checklist=checklist,
            query_meta={**query_meta, "relevance": rel_meta},
            brief_id=brief_id_nm,
            compare_to_prior=compare_nm,
            supplier_table=table_nm,
            export_text=export_nm,
            credits=credit_status(int(_user["id"])),
        )

    # Debate + ranking only on relevant priced product pages (never phone/truck junk)
    listings = kept if kept else listings
    live_ok = len(kept) > 0
    market_warning = None if live_ok else (
        fetch_warning or "Live market data unavailable; agents used form input only."
    )
    if dropped:
        note = (
            f"Dropped {len(dropped)} off-category or non-product rows; "
            f"{len(kept)} relevant priced product pages remain."
        )
        market_warning = f"{note} {market_warning}".strip() if market_warning else note
    if bulk_quote and bulk_quote.get("message"):
        market_warning = (
            f"{market_warning + ' ' if market_warning else ''}{bulk_quote['message']}"
        ).strip()
    if must_haves:
        labels = ", ".join(h.get("label") or h.get("id") or "" for h in must_haves[:6])
        note = f"Must-have specs from query: {labels}."
        market_warning = f"{note} {market_warning}".strip() if market_warning else note
    if query_meta.get("auto_narrowed"):
        note = (
            f"Query auto-narrowed from “{query_meta.get('original')}” to “{query_meta.get('used_query')}” "
            "because the original was too vague for useful ranking."
        )
        market_warning = f"{note} {market_warning}".strip() if market_warning else note
    if query_meta.get("ambiguous") and query_meta.get("options"):
        note = (
            "Ambiguous query — pick one: "
            + "; ".join(str(o) for o in query_meta["options"][:4])
        )
        market_warning = f"{note} {market_warning}".strip() if market_warning else note
    market_block = format_market_block(
        listings,
        preferred_currency=local_currency or None,
        bulk_mode=is_bulk,
    )
    # Pre-debate fact sheet so agents only cite extracted numbers
    pre_sheet = build_listing_fact_sheet(listings)
    sheet_prompt = fact_sheet_for_prompt(pre_sheet)
    if sheet_prompt:
        market_block = f"{market_block}\n\n{sheet_prompt}"

    # Per-listing landed cost (origin vs destination) — no pool-wide foreign_factory
    _buyer_vat = getattr(req, "buyer_vat_registered", None)
    _commodity = getattr(req, "commodity_code", None)
    budget_n_pre = parse_money(req.max_budget) if req.max_budget else None
    cost_assumptions = {
        "label": "per-listing origin vs destination",
        "profile_id": region_profile.get("id"),
        "trade_zone": region_profile.get("trade_zone"),
        "prompt_block": destination_prompt_block(
            profile=region_profile,
            local_currency=local_currency or None,
            buyer_vat_registered=_buyer_vat,
        ),
    }
    market_block = f"{market_block}\n\n{cost_assumptions['prompt_block']}"

    if qty:
        enriched: list[dict] = []
        for row in listings:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            landed_row = compute_landed_cost(
                item,
                quantity=qty,
                local_currency=local_currency or None,
                budget=budget_n_pre,
                buyer_vat_registered=_buyer_vat,
                commodity_code=_commodity,
                location=req.location,
                country_code=str(region_profile.get("country_code") or "") or None,
            )
            item["landed_cost"] = landed_row
            enriched.append(item)
        listings = enriched

    # Authoritative landed cost for the ranked pick — agents MUST cite these totals
    pre_pick = next((x for x in listings if x.get("best_pick")), listings[0] if listings else None)
    pre_landed = (
        (pre_pick.get("landed_cost") if isinstance(pre_pick, dict) else None)
        or (
            compute_landed_cost(
                pre_pick,
                quantity=qty,
                local_currency=local_currency or None,
                budget=budget_n_pre,
                buyer_vat_registered=_buyer_vat,
                commodity_code=_commodity,
                location=req.location,
                country_code=str(region_profile.get("country_code") or "") or None,
            )
            if pre_pick and qty
            else None
        )
    )
    if pre_landed and isinstance(pre_pick, dict):
        pre_pick["landed_cost"] = pre_landed
    if pre_landed:
        fb = (
            " [estimated, not a tariff lookup]"
            if pre_landed.get("duty_fallback")
            else ""
        )
        market_block = (
            f"{market_block}\n\n"
            "AUTHORITATIVE LANDED COST (shared calculator — cite ONLY these totals; "
            "do not invent alternate order totals from unverified tier prices):\n"
            f"- Listing: {pre_landed.get('listing_title') or (pre_pick or {}).get('title')}\n"
            f"- Origin: {pre_landed.get('origin_country')} "
            f"({'import' if pre_landed.get('is_import') else 'domestic'})\n"
            f"- Unit basis: {pre_landed.get('unit_price')} ({pre_landed.get('tier_label')})\n"
            f"- Mid landed for qty {qty}: {pre_landed.get('estimated_total')}{fb}\n"
            f"- Range: {pre_landed.get('range_low')}–{pre_landed.get('range_high')}\n"
            f"- Formula: {pre_landed.get('formula')}\n"
        )
        if pre_landed.get("unconfirmed_tier_note"):
            market_block += f"- Caveat: {pre_landed['unconfirmed_tier_note']}\n"

    run_id = str(uuid.uuid4())
    quantity_line = f"Quantity wanted: {qty}\n" if qty else "Quantity wanted: not specified\n"
    mode_line = f"Buying mode: {'bulk / wholesale' if is_bulk else 'retail'}\n"

    context = (
        f"Run ID: {run_id} (unique per search — generate fresh reasoning; do not copy prior runs)\n"
        f"Generated at: {_time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime())}\n"
        f"Item: {req.item_name}\n"
        f"Search query used: {query_meta.get('used_query') or product_query}\n"
        f"Location: {req.location}\n"
        f"Max budget: {req.max_budget or 'not specified'} {local_currency or ''}\n"
        f"{quantity_line}"
        f"{mode_line}"
        f"Marketplace: {marketplace_label}\n"
        f"Local currency: {local_currency or location_context.get('currency') or 'not specified'}\n"
        f"Trade zone: {location_context.get('trade_zone')}\n"
        f"Live listings available: {'yes' if live_ok else 'NO'}\n\n"
        f"{market_block}"
    )

    prompt_kwargs = {
        "marketplace": marketplace,
        "profile": profile,
        "location_context": location_context,
        "live_listings_available": live_ok,
        "buying_mode": "bulk" if is_bulk else "retail",
        "quantity": qty,
    }

    try:
        transcript_raw, verdict, raw = await run_three_agent_debate(
            context=context,
            agent1_prompt=thrift_advocate_prompt(**prompt_kwargs),
            agent1_name="thrift_advocate",
            agent2_prompt=risk_analyst_prompt(**prompt_kwargs),
            agent2_name="risk_analyst",
            agent3_prompt=contextual_persona_prompt(**prompt_kwargs),
            agent3_name="contextual_persona",
            judge_prompt=deal_judge_prompt(**prompt_kwargs),
            fixed_replies=None if live_ok else {"thrift_advocate": NO_LIVE_LISTINGS_THRIFT_REPLY},
            judge_context=market_block,
            agent_max_tokens=700,
            judge_max_tokens=1400,
        )
    except Exception:
        raise _public_agent_error()

    if not verdict:
        verdict = {
            "verdict": "PASS",
            "winner": {
                "title": "",
                "vendor": "",
                "price": "",
                "link": "",
                "reason": "Judge response could not be parsed.",
            },
            "alternatives": [],
            "agent_breakdown": {
                "thrift_advocate": "",
                "risk_analyst": "",
                "contextual_persona": "",
            },
            "summary": "Judge response could not be parsed.",
        }

    if not live_ok:
        verdict = apply_empty_listings_gate(verdict)
        transcript_raw = dict(transcript_raw or {})
        transcript_raw["thrift_advocate"] = NO_LIVE_LISTINGS_THRIFT_REPLY
    else:
        verdict = coerce_verdict_when_listings_exist(verdict, listings)

    # Block unverified SERP/tier prices as core Best-Value justifications
    from app.utils.debate_gates import scrub_and_clear_listings

    transcript_raw, listings, scrub_notes = scrub_and_clear_listings(
        dict(transcript_raw or {}), listings
    )

    pick = next((x for x in listings if x.get("best_pick")), listings[0] if listings else None)
    winner_pre = verdict.get("winner") if isinstance(verdict.get("winner"), dict) else {}
    w_link = str(winner_pre.get("link") or "")
    if w_link:
        for row in listings:
            if str(row.get("link") or "") == w_link:
                pick = row
                break

    budget_n = parse_money(req.max_budget) if req.max_budget else None

    # Early risk flags so Risk PASS can hard-signal before verifier softens to Maybe
    early_flags = build_listing_risk_flags(
        listings,
        winner=winner_pre if isinstance(winner_pre, dict) else None,
        query=req.item_name,
    )
    verdict, listings, risk_gate_notes = apply_risk_hard_signal(
        verdict,
        transcript_raw,
        listings,
        risk_flags=early_flags,
    )
    if scrub_notes or risk_gate_notes:
        gate_bits = scrub_notes + risk_gate_notes
        market_warning = (
            f"{market_warning + ' ' if market_warning else ''}"
            f"Debate gates: {'; '.join(gate_bits)}."
        ).strip()

    # Refresh pick after risk hard-signal may have moved/cleared Best pick
    winner_pre = verdict.get("winner") if isinstance(verdict.get("winner"), dict) else {}
    w_link = str(winner_pre.get("link") or "")
    pick = None
    if w_link:
        for row in listings:
            if str(row.get("link") or "") == w_link:
                pick = row
                break
    if not pick:
        pick = next((x for x in listings if x.get("best_pick")), listings[0] if listings else None)

    # Mark contradictory agent claims as disputed (agreement ≠ verification)
    agent_texts = {
        "thrift_advocate": str((transcript_raw or {}).get("thrift_advocate") or ""),
        "risk_analyst": str((transcript_raw or {}).get("risk_analyst") or ""),
        "contextual_persona": str((transcript_raw or {}).get("contextual_persona") or ""),
    }
    w_pre_link = str(
        (verdict.get("winner") or {}).get("link")
        if isinstance(verdict.get("winner"), dict)
        else ""
    )
    listings, disputed_claims = apply_disputed_to_listings(
        listings, agent_texts, winner_link=w_pre_link or None
    )

    fact_sheet = build_listing_fact_sheet(listings)
    # Allow qty + budget as citable context numbers
    allowed = set(fact_sheet.get("allowed_numbers") or [])
    if qty:
        allowed.add(float(qty))
    if budget_n:
        allowed.add(float(budget_n))
        allowed.add(float(round(budget_n)))
    fact_sheet["allowed_numbers"] = sorted(allowed)

    landed = (
        (pick.get("landed_cost") if isinstance(pick, dict) else None)
        or compute_landed_cost(
            pick,
            quantity=qty,
            local_currency=local_currency or None,
            budget=budget_n,
            buyer_vat_registered=_buyer_vat,
            commodity_code=_commodity,
            location=req.location,
            country_code=str(region_profile.get("country_code") or "") or None,
        )
    )
    if landed and isinstance(pick, dict):
        pick["landed_cost"] = landed

    # Fact flags first so the verifier can block Buy on unresolved high-risk pick flags
    fact_flags = build_listing_risk_flags(
        listings,
        winner=winner_pre if isinstance(winner_pre, dict) else None,
        query=req.item_name,
    )

    verdict, listings, verify_notes = verify_verdict_against_listings(
        verdict,
        listings,
        landed_cost=landed,
        risk_flags=fact_flags,
        fact_sheet=fact_sheet,
        budget=budget_n,
    )
    if verify_notes:
        market_warning = (
            f"{market_warning + ' ' if market_warning else ''}"
            f"Verifier: {'; '.join(verify_notes)}."
        ).strip()

    winner = verdict.get("winner") if isinstance(verdict.get("winner"), dict) else {}
    w_link = str(winner.get("link") or "")
    pick = next((x for x in listings if str(x.get("link") or "") == w_link), None)
    if not pick:
        pick = next((x for x in listings if x.get("best_pick")), listings[0] if listings else None)
    tag = str(verdict.get("verdict") or "").upper()
    # Keep checkable math for BUY and MAYBE; drop only on Skip
    if tag in ("BUY", "MAYBE"):
        landed = (
            (pick.get("landed_cost") if isinstance(pick, dict) else None)
            or compute_landed_cost(
                pick,
                quantity=qty,
                local_currency=local_currency or None,
                budget=budget_n,
                buyer_vat_registered=_buyer_vat,
                commodity_code=_commodity,
                location=req.location,
                country_code=str(region_profile.get("country_code") or "") or None,
            )
        )
    else:
        # Skip/PASS: keep per-listing landed on rows; do not clear them with winner
        landed = pick.get("landed_cost") if isinstance(pick, dict) else None
    if landed and tag in ("BUY", "MAYBE"):
        card_n = parse_money((pick or {}).get("price"))
        unit_n = parse_money(landed.get("unit_price")) or parse_money(landed.get("unit_price_local"))
        if card_n and unit_n and abs(card_n - unit_n) / max(card_n, unit_n) > 0.12:
            landed = compute_landed_cost(
                {**(pick or {}), "price_tiers": None, "unit_usd": None},
                quantity=qty,
                local_currency=local_currency or None,
                budget=budget_n,
                buyer_vat_registered=_buyer_vat,
                commodity_code=_commodity,
                location=req.location,
                country_code=str(region_profile.get("country_code") or "") or None,
            )
        if isinstance(pick, dict):
            pick["landed_cost"] = landed
        # Re-evaluate flip after rebuild
        if budget_n and landed:
            lo = float(landed.get("range_low_amount") or 0)
            hi = float(landed.get("range_high_amount") or 0)
            if lo > 0 and hi > 0 and lo <= budget_n < hi:
                landed["verdict_flips_in_range"] = True
                if tag == "BUY":
                    verdict = dict(verdict)
                    verdict["verdict"] = "MAYBE"
                    reason = (
                        f"Maybe, verify — under optimistic assumptions the deal fits (~{landed.get('range_low')}), "
                        f"but under cautious duty/freight it may not (~{landed.get('range_high')}). "
                        "Confirm weight, freight, duty, and MOQ on the seller page."
                    )
                    w = dict(verdict.get("winner") or {})
                    w["reason"] = reason
                    verdict["winner"] = w
                    verdict["summary"] = reason
                    tag = "MAYBE"
        verdict = dict(verdict)
        verdict["landed_cost"] = landed
        verdict["fact_sheet"] = fact_sheet
        verdict["cost_assumptions"] = {
            k: cost_assumptions.get(k)
            for k in (
                "duty_rate_mid",
                "duty_rate_low",
                "duty_rate_high",
                "sales_tax_rate",
                "freight_usd_per_kg_mid",
                "label",
            )
        }
        verdict["run_id"] = run_id
        if must_haves:
            verdict["must_haves"] = must_haves
        if bulk_quote:
            verdict["sourcing_action"] = bulk_quote
        # Surface cost vs budget + max units in the verdict prose
        if landed.get("cost_vs_budget") or landed.get("max_units_note"):
            w = dict(verdict.get("winner") or {})
            extras = []
            if landed.get("cost_vs_budget"):
                extras.append(str(landed["cost_vs_budget"]))
            if landed.get("max_units_that_fit") is not None:
                extras.append(
                    f"Max units that fit budget: {landed['max_units_that_fit']}"
                    + (f" — {landed['max_units_note']}" if landed.get("max_units_note") else "")
                )
            if extras:
                base = str(w.get("reason") or verdict.get("summary") or "").strip()
                add_on = " ".join(extras)
                if add_on not in base:
                    w["reason"] = f"{base} {add_on}".strip() if base else add_on
                    verdict["winner"] = w
                    if not str(verdict.get("summary") or "").strip():
                        verdict["summary"] = w["reason"]
        if pick and pick.get("sourcing_action") == "ask_bulk_quote" and is_bulk:
            verdict["verdict"] = "MAYBE" if str(verdict.get("verdict") or "").upper() == "BUY" else verdict.get("verdict")
            w = dict(verdict.get("winner") or {})
            note = (
                "Retail listing — ask the seller for a bulk/case quote before treating this as a wholesale buy."
            )
            if note not in str(w.get("reason") or ""):
                w["reason"] = f"{str(w.get('reason') or '').strip()} {note}".strip()
                verdict["winner"] = w
                verdict["summary"] = w["reason"]
            tag = str(verdict.get("verdict") or "").upper()

    # Cross-check agent-written totals vs calculator; caveat + flag if >15% apart
    totals_report: dict[str, Any] = {"ok": True}
    if landed and transcript_raw:
        totals_report, transcript_raw, totals_notes = check_totals_consistency(
            landed, transcript_raw, tolerance=0.15
        )
        if totals_notes:
            market_warning = (
                f"{market_warning + ' ' if market_warning else ''}"
                f"Totals check: {'; '.join(totals_notes)}."
            ).strip()
            agent_texts = {
                "thrift_advocate": str((transcript_raw or {}).get("thrift_advocate") or ""),
                "risk_analyst": str((transcript_raw or {}).get("risk_analyst") or ""),
                "contextual_persona": str((transcript_raw or {}).get("contextual_persona") or ""),
            }
        if not totals_report.get("ok"):
            # Do not ship contradicting totals — force Maybe + calculator-only summary
            verdict = dict(verdict)
            if str(verdict.get("verdict") or "").upper() == "BUY":
                verdict["verdict"] = "MAYBE"
            w = dict(verdict.get("winner") or {}) if isinstance(verdict.get("winner"), dict) else {}
            reason = (
                f"Maybe, verify — agents quoted order totals that disagree with the shared "
                f"calculator (mid {landed.get('estimated_total')}, "
                f"range {landed.get('range_low')}–{landed.get('range_high')}). "
                f"Use the calculator figures; confirm unit price on the seller page."
            )
            w["reason"] = reason
            verdict["winner"] = w
            verdict["summary"] = reason
            verdict["totals_consistency"] = totals_report
            tag = str(verdict.get("verdict") or "").upper()

    verdict, hedge_notes = hedge_verdict_confidence(verdict, transcript_raw)
    if hedge_notes:
        market_warning = (
            f"{market_warning + ' ' if market_warning else ''}"
            f"Confidence: {'; '.join(hedge_notes)}."
        ).strip()
        tag = str(verdict.get("verdict") or "").upper()

    winner = verdict.get("winner") if isinstance(verdict.get("winner"), dict) else {}
    fact_flags = build_listing_risk_flags(listings, winner=winner, query=req.item_name)
    # Surface disputed agent claims as high-severity flags
    if disputed_claims and any(c.get("disputed") for c in disputed_claims):
        fact_flags = list(fact_flags) + [
            {
                "code": "disputed_fact",
                "message": "Disputed seller fact",
                "cite": f"Agents contradicted on {c.get('kind')}: “{c.get('quote')}”",
                "link": str(winner.get("link") or ""),
                "listing_title": str(winner.get("title") or ""),
                "severity": "high",
            }
            for c in disputed_claims
            if c.get("disputed")
        ]
    risk_score = risk_score_from_flags(fact_flags)

    _, negotiation_script, buy_checklist = await AgentOrchestrator.enrich_deal_verdict(
        transcript=transcript_raw,
        verdict=verdict,
        item_name=req.item_name,
        marketplace=marketplace_label,
        location=req.location,
        buying_mode="bulk" if is_bulk else "retail",
        quantity=qty,
    )

    if is_bulk and tag == "BUY":
        verdict = apply_high_risk_bulk_guard(verdict, listings, risk_score)
        if landed:
            verdict = dict(verdict)
            verdict["landed_cost"] = landed

    tag = str(verdict.get("verdict") or "").upper()
    verdict = apply_verified_prose(
        verdict,
        landed=landed if tag in ("BUY", "MAYBE") else None,
        budget=budget_n,
    )
    tag = str(verdict.get("verdict") or "").upper()
    verdict = dict(verdict)
    verdict["run_id"] = run_id
    if cost_assumptions:
        verdict["cost_assumptions"] = {
            k: cost_assumptions.get(k)
            for k in (
                "duty_rate_mid",
                "duty_rate_low",
                "duty_rate_high",
                "sales_tax_rate",
                "freight_usd_per_kg_mid",
                "label",
            )
        }

    if tag in ("PASS", "SKIP", "NO_MATCH"):
        listings = clear_best_pick(listings)
        # Clear winner / BEST for Skip, but keep per-listing landed_cost on each row
        verdict = dict(verdict)
        verdict["winner"] = {
            "link": "",
            "price": "",
            "title": "",
            "vendor": "",
            "reason": str((verdict.get("winner") or {}).get("reason") or verdict.get("summary") or ""),
        }
        # Winner-level landed_cost cleared; listing["landed_cost"] rows remain
        verdict.pop("landed_cost", None)
        for row in listings:
            if isinstance(row, dict):
                row["best_pick"] = False
                row.pop("pick_reason", None)
    else:
        # Surface the pick first; renumber sequentially on the FINAL list only
        ranked: list[dict[str, Any]] = []
        ordered_rows = sorted(
            listings,
            key=lambda r: (0 if r.get("best_pick") else 1, str(r.get("title") or "")),
        )
        # Drop hard outliers before assigning Rank #N (prevents #2,#3,#5 gaps)
        display_rows = [
            r
            for r in ordered_rows
            if r.get("best_pick")
            or not (
                r.get("price_outlier")
                or r.get("implausible_metal")
                or r.get("counts_as_live_listing") is False
            )
        ]
        if not display_rows:
            display_rows = ordered_rows
        for display_i, row in enumerate(display_rows):
            item = dict(row)
            item["display_rank"] = display_i + 1
            if item.get("best_pick"):
                bits = ["Best pick for this region"]
                if qty:
                    bits.append("quantity")
                if budget_n is not None:
                    bits.append("budget")
                # Dynamic — never claim "budget" when none was set
                if len(bits) == 1:
                    pick_txt = bits[0]
                elif len(bits) == 2:
                    pick_txt = f"{bits[0]} and {bits[1]}"
                else:
                    pick_txt = f"{bits[0]}, {bits[1]}, and {bits[2]}"
                item["pick_reason"] = pick_txt
                item["rank_reason"] = f"#{display_i + 1} · {pick_txt}"
            elif display_i == 0:
                item.pop("pick_reason", None)
                item["rank_reason"] = f"#{display_i + 1} · Ranked first among remaining sellers (no Best pick)."
            else:
                item.pop("pick_reason", None)
                item["rank_reason"] = (
                    f"#{display_i + 1} · after Best pick / relevance; "
                    "not a same-seller duplicate comparison."
                )
            ranked.append(item)
        listings = ranked

    try:
        write_run_log(
            {
                "run_id": run_id,
                "original_query": req.item_name,
                "narrowed_query": query_meta.get("used_query") or product_query,
                "query_meta": {**query_meta, "relevance": rel_meta},
                "cost_assumptions": {
                    k: cost_assumptions.get(k)
                    for k in (
                        "duty_rate_mid",
                        "duty_rate_low",
                        "duty_rate_high",
                        "sales_tax_rate",
                        "freight_usd_per_kg_mid",
                        "label",
                    )
                },
                "debate_gates": scrub_notes + risk_gate_notes,
                "totals_consistency": totals_report,
                "result_urls": [str(r.get("link") or "") for r in listings],
                "page_facts": [
                    {
                        "link": r.get("link"),
                        "title": r.get("title"),
                        "price": r.get("price"),
                        "price_source": r.get("price_source"),
                        "moq": r.get("moq"),
                        "price_tiers": r.get("price_tiers"),
                        "warranty": r.get("warranty"),
                        "policy_links": r.get("policy_links"),
                        "package_weight_kg": r.get("package_weight_kg"),
                        "page_facts_fetched": r.get("page_facts_fetched"),
                        "counts_as_live_listing": r.get("counts_as_live_listing"),
                        "facts_disputed": r.get("facts_disputed"),
                    }
                    for r in listings
                ],
                "calculator": landed,
                "agent_claims": [
                    {"agent": k, "text": v, "fact_ids": []}
                    for k, v in agent_texts.items()
                ],
                "disputed_claims": disputed_claims,
                "verdict": {
                    "tag": tag,
                    "winner": verdict.get("winner"),
                    "summary": verdict.get("summary"),
                    "prose_validation": verdict.get("prose_validation"),
                    "agent_disagreement": verdict.get("agent_disagreement"),
                },
                "risk_flags": fact_flags,
            }
        )
    except Exception:
        pass

    from app.db.credits import credit_status
    from app.utils.supplier_table import (
        build_brief_export_text,
        build_negotiation_message,
        build_supplier_table,
    )

    supplier_table = build_supplier_table(
        listings if isinstance(listings, list) else [],
        verdict=verdict if isinstance(verdict, dict) else {},
        quantity=qty,
        is_bulk=is_bulk,
    )
    negotiation_message = build_negotiation_message(
        item_name=product_query or req.item_name,
        quantity=qty,
        verdict=verdict if isinstance(verdict, dict) else {},
        questions=negotiation_script or [],
        location=req.location,
    )

    brief_id: int | None = None
    compare_to_prior: dict[str, Any] | None = None
    try:
        from app.db import briefs as briefs_db

        saved = briefs_db.save_brief(
            user_id=int(_user["id"]),
            run_id=run_id,
            item_name=product_query or req.item_name,
            location=req.location,
            currency=local_currency or None,
            quantity=qty,
            buying_mode="bulk" if is_bulk else "retail",
            verdict=verdict if isinstance(verdict, dict) else {},
            market_listings=listings if isinstance(listings, list) else [],
            market_warning=market_warning,
            risk_score=risk_score if isinstance(risk_score, dict) else None,
            query_meta={
                **query_meta,
                "relevance": rel_meta,
                "supplier_table": supplier_table,
                "negotiation_message": negotiation_message,
            },
            transcript=dict(transcript_raw or {}),
        )
        brief_id = int(saved["id"]) if saved and saved.get("id") is not None else None
        if brief_id is not None:
            verdict = dict(verdict)
            verdict["brief_id"] = brief_id
            prior = briefs_db.find_prior_brief(
                int(_user["id"]),
                item_name=product_query or req.item_name,
                supplier_host=saved.get("supplier_host"),
                exclude_id=brief_id,
            )
            if prior:
                compare_to_prior = briefs_db.compare_briefs(saved, prior)
    except Exception as exc:
        print(f"[briefs] save failed: {exc}")

    export_text = build_brief_export_text(
        item_name=product_query or req.item_name,
        location=req.location,
        quantity=qty,
        buying_mode="bulk" if is_bulk else "retail",
        verdict=verdict if isinstance(verdict, dict) else {},
        supplier_table=supplier_table,
        negotiation_message=negotiation_message,
        brief_id=brief_id,
    )

    # Drop unsourced coverage brands (e.g. Trade Assurance) from agent prose
    _mp = profile if isinstance(profile, dict) else {}
    _mp_sourced = " ".join(
        str(_mp.get(k) or "") for k in ("regulatory_notes", "safety_guidelines", "name")
    )
    transcript_raw = scrub_agent_texts(
        transcript_raw, listings=listings, extra_sourced=_mp_sourced
    ) or transcript_raw
    buy_checklist = scrub_agent_texts(
        buy_checklist, listings=listings, extra_sourced=_mp_sourced
    ) or buy_checklist
    _list_blob = "\n".join(
        str(x.get("snippet") or "") + " " + str(x.get("title") or "")
        for x in (listings or [])
        if isinstance(x, dict)
    )
    if negotiation_message:
        negotiation_message = scrub_unsourced_coverage_brands(
            negotiation_message,
            sourced_blob=_mp_sourced + "\n" + _list_blob,
        )
    if isinstance(export_text, str):
        export_text = scrub_unsourced_coverage_brands(
            export_text,
            sourced_blob=_mp_sourced + "\n" + _list_blob,
        )

    return DealFinderResponse(
        transcript=transcript_raw,
        verdict=verdict,
        market_listings=listings,
        market_warning=market_warning,
        raw_verdict=raw,
        risk_score=risk_score,
        negotiation_script=negotiation_script,
        negotiation_message=negotiation_message,
        buy_checklist=buy_checklist,
        query_meta={**query_meta, "relevance": rel_meta},
        brief_id=brief_id,
        compare_to_prior=compare_to_prior,
        supplier_table=supplier_table,
        export_text=export_text,
        credits=credit_status(int(_user["id"])),
    )
