"""Phase 1–3 fixture tests for Buyer council correctness gates."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.utils.claim_dispute import apply_disputed_to_listings, extract_seller_claims, mark_disputed_claims
from app.utils.landed_cost import compute_landed_cost
from app.utils.listing_risk import build_listing_risk_flags
from app.utils.money import parse_money
from app.utils.relevance import filter_relevant_priced_listings, no_good_matches_verdict
from app.utils.tier_select import select_tier_for_quantity
from app.utils.verdict_prose import build_verdict_prose, validate_prose_numbers


class TestMoneyParse:
    def test_rs_thousands_comma(self):
        assert parse_money("Rs 1,569") == 1569.0
        assert parse_money("Rs. 1,569") == 1569.0
        assert parse_money("1,569") == 1569.0


class TestTierMoq:
    def test_tier_603_not_applied_to_qty_100(self):
        tiers = [
            {"min_qty": 603, "max_qty": None, "unit_price": "Rs 8"},
        ]
        sel = select_tier_for_quantity(tiers, 100)
        assert sel["moq_not_met"] is True
        assert sel["tier"] is None
        assert sel["lowest_min_qty"] == 603


class TestRelevanceNoMatch:
    def test_mobile_adapters_off_category_no_good_matches(self):
        listings = [
            {
                "title": "Bathroom Window Vinyl",
                "link": "https://shop.example/products/bathroom-window",
                "price": "Rs 500",
                "is_product_page": True,
                "counts_as_live_listing": True,
            },
            {
                "title": "Truck Camper Shell",
                "link": "https://shop.example/products/truck-camper",
                "price": "Rs 90000",
                "is_product_page": True,
                "counts_as_live_listing": True,
            },
            {
                "title": "Floral Wallpaper Roll",
                "link": "https://shop.example/products/wallpaper",
                "price": "Rs 1200",
                "is_product_page": True,
                "counts_as_live_listing": True,
            },
        ]
        kept, dropped, meta = filter_relevant_priced_listings(listings, "mobile adapters")
        assert meta["no_good_matches"] is True
        assert len(kept) < 2
        verdict = no_good_matches_verdict("mobile adapters", dropped=len(dropped))
        assert verdict["verdict"] == "NO_MATCH"
        assert not verdict["winner"].get("link")
        assert "Best pick" not in (verdict["winner"].get("reason") or "")

    def test_phone_handsets_rejected_for_adapter_query(self):
        listings = [
            {
                "title": "Hot Selling Global Version MT Mobile Phone 16G+1TB",
                "link": "https://www.alibaba.com/product-detail/phone_1.html",
                "price": "$80",
                "is_product_page": True,
                "counts_as_live_listing": True,
            },
            {
                "title": "Wholesale Mobile Phone",
                "link": "https://www.made-in-china.com/product/phone.html",
                "price": "$86.90",
                "is_product_page": True,
                "counts_as_live_listing": True,
            },
            {
                "title": "Drivable Mobile Street Truck Electric Food Truck",
                "link": "https://www.alibaba.com/product-detail/truck_1.html",
                "price": "$12000",
                "is_product_page": True,
                "counts_as_live_listing": True,
            },
            {
                "title": "USB Wall Charger Adapter 20W PD Type-C",
                "link": "https://www.indiamart.com/proddetail/usb-wall-charger-adapter-20w.html",
                "price": "Rs 180",
                "is_product_page": True,
                "counts_as_live_listing": True,
            },
        ]
        kept, dropped, meta = filter_relevant_priced_listings(
            listings, "usb wall mobile adapters"
        )
        assert all("phone" not in (k.get("title") or "").lower() or "charger" in (k.get("title") or "").lower() for k in kept)
        assert len(kept) == 1
        assert meta["no_good_matches"] is True
        assert any("Mobile Phone" in (d.get("title") or "") for d in dropped)


class TestVerdictProse:
    def test_orphan_number_fails_validation(self):
        prose = "Buy this at Rs 8 per piece with landed Rs 50,000."
        ok, orphans = validate_prose_numbers(
            prose,
            card_price="Rs 1,569",
            landed={
                "unit_price": "Rs 1,569",
                "estimated_total": "Rs 45,000",
                "range_low": "Rs 40,000",
                "range_high": "Rs 55,000",
            },
        )
        assert ok is False
        assert any("8" in o for o in orphans)

    def test_template_matches_card(self):
        winner = {"vendor": "Acme", "price": "Rs 1,569", "title": "USB Adapter"}
        landed = {
            "estimated_total": "Rs 45,000",
            "range_low": "Rs 40,000",
            "range_high": "Rs 55,000",
            "cost_vs_budget": "Mid landed Rs 45,000 is under budget Rs 50,000 (headroom Rs 5,000)",
            "max_units_that_fit": 110,
            "budget_display": "Rs 50,000",
        }
        prose = build_verdict_prose(tag="BUY", winner=winner, landed=landed, budget=50000)
        ok, orphans = validate_prose_numbers(
            prose, card_price=winner["price"], landed=landed
        )
        assert ok is True, orphans


class TestWarrantyFlag:
    def test_page_with_warranty_and_refund_no_unverified_flag(self):
        listings = [
            {
                "title": "USB Wall Charger",
                "link": "https://shop.example/products/charger-1",
                "price": "Rs 450",
                "price_source": "page",
                "page_facts_fetched": True,
                "is_product_page": True,
                "warranty": "1-year manufacturer warranty",
                "warranty_source": "page",
                "policy_links": [
                    {"label": "Refund policy", "url": "https://shop.example/pages/refund-policy"},
                ],
                "vendor_status": "Verified",
            }
        ]
        flags = build_listing_risk_flags(listings, query="USB wall charger")
        codes = [f["code"] for f in flags]
        assert "warranty_not_verified" not in codes


class TestLandedFreightWarn:
    def test_assumed_weight_freight_dominates(self):
        listing = {
            "title": "USB adapter wholesale",
            "link": "https://www.alibaba.com/product-detail/adapter_123.html",
            "price": "$0.50",
            "currency": "USD",
            "price_source": "page",
            "is_product_page": True,
            "supplier_origin": "CN",
            # no package_weight_kg → assumed category weight
        }
        landed = compute_landed_cost(
            listing, quantity=100, local_currency="PKR", budget=None
        )
        assert landed is not None
        assert landed.get("freight_share") is not None
        # Force path: tiny unit price + assumed weight should trigger 3x warn
        assert landed.get("freight_dominates_warning") is True or (
            landed.get("package_weight_kg") or 0
        ) > 0
        # Explicit 0.15 kg assumption when no category match
        listing2 = {
            **listing,
            "title": "Generic widget",
            "price": "$0.20",
        }
        landed2 = compute_landed_cost(
            listing2,
            quantity=50,
            local_currency="PKR",
            country_code="pk",
            location="Lahore, Pakistan",
            budget=None,
        )
        assert landed2 is not None
        assert landed2.get("package_weight_kg") == 0.15 or landed2.get(
            "freight_dominates_warning"
        )
        # With 0.15 kg assumed and cheap unit, freight share warning should fire
        assert landed2.get("freight_dominates_warning") is True


class TestDisputedAddress:
    def test_two_agents_contradictory_address(self):
        texts = {
            "thrift_advocate": "Seller office address: 12 Clifton Block 5, Karachi.",
            "risk_analyst": "Seller warehouse address: 88 Gulberg III, Lahore industrial area.",
        }
        claims = mark_disputed_claims(extract_seller_claims(texts, seller_hint="Acme"))
        disputed = [c for c in claims if c.get("disputed")]
        assert len(disputed) >= 2
        listings = [
            {
                "title": "Adapter",
                "link": "https://shop.example/products/a1",
                "vendor": "Acme",
                "best_pick": True,
            }
        ]
        annotated, _ = apply_disputed_to_listings(listings, texts)
        assert annotated[0].get("facts_disputed") is True


class TestWiredHandsfree:
    def test_wireless_earbuds_dropped_for_wired_query(self):
        from app.utils.spec_check import annotate_listings_with_spec_check
        from app.utils.relevance import filter_relevant_priced_listings

        q = "wired mobile handfrees wholesale"
        listings = [
            {
                "title": "Waterproof Sports Earphones Earbuds",
                "link": "https://www.alibaba.com/product-detail/a.html",
                "price": "$2.85",
                "is_product_page": True,
            },
            {
                "title": "New Bee Bluetooth Earphones",
                "link": "https://www.alibaba.com/product-detail/b.html",
                "price": "$7.99",
                "is_product_page": True,
            },
            {
                "title": "Wired Handsfree 3.5mm Jack Earphones",
                "link": "https://www.indiamart.com/proddetail/wired.html",
                "price": "Rs 45",
                "is_product_page": True,
            },
        ]
        ann, must = annotate_listings_with_spec_check(listings, q)
        assert any(m.get("id") == "wired" for m in must)
        kept, _, meta = filter_relevant_priced_listings(ann, q)
        titles = " ".join(str(k.get("title") or "") for k in kept).lower()
        assert "wired" in titles or "3.5" in titles
        assert "bluetooth" not in titles
        assert "earbuds" not in titles
        assert len(kept) >= 1

    def test_wired_query_auto_narrows_to_3_5mm(self):
        from app.utils.query_specificity import maybe_narrow_query

        used, meta = maybe_narrow_query("wired handfrees wholesale", auto=True)
        assert "handsfree" in used.lower()
        assert "3.5" in used.lower() or "earphone" in used.lower()
        assert meta.get("auto_narrowed") is True

    def test_clear_best_pick_strips_pick_reason(self):
        from app.utils.verdict_verify import clear_best_pick

        rows = clear_best_pick(
            [
                {
                    "title": "TWS Wireless",
                    "best_pick": True,
                    "pick_reason": "best overall for this region, quantity, and budget",
                    "rank_reason": "Ranked first",
                }
            ]
        )
        assert rows[0]["best_pick"] is False
        assert "pick_reason" not in rows[0]
        assert "rank_reason" not in rows[0]


class TestPriceOutliers:
    def test_extreme_spread_dropped(self):
        listings = [
            {
                "title": "Ceramic mug A",
                "link": "https://www.alibaba.com/product-detail/a.html",
                "price": "$1.17",
                "currency": "USD",
                "is_product_page": True,
            },
            {
                "title": "Ceramic mug B",
                "link": "https://www.alibaba.com/product-detail/b.html",
                "price": "$1.50",
                "currency": "USD",
                "is_product_page": True,
            },
            {
                "title": "Ceramic mug C",
                "link": "https://www.alibaba.com/product-detail/c.html",
                "price": "$2.00",
                "currency": "USD",
                "is_product_page": True,
            },
            {
                "title": "Ceramic mug lot misread",
                "link": "https://www.alibaba.com/product-detail/d.html",
                "price": "$1200",
                "currency": "USD",
                "is_product_page": True,
            },
        ]
        kept, dropped, meta = filter_relevant_priced_listings(listings, "ceramic mugs wholesale")
        assert all(parse_money(k.get("price")) < 100 for k in kept)
        assert any(d.get("drop_reason") == "price_outlier" for d in dropped)
        assert any("1200" in str(d.get("price")) for d in dropped)


class TestMustHaveHardExclude:
    def test_ceramic_miss_excluded_from_kept(self):
        from app.utils.spec_check import annotate_listings_with_spec_check

        listings = [
            {
                "title": "Ceramic Coffee Mug Wholesale",
                "link": "https://www.alibaba.com/product-detail/mug.html",
                "price": "$1.20",
                "is_product_page": True,
            },
            {
                "title": "Stainless Steel Thermos Flask",
                "link": "https://www.alibaba.com/product-detail/thermos.html",
                "price": "$3.50",
                "is_product_page": True,
            },
            {
                "title": "Ceramic Tea Cup Set",
                "link": "https://www.indiamart.com/proddetail/cup.html",
                "price": "Rs 90",
                "is_product_page": True,
            },
        ]
        ann, must = annotate_listings_with_spec_check(listings, "ceramic mugs wholesale")
        assert any(m.get("id") == "ceramic" for m in must)
        kept, dropped, meta = filter_relevant_priced_listings(ann, "ceramic mugs wholesale")
        titles = " ".join(str(k.get("title") or "") for k in kept).lower()
        assert "thermos" not in titles
        assert "stainless" not in titles
        assert any(d.get("drop_reason") == "must_have_miss" for d in dropped)
        assert meta["relevant_priced_count"] == len(kept)
        assert all("ceramic" in (k.get("title") or "").lower() for k in kept)

    def test_moq_not_met_clears_tier_price(self):
        listing = {
            "title": "Bulk beads",
            "link": "https://www.alibaba.com/product-detail/beads_1.html",
            "price": "Rs 50",
            "currency": "PKR",
            "price_source": "page",
            "is_product_page": True,
            "supplier_origin": "CN",
            "tiers_source": "page",
            "tiers_reliable": True,
            "price_tiers": [
                {"min_qty": 603, "unit_price": "Rs 8", "currency": "PKR"},
            ],
            "package_weight_kg": 0.01,
        }
        landed = compute_landed_cost(listing, quantity=100, local_currency="PKR")
        assert landed is not None
        assert landed.get("moq_not_met") is True
        # Should not use Rs 8 as the unit
        unit = parse_money(landed.get("unit_price"))
        assert unit is not None
        assert unit != 8.0


class TestLandedIgnoresSnippetTier:
    def test_snippet_rs3_tier_does_not_replace_usd_card(self):
        """$3.30 card must not become Rs 3 just because a snippet tier says so."""
        listing = {
            "title": "Wholesale DX-45 Sports Wireless Headset",
            "link": "https://www.alibaba.com/product-detail/High-Quality-Manufact.html",
            "price": "$3.30",
            "currency": "USD",
            "price_source": "serp",
            "is_product_page": True,
            "supplier_origin": "CN",
            "tiers_source": "snippet",
            "tiers_reliable": True,  # even if structurally "reliable", source is snippet
            "price_tiers": [
                {"min_qty": 100, "unit_price": "Rs 3", "currency": "PKR"},
            ],
            "package_weight_kg": 0.05,
        }
        shared = __import__(
            "app.utils.cost_assumptions", fromlist=["shared_cost_assumptions"]
        ).shared_cost_assumptions(local_currency="PKR", foreign_factory=True)
        landed = compute_landed_cost(
            listing, quantity=200, local_currency="PKR", cost_assumptions=shared
        )
        assert landed is not None
        assert landed.get("tiers_verified") is False
        assert landed.get("unconfirmed_tier_note")
        unit_local = parse_money(landed.get("unit_price_local"))
        # $3.30 → PKR should be hundreds, not ~3
        assert unit_local is not None and unit_local > 100
        mid = float(landed.get("estimated_total_amount") or 0)
        # 200 × ~Rs900-scale unit → mid well above 50k, not ~20k from Rs3
        assert mid > 100_000


class TestTotalsConsistency:
    def test_divergent_agent_total_gets_caveat(self):
        from app.utils.total_consistency import check_totals_consistency

        landed = {
            "estimated_total": "Rs 220,000",
            "estimated_total_amount": 220000.0,
            "range_low": "Rs 180,000",
            "range_high": "Rs 280,000",
            "range_low_amount": 180000.0,
            "range_high_amount": 280000.0,
        }
        transcript = {
            "risk_analyst": "Landed cost is about Rs 25,000 using the Rs 3 tier — too good to trust.",
            "contextual_persona": "Total around Rs 248,000 fits the budget story.",
            "thrift_advocate": "Best value at $3.30.",
        }
        report, out, notes = check_totals_consistency(landed, transcript, tolerance=0.15)
        assert report["ok"] is False
        assert "totals_inconsistent" in notes
        assert "Consistency note" in out["risk_analyst"]
        # Persona total is within range → may or may not diverge; risk at 25k must diverge
        assert any(d.get("agent") == "risk_analyst" for d in report["divergences"])


class TestVerdictHedge:
    def test_safest_downgraded_when_agents_hedge(self):
        from app.utils.verdict_hedge import hedge_verdict_confidence

        verdict = {
            "verdict": "BUY",
            "summary": "Buy — the safest bulk choice on Alibaba.",
            "winner": {
                "reason": "The safest bulk choice given the listings.",
                "link": "https://www.alibaba.com/product-detail/x.html",
            },
        }
        transcript = {
            "risk_analyst": "This is only marginally safer, not fully safe — verify MOQ.",
            "contextual_persona": "Prefer this with caution.",
            "thrift_advocate": "Cheapest.",
        }
        out, notes = hedge_verdict_confidence(verdict, transcript)
        assert str(out.get("verdict") or "").upper() == "MAYBE"
        assert "safest" not in str(out.get("summary") or "").lower()
        assert "confidence_capped_maybe" in notes


class TestSharedCostAssumptions:
    def test_agents_and_calculator_share_duty_band(self):
        from app.utils.cost_assumptions import shared_cost_assumptions

        shared = shared_cost_assumptions(local_currency="PKR", foreign_factory=True)
        assert shared["duty_rate_mid"] == 0.25
        assert "do NOT invent" in shared["prompt_block"] or "Do NOT invent" in shared["prompt_block"]
        assert "25%" in shared["prompt_block"]

        listing = {
            "title": "USB adapter",
            "link": "https://www.alibaba.com/product-detail/a.html",
            "price": "$1.50",
            "currency": "USD",
            "price_source": "page",
            "is_product_page": True,
            "supplier_origin": "CN",
            "package_weight_kg": 0.05,
        }
        landed = compute_landed_cost(
            listing,
            quantity=100,
            local_currency="PKR",
            cost_assumptions=shared,
        )
        assert landed is not None
        assert landed["duty_rate"] == shared["duty_rate_mid"]
        assert landed["sales_tax_rate"] == shared["sales_tax_rate"]
        assert any("25%" in a for a in (landed.get("assumptions") or []))


class TestMoqNotConfirmed:
    def test_not_on_snippet_hides_number(self):
        listing = {
            "title": "Beads",
            "link": "https://www.alibaba.com/product-detail/b.html",
            "price": "$2",
            "currency": "USD",
            "price_source": "page",
            "is_product_page": True,
            "supplier_origin": "CN",
            "moq": 18,
            "moq_source": "not_on_snippet",
            "package_weight_kg": 0.02,
        }
        landed = compute_landed_cost(listing, quantity=50, local_currency="PKR")
        assert landed is not None
        assert landed.get("moq") is None
        assert "not confirmed" in str(landed.get("moq_assumption") or "").lower()
        assert "MOQ 18" not in str(landed.get("moq_assumption") or "")


class TestRiskHardSignal:
    def test_risk_pass_on_unverified_clears_buy(self):
        from app.utils.debate_gates import apply_risk_hard_signal

        listings = [
            {
                "title": "Cheap pick",
                "link": "https://www.alibaba.com/product-detail/cheap.html",
                "price": "$1",
                "price_source": "serp",
                "unit_price_verified": False,
                "best_pick": True,
                "is_product_page": True,
            },
            {
                "title": "Safer pick",
                "link": "https://www.indiamart.com/proddetail/safe.html",
                "price": "Rs 120",
                "price_source": "page",
                "is_product_page": True,
            },
        ]
        verdict = {
            "verdict": "MAYBE",
            "winner": {
                "title": "Cheap pick",
                "vendor": "Factory",
                "price": "$1",
                "link": listings[0]["link"],
                "reason": "Cheapest unit.",
            },
            "summary": "Maybe, verify — cheapest option.",
        }
        transcript = {
            "thrift_advocate": "Best value is $1 per unit after 100+.",
            "risk_analyst": (
                "I recommend PASS on the thrift pick — unverified SERP pricing and fraud risk. "
                "Prefer the IndiaMART page-verified listing."
            ),
            "contextual_persona": "Budget is tight.",
        }
        flags = build_listing_risk_flags(listings, winner=verdict["winner"])
        out, rows, notes = apply_risk_hard_signal(
            verdict, transcript, listings, risk_flags=flags
        )
        assert "risk_hard_signal_pass" in notes
        assert str(out.get("verdict") or "").upper() in ("PASS", "MAYBE")
        assert "disagree" in str(out.get("summary") or "").lower() or "Risk" in str(
            out.get("summary") or ""
        )
        if str(out.get("verdict") or "").upper() == "MAYBE":
            assert "cheap.html" not in str((out.get("winner") or {}).get("link") or "")
        assert out.get("agent_disagreement")


class TestUnverifiedPriceScrub:
    def test_thrift_caveat_on_serp_tier(self):
        from app.utils.debate_gates import scrub_unverified_price_claims

        listings = [
            {
                "title": "Tier claim",
                "link": "https://www.alibaba.com/product-detail/t.html",
                "price": "$1",
                "price_source": "serp",
                "price_tiers": [{"min_qty": 100, "unit_price": "$1"}],
            }
        ]
        transcript = {
            "thrift_advocate": (
                "Best value is this listing at only $1 per unit after 100+ units."
            ),
            "risk_analyst": "Pass on unverified pricing.",
            "contextual_persona": "Ok.",
        }
        out, notes = scrub_unverified_price_claims(transcript, listings)
        assert any("unverified_price_caveat" in n for n in notes)
        assert "unverified" in out["thrift_advocate"].lower()


class TestRiskFlagSeverityOrder:
    def test_best_pick_high_risk_sorted_first(self):
        listings = [
            {
                "title": "Best pick unverified",
                "link": "https://www.alibaba.com/product-detail/best.html",
                "price": "$1",
                "price_source": "serp",
                "best_pick": True,
                "is_product_page": True,
                "vendor_status": "Known marketplace",
            },
            {
                "title": "Other medium",
                "link": "https://www.alibaba.com/product-detail/other.html",
                "price": "$3",
                "price_source": "page",
                "page_facts_fetched": True,
                "is_product_page": True,
                "vendor_status": "Known marketplace",
                "moq": None,
            },
        ]
        winner = {"link": listings[0]["link"], "title": listings[0]["title"]}
        flags = build_listing_risk_flags(listings, winner=winner, max_flags=8)
        assert flags
        assert flags[0].get("severity") == "high"
        assert "best.html" in str(flags[0].get("link") or "")
        assert flags[0].get("code") == "price_not_verified"


class TestPhoneCoverRelevance:
    def test_iphone_covers_keep_case_listings(self):
        listings = [
            {
                "title": "Soft TPU Mobile Phone Cover Protective Case",
                "link": "https://www.alibaba.com/product-detail/Soft-TPU-Cover_1.html",
                "price": "$0.35",
                "is_product_page": True,
                "wholesale": True,
            },
            {
                "title": "For iPhone 14/15 Silicone Case Cover Wholesale",
                "link": "https://www.alibaba.com/product-detail/iPhone-Case_2.html",
                "price": "$0.55",
                "is_product_page": True,
                "wholesale": True,
            },
            {
                "title": "Hot Selling Global Version Smartphone 16G+1TB",
                "link": "https://www.alibaba.com/product-detail/phone_3.html",
                "price": "$89",
                "is_product_page": True,
            },
        ]
        kept, dropped, meta = filter_relevant_priced_listings(
            listings, "iphone mobile covers"
        )
        assert meta["relevant_priced_count"] >= 2
        assert meta["no_good_matches"] is False
        assert all("cover" in (k.get("title") or "").lower() or "case" in (k.get("title") or "").lower() for k in kept)
        assert any("Smartphone" in (d.get("title") or "") for d in dropped)

    def test_reviewable_unpriced_cover(self):
        from app.utils.relevance import is_reviewable_product_listing, listing_relevant_to_query

        row = {
            "title": "Mobile Phone Soft Cover Wholesale",
            "link": "https://www.alibaba.com/product-detail/Cover_9.html",
            "price": "See listing",
            "is_product_page": True,
            "wholesale": True,
            "needs_price_confirm": True,
        }
        assert is_reviewable_product_listing(row) is True
        assert listing_relevant_to_query(row, "iphone mobile covers") is True


class TestAuditGatesABC:
    def test_implausible_gold_hard_excluded(self):
        listings = [
            {
                "title": "Solid 18K Gold Ring Wholesale",
                "link": "https://www.alibaba.com/product-detail/gold_1.html",
                "price": "$1.31",
                "is_product_page": True,
                "wholesale": True,
            },
            {
                "title": "Fashion Alloy Finger Ring",
                "link": "https://www.alibaba.com/product-detail/alloy_2.html",
                "price": "$0.55",
                "is_product_page": True,
                "wholesale": True,
            },
            {
                "title": "Stainless Steel Women Ring",
                "link": "https://www.alibaba.com/product-detail/ss_3.html",
                "price": "$0.80",
                "is_product_page": True,
                "wholesale": True,
            },
        ]
        kept, dropped, meta = filter_relevant_priced_listings(
            listings, "gold rings wholesale", is_bulk=True
        )
        assert any(d.get("implausible_metal") == "gold" or "Implausible" in str(d.get("price_outlier_reason") or "") for d in dropped)
        assert all("$1.31" not in str(k.get("price")) for k in kept)

    def test_retail_hard_excluded_in_bulk(self):
        listings = [
            {
                "title": "Women Ring Retail",
                "link": "https://www.daraz.pk/products/ring-1.html",
                "price": "Rs 450",
                "is_product_page": True,
                "channel": "retail",
                "sourcing_action": "ask_bulk_quote",
            },
            {
                "title": "Finger Ring Wholesale A",
                "link": "https://www.indiamart.com/proddetail/ring-a.html",
                "price": "₹70",
                "is_product_page": True,
                "wholesale": True,
                "channel": "wholesale",
            },
            {
                "title": "Finger Ring Wholesale B",
                "link": "https://www.indiamart.com/proddetail/ring-b.html",
                "price": "₹85",
                "is_product_page": True,
                "wholesale": True,
                "channel": "wholesale",
            },
        ]
        kept, dropped, meta = filter_relevant_priced_listings(
            listings, "women rings wholesale", is_bulk=True
        )
        assert any(d.get("drop_reason") == "retail_in_bulk" for d in dropped)
        assert all(k.get("channel") != "retail" for k in kept)
        assert meta["retail_dropped"] >= 1

    def test_landed_refuses_outlier_and_mid_in_range(self):
        from app.utils.landed_cost import compute_landed_cost
        from app.utils.cost_assumptions import shared_cost_assumptions

        bad = {
            "title": "Solid 18K Gold",
            "link": "https://www.alibaba.com/product-detail/g.html",
            "price": "$1.31",
            "currency": "USD",
            "price_source": "page",
            "is_product_page": True,
            "price_outlier": True,
            "unit_price_unreliable": True,
            "implausible_metal": "gold",
            "supplier_origin": "CN",
        }
        bad_lc = compute_landed_cost(bad, quantity=100, local_currency="PKR")
        assert bad_lc is not None and bad_lc.get("hide_landed") is True
        assert bad_lc.get("estimated_total") is None

        good = {
            "title": "Alloy Ring",
            "link": "https://www.alibaba.com/product-detail/a.html",
            "price": "$0.80",
            "currency": "USD",
            "price_source": "page",
            "is_product_page": True,
            "unit_price_verified": True,
            "supplier_origin": "CN",
            "package_weight_kg": 0.02,
            "package_weight_source": "page",
        }
        ca = shared_cost_assumptions(local_currency="PKR", foreign_factory=True)
        landed = compute_landed_cost(
            good, quantity=100, local_currency="PKR", cost_assumptions=ca
        )
        assert landed is not None
        lo = float(str(landed["range_low"]).replace(",", "").split()[-1]) if False else None
        # Prefer structured fields if present
        totals = []
        for key in ("total_low", "total_mid", "total_high"):
            if landed.get(key) is not None:
                totals.append(float(landed[key]))
        if len(totals) == 3:
            assert totals[0] <= totals[1] <= totals[2]
        assert "page" in str(landed.get("weight_assumption") or landed.get("assumptions") or "")

    def test_moq_not_on_snippet_hidden_in_fact_sheet(self):
        from app.utils.fact_sheet import build_listing_fact_sheet, fact_sheet_for_prompt

        sheet = build_listing_fact_sheet(
            [
                {
                    "title": "Ring",
                    "link": "https://www.alibaba.com/product-detail/r.html",
                    "price": "$0.80",
                    "price_source": "page",
                    "is_product_page": True,
                    "unit_price_verified": True,
                    "moq": 18,
                    "moq_source": "not_on_snippet",
                    "package_weight_kg": 0.01,
                    "package_weight_source": "snippet",
                }
            ]
        )
        row = sheet["listings"][0]
        assert row.get("moq") is None
        assert row.get("package_weight_kg") is None
        prompt = fact_sheet_for_prompt(sheet)
        assert "MOQ=18" not in prompt
        assert "MOQ=not_confirmed" in prompt
        assert "weight_kg=not_confirmed" in prompt

    def test_malformed_price_concat_rejected(self):
        from app.utils.money import is_malformed_price_string, parse_money, sanitize_price_raw
        from app.utils.price_plausibility import annotate_price_outliers

        raw = "$1.321,000"
        assert is_malformed_price_string(raw)
        assert sanitize_price_raw(raw) == "$1.32"
        assert parse_money(raw) == 1.32

        rows = annotate_price_outliers(
            [
                {
                    "title": "Ceramic Mug",
                    "price": raw,
                    "currency": "USD",
                    "link": "https://www.alibaba.com/product-detail/m.html",
                },
                {
                    "title": "Ceramic Mug B",
                    "price": "$0.80",
                    "currency": "USD",
                    "link": "https://www.alibaba.com/product-detail/b.html",
                },
                {
                    "title": "Ceramic Mug C",
                    "price": "$1.10",
                    "currency": "USD",
                    "link": "https://www.alibaba.com/product-detail/c.html",
                },
            ],
            query="ceramic mugs wholesale",
        )
        bad = next(r for r in rows if "1.321" in str(r.get("price_malformed_original") or r.get("price") or "") or r.get("price_outlier"))
        assert bad.get("price_outlier") is True
        assert "1.321,000" not in str(bad.get("price") or "")

    def test_mid_always_inside_range_amounts(self):
        from app.utils.landed_cost import compute_landed_cost
        from app.utils.cost_assumptions import shared_cost_assumptions
        from app.utils.money import parse_money

        listing = {
            "title": "Ceramic Mug",
            "link": "https://www.alibaba.com/product-detail/m.html",
            "price": "$0.85",
            "currency": "USD",
            "price_source": "page",
            "is_product_page": True,
            "unit_price_verified": True,
            "supplier_origin": "CN",
            "package_weight_kg": 0.35,
            "package_weight_source": "page",
        }
        ca = shared_cost_assumptions(local_currency="PKR", foreign_factory=True)
        landed = compute_landed_cost(
            listing, quantity=150, local_currency="PKR", cost_assumptions=ca
        )
        assert landed is not None
        lo = float(landed["range_low_amount"])
        hi = float(landed["range_high_amount"])
        mid = float(landed["estimated_total_amount"])
        assert lo <= mid <= hi
        # Displayed mid must also parse inside displayed range
        mid_disp = parse_money(landed["estimated_total"])
        lo_disp = parse_money(landed["range_low"])
        hi_disp = parse_money(landed["range_high"])
        assert mid_disp is not None and lo_disp is not None and hi_disp is not None
        assert lo_disp <= mid_disp <= hi_disp
        assert "Mid landed:" in str(landed["formula"])
        # Formula must not use a bare "= Rs X" line-total that readers confuse for mid
        assert not re.search(r"=\s*Rs\s*[\d,]+\s*\+", str(landed["formula"]))
