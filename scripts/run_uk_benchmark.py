"""
UK deal-finder benchmark runner (caching ON).

Modes:
  --data-only   No LLM. Market fetch + relevance + landed cost only.
  --full        Full deal-finder (LLM). Records model; FAILS if fallback model used.

Examples:
  python scripts/run_uk_benchmark.py --data-only --limit 3
  python scripts/run_uk_benchmark.py --full --limit 3
  python scripts/run_uk_benchmark.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

_env = BACKEND / ".env"
if _env.is_file():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

DEFAULT_CSV = ROOT / "benchmark" / "uk_queries.csv"
REPORT_DIR = ROOT / "benchmark" / "reports"

# Observed bulk UK path: 1 primary google_shopping + 3 wholesale site searches
SERPAPI_PER_BRIEF_ESTIMATE = 4


class _CaptureStream(io.TextIOBase):
    def __init__(self, underlying: Any):
        self._u = underlying
        self.chunks: list[str] = []

    def write(self, s: str) -> int:  # type: ignore[override]
        self.chunks.append(s)
        return self._u.write(s)

    def flush(self) -> None:
        self._u.flush()

    def text(self) -> str:
        return "".join(self.chunks)


def _auth_headers(client) -> dict[str, str]:
    email = f"bench_{uuid.uuid4().hex[:10]}@example.com"
    password = "BenchPass123!"
    r = client.post("/auth/register", json={"email": email, "password": password})
    if r.status_code >= 400:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _location(row: dict[str, str]) -> str:
    city = row.get("city") or "London"
    return f"{city}, United Kingdom"


async def run_data_only(row: dict[str, str]) -> dict[str, Any]:
    """Market + relevance + landed — no LLM / Groq."""
    from app.core.market_client import fetch_market_prices
    from app.utils.landed_cost import compute_landed_cost
    from app.utils.listing_channel import annotate_listing_channels
    from app.utils.relevance import filter_relevant_priced_listings
    from app.utils.spec_check import annotate_listings_with_spec_check
    from app.utils.supplier_table import attach_limited_data_landed

    qty = int(row.get("quantity") or 100)
    mode = (row.get("buying_mode") or "bulk").strip().lower()
    is_bulk = mode == "bulk" or qty >= 5
    currency = (row.get("currency") or "GBP").upper()
    location = _location(row)

    t0 = time.perf_counter()
    listings, warn = await fetch_market_prices(
        row["query"],
        location,
        country_code="uk",
        preferred_currency=currency,
        bulk_mode=is_bulk,
        quantity=qty,
        use_cache=True,
    )
    listings = annotate_listing_channels(listings, is_bulk=is_bulk)
    listings, _ = annotate_listings_with_spec_check(listings, row["query"])
    kept, dropped, rel_meta = filter_relevant_priced_listings(
        listings, row["query"], is_bulk=is_bulk
    )
    display = kept if kept else []
    if kept and len(kept) < 2:
        display = attach_limited_data_landed(
            kept,
            quantity=qty,
            local_currency=currency,
            location=location,
            country_code="uk",
        )
    else:
        enriched = []
        for item in display:
            landed = compute_landed_cost(
                item,
                quantity=qty,
                local_currency=currency,
                location=location,
                country_code="uk",
            )
            row_out = dict(item)
            row_out["landed_cost"] = landed
            enriched.append(row_out)
        display = enriched

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    local_n = sum(1 for x in display if not x.get("currency_mismatch") and not x.get("is_import"))
    import_n = 0
    landed_rows = []
    for x in display:
        lc = x.get("landed_cost") if isinstance(x.get("landed_cost"), dict) else None
        if lc and lc.get("is_import"):
            import_n += 1
        if lc:
            landed_rows.append(
                {
                    "vendor": x.get("vendor"),
                    "price": x.get("price"),
                    "landed_mid": lc.get("estimated_total"),
                    "landed_goods_multiple": lc.get("landed_goods_multiple"),
                    "limited_data": bool(lc.get("limited_data")),
                    "origin": lc.get("origin_country"),
                }
            )

    no_match = bool(rel_meta.get("no_good_matches"))
    return {
        "mode": "data-only",
        "query_id": row.get("query_id"),
        "category": row.get("category"),
        "query": row.get("query"),
        "quantity": qty,
        "buying_mode": mode,
        "city": row.get("city"),
        "elapsed_ms": elapsed_ms,
        "listing_count_raw": len(listings),
        "kept_priced": len(kept),
        "dropped": len(dropped),
        "priced_rate": (len(kept) / len(listings)) if listings else 0.0,
        "local_count": local_n,
        "import_count": import_n,
        "no_match": no_match,
        "landed_rows": landed_rows,
        "market_warning": (warn or "")[:500],
        "relevance": rel_meta,
        "searches_estimate": SERPAPI_PER_BRIEF_ESTIMATE,
        "llm": False,
    }


def run_full(client, headers: dict[str, str], row: dict[str, str]) -> dict[str, Any]:
    """Full deal-finder; fail if Groq fallback model was used."""
    primary = (os.getenv("GROQ_MODEL") or "").strip()
    fallback = (os.getenv("GROQ_FALLBACK_MODEL") or "").strip()

    body = {
        "item_name": row["query"],
        "location": _location(row),
        "currency": row.get("currency") or "GBP",
        "quantity": int(row.get("quantity") or 100),
        "buying_mode": row.get("buying_mode") or "bulk",
        "marketplace": "local_retailers",
    }

    cap_out = _CaptureStream(sys.stdout)
    cap_err = _CaptureStream(sys.stderr)
    old_out, old_err = sys.stdout, sys.stderr
    t0 = time.perf_counter()
    try:
        sys.stdout, sys.stderr = cap_out, cap_err
        r = client.post("/api/modes/deal-finder", headers=headers, json=body)
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    log_blob = cap_out.text() + "\n" + cap_err.text()

    fallback_used = bool(
        re.search(r"falling back to\s+(\S+)", log_blob, re.I)
        or (fallback and re.search(re.escape(fallback), log_blob) and "falling back" in log_blob.lower())
    )
    model_match = re.findall(r"falling back to\s+(\S+)", log_blob, re.I)
    model_used = model_match[-1].rstrip(":") if model_match else (primary or "unknown")
    if fallback_used:
        raise RuntimeError(
            f"FULL mode refused mixed models for query_id={row.get('query_id')!r}: "
            f"fallback model was used ({model_used}). Primary={primary!r} fallback={fallback!r}. "
            f"Re-run when primary quota recovers, or set GROQ_MODEL to the only model you accept."
        )

    out: dict[str, Any] = {
        "mode": "full",
        "query_id": row.get("query_id"),
        "category": row.get("category"),
        "query": row.get("query"),
        "quantity": body["quantity"],
        "buying_mode": body["buying_mode"],
        "city": row.get("city"),
        "http_status": r.status_code,
        "elapsed_ms": elapsed_ms,
        "model_primary_env": primary,
        "model_used": model_used,
        "fallback_used": False,
        "searches_estimate": SERPAPI_PER_BRIEF_ESTIMATE,
        "llm": True,
    }
    if r.status_code != 200:
        out["error"] = r.text[:800]
        return out
    data = r.json()
    verdict = data.get("verdict") if isinstance(data.get("verdict"), dict) else {}
    listings = data.get("market_listings") or []
    out.update(
        {
            "verdict": verdict.get("verdict"),
            "listing_count": len(listings),
            "landed_rows": sum(
                1 for x in listings if isinstance(x, dict) and isinstance(x.get("landed_cost"), dict)
            ),
            "limited_data_rows": sum(
                1
                for x in listings
                if isinstance(x, dict)
                and isinstance(x.get("landed_cost"), dict)
                and x["landed_cost"].get("limited_data")
            ),
            "market_warning": str(data.get("market_warning") or "")[:500],
            "relevance": (data.get("query_meta") or {}).get("relevance")
            if isinstance(data.get("query_meta"), dict)
            else None,
        }
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UK deal-finder benchmark")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--limit", type=int, default=0, help="Max rows (0 = all)")
    parser.add_argument("--dry-run", action="store_true")
    mode = parser.add_mutually_exclusive_group(required=False)
    mode.add_argument(
        "--data-only",
        action="store_true",
        help="No LLM: market + relevance + landed only",
    )
    mode.add_argument(
        "--full",
        action="store_true",
        help="Full deal-finder; fail if Groq fallback model used",
    )
    args = parser.parse_args(argv)

    if not args.dry_run and not args.data_only and not args.full:
        parser.error("Specify --data-only or --full (or --dry-run)")

    if not args.csv.is_file():
        print(f"Missing CSV: {args.csv}", file=sys.stderr)
        return 1

    rows: list[dict[str, str]] = []
    with args.csv.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("query"):
                rows.append(row)
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    print(f"Loaded {len(rows)} queries from {args.csv}")
    print(f"Per-brief SerpApi estimate (current bulk path): {SERPAPI_PER_BRIEF_ESTIMATE}")
    print(f"Estimated total SerpApi for this run: {SERPAPI_PER_BRIEF_ESTIMATE * len(rows)}")
    if args.dry_run:
        for r in rows:
            print(
                f"  [{r.get('query_id')}] {r.get('category')}: {r.get('query')!r} "
                f"qty={r.get('quantity')} mode={r.get('buying_mode')}"
            )
        print("Dry run only — not calling APIs.")
        return 0

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tag = "data" if args.data_only else "full"
    report_path = REPORT_DIR / f"uk_benchmark_{tag}_{stamp}.json"

    results: list[dict[str, Any]] = []
    if args.data_only:
        import asyncio

        for i, row in enumerate(rows, 1):
            print(f"[data-only {i}/{len(rows)}] {row.get('query')} …")
            results.append(asyncio.run(run_data_only(row)))
    else:
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        headers = _auth_headers(client)
        for i, row in enumerate(rows, 1):
            print(f"[full {i}/{len(rows)}] {row.get('query')} …")
            results.append(run_full(client, headers, row))

    payload = {
        "generated_at": stamp,
        "mode": "data-only" if args.data_only else "full",
        "csv": str(args.csv.as_posix()),
        "count": len(results),
        "serpapi_per_brief_estimate": SERPAPI_PER_BRIEF_ESTIMATE,
        "serpapi_total_estimate": SERPAPI_PER_BRIEF_ESTIMATE * len(results),
        "market_cache_ttl_sec": float(os.getenv("MARKET_CACHE_TTL_SEC", "90")),
        "results": results,
    }
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
