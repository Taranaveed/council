"""Offline audit: why huge landed totals still displayed."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.utils.landed_cost import compute_landed_cost
from app.utils.listing_channel import annotate_listing_channels
from app.utils.listing_locality import annotate_listing_locality
from app.utils.pack_price import detect_pack_pricing, normalize_pack_unit_price
from app.utils.price_plausibility import annotate_price_outliers
from app.utils.relevance import filter_relevant_priced_listings
from app.utils.spec_check import annotate_listings_with_spec_check

FIX = ROOT / "benchmark" / "fixtures" / "market"
REPLAY = ROOT / "benchmark" / "reports" / "uk_benchmark_data_replay_20261026T010617Z.json"

# qty from uk_queries.csv for these queries
QTY = {
    "uk plug extension lead": 80,
    "tote bag": 80,
    "ballpoint pens": 1000,
    "lip gloss bulk": 100,
}


def main() -> None:
    report = json.loads(REPLAY.read_text(encoding="utf-8"))
    by_q = {r["query"]: r for r in report["results"]}

    for query, qty in QTY.items():
        slug = query.replace(" ", "_")
        path = FIX / f"{slug}__uk__bulk__GBP.json"
        fix = json.loads(path.read_text(encoding="utf-8"))
        print("=" * 80)
        print(f"QUERY: {query!r} qty={qty}")
        print(f"fixture raw={len(fix.get('listings_raw') or [])} kept_fetch={len(fix.get('listings') or [])}")
        rr = by_q.get(query) or {}
        print(
            f"replay: priced={rr.get('kept_priced')} NM={rr.get('no_match')} "
            f"local/imp={rr.get('local_count')}/{rr.get('import_count')}"
        )
        print("--- replay landed_rows ---")
        for lr in rr.get("landed_rows") or []:
            print(
                f"  vendor={lr.get('vendor')} price={lr.get('price')!r} "
                f"unit={lr.get('unit_price')!r} unit_local={lr.get('unit_price_local')!r} "
                f"goods={lr.get('goods_amount')} landed={lr.get('landed_mid')!r} "
                f"mult={lr.get('landed_goods_multiple')} hide={lr.get('hide_landed')} "
                f"pack={lr.get('pack_text')!r} flags_freight={bool(lr.get('warning_freight_minimum'))} "
                f"flags_impl={lr.get('warning_implausible_price')!r} "
                f"goods_ok={lr.get('goods_matches_unit_x_qty')}"
            )

        listings = list(fix.get("listings") or [])
        listings = annotate_listing_channels(listings, is_bulk=True)
        listings = annotate_listing_locality(
            listings, country_code="uk", local_currency="GBP", location="London, United Kingdom"
        )
        listings, _ = annotate_listings_with_spec_check(listings, query)
        kept, dropped, meta = filter_relevant_priced_listings(listings, query, is_bulk=True)
        print(f"--- pipeline kept={len(kept)} dropped={len(dropped)} meta={meta} ---")
        for item in kept:
            pack = detect_pack_pricing(item)
            unit_raw = item.get("price")
            # What guards see
            peers = annotate_price_outliers([dict(x) for x in kept], query=query)
            peer = next((p for p in peers if p.get("link") == item.get("link")), item)
            print()
            print(f"  KEPT vendor={item.get('vendor')} link={(item.get('link') or '')[:70]}")
            print(f"    price_text={unit_raw!r} currency={item.get('currency')}")
            print(f"    title={(item.get('title') or '')[:80]!r}")
            print(
                f"    pack_detect={pack} "
                f"outlier={peer.get('price_outlier')} reason={peer.get('price_outlier_reason')!r}"
            )
            u_amt = None
            try:
                from app.utils.money import parse_money

                u_amt = parse_money(str(unit_raw or ""))
            except Exception:
                pass
            if u_amt is not None:
                norm, nmeta = normalize_pack_unit_price(float(u_amt), item)
                print(f"    parsed_unit={u_amt} after_pack_norm={norm} norm_meta={nmeta}")
            lc = compute_landed_cost(
                peer,
                quantity=qty,
                local_currency="GBP",
                location="London, United Kingdom",
                country_code="uk",
            )
            if not lc:
                print("    landed=None (guard returned None)")
                continue
            print(
                f"    landed.hide={lc.get('hide_landed')} estimated={lc.get('estimated_total')!r} "
                f"unit={lc.get('unit_price')!r} unit_local={lc.get('unit_price_local')!r} "
                f"goods={lc.get('goods_amount')} qty={lc.get('quantity')} "
                f"mult={lc.get('landed_goods_multiple')} "
                f"warn_impl={lc.get('warning_implausible_price')!r} "
                f"warn_freight={lc.get('warning_freight_minimum')!r} "
                f"pack_text={lc.get('pack_text')!r}"
            )
            goods = lc.get("goods_amount")
            if goods and qty:
                print(f"    implied_unit_gbp={float(goods)/qty:.4f}  goods/qty check")

        # Sample google.com UK-looking raw rows for Serp field inventory
        print("--- sample UK-looking RAW google shopping fields ---")
        raw = fix.get("listings_raw") or []
        ukish = [
            x
            for x in raw
            if any(
                k in str(x.get("vendor") or "").lower()
                for k in ("amazon.co.uk", "ebay", "argos", "frasers", "currys", ".co.uk")
            )
            or "co.uk" in str(x.get("vendor") or "").lower()
        ][:3]
        if not ukish:
            ukish = [x for x in raw if (x.get("host") or "") == "google.com"][:2]
        for x in ukish:
            print("  raw keys:", sorted(x.keys()))
            for k in sorted(x.keys()):
                v = x.get(k)
                if v is None or v == "" or v == []:
                    continue
                s = repr(v)
                if len(s) > 120:
                    s = s[:117] + "..."
                print(f"    {k}: {s}")


if __name__ == "__main__":
    main()
