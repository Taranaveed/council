"""Load per-category conflict terms (e.g. disposable vs soft towels)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
_PATH = _ROOT / "shared" / "conflict_terms.json"


@lru_cache(maxsize=1)
def load_conflict_terms() -> dict[str, Any]:
    if not _PATH.is_file():
        return {"categories": {}}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"categories": {}}


def detect_attribute_conflicts(
    listing: dict[str, Any],
    query: str | None,
) -> list[dict[str, str]]:
    """
    Return conflict hits [{id, label, term}] when listing contradicts category intent.
    Does not drop the row by itself — caller sets drop_reason / wired_conflict-style flags.
    """
    q = str(query or "").lower()
    blob = " ".join(
        str(listing.get(k) or "")
        for k in ("title", "snippet", "note", "description")
    ).lower()
    if not q or not blob:
        return []
    cats = (load_conflict_terms().get("categories") or {})
    hits: list[dict[str, str]] = []
    for cid, cfg in cats.items():
        if not isinstance(cfg, dict):
            continue
        require = str(cfg.get("require_query_token") or "").lower()
        if require and require not in q:
            continue
        triggers = [str(t).lower() for t in (cfg.get("query_any") or []) if t]
        if triggers and not any(t in q for t in triggers):
            continue
        for term in cfg.get("conflict_terms") or []:
            t = str(term).lower()
            if t and re.search(rf"\b{re.escape(t)}\b", blob):
                hits.append(
                    {
                        "id": f"conflict_{cid}",
                        "label": str(cfg.get("conflict_label") or term),
                        "term": t,
                    }
                )
                break
    return hits
