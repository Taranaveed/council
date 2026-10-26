"""Strip raw HTTP codes and URLs from buyer-facing market warnings."""
from __future__ import annotations

import re


_URL_RE = re.compile(r"https?://\S+", re.I)
_HTTP_RE = re.compile(
    r"\b(?:client error|http)\s*'?\d{3}[^.\n]*|\b429\b|\btoo many requests\b",
    re.I,
)
_TRACE_RE = re.compile(r"for more information check:.*", re.I)


def scrub_buyer_warning(text: str | None) -> str | None:
    """
    Keep useful search notes; replace infra failures with a short user-safe line.
    """
    w = str(text or "").strip()
    if not w:
        return None
    if _HTTP_RE.search(w) or "market service unreachable" in w.lower():
        # Drop the infra sentence; keep any preceding useful bits
        parts = re.split(r"(?<=[.!?])\s+", w)
        keep = [
            p
            for p in parts
            if p
            and not _HTTP_RE.search(p)
            and "unreachable" not in p.lower()
            and not _TRACE_RE.search(p)
        ]
        cleaned = " ".join(keep).strip()
        safe = "Wholesale search is busy — wait a moment and retry."
        w = f"{cleaned} {safe}".strip() if cleaned else safe
    w = _URL_RE.sub("", w)
    w = _TRACE_RE.sub("", w)
    w = re.sub(r"\s{2,}", " ", w).strip(" .")
    return w or None
