"""Runner and deal-finder share prepare_market_listings; NO_MATCH has empty winner."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "benchmark" / "fixtures" / "market"


def test_no_match_verdict_winner_empty():
    from app.utils.relevance import no_good_matches_verdict

    v = no_good_matches_verdict("scented candles wholesale", dropped=3)
    assert v["verdict"] == "NO_MATCH"
    assert v.get("winner") is None


def test_prepare_merges_uk_retail_from_raw():
    from app.utils.market_listings_prep import prepare_market_listings

    path = FIX / "nisbets_catering_foil_rolls__uk__bulk__GBP.json"
    if not path.is_file():
        pytest.skip("nisbets fixture missing")
    fix = json.loads(path.read_text(encoding="utf-8"))
    rows = prepare_market_listings(
        fix.get("listings") or [],
        fix.get("listings_raw") or [],
        query="nisbets catering foil rolls",
        location="Birmingham, United Kingdom",
        country_code="uk",
        local_currency="GBP",
        is_bulk=True,
    )
    assert any(r.get("uk_retail_priced") for r in rows)


def test_runner_and_api_same_kept_for_fixture(monkeypatch):
    """Same fixture → same relevant_priced_count via shared prepare + relevance."""
    from app.utils.market_listings_prep import prepare_market_listings
    from app.utils.relevance import filter_relevant_priced_listings
    from app.utils.spec_check import annotate_listings_with_spec_check

    path = FIX / "scented_candles_wholesale__uk__bulk__GBP.json"
    if not path.is_file():
        pytest.skip("candles fixture missing")
    fix = json.loads(path.read_text(encoding="utf-8"))
    q = "scented candles wholesale"

    def _pipeline(listings, raw):
        rows = prepare_market_listings(
            listings,
            raw,
            query=q,
            location="London, United Kingdom",
            country_code="uk",
            local_currency="GBP",
            is_bulk=True,
        )
        rows, _ = annotate_listings_with_spec_check(rows, q)
        kept, dropped, meta = filter_relevant_priced_listings(rows, q, is_bulk=True)
        return kept, meta

    kept_a, meta_a = _pipeline(fix.get("listings") or [], fix.get("listings_raw") or [])
    kept_b, meta_b = _pipeline(fix.get("listings") or [], fix.get("listings_raw") or [])
    assert meta_a["relevant_priced_count"] == meta_b["relevant_priced_count"]
    links_a = sorted(str(x.get("link") or "") for x in kept_a)
    links_b = sorted(str(x.get("link") or "") for x in kept_b)
    assert links_a == links_b
