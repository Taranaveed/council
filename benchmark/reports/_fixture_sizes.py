import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from run_uk_benchmark import fixture_path  # noqa: E402

qs = [
    "scented candles wholesale",
    "ceramic mug blank sublimation",
    "earphones",
    "notebooks",
    "uk plug extension lead",
    "lip gloss bulk",
    "nisbets catering foil rolls",
    "asdf qwer zxcv notaproduct",
    "ballpoint pens",
    "cash and carry rice 5kg",
    "tote bag",
    "allen keys",
    "tempered glass screen protector",
    "usb c cable",
    "purple flying toaster moon cheese",
]
for q in qs:
    p = fixture_path(q, gl="uk", mode="bulk", currency="GBP")
    if not p.exists():
        print("MISSING", q)
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    w = (d.get("warning") or "")[:60]
    print(
        f"{q!r}: listings={len(d.get('listings') or [])} "
        f"raw={len(d.get('listings_raw') or [])} warn={w}"
    )
