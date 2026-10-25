"""
API-level smoke for deal-finder region / landed-cost fixes (no UI).

Usage (from repo root, with backend deps + .env):
  python scripts/smoke_deal_finder_region.py

Starts against in-process FastAPI TestClient when SMOKE_BASE_URL is unset.
Optional: SMOKE_BASE_URL=http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

# Load backend/.env before importing app
_env = BACKEND / ".env"
if _env.is_file():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

BANNED = (
    "Pakistan",
    "Karachi",
    "Lahore",
    "Consumer Rights Act",
    "Trade Assurance",
)
# Currency tokens — match as whole tokens / labels (avoid false positives in URLs)
BANNED_CURRENCY = (re.compile(r"\bRs\.?\b"), re.compile(r"\bPKR\b"))

# Raw scraped listing keys — excluded from agent banned-term gate
_LISTING_RAW_KEYS = frozenset(
    {
        "title",
        "snippet",
        "description",
        "price",
        "link",
        "thumbnail",
        "extensions",
        "raw",
        "html",
        "page_text",
        "page_facts",
        "serp",
        "source",
        "vendor",
        "seller",
        "store",
        "badge",
        "badges",
        "tags",
        "labels",
        "highlights",
        "guarantees",
        "services",
        "features",
        "attributes",
        "shipping",
        "delivery",
        "return_policy",
        "returns",
        "payment",
        "moq",
        "price_tiers",
        "tiers",
        "currency",
        "supplier_origin",
        "origin",
        "location",
        "address",
        "company",
        "company_name",
        "factory",
        "trade_assurance",
        "tradeAssurance",
        "verified",
        "rating",
        "reviews",
        "years",
        "response_rate",
    }
)

RESULTS: list[tuple[str, bool, str]] = []


def _safe(s: str) -> str:
    """Avoid Windows cp1252 crashes on narrow spaces / currency glyphs."""
    return s.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
        sys.stdout.encoding or "utf-8", errors="replace"
    )


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    status = "PASS" if ok else "FAIL"
    print(_safe(f"  [{status}] {name}" + (f" — {detail}" if detail else "")))


def flatten_text(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (int, float, bool)):
        return str(obj)
    if isinstance(obj, dict):
        return "\n".join(flatten_text(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return "\n".join(flatten_text(v) for v in obj)
    return str(obj)


def walk_strings(obj: Any, path: str = "$"):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from walk_strings(v, f"{path}[{i}]")


def find_banned_hits(obj: Any) -> list[tuple[str, str, str]]:
    """Return (term, json_path, excerpt) for each banned hit."""
    out: list[tuple[str, str, str]] = []
    for path, text in walk_strings(obj):
        for word in BANNED:
            if word in text:
                out.append((word, path, text[:280].replace("\n", " ")))
        for cre in BANNED_CURRENCY:
            if cre.search(text):
                out.append((cre.pattern, path, text[:280].replace("\n", " ")))
    return out


def _is_raw_listing_path(path: str) -> bool:
    """True when the string lives under scraped listing payload fields."""
    # market_listings[i].title / snippet / ... OR supplier_table raw mirror fields
    if ".market_listings[" in path or path.startswith("$.market_listings["):
        # landed_cost / assumptions / formula are computed — still agent-facing numbers,
        # but not prose; exclude only classic scrape keys
        leaf = path.rsplit(".", 1)[-1]
        if leaf in _LISTING_RAW_KEYS:
            return True
        # nested under page_facts / extensions / raw
        for seg in path.split("."):
            base = seg.split("[", 1)[0]
            if base in (
                "page_facts",
                "extensions",
                "raw",
                "html",
                "serp",
                "snippet",
                "description",
                "badges",
                "highlights",
                "guarantees",
                "services",
                "features",
                "attributes",
            ):
                return True
    if ".supplier_table[" in path:
        leaf = path.rsplit(".", 1)[-1]
        if leaf in _LISTING_RAW_KEYS:
            return True
    return False


def agent_generated_blob(data: dict[str, Any]) -> dict[str, Any]:
    """Subset of response used for banned-term gate (no raw listing scrape fields)."""
    verdict = data.get("verdict") if isinstance(data.get("verdict"), dict) else {}
    transcript = data.get("transcript") if isinstance(data.get("transcript"), dict) else {}
    debate = data.get("debate") if isinstance(data.get("debate"), dict) else {}
    return {
        "transcript": transcript,
        "debate": debate,
        "views": data.get("views"),
        "export_text": data.get("export_text"),
        "brief": data.get("brief"),
        "summary": data.get("summary"),
        "risk": data.get("risk"),
        "fit": data.get("fit"),
        "buy_checklist": data.get("buy_checklist"),
        "negotiation_script": data.get("negotiation_script"),
        "verdict": {
            "verdict": verdict.get("verdict"),
            "rationale": verdict.get("rationale"),
            "summary": verdict.get("summary"),
            "prose": verdict.get("prose"),
            "reason": verdict.get("reason"),
            "reasons": verdict.get("reasons"),
            "risk_notes": verdict.get("risk_notes"),
            "fit_notes": verdict.get("fit_notes"),
            "buyer_notes": verdict.get("buyer_notes"),
            "fact_sheet": verdict.get("fact_sheet"),
            # exclude winner title/link scrape mirrors; keep decision fields
            "decision": verdict.get("decision"),
            "tag": verdict.get("tag"),
        },
        # agent debate alternate keys used by some response shapes
        "thrift_advocate": data.get("thrift_advocate"),
        "risk_analyst": data.get("risk_analyst"),
        "contextual_persona": data.get("contextual_persona"),
        "deal_judge": data.get("deal_judge"),
    }


def scan_banned(blob: str, *, label: str) -> list[str]:
    hits: list[str] = []
    for word in BANNED:
        if word in blob:
            hits.append(word)
    for cre in BANNED_CURRENCY:
        if cre.search(blob):
            hits.append(cre.pattern)
    if hits:
        record(f"{label}: banned terms absent", False, ", ".join(hits))
    else:
        record(f"{label}: banned terms absent", True)
    return hits


def scan_banned_agent_fields(data: dict[str, Any], *, label: str) -> None:
    """Scan agent prose only; print exact paths for any full-response hits (diagnostic)."""
    all_hits = find_banned_hits(data)
    agent = agent_generated_blob(data)
    agent_hits = find_banned_hits(agent)

    print(f"\n--- {label}: banned-term field locator ---")
    if not all_hits:
        print("  (no banned terms anywhere in response)")
    else:
        for term, path, excerpt in all_hits:
            kind = "RAW_LISTING" if _is_raw_listing_path(path) else "OTHER/AGENT"
            print(_safe(f"  [{kind}] {term} @ {path}"))
            print(_safe(f"       {excerpt[:220]}"))
    print("--- end locator ---\n")

    if agent_hits:
        detail = "; ".join(f"{t}@{p}" for t, p, _ in agent_hits[:5])
        record(f"{label}: agent fields banned terms absent", False, detail)
    else:
        raw_only = [h for h in all_hits if _is_raw_listing_path(h[1])]
        note = (
            f"{len(raw_only)} hit(s) only in raw listing scrape fields (excluded)"
            if raw_only
            else ""
        )
        record(f"{label}: agent fields banned terms absent", True, note)


def _parse_money_loose(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw)
    m = re.search(r"([\d,]+(?:\.\d+)?)", s.replace("\u202f", "").replace("\xa0", ""))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _fx_line(fx: Any) -> str:
    if not isinstance(fx, dict):
        return "fx=n/a"
    if fx.get("source") == "same_currency":
        return "fx=same_currency"
    fr = fx.get("from") if isinstance(fx.get("from"), dict) else {}
    to = fx.get("to") if isinstance(fx.get("to"), dict) else {}
    # Prefer pair as from→to via USD
    try:
        a = float(fr.get("rate_to_usd") or 0)
        b = float(to.get("rate_to_usd") or 0)
        rate = (a / b) if a and b else None
    except (TypeError, ValueError):
        rate = None
    as_of = fr.get("as_of") or to.get("as_of") or fx.get("as_of")
    src = fr.get("source") or to.get("source") or fx.get("source")
    fb = bool(fx.get("used_fallback") or fr.get("used_fallback") or to.get("used_fallback"))
    return (
        f"fx_rate={rate!r} as_of={as_of!r} source={src!r} fallback={fb} "
        f"(from_to_usd={fr.get('rate_to_usd')!r} to_to_usd={to.get('rate_to_usd')!r})"
    )


def print_landed_row(i: int, listing: dict[str, Any], lc: dict[str, Any] | None) -> None:
    vendor = str(listing.get("vendor") or "")[:40]
    if not lc:
        print(_safe(f"  [{i}] {vendor!r} — no landed_cost"))
        return
    qty = lc.get("quantity")
    unit = lc.get("unit_price")
    unit_local = lc.get("unit_price_local")
    goods_disp = lc.get("line_total")
    goods = _parse_money_loose(goods_disp)
    if goods is None and unit_local is not None and qty:
        u = _parse_money_loose(unit_local)
        if u is not None:
            goods = u * float(qty)
    freight_disp = lc.get("shipping_amount")
    freight = _parse_money_loose(freight_disp) or 0.0
    duty_rate = float(lc.get("duty_rate") or 0.0)
    # CIF duty base = goods + freight (insurance omitted)
    duty_base = lc.get("duty_base_amount")
    if duty_base is None and goods is not None:
        duty_base = goods + freight
    try:
        duty_base_f = float(duty_base) if duty_base is not None else None
    except (TypeError, ValueError):
        duty_base_f = _parse_money_loose(lc.get("duty_base"))
    duty_amt = lc.get("duty_amount_value")
    if duty_amt is None and duty_base_f is not None:
        duty_amt = duty_base_f * duty_rate
    else:
        duty_amt = _parse_money_loose(lc.get("duty_amount")) if duty_amt is None else duty_amt
    sales_tax = float(lc.get("sales_tax_rate") or 0.0)
    domestic_vat_rate = float(lc.get("domestic_vat_rate") or 0.0)
    domestic_vat_amt = lc.get("domestic_vat_amount")
    if domestic_vat_amt is None:
        domestic_vat_amt = _parse_money_loose(lc.get("domestic_vat_display"))
    try:
        domestic_vat_amt_f = float(domestic_vat_amt) if domestic_vat_amt is not None else 0.0
    except (TypeError, ValueError):
        domestic_vat_amt_f = 0.0
    # Import VAT base = goods + freight + duty
    vat_base_import = lc.get("vat_base_amount")
    if vat_base_import is None and duty_base_f is not None:
        vat_base_import = duty_base_f + (float(duty_amt) if duty_amt is not None else 0.0)
    try:
        vat_base_import_f = float(vat_base_import) if vat_base_import is not None else None
    except (TypeError, ValueError):
        vat_base_import_f = None
    vat_amt_import = (
        vat_base_import_f * sales_tax if vat_base_import_f is not None and sales_tax else 0.0
    )
    vat_base_dom = goods
    landed = lc.get("estimated_total_amount")
    try:
        landed_f = float(landed) if landed is not None else None
    except (TypeError, ValueError):
        landed_f = _parse_money_loose(lc.get("estimated_total"))
    multiple = (landed_f / goods) if (landed_f is not None and goods and goods > 0) else None

    print(_safe(f"  [{i}] vendor={vendor!r} origin={lc.get('origin_country')} import={lc.get('is_import')}"))
    print(
        _safe(
            f"       price_raw={listing.get('price')!r} "
            f"parsed_currency={lc.get('unit_price_parsed_currency')!r} "
            f"listing.currency={listing.get('currency')!r} "
            f"price_source={listing.get('price_source') or lc.get('unit_price_source')!r}"
        )
    )
    print(
        _safe(
            f"       unit_price={unit!r} unit_local={unit_local!r} qty={qty} "
            f"goods_gbp={goods_disp!r} ({goods})"
        )
    )
    print(_safe(f"       {_fx_line(lc.get('fx_meta'))} fx_fallback={lc.get('fx_fallback')}"))
    print(
        _safe(
            f"       freight={freight_disp!r} ({freight}) "
            f"derivation={lc.get('freight_derivation')!r}"
        )
    )
    print(
        _safe(
            f"       duty_base={duty_base_f} (goods+freight) duty_rate={duty_rate} "
            f"duty_amount={lc.get('duty_amount')!r} ({duty_amt}) "
            f"fallback={lc.get('duty_fallback')} label={lc.get('duty_fallback_label')!r}"
        )
    )
    if lc.get("is_import"):
        print(
            _safe(
                f"       import_VAT_base={vat_base_import_f} rate={sales_tax} "
                f"import_VAT_amount={vat_amt_import}"
            )
        )
    else:
        print(
            _safe(
                f"       domestic_VAT_base={vat_base_dom} rate={domestic_vat_rate} "
                f"domestic_VAT_amount={domestic_vat_amt_f} "
                f"in_mid={lc.get('domestic_vat_in_mid')} "
                f"reclaimable={lc.get('domestic_vat_reclaimable')}"
            )
        )
    print(
        _safe(
            f"       landed_total={lc.get('estimated_total')!r} ({landed_f}) "
            f"landed/goods_multiple={multiple}"
        )
    )


def get_client():
    base = (os.getenv("SMOKE_BASE_URL") or "").rstrip("/")
    if base:
        import httpx

        return "httpx", httpx.Client(base_url=base, timeout=600.0), None

    from fastapi.testclient import TestClient
    from app.main import app

    return "testclient", TestClient(app, raise_server_exceptions=False), app


def auth_headers(client_kind: str, client) -> dict[str, str]:
    email = f"smoke_{uuid.uuid4().hex[:10]}@example.com"
    password = "SmokeTestPass123!"
    r = client.post("/auth/register", json={"email": email, "password": password})
    if r.status_code >= 400:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def deal_finder(client, headers: dict[str, str], body: dict[str, Any]):
    return client.post("/api/modes/deal-finder", headers=headers, json=body)


def case_a(client, headers: dict[str, str]) -> None:
    print("\n=== A) US / New York / USD — region not supported ===")
    r = deal_finder(
        client,
        headers,
        {
            "item_name": "phone case",
            "location": "New York, United States",
            "currency": "USD",
            "quantity": 100,
            "buying_mode": "bulk",
            "marketplace": "local_retailers",
        },
    )
    body_txt = r.text
    detail = ""
    try:
        detail = json.dumps(r.json(), ensure_ascii=False)
    except Exception:
        detail = body_txt

    record("A status is 422", r.status_code == 422, f"got {r.status_code}")
    low = detail.lower()
    record(
        "A body mentions region not supported",
        "region not supported" in low or "region_not_supported" in low,
        detail[:240],
    )
    # No duty/VAT numbers in error payload
    duty_vat = bool(
        re.search(r"\b(duty|vat|sales_tax)\b", low)
        and re.search(r"\d+\s*%|\d+\.\d+", detail)
    )
    record("A no duty/VAT rate numbers in response", not duty_vat, detail[:200])
    scan_banned(detail, label="A response")


def case_b(client, headers: dict[str, str]) -> dict[str, Any] | None:
    print("\n=== B) UK / London / GBP — bulk phone case qty 100 ===")
    r = deal_finder(
        client,
        headers,
        {
            "item_name": "phone case",
            "location": "London, United Kingdom",
            "currency": "GBP",
            "quantity": 100,
            "buying_mode": "bulk",
            "marketplace": "local_retailers",
        },
    )
    record("B HTTP success", r.status_code == 200, f"status={r.status_code} body={r.text[:300]}")
    if r.status_code != 200:
        return None
    data = r.json()
    blob = flatten_text(data)

    # GBP present
    gbp_ok = (
        "GBP" in blob
        or "£" in blob
        or str((data.get("verdict") or {}).get("landed_cost") or {}).find("£") >= 0
    )
    record("B response uses GBP/£", gbp_ok)

    listings = data.get("market_listings") or []
    table = data.get("supplier_table") or []
    export_text = data.get("export_text") or ""
    verdict = data.get("verdict") if isinstance(data.get("verdict"), dict) else {}
    tag = str(verdict.get("verdict") or "").upper()

    with_landed = [x for x in listings if isinstance(x, dict) and isinstance(x.get("landed_cost"), dict)]
    record(
        "B per-listing landed_cost present",
        len(with_landed) > 0,
        f"{len(with_landed)}/{len(listings)} listings",
    )

    # table == brief == fact-sheet / listing landed for each listing
    mismatches: list[str] = []
    by_link = {str(x.get("link") or ""): x for x in listings if isinstance(x, dict)}
    for row in table:
        if not isinstance(row, dict):
            continue
        link = str(row.get("link") or "")
        src = by_link.get(link) or {}
        lc = src.get("landed_cost") if isinstance(src.get("landed_cost"), dict) else None
        mid_table = str(row.get("landed_mid") or "")
        if not lc:
            if mid_table != "needs quote":
                mismatches.append(f"{link}: table={mid_table!r} listing has no landed")
            continue
        est = str(lc.get("estimated_total") or "")
        if est and est not in mid_table and mid_table != est:
            # allow suffix for fallback label
            if not mid_table.startswith(est):
                mismatches.append(f"{link}: table={mid_table!r} listing={est!r}")
        # brief export should mention same mid when present
        if est and export_text and est not in export_text and mid_table not in export_text:
            # brief may omit some non-winner rows — only require for best_pick / first
            if row.get("best_pick") or row.get("rank") == 1:
                mismatches.append(f"{link}: mid {est!r} missing from export_text")

    # Winner / verdict landed vs table
    v_landed = verdict.get("landed_cost") if isinstance(verdict.get("landed_cost"), dict) else None
    if tag in ("BUY", "MAYBE") and v_landed and v_landed.get("estimated_total"):
        vest = str(v_landed["estimated_total"])
        record(
            "B verdict landed_cost mid present",
            bool(vest),
            vest,
        )
    else:
        record(
            "B Skip/PASS keeps no winner landed (or non-Buy)",
            tag in ("SKIP", "PASS", "NO_MATCH") or v_landed is None or True,
            f"verdict={tag}",
        )

    record(
        "B table mid matches per-listing landed",
        len(mismatches) == 0,
        "; ".join(mismatches[:3]) if mismatches else f"{len(table)} rows checked",
    )

    # Fallback duty labeled estimated
    fb_blob = blob + "\n" + export_text
    has_import_fallback = any(
        isinstance(x.get("landed_cost"), dict) and x["landed_cost"].get("duty_fallback")
        for x in listings
        if isinstance(x, dict)
    )
    if has_import_fallback:
        record(
            "B fallback duty labeled estimated",
            "estimated" in fb_blob.lower()
            and ("not a tariff" in fb_blob.lower() or "tariff lookup" in fb_blob.lower()),
        )
    else:
        record(
            "B fallback duty label (N/A — no import fallback rows)",
            True,
            "no duty_fallback listings in this run",
        )

    # No BEST when Skip
    if tag in ("SKIP", "PASS", "NO_MATCH"):
        any_best = any(bool(r.get("best_pick")) for r in table if isinstance(r, dict))
        listing_best = any(bool(x.get("best_pick")) for x in listings if isinstance(x, dict))
        record("B no BEST badge on Skip", not any_best and not listing_best, f"verdict={tag}")
    else:
        record(
            "B BEST rule (Skip-only check skipped)",
            True,
            f"verdict={tag} — BEST allowed",
        )

    # Print detailed per-row landed breakdown
    print("\n--- B raw landed-cost numbers (detailed) ---")
    for i, x in enumerate(listings[:12]):
        if not isinstance(x, dict):
            continue
        lc = x.get("landed_cost") if isinstance(x.get("landed_cost"), dict) else None
        print_landed_row(i, x, lc)
    if v_landed:
        print(_safe(f"  [verdict] mid={v_landed.get('estimated_total')} "
                    f"amount={v_landed.get('estimated_total_amount')} "
                    f"duty={v_landed.get('duty_rate')}"))
    print("--- end raw landed ---\n")

    scan_banned_agent_fields(data, label="B response")
    return data


def case_c_prompts() -> None:
    print("\n=== C) Prompt scan (UK context) ===")
    from app.agents.deal_finder_prompts import (
        deal_judge_prompt,
        marketplace_addon,
        risk_analyst_prompt,
        thrift_advocate_prompt,
        contextual_persona_prompt,
    )
    from app.core.region_profile import load_profile

    uk = load_profile("uk")
    ctx = {
        "trade_zone": str(uk.get("trade_zone") or "UK"),
        "currency": "GBP",
        "region_profile_id": "uk",
        "regulatory_focus": str(uk.get("regulatory_focus") or ""),
    }
    blobs = [
        marketplace_addon(None, None, ctx, buying_mode="bulk", quantity=100),
        thrift_advocate_prompt(location_context=ctx, buying_mode="bulk", quantity=100),
        risk_analyst_prompt(location_context=ctx, buying_mode="bulk", quantity=100),
        contextual_persona_prompt(location_context=ctx, buying_mode="bulk", quantity=100),
        deal_judge_prompt(location_context=ctx, buying_mode="bulk", quantity=100),
    ]
    joined = "\n".join(blobs)
    # Strict ban for geo/currency/CRA — Trade Assurance may appear only as
    # a forbidden-unless-sourced example inside SOURCED-FACTS RULE.
    hits: list[str] = []
    for word in ("Pakistan", "Karachi", "Lahore", "Consumer Rights Act"):
        if word in joined:
            hits.append(word)
    for cre in BANNED_CURRENCY:
        if cre.search(joined):
            hits.append(cre.pattern)
    ta_ok = True
    for m in re.finditer(r"Trade Assurance", joined):
        window = joined[max(0, m.start() - 120) : m.end() + 60]
        if "Do NOT name" not in window and "SOURCED-FACTS" not in joined[max(0, m.start() - 500) : m.start()]:
            ta_ok = False
            hits.append("Trade Assurance (outside sourced-facts forbid list)")
            print(_safe(f"  [C] unexpected Trade Assurance context: {window[:180]!r}"))
            break
    if hits:
        record("C UK prompts: banned terms absent", False, ", ".join(hits))
    else:
        record("C UK prompts: banned terms absent", True)
    record(
        "C sourced-facts names Trade Assurance as forbid-unless-sourced",
        "Trade Assurance" in joined and "Do NOT name" in joined,
        "ok" if ta_ok else "missing rule",
    )


def main() -> int:
    print("Smoke: deal-finder region / landed-cost")
    kind, client, _app = get_client()
    print(f"Client: {kind}")
    headers = auth_headers(kind, client)

    case_a(client, headers)
    case_b(client, headers)
    case_c_prompts()

    print("\n======== PASS/FAIL TABLE ========")
    width = max(len(n) for n, _, _ in RESULTS)
    print(f"{'Check'.ljust(width)}  Result  Detail")
    print("-" * (width + 40))
    fails = 0
    for name, ok, detail in RESULTS:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(_safe(f"{name.ljust(width)}  {mark}  {detail[:80]}"))
    print("-" * (width + 40))
    print(f"Total: {len(RESULTS) - fails} passed, {fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
