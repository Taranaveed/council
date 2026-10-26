"""Extra flags: landed >3x ceiling*qty; nonsense with a winner."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.utils.price_bands import band_for_query  # noqa: E402


def parse_money(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[\d,.]+", str(v).replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


path = Path(sys.argv[1])
d = json.loads(path.read_text(encoding="utf-8"))
print(f"=== EXTRA FLAGS ({path.name}) ===")
print()

over_3x = []
nonsense_winners = []
for r in d.get("results") or []:
    q = r.get("query") or ""
    qty = int(r.get("quantity") or 100)
    cat = (r.get("category") or "").lower()
    band = band_for_query(q, price_type="retail") or {}
    ceiling = band.get("ceiling_gbp")
    try:
        ceiling_f = float(ceiling) if ceiling is not None else None
    except (TypeError, ValueError):
        ceiling_f = None
    hard_line = (ceiling_f * qty * 3.0) if ceiling_f else None

    has_visible_winner = False
    for lr in r.get("landed_rows") or []:
        if lr.get("hide_landed"):
            continue
        mid = parse_money(lr.get("landed_mid") or lr.get("estimated_total"))
        if mid is None:
            continue
        has_visible_winner = True
        if hard_line is not None and mid > hard_line:
            over_3x.append(
                {
                    "query": q,
                    "vendor": lr.get("vendor"),
                    "landed": mid,
                    "ceiling": ceiling_f,
                    "qty": qty,
                    "hard_3x_line": hard_line,
                    "ratio": round(mid / hard_line, 2) if hard_line else None,
                }
            )

    # nonsense: any visible landed / non-NO_MATCH counts as "winner"
    if cat == "nonsense":
        nm = bool(r.get("no_match"))
        priced = int(r.get("kept_priced") or 0)
        if (not nm and priced > 0) or has_visible_winner:
            nonsense_winners.append(
                {
                    "query": q,
                    "no_match": nm,
                    "kept_priced": priced,
                    "landed_visible": has_visible_winner,
                }
            )

print("Landed mid > 3×(retail ceiling × qty) [HARD line]:")
if not over_3x:
    print("  (none)")
else:
    for x in over_3x:
        print(
            f"  [{x['query']}] {x['vendor']}: landed=£{x['landed']:.0f} "
            f"> 3×(£{x['ceiling']}×{x['qty']})=£{x['hard_3x_line']:.0f} "
            f"(×{x['ratio']})"
        )

print()
print("Nonsense queries with a winner (should be empty):")
if not nonsense_winners:
    print("  (none) — OK")
else:
    for x in nonsense_winners:
        print(f"  FLAG {x}")
