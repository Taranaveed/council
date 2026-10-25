"""Shared money parsing — preserve thousands separators (1,569 → 1569)."""
from __future__ import annotations

import re
from typing import Any

_CURRENCY_RE = re.compile(
    r"(?:Rs\.?|PKR|USD|INR|AED|SAR|EUR|GBP|\$|€|£|₹)",
    re.I,
)


def is_malformed_price_string(raw: Any) -> bool:
    """Detect glued unit+MOQ scrapes like '$1.321,000' or raw ranges."""
    text = str(raw or "").strip()
    if not text:
        return False
    if re.search(r"[-–—]\s*[\d$]", text) and re.search(r"\$|USD|Rs|PKR", text, re.I):
        return True
    s = _CURRENCY_RE.sub(" ", text)
    s = re.sub(r"[^\d.,]", "", s)
    s = re.sub(r"^[.,]+", "", s)
    if not s:
        return False
    if re.fullmatch(r"\d+\.\d+,\d{3}", s):
        return True
    if s.count(",") > 1 and "." in s:
        return True
    if re.fullmatch(r"\d+\.\d{1,2},000", s):
        return True
    return False


def sanitize_price_raw(raw: Any) -> str:
    """Keep the first sane unit token from ranges / concatenations."""
    text = str(raw or "").strip()
    if not text:
        return text
    m = re.match(
        r"^((?:US\s*)?(?:\$|USD|Rs\.?|PKR|€|£)\s*[\d,.]+)\s*[-–—]\s*[\d,.]+",
        text,
        re.I,
    )
    if m:
        return m.group(1).strip()
    if not is_malformed_price_string(text):
        return text
    m2 = re.search(
        r"((?:US\s*)?(?:\$|USD|Rs\.?|PKR|€|£)\s*\d+\.\d{1,2})(?:,\d{3})",
        text,
        re.I,
    )
    if m2:
        return m2.group(1).strip()
    m3 = re.search(r"((?:US\s*)?(?:\$|USD)\s*\d+\.\d{1,2})", text, re.I)
    if m3:
        return m3.group(1).strip()
    return text


def parse_money(raw: Any) -> float | None:
    """
    Parse free-text money. "Rs 1,569" / "1,569.00" → 1569.
    Never take only the digits before the first comma.
    Rejects ambiguous concatenations like "1.321,000" after sanitize fails.
    """
    text = sanitize_price_raw(raw)
    if not text:
        return None
    s = _CURRENCY_RE.sub(" ", text).strip()
    s = re.sub(r"[^\d.,]", "", s)
    s = re.sub(r"^[.,]+", "", s)
    s = re.sub(r"[.,]+$", "", s)  # "7.15." / "1,569," from OCR/snippet junk
    if not s:
        return None

    # Ambiguous unit+MOQ concat — try first decimal token only
    if re.fullmatch(r"\d+\.\d+,\d{3}", s):
        m = re.match(r"(\d+\.\d{1,2})", s)
        if not m:
            return None
        s = m.group(1)

    def _pos(n: float) -> float | None:
        return n if n > 0 else None

    try:
        # US/PK grouping: 1,234.56 or 9,500
        if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):
            return _pos(float(s.replace(",", "")))
        # Plain: 9500.00 / 9500
        if re.fullmatch(r"\d+(\.\d+)?", s):
            return _pos(float(s))
        # EU grouping: 1.234,56
        if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):
            return _pos(float(s.replace(".", "").replace(",", ".")))
        # EU decimal: 9500,00
        if re.fullmatch(r"\d+,\d{1,2}", s):
            return _pos(float(s.replace(",", ".")))

        # Still ambiguous after sanitize
        if re.fullmatch(r"\d+\.\d+,\d{3}", s):
            return None

        last_dot = s.rfind(".")
        last_comma = s.rfind(",")
        if last_dot > last_comma:
            return _pos(float(s.replace(",", "")))
        if last_comma > last_dot:
            if re.fullmatch(r"\d{1,3}(,\d{3})+", s):
                return _pos(float(s.replace(",", "")))
            return _pos(float(s.replace(".", "").replace(",", ".")))

        return _pos(float(s.replace(",", "")))
    except ValueError:
        return None
