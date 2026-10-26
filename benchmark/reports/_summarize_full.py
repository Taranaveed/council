import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
d = json.loads(path.read_text(encoding="utf-8"))
print(f"Report: {path.name}")
print(f"replay={d.get('replay')} count={d.get('count')} early={d.get('early_stop')}")
print()
hdr = (
    f"{'id':>3} {'query':<28} {'model':<22} {'fb':>2} {'verdict':<10} "
    f"{'landed':<12} {'winner/vendor':<28} flags"
)
print(hdr)
print("-" * 140)
for r in d.get("results") or []:
    mid_min = r.get("landed_mid_min")
    mid_max = r.get("landed_mid_max")
    if mid_min is not None and mid_max is not None and mid_min != mid_max:
        landed = f"£{mid_min:.0f}-£{mid_max:.0f}"
    elif mid_min is not None:
        landed = f"£{mid_min:.0f}"
    elif r.get("winner_landed") is not None:
        landed = str(r.get("winner_landed"))
    else:
        landed = "—"
    w = (r.get("winner_vendor") or r.get("winner_title") or "—")[:28]
    reason = (r.get("winner_reason") or "")[:40]
    flags = ",".join(r.get("flags") or [])
    if r.get("error"):
        flags = (flags + ",ERROR").strip(",")
    print(
        f"{str(r.get('query_id')):>3} {str(r.get('query') or '')[:28]:<28} "
        f"{str(r.get('model_used') or '')[:22]:<22} "
        f"{'Y' if r.get('fallback_used') else 'n':>2} "
        f"{str(r.get('verdict') or r.get('http_status') or '')[:10]:<10} "
        f"{landed:<12} {w:<28} {flags}"
    )
    if reason:
        print(f"     reason: {reason}")
    if r.get("error"):
        print(f"     error: {str(r.get('error'))[:160]}")

print()
print("Manual-review columns per row: verdict, winner_title, winner_vendor,")
print("winner_reason, winner_landed, landed_mid_min/max, flags, model_used, fallback_used")
