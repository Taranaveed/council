"""Pack '1000 Count' parsing + towel disposable conflict terms."""
from __future__ import annotations

from app.utils.conflict_terms import detect_attribute_conflicts
from app.utils.pack_price import detect_pack_pricing, normalize_pack_unit_price
from app.utils.relevance import filter_relevant_priced_listings


def test_1000_count_pack_units():
    meta = detect_pack_pricing(
        {"title": "Hand Towels Wholesale: 1000 Count White Disposable", "price": "$12"}
    )
    assert meta["pack_units"] == 1000
    assert meta["pack_kind"] == "n_count"
    unit, norm = normalize_pack_unit_price(12.0, {"title": "1000 Count towels", "price": "$12"})
    assert norm["normalized"] is True
    assert abs(unit - 0.012) < 1e-9


def test_ct_abbreviation():
    meta = detect_pack_pricing({"title": "Soft towels 500 ct bulk", "price": "Rs 2000"})
    assert meta["pack_units"] == 500


def test_disposable_towel_conflict_drops_from_priced():
    listings = [
        {
            "title": "1000 Count White Disposable Hand Towels",
            "link": "https://www.dhgate.com/product/x.html",
            "price": "$8.50",
            "is_product_page": True,
            "wholesale": True,
        },
        {
            "title": "Soft Cotton Hand Towels Wholesale",
            "link": "https://www.indiamart.com/proddetail/soft-towel.html",
            "price": "₹90",
            "is_product_page": True,
            "wholesale": True,
        },
        {
            "title": "Hotel Soft Hand Towels Bulk Pack",
            "link": "https://www.indiamart.com/proddetail/hotel-towel.html",
            "price": "₹45",
            "is_product_page": True,
            "wholesale": True,
        },
    ]
    hits = detect_attribute_conflicts(listings[0], "soft hand towels")
    assert hits and "disposable" in hits[0]["term"]
    kept, dropped, meta = filter_relevant_priced_listings(
        listings, "soft hand towels", is_bulk=True
    )
    assert all("disposable" not in (k.get("title") or "").lower() for k in kept)
    assert any(
        d.get("attribute_conflicts") or d.get("drop_reason") == "must_have_miss"
        for d in dropped
    )
    assert meta["listing_counts"]["priced"] == len(kept)
    assert "found" in meta["listing_counts"] and "relevant" in meta["listing_counts"]
