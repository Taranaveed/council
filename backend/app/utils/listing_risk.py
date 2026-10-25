"""Risk flags grounded in listing facts (not debate keyword echo)."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.utils.money import parse_money


def _url(value: Any) -> str:
    text = str(value or "").strip()
    try:
        p = urlparse(text)
    except Exception:
        return ""
    if p.scheme not in ("http", "https") or not p.netloc:
        return ""
    return text


def _blob(listing: dict[str, Any]) -> str:
    parts = [
        str(listing.get("title") or ""),
        str(listing.get("snippet") or ""),
        str(listing.get("pick_reason") or ""),
        str(listing.get("note") or ""),
        str(listing.get("warranty") or ""),
    ]
    for v in listing.get("variants") or []:
        if isinstance(v, dict):
            parts.append(str(v.get("label") or ""))
        else:
            parts.append(str(v))
    for p in listing.get("policy_links") or []:
        if isinstance(p, dict):
            parts.append(str(p.get("label") or ""))
            parts.append(str(p.get("url") or ""))
    return " ".join(parts).lower()


def _is_product_url(link: str) -> bool:
    u = (link or "").lower()
    if not u:
        return False
    if re.search(r"/product-detail/|/products?/|/proddetail|/item/|/itm/|/dp/", u):
        return True
    return False


def build_listing_risk_flags(
    listings: list[dict[str, Any]],
    *,
    winner: dict[str, Any] | None = None,
    query: str | None = None,
    max_flags: int = 48,
) -> list[dict[str, str]]:
    """
    Flag every listing. Prefer page-fetched facts over snippet-only cites.
    """
    flags: list[dict[str, str]] = []
    focus = list(listings or [])
    q = (query or "").lower()

    seen: set[str] = set()

    def add(
        code: str,
        message: str,
        cite: str,
        *,
        link: str,
        title: str,
        severity: str = "medium",
    ) -> None:
        key = f"{code}:{link or title}"
        if key in seen:
            return
        seen.add(key)
        flags.append(
            {
                "code": code,
                "message": message,
                "cite": cite,
                "link": link,
                "listing_title": title,
                "severity": severity,
            }
        )

    for row in focus:
        title = str(row.get("title") or "Listing")[:80]
        link = _url(row.get("link"))
        blob = _blob(row)
        status = str(row.get("vendor_status") or "").strip()
        moq = row.get("moq")
        price = str(row.get("price") or "")
        amount = parse_money(price)
        source = str(row.get("price_source") or "serp")
        page_fetched = bool(row.get("page_facts_fetched"))
        warranty_src = str(row.get("warranty_source") or "")
        policy_links = row.get("policy_links") if isinstance(row.get("policy_links"), list) else []
        variants = row.get("variants") if isinstance(row.get("variants"), list) else []

        if not _is_product_url(link):
            add(
                "not_product_page",
                "Not a product-detail page",
                f"“{title}” URL is a storefront/homepage/collection — not a single SKU page.",
                link=link,
                title=title,
                severity="high",
            )

        if not status or status.lower() in ("unknown", "unverified", ""):
            add(
                "unverified_supplier",
                "Unverified supplier",
                f"“{title}” has vendor_status={status or 'Unknown'} — not a known marketplace badge.",
                link=link,
                title=title,
                severity="medium",
            )

        if moq is None or moq == "" or moq == 0:
            add(
                "moq_not_verified",
                "MOQ not verified",
                (
                    f"“{title}” — MOQ not found on product page."
                    if page_fetched
                    else f"“{title}” — no MOQ in title/snippet (source={source})."
                ),
                link=link,
                title=title,
                severity="medium",
            )
        else:
            moq_src = str(row.get("moq_source") or "").lower()
            if moq_src in ("not_on_snippet", "not_verified", "assumed_1_from_page_price", "missing", "") or moq_src.startswith("not_"):
                # Never leave a specific MOQ number when the source is missing/assumed
                row["moq"] = None
                row["has_moq"] = False
                row["moq_display"] = "MOQ not confirmed — verify on seller page"
                add(
                    "moq_not_verified",
                    "MOQ not confirmed",
                    f"“{title}” — MOQ not confirmed — verify on seller page (source={moq_src or 'missing'}).",
                    link=link,
                    title=title,
                    severity="medium",
                )

        if amount is None:
            add(
                "price_not_verified",
                "Unit price not verified",
                f"“{title}” — no parseable unit price on the listing row.",
                link=link,
                title=title,
                severity="high",
            )
        elif row.get("price_outlier") or row.get("unit_price_unreliable"):
            add(
                "price_outlier",
                "Price could not be reliably parsed",
                str(row.get("price_outlier_reason") or f"“{title}” unit price is an outlier vs peers — check listing directly."),
                link=link,
                title=title,
                severity="high",
            )
        elif page_fetched and source == "page":
            # Positive page fact — no flag
            pass
        elif source in ("serp", "snippet") or row.get("unit_price_verified") is False:
            add(
                "price_not_verified",
                "Unverified SERP/snippet price",
                f"“{title}” quotes {price} from search snippet only — not confirmed on the product page. "
                "Do not treat tier discounts from SERP as confirmed unit cost.",
                link=link,
                title=title,
                severity="high",
            )

        # Warranty / returns — page facts replace snippet guessing
        has_warranty_text = bool(row.get("warranty")) or bool(
            re.search(r"warrant|guarantee|return policy|refund", blob)
        )
        has_policy_link = any(
            isinstance(p, dict) and re.search(r"refund|return|warranty", str(p.get("label") or ""), re.I)
            for p in policy_links
        )
        if page_fetched:
            if has_warranty_text or has_policy_link:
                cite_bits = []
                if row.get("warranty"):
                    cite_bits.append(f"page: “{str(row.get('warranty'))[:120]}”")
                if has_policy_link:
                    urls = [
                        str(p.get("url"))
                        for p in policy_links
                        if isinstance(p, dict) and re.search(r"refund|return|warranty", str(p.get("label") or ""), re.I)
                    ]
                    if urls:
                        cite_bits.append(f"policy link: {urls[0]}")
                # Informational — do not flag as risk when page confirms policy
            elif warranty_src == "page_checked_absent":
                add(
                    "warranty_not_verified",
                    "Warranty/returns not verified on page",
                    f"“{title}” — product page checked; no warranty/return text or policy link found.",
                    link=link,
                    title=title,
                    severity="medium",
                )
        elif not has_warranty_text:
            add(
                "warranty_not_verified",
                "Warranty/returns not verified",
                f"“{title}” — not checked on product page yet (snippet only).",
                link=link,
                title=title,
                severity="info",
            )

        if row.get("page_fetch_failed") or row.get("fetch_error"):
            add(
                "could_not_fetch",
                "Could not fetch page",
                f"“{title}” — page fetch failed; facts are incomplete (not the same as confirmed missing).",
                link=link,
                title=title,
                severity="info",
            )

        if row.get("moq_not_met"):
            add(
                "moq_not_met",
                "MOQ not met",
                f"“{title}” — order qty is below the lowest price tier MOQ; tier price not applied.",
                link=link,
                title=title,
                severity="high",
            )

        if row.get("tiers_reliable") is False or (
            str(row.get("tiers_source") or "").lower() in ("snippet", "serp")
            and row.get("price_tiers")
        ):
            add(
                "unreliable_price_tier",
                "Unverified / unreliable price tier",
                f"“{title}” has tier pricing from {row.get('tiers_source') or 'snippet'} that is not page-confirmed — "
                "do not use those tiers as the landed-cost unit basis.",
                link=link,
                title=title,
                severity="high",
            )

        if row.get("facts_disputed"):
            add(
                "disputed_fact",
                "Disputed seller fact",
                f"“{title}” — agents asserted contradictory facts; treat as disputed, not verified.",
                link=link,
                title=title,
                severity="high",
            )

        if page_fetched and variants:
            pass  # variants are fact-sheet data, not risk flags

        if row.get("sourcing_action") == "ask_bulk_quote":
            add(
                "retail_ask_bulk_quote",
                "Retail listing — ask for a bulk quote",
                f"“{title}” looks retail; shelf price is not a wholesale unit cost. Ask for MOQ / case pricing.",
                link=link,
                title=title,
                severity="medium",
            )

        for miss in row.get("spec_misses") or []:
            if not isinstance(miss, dict):
                continue
            label = str(miss.get("label") or miss.get("id") or "spec")
            add(
                "spec_missing",
                f"Missing must-have: {label}",
                f"“{title}” — query implies “{label}” but it was not found in title/snippet/page variants.",
                link=link,
                title=title,
                severity="high",
            )

        # Plausibility: precious metal vs quoted unit
        if amount is not None:
            if re.search(r"\b18\s*k|\b22\s*k|\b24\s*k|\bgold\b", blob) and not re.search(
                r"\b(plated|filled|vermeil|colour|color|tone)\b", blob
            ):
                usdish = amount if re.search(r"\$|usd", price, re.I) else amount / 278
                if usdish < 80:
                    add(
                        "implausible_gold_price",
                        "Implausible gold price",
                        f"“{title}” quotes {price} for apparent solid gold — far below typical solid-gold piece cost. "
                        "Likely plated, per-lot, or a bad scrape.",
                        link=link,
                        title=title,
                        severity="high",
                    )
            if re.search(r"\b925\b|\bsterling\b|\bsilver\b", blob) and re.search(
                r"\$|usd", price, re.I
            ):
                if amount is not None and amount < 1.5:
                    add(
                        "implausible_silver_price",
                        "Implausible silver price",
                        f"“{title}” at {price} is unusually low for sterling silver — verify unit vs lot.",
                        link=link,
                        title=title,
                        severity="high",
                    )

        if q and re.search(r"\b(jewel|ring|pendant|earring|necklace|silver|gold)\b", q):
            if re.search(r"\b(handbag|tote|bag|purse|wallet)\b", blob) and not re.search(
                r"\b(jewel|ring|pendant|earring|necklace)\b", blob
            ):
                add(
                    "wrong_category",
                    "Category mismatch",
                    f"“{title}” looks like a bag/accessories SKU while the query looks like jewelry.",
                    link=link,
                    title=title,
                    severity="high",
                )

    if winner and isinstance(winner, dict):
        w_link = _url(winner.get("link"))
    else:
        w_link = ""

    # Dedupe to one line per seller+code; prefer higher severity
    sev_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    by_key: dict[str, dict[str, str]] = {}
    for f in flags:
        host = ""
        try:
            host = urlparse(str(f.get("link") or "")).netloc.lower()
        except Exception:
            host = ""
        key = f"{host}|{f.get('code')}"
        prev = by_key.get(key)
        if not prev or sev_rank.get(str(f.get("severity")), 9) < sev_rank.get(
            str(prev.get("severity")), 9
        ):
            by_key[key] = f
    flags = list(by_key.values())

    # Severity first, then Best-pick / winner link, then title
    def _flag_sort(f: dict[str, str]) -> tuple:
        sev = sev_rank.get(str(f.get("severity")), 9)
        fl = _url(f.get("link"))
        on_pick = 0 if (w_link and fl and fl == w_link) else 1
        # Prefer flags on the winner even within same severity
        return (sev, on_pick, str(f.get("listing_title") or ""))

    flags.sort(key=_flag_sort)
    return flags[:max_flags]


def pick_has_blocking_flags(flags: list[dict[str, str]], winner_link: str | None) -> list[dict[str, str]]:
    """High-severity flags on the chosen winner that should block Buy."""
    w = (winner_link or "").strip()
    blocking_codes = {
        "not_product_page",
        "implausible_gold_price",
        "wrong_category",
        "price_not_verified",
        "unreliable_price_tier",
        "unverified_supplier",
        "warranty_not_verified",
        "moq_not_verified",
        "moq_not_met",
        "spec_missing",
        "retail_ask_bulk_quote",
        "disputed_fact",
        "implausible_silver_price",
    }
    out = []
    for f in flags or []:
        if f.get("code") not in blocking_codes:
            continue
        if w and f.get("link") and f.get("link") != w:
            continue
        # Snippet-only warranty (info/low) should not block alone
        if f.get("code") == "warranty_not_verified" and f.get("severity") in ("low", "info"):
            continue
        if f.get("code") == "could_not_fetch":
            continue
        if f.get("severity") == "high" or f.get("code") in (
            "unverified_supplier",
            "not_product_page",
            "implausible_gold_price",
            "implausible_silver_price",
            "wrong_category",
            "spec_missing",
            "disputed_fact",
            "moq_not_met",
            "unreliable_price_tier",
            "price_not_verified",
        ):
            out.append(f)
        elif f.get("code") == "warranty_not_verified" and f.get("severity") == "medium":
            out.append(f)
        elif f.get("code") == "retail_ask_bulk_quote":
            out.append(f)
    return out


def risk_score_from_flags(flags: list[dict[str, str]]) -> dict[str, Any]:
    high = sum(1 for f in flags if f.get("severity") == "high")
    medium = sum(1 for f in flags if f.get("severity") == "medium")
    info = sum(1 for f in flags if f.get("severity") in ("info", "low"))
    if high:
        level = "high"
        score = 3 if high >= 2 else 2
    elif medium:
        level = "medium"
        score = 2 if medium >= 3 else 1
    elif info or flags:
        level = "info"
        score = 1
    else:
        level = "low"
        score = 0
    triggers: list[str] = []
    codes = {str(f.get("code") or "") for f in flags}
    if "warranty_not_verified" in codes:
        triggers.append("warranty")
    if any(
        c in codes
        for c in (
            "moq_not_verified",
            "moq_not_met",
            "unverified_supplier",
            "not_product_page",
            "retail_ask_bulk_quote",
        )
    ):
        triggers.append("shipping")
    if any(
        c in codes
        for c in ("implausible_gold_price", "wrong_category", "spec_missing", "disputed_fact")
    ):
        triggers.append("customs")
    header = (
        "High risk flags"
        if level == "high"
        else "Mixed risk flags"
        if level == "medium"
        else "Info flags"
        if level == "info"
        else "No listing risk flags"
    )
    return {
        "score": score,
        "max_score": 3,
        "level": level,
        "triggers": triggers,
        "echoed_by_others": [],
        "source_agent": "listing_facts",
        "flags": flags,
        "header": header,
    }

