"""Key product nouns required in title for ALL rows (incl. UK retail)."""
from __future__ import annotations

from app.utils.relevance import (
    filter_relevant_priced_listings,
    key_product_nouns,
    listing_relevant_to_query,
)


def test_foil_rolls_nouns():
    nouns = key_product_nouns("nisbets catering foil rolls")
    assert "foil" in nouns
    assert "rolls" in nouns


def test_nisbets_junk_rows_not_relevant():
    q = "nisbets catering foil rolls"
    junk = [
        {
            "title": "Extra Wide Kitchen Foil 5m x 440mm",
            "vendor": "Britnuts",
            "price": "£1.99",
            "extracted_price": 1.99,
            "link": "https://www.google.com/search?ibp=oshop&q=x",
            "uk_retail_priced": True,
            "counts_as_priced_comparison": True,
            "is_shopping_offer": True,
        },
        {
            "title": "Bacofoil Non Stick Kitchen Foil",
            "vendor": "Dunelm",
            "price": "£3.50",
            "extracted_price": 3.5,
            "link": "https://www.google.com/search?ibp=oshop&q=y",
            "uk_retail_priced": True,
            "counts_as_priced_comparison": True,
            "is_shopping_offer": True,
        },
        {
            "title": "Nisbets Essentials Foil Disposable Containers with Lids 660ml (50 pack)",
            "vendor": "u-buy.co.uk",
            "price": "£36",
            "extracted_price": 36,
            "link": "https://www.google.com/search?ibp=oshop&q=z",
            "uk_retail_priced": True,
            "counts_as_priced_comparison": True,
            "is_shopping_offer": True,
        },
    ]
    for row in junk:
        assert listing_relevant_to_query(row, q) is False, row["vendor"]

    ok = {
        "title": "Vogue Aluminium Foil Rolls 90m Catering",
        "vendor": "Nisbets.co.uk",
        "price": "£46",
        "extracted_price": 45.58,
        "link": "https://www.nisbets.co.uk/product/foil-roll",
        "is_product_page": True,
        "uk_retail_priced": True,
        "counts_as_priced_comparison": True,
    }
    assert listing_relevant_to_query(ok, q) is True

    kept, dropped, meta = filter_relevant_priced_listings(junk + [ok], q, is_bulk=True)
    vendors = {str(x.get("vendor") or "") for x in kept}
    assert "Britnuts" not in vendors
    assert "Dunelm" not in vendors
    assert "u-buy.co.uk" not in vendors
    assert "Nisbets.co.uk" in vendors
    assert meta["relevant_priced_count"] == 1
