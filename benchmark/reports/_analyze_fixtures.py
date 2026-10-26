import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

report = Path("benchmark/reports/uk_benchmark_data_record_20261026T005626Z.json")
d = json.loads(report.read_text(encoding="utf-8"))
print("searches sum", d.get("serpapi_searches_used_sum"), "early", d.get("early_stop"))
for r in d["results"]:
    print(
        f"  {r['query']}: searches={r.get('searches_used')} raw={r.get('listings_raw_count')} "
        f"kept_fetch={r.get('listing_count_kept_fetch')} priced={r.get('kept_priced')} "
        f"local={r.get('local_count')} imp={r.get('import_count')} NM={r.get('no_match')}"
    )

print("\n=== HOST RAW vs KEPT + UK DROP REASONS ===")
fixdir = Path("benchmark/fixtures/market")


def host_of(row: dict) -> str:
    h = row.get("host")
    if h:
        return str(h).replace("www.", "")
    try:
        return (urlparse(row.get("link") or "").hostname or "?").replace("www.", "")
    except Exception:
        return "?"


def is_uk(row: dict) -> bool:
    blob = f"{row.get('host') or ''} {row.get('link') or ''}".lower()
    return ".co.uk" in blob


for p in sorted(fixdir.glob("*__uk__bulk__GBP.json")):
    fix = json.loads(p.read_text(encoding="utf-8"))
    raw = fix.get("listings_raw") or []
    kept = fix.get("listings") or []
    kept_links = {str(x.get("link") or "") for x in kept}
    raw_hosts = Counter(host_of(x) for x in raw)
    kept_hosts = Counter(host_of(x) for x in kept)
    uk_raw = [x for x in raw if is_uk(x)]
    print(f"\n{fix.get('query')}: raw={len(raw)} kept={len(kept)}")
    print("  raw hosts:", dict(raw_hosts.most_common(10)))
    print("  kept hosts:", dict(kept_hosts.most_common(10)))
    print(f"  UK(.co.uk) raw={len(uk_raw)}")
    for x in uk_raw:
        link = str(x.get("link") or "")
        survived = link in kept_links
        reasons = []
        if not survived:
            price = str(x.get("price") or "")
            if not price or price.lower().startswith("see"):
                reasons.append("no_usable_price")
            if x.get("price_source") in (None, "pending", "serp", "snippet"):
                reasons.append(f"price_source={x.get('price_source')}")
            # Heuristic: filter drops weak/mismatch/non-product — note fields present
            if x.get("unit_price_rejected"):
                reasons.append(f"rejected={x.get('unit_price_rejected')}")
            if not reasons:
                reasons.append("dropped_by_quality_or_rank_filter")
        status = "KEPT" if survived else "DROPPED"
        title = (x.get("title") or "")[:55]
        print(
            f"    [{status}] host={host_of(x)} price={x.get('price')!r} "
            f"src={x.get('price_source')} :: {title!r}"
            + (f" | why={reasons}" if reasons else "")
        )
