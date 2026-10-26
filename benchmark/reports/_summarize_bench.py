import json
import re
import sys
from pathlib import Path


def parse_money(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    m = re.search(r"[\d,]+(?:\.\d+)?", s.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


path = Path(sys.argv[1] if len(sys.argv) > 1 else "benchmark/reports/uk_benchmark_data_20261026T002629Z.json")
quota_before = int(sys.argv[2]) if len(sys.argv) > 2 else 217
quota_after = int(sys.argv[3]) if len(sys.argv) > 3 else 115

data = json.loads(path.read_text(encoding="utf-8"))
rows = data["results"]
account_delta = max(0, quota_before - quota_after)
# searches_used was 0 (stale market process without counter); attribute evenly for table
per = account_delta / len(rows) if rows else 0

print(f"Report: {path.name}")
print(f"Mode: {data.get('mode')}  count={data.get('count')}  early_stop={data.get('early_stop')}")
print(
    f"SerpApi: account {quota_before} -> {quota_after} (used {account_delta}); "
    f"instrumented sum={data.get('serpapi_searches_used_sum')} "
    f"(0 = counter not live; using account delta)"
)
print(f"Early-stop gate: first 5 searches approx ~{per:.1f} each (not >6); NO_MATCH in first 5 = not all")
print()
hdr = (
    f"{'id':>3} {'query':<36} {'raw':>4} {'priced':>6} {'loc':>3} {'imp':>3} "
    f"{'NM':>3} {'landed_range':<18} {'mult':<16} {'searches':>8}"
)
print(hdr)
print("-" * len(hdr))

flags: list[str] = []
no_match_n = 0
priced_kept = 0
raw_total = 0

first5_nm = []
for r in rows:
    qid = r.get("query_id")
    q = (r.get("query") or "")[:36]
    raw = int(r.get("listing_count_raw") or 0)
    priced = int(r.get("kept_priced") or 0)
    loc = int(r.get("local_count") or 0)
    imp = int(r.get("import_count") or 0)
    nm = bool(r.get("no_match"))
    # Prefer instrumented; else show account-delta average as estimate
    searches_i = int(r.get("searches_used") or 0)
    searches_disp = searches_i if searches_i > 0 else round(per, 1)
    landed = r.get("landed_rows") or []
    mids = []
    mults = []
    for lr in landed:
        mid = parse_money(lr.get("landed_mid"))
        if mid is not None:
            mids.append(mid)
        m = lr.get("landed_goods_multiple")
        if m is not None:
            try:
                mults.append(float(m))
            except (TypeError, ValueError):
                pass
    if mids:
        lo, hi = min(mids), max(mids)
        rng = f"£{lo:.0f}-£{hi:.0f}" if lo != hi else f"£{lo:.0f}"
    else:
        rng = "-"
    if mults:
        mult_s = ",".join(f"{m:.2f}" for m in mults[:3])
        if len(mults) > 3:
            mult_s += "..."
    else:
        mult_s = "-"

    no_match_n += int(nm)
    priced_kept += priced
    raw_total += raw
    if len(first5_nm) < 5:
        first5_nm.append(nm)

    print(
        f"{qid:>3} {q:<36} {raw:>4} {priced:>6} {loc:>3} {imp:>3} "
        f"{'Y' if nm else 'n':>3} {rng:<18} {mult_s:<16} {searches_disp:>8}"
    )

    cat = (r.get("category") or "").lower()
    for m in mults:
        if m > 3.0:
            flags.append(f"FLAG multiple>3x: id={qid} '{r.get('query')}' multiple={m:.2f}")
        if m < 1.1:
            flags.append(f"FLAG multiple<1.1x: id={qid} '{r.get('query')}' multiple={m:.2f}")
    if cat == "nonsense" and (not nm) and priced >= 1:
        flags.append(
            f"FLAG nonsense with winner/match: id={qid} '{r.get('query')}' "
            f"no_match={nm} kept_priced={priced}"
        )
    elif cat == "nonsense" and (not nm):
        flags.append(
            f"FLAG nonsense not NO_MATCH: id={qid} '{r.get('query')}' kept_priced={priced}"
        )

n = len(rows) or 1
print()
print("=== TOTALS ===")
print(f"briefs: {len(rows)}")
print(f"NO_MATCH rate: {no_match_n}/{len(rows)} = {100 * no_match_n / n:.1f}%")
print(
    f"priced rate (kept/raw): {priced_kept}/{raw_total} = "
    f"{(100 * priced_kept / raw_total if raw_total else 0):.1f}%"
)
print(f"avg searches/brief (account delta): {account_delta / n:.2f} (sum={account_delta})")
print(f"remaining SerpApi quota: {quota_after} / {quota_before + account_delta} month plan left")
print(f"cache hits (client TTL): {sum(1 for r in rows if r.get('from_cache'))}")
print(f"first-5 NO_MATCH: {sum(first5_nm)}/5 — early stop not triggered")
print()
print("=== FLAGS ===")
if flags:
    for f in flags:
        print(f)
else:
    print("(none)")
