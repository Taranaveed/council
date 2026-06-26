import re
from typing import Literal

PriceSegment = Literal["SUSPICIOUSLY_CHEAP", "BUDGET", "PREMIUM", "NICHE_LUXURY", "UNKNOWN"]

# Approximate units of local currency per 1 USD.
# These are reference rates for classification only — not financial data.
_USD_RATES: dict[str, float] = {
    "USD": 1.0,
    "PKR": 280.0,
    "GBP": 0.79,
    "EUR": 0.92,
    "INR": 83.0,
}

# USD price thresholds that define each segment.
# Tune these numbers to shift segment boundaries without touching any prompt.
_THRESHOLDS = {
    "SUSPICIOUSLY_CHEAP": 25.0,   # < $25 USD  → dangerously cheap for tech
    "BUDGET":             200.0,  # $25–$200   → reasonable consumer range
    "PREMIUM":            800.0,  # $200–$800  → aspirational but attainable
    # anything above $800 USD     → niche luxury
}


def extract_price_value(price_str: str) -> float | None:
    """Pull the first valid number out of a free-text price field."""
    cleaned = price_str.replace(",", "")
    matches = re.findall(r"\d+\.?\d*", cleaned)
    return float(matches[0]) if matches else None


def classify_price(price_str: str, currency: str) -> PriceSegment:
    """
    Convert the price to a USD equivalent and return a PriceSegment label.
    Falls back to UNKNOWN if the price cannot be parsed or the currency
    is not in the reference table.
    """
    value = extract_price_value(price_str)
    if value is None:
        return "UNKNOWN"

    rate = _USD_RATES.get(currency.upper(), None)
    if rate is None:
        return "UNKNOWN"

    usd = value / rate

    if usd < _THRESHOLDS["SUSPICIOUSLY_CHEAP"]:
        return "SUSPICIOUSLY_CHEAP"
    elif usd < _THRESHOLDS["BUDGET"]:
        return "BUDGET"
    elif usd < _THRESHOLDS["PREMIUM"]:
        return "PREMIUM"
    else:
        return "NICHE_LUXURY"
