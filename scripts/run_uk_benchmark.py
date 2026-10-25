"""
UK deal-finder benchmark runner (caching ON).

Reads benchmark/uk_queries.csv, calls deal-finder for each row, and writes a
dated JSON report under benchmark/reports/.

Does NOT run automatically — invoke explicitly:

  python scripts/run_uk_benchmark.py
  python scripts/run_uk_benchmark.py --limit 3   # smoke a few rows

Logs SerpApi/search usage proxies when present in market_warning / query_meta,
and records whether the backend market cache was warm (repeat identical keys).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
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


def _auth_headers(client) -> dict[str, str]:
    email = f"bench_{uuid.uuid4().hex[:10]}@example.com"
    password = "BenchPass123!"
    r = client.post("/auth/register", json={"email": email, "password": password})
    if r.status_code >= 400:
        r = client.post("/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _searches_used_estimate(data: dict[str, Any], warning: str | None) -> dict[str, Any]:
    """Best-effort search-call accounting from response text (no live Serp counters)."""
    warn = warning or str(data.get("market_warning") or "")
    meta = data.get("query_meta") if isinstance(data.get("query_meta"), dict) else {}
    # Heuristic tokens that market-service embeds in warnings
    wholesale = "wholesale" in warn.lower() or "alibaba" in warn.lower()
    page_opened = "opened" in warn.lower() and "seller page" in warn.lower()
    return {
        "market_warning": warn[:500],
        "relevance": meta.get("relevance"),
        "heuristic": {
            "mentions_wholesale_compare": wholesale,
            "mentions_page_enrich": page_opened,
            "note": (
                "Exact SerpApi unit counts are logged in market-service stdout; "
                "this report captures warning/relevance signals only."
            ),
        },
    }


def run_one(client, headers: dict[str, str], row: dict[str, str]) -> dict[str, Any]:
    body = {
        "item_name": row["query"],
        "location": f"{row.get('city') or 'London'}, United Kingdom",
        "currency": row.get("currency") or "GBP",
        "quantity": int(row.get("quantity") or 100),
        "buying_mode": row.get("buying_mode") or "bulk",
        "marketplace": "local_retailers",
    }
    t0 = time.perf_counter()
    r = client.post("/api/modes/deal-finder", headers=headers, json=body)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    out: dict[str, Any] = {
        "query_id": row.get("query_id"),
        "category": row.get("category"),
        "query": row.get("query"),
        "quantity": body["quantity"],
        "buying_mode": body["buying_mode"],
        "city": row.get("city"),
        "http_status": r.status_code,
        "elapsed_ms": elapsed_ms,
    }
    if r.status_code != 200:
        out["error"] = r.text[:800]
        return out
    data = r.json()
    verdict = data.get("verdict") if isinstance(data.get("verdict"), dict) else {}
    listings = data.get("market_listings") or []
    table = data.get("supplier_table") or []
    with_landed = sum(
        1
        for x in listings
        if isinstance(x, dict) and isinstance(x.get("landed_cost"), dict)
    )
    out.update(
        {
            "verdict": verdict.get("verdict"),
            "listing_count": len(listings),
            "table_rows": len(table),
            "landed_rows": with_landed,
            "limited_data_rows": sum(
                1
                for x in listings
                if isinstance(x, dict)
                and isinstance(x.get("landed_cost"), dict)
                and x["landed_cost"].get("limited_data")
            ),
            "searches": _searches_used_estimate(data, data.get("market_warning")),
            "cache_note": (
                "Backend MARKET_CACHE_TTL_SEC applies (default 90s); "
                "repeat identical queries within TTL reuse listings."
            ),
        }
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UK deal-finder benchmark (caching on)")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--limit", type=int, default=0, help="Max rows (0 = all)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load CSV and print plan only; do not call the API",
    )
    args = parser.parse_args(argv)

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
    if args.dry_run:
        for r in rows:
            print(f"  [{r.get('query_id')}] {r.get('category')}: {r.get('query')}")
        print("Dry run only — not calling deal-finder.")
        return 0

    from fastapi.testclient import TestClient
    from app.main import app

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = REPORT_DIR / f"uk_benchmark_{stamp}.json"

    client = TestClient(app, raise_server_exceptions=False)
    headers = _auth_headers(client)
    results = []
    for i, row in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {row.get('query')} …")
        results.append(run_one(client, headers, row))

    payload = {
        "generated_at": stamp,
        "csv": str(args.csv.as_posix()),
        "count": len(results),
        "market_cache_ttl_sec": float(os.getenv("MARKET_CACHE_TTL_SEC", "90")),
        "results": results,
    }
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
