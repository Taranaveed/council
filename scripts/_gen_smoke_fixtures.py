"""One-shot generator for deal-finder smoke fixtures (no live search)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.utils.landed_cost import compute_landed_cost  # noqa: E402
from app.utils.supplier_table import build_supplier_table  # noqa: E402

FIXTURES = ROOT / "scripts" / "fixtures" / "deal_finder_smoke"


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)

    (FIXTURES / "case_a_us_unsupported.json").write_text(
        json.dumps(
            {
                "status_code": 422,
                "body": {
                    "detail": {
                        "error": "region_not_supported",
                        "message": "Region not supported: 'us'. Supported regions: pk, uk.",
                        "profile_id": "us",
                        "supported": ["pk", "uk"],
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    listings: list[dict] = []
    l0 = {
        "title": "Alcantara Phone Case",
        "vendor": "Alibaba",
        "link": "https://www.alibaba.com/product-detail/fixture-case-0.html",
        "price": "$9.00",
        "currency": "USD",
        "price_source": "page",
        "supplier_origin": "CN",
        "origin_country": "CN",
    }
    lc0 = compute_landed_cost(
        l0,
        quantity=100,
        local_currency="GBP",
        location="London, United Kingdom",
        country_code="uk",
        origin_country="CN",
        buyer_vat_registered=False,
    )
    assert lc0 is not None
    l0["landed_cost"] = lc0
    listings.append(l0)

    l1 = {
        "title": "Other Phone Case",
        "vendor": "Alibaba",
        "link": "https://www.alibaba.com/product-detail/fixture-case-1.html",
        "price": "$18.01",
        "currency": "USD",
        "price_source": "snippet",
        "supplier_origin": "CN",
        "origin_country": "CN",
    }
    lc1 = compute_landed_cost(
        l1,
        quantity=100,
        local_currency="GBP",
        location="London, United Kingdom",
        country_code="uk",
        origin_country="CN",
        buyer_vat_registered=False,
    )
    assert lc1 is not None
    l1["landed_cost"] = lc1
    listings.append(l1)

    verdict = {
        "verdict": "SKIP",
        "winner": {"title": "", "link": "", "vendor": ""},
        "rationale": "Fixture Skip — no Best pick.",
        "prose": "Skip this order for now.",
    }
    table = build_supplier_table(listings, verdict=verdict, quantity=100)
    for row in table:
        row["best_pick"] = False
    for listing in listings:
        listing["best_pick"] = False

    export_bits: list[str] = []
    for listing in listings:
        mid = (listing.get("landed_cost") or {}).get("estimated_total")
        if mid:
            export_bits.append(f"Landed mid {mid}")
        lab = (listing.get("landed_cost") or {}).get("duty_fallback_label")
        if lab:
            export_bits.append(str(lab))
    export_bits.append("estimated, not a tariff lookup")

    priced = {
        "market_listings": listings,
        "supplier_table": table,
        "export_text": "\n".join(export_bits),
        "verdict": verdict,
        "transcript": {
            "thrift_advocate": "Fixture advocate text in GBP terms.",
            "risk_analyst": "Fixture risk text.",
            "contextual_persona": "Fixture persona.",
        },
        "currency": "GBP",
    }
    (FIXTURES / "case_b_uk_priced.json").write_text(
        json.dumps(priced, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    nq_listing = {
        "title": "Unpriced Phone Case Listing",
        "vendor": "Alibaba",
        "link": "https://www.alibaba.com/product-detail/fixture-unpriced.html",
        "price": "See listing",
        "currency": None,
        "price_source": "snippet",
        "supplier_origin": "CN",
        "best_pick": False,
    }
    nq_verdict = {
        "verdict": "NO_MATCH",
        "winner": {
            "title": nq_listing["title"],
            "link": nq_listing["link"],
            "vendor": "Alibaba",
        },
        "rationale": "No usable priced listing.",
        "prose": "Insufficient relevant product pages.",
    }
    nq_table = build_supplier_table([nq_listing], verdict=nq_verdict, quantity=100)
    assert nq_table[0]["landed_mid"] == "needs quote"
    nq = {
        "market_listings": [nq_listing],
        "supplier_table": nq_table,
        "export_text": "Landed mid needs quote\nCurrency GBP / £",
        "verdict": nq_verdict,
        "transcript": {
            "thrift_advocate": "Insufficient relevant product pages.",
            "risk_analyst": "Off-category results are not usable.",
            "contextual_persona": "Ask the buyer to clarify.",
        },
        "currency": "GBP",
    }
    (FIXTURES / "case_b_uk_needs_quote.json").write_text(
        json.dumps(nq, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("wrote", FIXTURES)
    print("priced", lc0.get("estimated_total"), lc1.get("estimated_total"))
    print("needs_quote", nq_table[0]["landed_mid"])


if __name__ == "__main__":
    main()
