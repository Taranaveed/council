from app.utils.origin_policy import annotate_restricted_origins
from app.utils.safe_errors import scrub_buyer_warning


def test_scrub_raw_429_and_url():
    raw = (
        "Relevance: 1 usable. Market service unreachable: Client error "
        "'429 Too Many Requests' for url 'https://council-market.onrender.com/market/prices' "
        "For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429"
    )
    cleaned = scrub_buyer_warning(raw)
    assert cleaned
    assert "429" not in cleaned
    assert "http" not in cleaned.lower()
    assert "busy" in cleaned.lower() or "retry" in cleaned.lower()


def test_restricted_origin_warns_clears_best_pick():
    rows = annotate_restricted_origins(
        [
            {
                "title": "IndiaMART towel",
                "link": "https://www.indiamart.com/proddetail/x.html",
                "supplier_origin": "IN",
                "best_pick": True,
                "pick_reason": "cheapest",
            },
            {
                "title": "Local PK",
                "link": "https://www.daraz.pk/products/x.html",
                "supplier_origin": "PK",
                "best_pick": False,
            },
        ],
        country_code="pk",
        local_currency="PKR",
    )
    assert rows[0]["origin_restricted"] is True
    assert rows[0]["best_pick"] is False
    assert "pick_reason" not in rows[0]
    assert "Restricted origin" in (rows[0].get("rank_reason") or "")
    assert rows[1].get("origin_restricted") is False
