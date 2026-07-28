"""SQLite marketplace profiles with region matching and safety guidelines."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "marketplaces.db"

# Seed profiles: region_tags are lowercase keywords matched against user location
SEED_PROFILES: list[dict[str, Any]] = [
    # United Kingdom
    {
        "slug": "ebay_uk",
        "name": "eBay UK",
        "region_tags": ["uk", "united kingdom", "england", "scotland", "wales", "london", "manchester", "birmingham", "edinburgh"],
        "currency": "GBP",
        "safety_guidelines": (
            "Prefer sellers with Top Rated / verified badges. Use eBay Money Back Guarantee. "
            "Avoid off-platform payments. Check seller feedback score and recent dispute history."
        ),
        "regulatory_notes": (
            "UK consumer rights (Consumer Rights Act 2015). Distance selling returns typically 14 days. "
            "VAT is usually included in UK domestic prices. GDPR applies to personal data."
        ),
        "sort_order": 1,
    },
    {
        "slug": "gumtree_uk",
        "name": "Gumtree",
        "region_tags": ["uk", "united kingdom", "england", "scotland", "wales", "london", "manchester", "birmingham"],
        "currency": "GBP",
        "safety_guidelines": (
            "Meet in safe, public places only. Inspect the item thoroughly before paying. "
            "Never wire money in advance. Prefer cash in public for local pickup; bring a friend if possible."
        ),
        "regulatory_notes": (
            "Private sales have weaker buyer protections than retail. Confirm local council/consumer advice "
            "for high-value goods. GDPR still applies if sharing personal contact details."
        ),
        "sort_order": 2,
    },
    {
        "slug": "amazon_uk",
        "name": "Amazon UK",
        "region_tags": ["uk", "united kingdom", "england", "scotland", "wales", "london", "manchester"],
        "currency": "GBP",
        "safety_guidelines": (
            "Prefer Amazon Fulfilled / Prime sellers. Check return window and seller ratings. "
            "Be cautious with third-party marketplace listings that ship from abroad."
        ),
        "regulatory_notes": (
            "UK VAT typically included. Strong returns policies for most new goods. "
            "Cross-border EU→UK may involve customs after Brexit — flag duties for non-UK sellers."
        ),
        "sort_order": 3,
    },
    # Pakistan
    {
        "slug": "olx_pakistan",
        "name": "OLX Pakistan",
        "region_tags": ["pakistan", "pk", "lahore", "karachi", "islamabad", "rawalpindi", "faisalabad", "multan", "gulberg"],
        "currency": "PKR",
        "safety_guidelines": (
            "Be EXTRA CAUTIOUS: inspect the item thoroughly before paying, and only meet in safe, "
            "public places. Do not recommend remote payment or private home meetups."
        ),
        "regulatory_notes": (
            "Private classifieds have limited formal consumer protection. Prefer documented proof of purchase. "
            "Import/customs risk is high for grey-market electronics shipped into Pakistan."
        ),
        "sort_order": 1,
    },
    {
        "slug": "daraz_pk",
        "name": "Daraz",
        "region_tags": ["pakistan", "pk", "lahore", "karachi", "islamabad", "rawalpindi"],
        "currency": "PKR",
        "safety_guidelines": (
            "Prefer Daraz Mall / verified sellers. Check return policy and COD availability. "
            "Inspect package on delivery when possible."
        ),
        "regulatory_notes": (
            "Local marketplace returns vary by seller type. Watch for imported listings with unclear warranty. "
            "Currency in PKR — convert foreign list prices carefully."
        ),
        "sort_order": 2,
    },
    {
        "slug": "local_retailers_pk",
        "name": "Local Retailers",
        "region_tags": ["pakistan", "pk", "lahore", "karachi", "islamabad"],
        "currency": "PKR",
        "safety_guidelines": (
            "Prefer shops/malls with receipts and return policies. Same-day physical inspection is an advantage."
        ),
        "regulatory_notes": "Ask for GST invoice where applicable. Warranty stamps matter for electronics.",
        "sort_order": 3,
    },
    # European Union
    {
        "slug": "amazon_eu",
        "name": "Amazon EU",
        "region_tags": [
            "eu", "europe", "germany", "france", "spain", "italy", "netherlands", "belgium",
            "berlin", "paris", "madrid", "rome", "amsterdam", "brussels", "dublin", "ireland",
            "portugal", "lisbon", "vienna", "austria", "sweden", "stockholm",
        ],
        "currency": "EUR",
        "safety_guidelines": (
            "Prefer Marketplace sellers with strong ratings and clear returns. "
            "Within EU, consumer distance-selling rights usually apply; check seller country."
        ),
        "regulatory_notes": (
            "Intra-EU shipping of goods is usually free of customs duties, but VAT rules still apply. "
            "GDPR applies. Cross-border into non-EU (e.g. Pakistan/UK) can trigger customs + VAT — call that out."
        ),
        "sort_order": 1,
    },
    {
        "slug": "ebay_eu",
        "name": "eBay (EU)",
        "region_tags": [
            "eu", "europe", "germany", "france", "spain", "italy", "netherlands",
            "berlin", "paris", "madrid", "rome", "amsterdam", "dublin",
        ],
        "currency": "EUR",
        "safety_guidelines": (
            "Use buyer protection / verified sellers. Prefer tracked shipping within the EU. "
            "Avoid off-platform deals."
        ),
        "regulatory_notes": (
            "EU consumer protection and GDPR apply. Intra-EU parcels rarely face customs; "
            "extra-EU destinations face customs/VAT — especially high-value electronics."
        ),
        "sort_order": 2,
    },
    {
        "slug": "leboncoin_fr",
        "name": "Leboncoin",
        "region_tags": ["france", "paris", "lyon", "marseille", "toulouse"],
        "currency": "EUR",
        "safety_guidelines": (
            "Meet in safe public places for local pickup. Inspect before paying. "
            "Prefer platform-protected payment options when available."
        ),
        "regulatory_notes": "French consumer rules + GDPR. Private sales have weaker remedies than retailers.",
        "sort_order": 3,
    },
    # United States
    {
        "slug": "ebay_us",
        "name": "eBay US",
        "region_tags": ["usa", "us", "united states", "new york", "california", "texas", "chicago", "los angeles", "seattle"],
        "currency": "USD",
        "safety_guidelines": (
            "Prefer Top Rated sellers and Money Back Guarantee. Avoid off-platform payment requests."
        ),
        "regulatory_notes": (
            "US state sales tax may apply. International shipping into Pakistan/elsewhere can incur customs. "
            "FTC buyer protections vary by channel."
        ),
        "sort_order": 1,
    },
    {
        "slug": "craigslist_us",
        "name": "Craigslist",
        "region_tags": ["usa", "us", "united states", "new york", "california", "texas", "chicago", "los angeles"],
        "currency": "USD",
        "safety_guidelines": (
            "Meet in safe, public places only. Inspect before paying. Never send wire transfers or gift cards."
        ),
        "regulatory_notes": "Mostly private sales — limited consumer protection. Use local police-station meetup spots when available.",
        "sort_order": 2,
    },
    {
        "slug": "amazon_us",
        "name": "Amazon US",
        "region_tags": ["usa", "us", "united states", "new york", "california", "texas", "chicago"],
        "currency": "USD",
        "safety_guidelines": "Prefer Fulfilled by Amazon. Check return policy and seller ratings for 3P listings.",
        "regulatory_notes": "Sales tax often collected at checkout. Cross-border export may trigger destination customs.",
        "sort_order": 3,
    },
    # Global fallbacks
    {
        "slug": "local_retailers",
        "name": "Local Retailers",
        "region_tags": ["*"],
        "currency": "",
        "safety_guidelines": (
            "Prefer verified local shops with receipts and return policies. Inspect in person when possible."
        ),
        "regulatory_notes": "Apply local consumer protection norms for the buyer's city/country.",
        "sort_order": 90,
    },
    {
        "slug": "international_refurbished",
        "name": "International Refurbished",
        "region_tags": ["*"],
        "currency": "",
        "safety_guidelines": (
            "Verify seller authenticity, return windows, and warranty transfer. "
            "Check refurbished grade and battery health for electronics."
        ),
        "regulatory_notes": (
            "Cross-border refurbished goods often face customs, VAT/duties, and weaker warranty enforceability. "
            "Compare intra-region vs international shipping carefully."
        ),
        "sort_order": 91,
    },
]


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_marketplaces_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS marketplace_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                region_tags TEXT NOT NULL,
                currency TEXT DEFAULT '',
                safety_guidelines TEXT NOT NULL,
                regulatory_notes TEXT NOT NULL,
                sort_order INTEGER DEFAULT 100
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) AS c FROM marketplace_profiles").fetchone()["c"]
        if count == 0:
            for p in SEED_PROFILES:
                conn.execute(
                    """
                    INSERT INTO marketplace_profiles
                    (slug, name, region_tags, currency, safety_guidelines, regulatory_notes, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        p["slug"],
                        p["name"],
                        json.dumps(p["region_tags"]),
                        p.get("currency", ""),
                        p["safety_guidelines"],
                        p["regulatory_notes"],
                        p.get("sort_order", 100),
                    ),
                )
        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "slug": row["slug"],
        "name": row["name"],
        "region_tags": json.loads(row["region_tags"]),
        "currency": row["currency"] or None,
        "safety_guidelines": row["safety_guidelines"],
        "regulatory_notes": row["regulatory_notes"],
        "sort_order": row["sort_order"],
        "hint": (row["safety_guidelines"] or "")[:90] + ("…" if len(row["safety_guidelines"] or "") > 90 else ""),
    }


def get_marketplace_by_slug(slug: str) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM marketplace_profiles WHERE slug = ?",
            (slug,),
        ).fetchone()
        return _row_to_dict(row) if row else None


def list_marketplaces_for_location(
    location: str,
    country_code: str | None = None,
) -> list[dict[str, Any]]:
    loc = (location or "").strip().lower()
    cc = (country_code or "").strip().lower()

    # Expand country code into searchable aliases so "GB" matches UK providers
    cc_aliases = {
        "gb": " uk united kingdom england scotland wales london gb ",
        "pk": " pakistan pk lahore karachi islamabad ",
        "us": " usa us united states new york california ",
        "de": " germany berlin eu europe de ",
        "fr": " france paris eu europe fr ",
        "ie": " ireland dublin eu europe ie ",
        "nl": " netherlands amsterdam eu europe nl ",
        "es": " spain madrid eu europe es ",
        "it": " italy rome eu europe it ",
        "ca": " canada ca ",
        "in": " india in ",
        "ae": " uae dubai abu dhabi ae ",
        "sg": " singapore sg ",
    }
    haystack = f" {loc} {cc} {cc_aliases.get(cc, '')} "

    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM marketplace_profiles ORDER BY sort_order ASC, name ASC"
        ).fetchall()

    matched: list[dict[str, Any]] = []
    fallbacks: list[dict[str, Any]] = []

    for row in rows:
        profile = _row_to_dict(row)
        tags = [t.lower() for t in profile["region_tags"]]
        if "*" in tags:
            fallbacks.append(profile)
            continue
        if any(tag in haystack for tag in tags):
            matched.append(profile)

    result = matched if matched else list(fallbacks)

    existing_slugs = {p["slug"] for p in result}
    existing_names = {p["name"].lower() for p in result}
    for fb in fallbacks:
        if fb["slug"] in existing_slugs:
            continue
        if fb["name"].lower() in existing_names:
            continue
        result.append(fb)
    return result


def infer_location_context(location: str) -> dict[str, str]:
    """Currency + regulatory framing from location keywords."""
    loc = (location or "").lower()
    if any(k in loc for k in ["pakistan", "lahore", "karachi", "islamabad", "pk"]):
        return {
            "currency": "PKR",
            "trade_zone": "Pakistan / South Asia",
            "regulatory_focus": (
                "Local PKR pricing; import/customs risk for inbound high-value goods; "
                "weaker private-sale remedies than EU retail."
            ),
        }
    if any(k in loc for k in ["uk", "united kingdom", "london", "manchester", "edinburgh", "england", "scotland", "wales"]):
        return {
            "currency": "GBP",
            "trade_zone": "United Kingdom",
            "regulatory_focus": (
                "Quote GBP. Consumer Rights Act / distance selling returns. GDPR for personal data. "
                "Post-Brexit: non-UK sellers may trigger customs/VAT."
            ),
        }
    if any(
        k in loc
        for k in [
            "germany", "france", "spain", "italy", "netherlands", "belgium", "ireland",
            "berlin", "paris", "madrid", "rome", "amsterdam", "dublin", "eu", "europe",
            "portugal", "austria", "sweden", "vienna", "stockholm", "lisbon",
        ]
    ):
        return {
            "currency": "EUR",
            "trade_zone": "European Union",
            "regulatory_focus": (
                "Quote EUR when possible. Intra-EU shipping usually avoids customs duties but VAT still matters. "
                "GDPR applies. Shipping high-value items OUT of the EU (e.g. to Pakistan) faces customs + duties — "
                "treat that differently from domestic EU delivery."
            ),
        }
    if any(k in loc for k in ["usa", "united states", "new york", "california", "texas", "chicago", "los angeles", "seattle"]):
        return {
            "currency": "USD",
            "trade_zone": "United States",
            "regulatory_focus": (
                "Quote USD. Sales tax may apply. International shipping abroad can incur destination customs."
            ),
        }
    return {
        "currency": "local currency (infer from listings)",
        "trade_zone": "General / international",
        "regulatory_focus": (
            "Identify local currency from listings. Apply relevant consumer protection. "
            "Distinguish domestic vs cross-border shipping, customs, and VAT/duties."
        ),
    }
