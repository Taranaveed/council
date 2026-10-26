import json

import re

import sys

from pathlib import Path





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

rows = d["results"]

print(f"Report: {path.name}  replay={d.get('replay')} count={d.get('count')}")

print(f"searches sum={d.get('serpapi_searches_used_sum')} early={d.get('early_stop')}")

stats_sum = {

    "attempts": 0,

    "retries": 0,

    "successes": 0,

    "failures": 0,

    "cache_hits": 0,

    "cache_misses": 0,

    "cache_unknown": 0,

}

for r in rows:

    st = r.get("serpapi_stats") or {}

    for k in stats_sum:

        stats_sum[k] += int(st.get(k) or 0)

print(f"serpapi_stats totals: {stats_sum}")

print()

hdr = (

    f"{'id':>3} {'query':<26} {'raw':>4} {'prc':>4} {'NM':>3} {'UK':>3} "

    f"{'loc':>3} {'imp':>3} {'landed':<14} {'flags/guards'}"

)

print(hdr)

print("-" * 130)



borderline: list[dict] = []

hidden_detail: list[dict] = []

soft_shown: list[dict] = []

unrecognized: list[dict] = []



nm = 0

for r in rows:

    qid = r.get("query_id")

    q = (r.get("query") or "")[:26]

    raw = int(r.get("listings_raw_count") or 0)

    pr = int(r.get("kept_priced") or 0)

    ukn = int(r.get("uk_seller_review_count") or 0)

    loc = int(r.get("local_count") or 0)

    imp = int(r.get("import_count") or 0)

    is_nm = bool(r.get("no_match"))

    nm += int(is_nm)

    for u in r.get("uk_unrecognized_merchants") or []:

        unrecognized.append({"query": r.get("query"), **u})

    mids = []

    flag_bits = []

    for lr in r.get("landed_rows") or []:

        mid = parse_money(lr.get("landed_mid"))

        if mid is not None and not lr.get("hide_landed"):

            mids.append(mid)

        pt = lr.get("price_type")

        if pt:

            flag_bits.append(f"pt={pt}")

        vb = lr.get("vat_basis")

        if vb:

            flag_bits.append(f"vat={vb}")

        if lr.get("needs_quote"):

            flag_bits.append("needs_quote")

        if lr.get("branded_goods"):

            flag_bits.append("branded")

        if lr.get("if_seller_uk_based"):

            flag_bits.append(f"if_UK={lr.get('if_seller_uk_based')}")

        if lr.get("price_soft_flagged"):

            flag_bits.append("soft_3x")

            soft_shown.append(

                {

                    "query": r.get("query"),

                    "vendor": lr.get("vendor"),

                    "price": lr.get("price"),

                    "guards": lr.get("guards") or [],

                }

            )

        for g in lr.get("guards") or []:

            rule = g.get("rule")

            bound = g.get("bound")

            note = (g.get("source_note") or "")[:70]

            trig = g.get("trigger_price_gbp")

            if trig is None:

                trig = g.get("trigger_price")

            bit = f"{rule}@{bound} trig={trig}"

            flag_bits.append(bit)

            row_hide = {

                "query_id": qid,

                "query": r.get("query"),

                "vendor": lr.get("vendor"),

                "price": lr.get("price") or lr.get("extracted_price") or lr.get("unit_price_local"),

                "rule": rule,

                "bound": bound,

                "bound_kind": g.get("bound_kind"),

                "source_note": note,

                "trigger": trig,

                "trigger_kind": g.get("trigger_kind"),

                "borderline": bool(g.get("borderline")),

                "hidden": bool(lr.get("hide_landed")),

                "soft": bool(lr.get("price_soft_flagged")),

                "price_type": lr.get("price_type"),

                "origin_class": lr.get("uk_origin_class"),

            }

            if lr.get("hide_landed"):

                hidden_detail.append(row_hide)

            if g.get("borderline"):

                borderline.append(row_hide)

        if lr.get("hide_landed") and not (lr.get("guards") or []):

            flag_bits.append("hide_landed")

        if lr.get("needs_quote"):

            flag_bits.append("needs_quote")

        if lr.get("verify_seller_origin"):

            flag_bits.append("verify_origin")

        if lr.get("uk_retail_priced"):

            flag_bits.append("uk_retail")

        for reason in lr.get("price_flag_reasons") or []:

            if reason not in " ".join(flag_bits):

                flag_bits.append(str(reason))

    if ukn:

        flag_bits.append(f"uk_review={ukn}")

    ukp = int(r.get("uk_retail_priced_count") or 0)

    if ukp:

        flag_bits.append(f"uk_priced={ukp}")

    rng = (

        f"£{min(mids):.0f}-£{max(mids):.0f}"

        if mids and min(mids) != max(mids)

        else (f"£{mids[0]:.0f}" if mids else "—")

    )

    print(

        f"{qid:>3} {q:<26} {raw:>4} {pr:>4} {'Y' if is_nm else 'n':>3} {ukn:>3} "

        f"{loc:>3} {imp:>3} {rng:<14} {','.join(dict.fromkeys(flag_bits))}"

    )



n = len(rows) or 1

print()

print(f"NO_MATCH {nm}/{n} ({100 * nm / n:.1f}%)")

print()

print("=== HIDDEN BY CEILING/FLOOR/CAP (price | bound | source note | within 3×?) ===")

print(

    f"{'qid':>3} {'query':<22} {'vendor':<28} {'price':<10} {'rule':<16} "

    f"{'bound':>8} {'trig':>10} {'3x?':>4}  note"

)

print("-" * 140)

if hidden_detail:

    for h in hidden_detail:

        bl = "Y" if h.get("borderline") else "n"

        print(

            f"{str(h.get('query_id') or ''):>3} {(h.get('query') or '')[:22]:<22} "

            f"{(h.get('vendor') or '')[:28]:<28} {str(h.get('price') or '')[:10]:<10} "

            f"{(h.get('rule') or '')[:16]:<16} {str(h.get('bound') if h.get('bound') is not None else ''):>8} "

            f"{str(h.get('trigger') if h.get('trigger') is not None else ''):>10} {bl:>4}  "

            f"{(h.get('source_note') or '')[:60]}"

        )

else:

    print("  (none)")

print()

print("=== SOFT FLAG SHOWN (within 3× — not hidden) ===")

if soft_shown:

    for s in soft_shown:

        g0 = (s.get("guards") or [{}])[0]

        print(

            f"  [{s.get('query')}] {s.get('vendor')} price={s.get('price')} "

            f"rule={g0.get('rule')} bound={g0.get('bound')} trig={g0.get('trigger_price_gbp')}"

        )

else:

    print("  (none)")

print()

print("=== BORDERLINE (within 3× of bound) ===")

if borderline:

    for h in borderline:

        status = "HIDDEN" if h.get("hidden") else ("SOFT" if h.get("soft") else "flag")

        print(

            f"  [{h.get('query_id')} {h.get('query')}] {h.get('vendor')} "

            f"price={h.get('price')} rule={h.get('rule')} bound={h.get('bound')} "

            f"trig={h.get('trigger')} status={status} | {h.get('source_note')}"

        )

else:

    print("  (none)")

print()

print("=== SEARCH CACHE HITS (per brief) ===")

for r in rows:

    st = r.get("serpapi_stats") or {}

    log = r.get("serpapi_search_log") or []

    print(

        f"  [{r.get('query')}] client_from_cache={st.get('client_from_cache')} "

        f"replay={r.get('replay')} "

        f"cache_hits={st.get('cache_hits')} misses={st.get('cache_misses')} "

        f"unknown={st.get('cache_unknown')} log_n={len(log)}"

    )


