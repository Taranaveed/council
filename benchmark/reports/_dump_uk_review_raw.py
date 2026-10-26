"""One-off: dump shopping / merchant rows from the four live fixtures."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

QUERIES = [
    "notebooks",
    "earphones",
    "lip_gloss_bulk",
    "uk_plug_extension_lead",
]
BASE = Path(__file__).resolve().parents[1] / "fixtures" / "market"


def host_of(url: str | None) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except Exception:
        return ""


def main() -> None:
    for q in QUERIES:
        p = BASE / f"{q}__uk__bulk__GBP.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        raw = d.get("listings_raw") or []
        kept = d.get("listings") or []
        print(f"==== {q} raw={len(raw)} kept={len(kept)}")
        if raw:
            print("  keys:", sorted(raw[0].keys()))
        n = 0
        for x in raw:
            link = str(x.get("link") or "")
            host = str(x.get("host") or "")
            mer = x.get("merchant") or x.get("source") or x.get("vendor")
            shopping = "google.com" in link or host == "google.com" or bool(x.get("merchant"))
            if not shopping:
                continue
            pl = str(x.get("product_link") or x.get("link") or "")
            ship = str(
                x.get("shipping")
                or x.get("delivery")
                or x.get("delivery_info")
                or x.get("extensions")
                or ""
            )[:80]
            print(
                f"  mer={mer!r} host={host!r} phost={host_of(pl)!r} "
                f"price={x.get('price')!r} ext={x.get('extracted_price')!r} "
                f"curr={x.get('currency')!r} src={x.get('price_source')!r} "
                f"ship={ship!r}"
            )
            n += 1
            if n >= 12:
                break
        print(f"  shown={n}")
        # also: which kept rows look like shopping
        sk = 0
        for x in kept:
            if x.get("merchant") or "google.com" in str(x.get("link") or ""):
                print(
                    f"  KEPT mer={x.get('merchant') or x.get('vendor')!r} "
                    f"price={x.get('price')!r} ext={x.get('extracted_price')!r} "
                    f"src={x.get('price_source')!r}"
                )
                sk += 1
        print(f"  kept_shoppingish={sk}")


if __name__ == "__main__":
    main()
