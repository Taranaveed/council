"""Dump 10 priced Nisbets replay rows + explain cheapest landed (~£9)."""
from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_uk_benchmark import run_data_only  # noqa: E402


def main() -> None:
    row = None
    with (ROOT / "benchmark" / "uk_queries.csv").open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("query") == "nisbets catering foil rolls":
                row = r
                break
    if not row:
        raise SystemExit("nisbets row missing from CSV")
    result = asyncio.run(run_data_only(row, replay=True))
    print(f"query={result.get('query')} qty={result.get('quantity')}")
    print(f"warning={(result.get('market_warning') or '')[:160]}")
    print(f"kept_priced={result.get('kept_priced')} uk_review={result.get('uk_seller_review_count')}")
    print()
    hdr = (
        f"{'#':>2} {'merchant':<28} {'price':>8} {'unit':>8} {'pack':>6} "
        f"{'qty':>5} {'goods':>8} {'landed':>8} {'ptype':<8}"
    )
    print(hdr)
    print("-" * len(hdr))
    def _mid_f(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).replace(",", "").replace("£", "").replace("$", "").strip()
        try:
            return float(s)
        except ValueError:
            return None

    rows = []
    for lr in result.get("landed_rows") or []:
        if lr.get("hide_landed"):
            continue
        mid_f = _mid_f(lr.get("landed_mid"))
        rows.append((mid_f if mid_f is not None else 1e18, lr))
    rows.sort(key=lambda t: t[0])
    for i, (_, lr) in enumerate(rows[:10], 1):
        goods = lr.get("goods_amount")
        print(
            f"{i:>2} {str(lr.get('vendor') or lr.get('merchant') or '')[:28]:<28} "
            f"{str(lr.get('price') or '')[:8]:>8} "
            f"{str(lr.get('unit_price_local') or lr.get('unit_price') or '')[:8]:>8} "
            f"{str(lr.get('pack_size') or lr.get('tier_label') or '')[:6]:>6} "
            f"{str(lr.get('quantity') or result.get('quantity') or '')[:5]:>5} "
            f"{str(goods if goods is not None else '')[:8]:>8} "
            f"{str(lr.get('landed_mid') if lr.get('landed_mid') is not None else '')[:8]:>8} "
            f"{str(lr.get('price_type') or '')[:8]:<8}"
        )
    print()
    if rows:
        cheapest = rows[0][1]
        print("=== Why ~£9 landed (cheapest visible) ===")
        for k in (
            "vendor",
            "price",
            "extracted_price",
            "unit_price",
            "unit_price_local",
            "goods_amount",
            "quantity",
            "tier_label",
            "landed_mid",
            "price_type",
            "uk_origin_class",
            "landed_assumption",
            "if_seller_uk_based",
            "local_or_import",
            "guards",
            "price_flag_reasons",
            "hide_landed",
            "price_soft_flagged",
            "link",
        ):
            if cheapest.get(k) is not None:
                print(f"  {k}: {cheapest.get(k)}")


if __name__ == "__main__":
    main()
