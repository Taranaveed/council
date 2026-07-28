from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends

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
from app.core.market_client import (
    fetch_market_prices,
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
from app.utils.listing_links import attach_listing_links
from app.utils.price_stats import build_price_explanation
from app.utils.search_query import shorten_product_query
from app.utils.seller_pack import (
    build_action_pack,
    build_channel_creatives,
    build_export_text,
    empty_state_note,
)
from app.utils.vendor_check import enrich_listings_with_vendor_status

router = APIRouter(prefix="/api/modes", tags=["modes"])


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
    listings, warning = await fetch_market_prices(
        shorten_product_query(product_name),
        location,
        preferred_currency=currency,
    )
    listings = await enrich_listings_with_vendor_status(listings)
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
            agent_max_tokens=180,
            judge_max_tokens=450,
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
        agent_max_tokens=180 if lean else 280,
        judge_max_tokens=500 if lean else 600,
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

    price_result, audience_result = await asyncio.gather(
        _run_price_debate(context=price_context, lean=lean),
        _run_audience_debate(context=audience_context, lean=lean),
    )
    price_t, price_v, _price_raw = price_result
    aud_t, aud_v, _aud_raw = audience_result
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
    if price_v.get("why_this_price") and not explanation.get("why"):
        explanation["why"] = price_v["why_this_price"]
    elif price_v.get("why_this_price"):
        explanation["why"] = f"{explanation.get('why', '')} {price_v['why_this_price']}".strip()

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

    transcript_raw, verdict, raw = await _run_price_debate(context=context, lean=False)
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

    transcript_raw, verdict, raw = await _run_audience_debate(context=context, lean=False)
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
    marketplace = req.marketplace
    profile = get_marketplace_by_slug(marketplace) if marketplace else None
    location_context = infer_location_context(req.location)
    marketplace_label = (profile or {}).get("name") or marketplace or "unspecified"
    local_currency = (location_context.get("currency") or "").strip()

    qty = req.quantity if isinstance(req.quantity, int) and req.quantity > 0 else None
    mode = (req.buying_mode or "retail").strip().lower()
    if mode not in ("retail", "bulk"):
        mode = "retail"
    is_bulk = mode == "bulk" or (qty is not None and qty >= 5)

    budget_hint = ""
    if req.max_budget:
        budget_hint = f"under {req.max_budget} {local_currency}".strip()

    bulk_terms = "wholesale bulk supplier MOQ" if is_bulk else ""
    qty_hint = f"{qty} units" if qty and qty > 1 else ""
    search_query = " ".join(
        part for part in [req.item_name, qty_hint, bulk_terms, budget_hint, req.location] if part
    ).strip()
    fetch_limit = 12 if is_bulk else 8

    listings, fetch_warning = await fetch_market_prices(
        search_query or req.item_name,
        req.location,
        limit=fetch_limit,
    )
    if not listings and (req.max_budget or is_bulk):
        fallback_query = " ".join(
            part for part in [req.item_name, bulk_terms if is_bulk else "", req.location] if part
        ).strip()
        listings, fetch_warning2 = await fetch_market_prices(
            fallback_query or req.item_name,
            req.location,
            limit=fetch_limit,
        )
        fetch_warning = fetch_warning or fetch_warning2

    # Merge a second wholesale-leaning pass when bulk and first pass is thin.
    if is_bulk and len(listings) < 4:
        wholesale_query = f"{req.item_name} wholesale bulk {req.location}".strip()
        extra, _ = await fetch_market_prices(wholesale_query, req.location, limit=fetch_limit)
        seen = {str(x.get("link") or "").strip() for x in listings}
        for row in extra:
            link = str(row.get("link") or "").strip()
            if link and link not in seen:
                listings.append(row)
                seen.add(link)
            if len(listings) >= fetch_limit:
                break

    listings = await enrich_listings_with_vendor_status(listings)
    live_ok = len(listings) > 0
    market_warning = None if live_ok else (
        fetch_warning or "Live market data unavailable; agents used form input only."
    )
    market_block = format_market_block(listings)

    quantity_line = f"Quantity wanted: {qty}\n" if qty else "Quantity wanted: not specified\n"
    mode_line = f"Buying mode: {'bulk / wholesale' if is_bulk else 'retail'}\n"

    context = (
        f"Item: {req.item_name}\n"
        f"Location: {req.location}\n"
        f"Max budget: {req.max_budget or 'not specified'}\n"
        f"{quantity_line}"
        f"{mode_line}"
        f"Marketplace: {marketplace_label}\n"
        f"Local currency hint: {location_context.get('currency')}\n"
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
    )

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
        verdict = attach_listing_links(verdict, listings)

    risk_score, negotiation_script, buy_checklist = await AgentOrchestrator.enrich_deal_verdict(
        transcript=transcript_raw,
        verdict=verdict,
        item_name=req.item_name,
        marketplace=marketplace_label,
        location=req.location,
        buying_mode="bulk" if is_bulk else "retail",
        quantity=qty,
    )

    return DealFinderResponse(
        transcript=transcript_raw,
        verdict=verdict,
        market_listings=listings,
        market_warning=market_warning,
        raw_verdict=raw,
        risk_score=risk_score,
        negotiation_script=negotiation_script,
        buy_checklist=buy_checklist,
    )
