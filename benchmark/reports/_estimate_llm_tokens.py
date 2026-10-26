"""Estimate LLM tokens per deal-finder brief and briefs/day at Groq limits."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

CHARS_PER_TOKEN = 4.0


def _tok(s: str) -> int:
    return max(1, int(len(s) / CHARS_PER_TOKEN))


def main() -> None:
    from app.agents.deal_finder_prompts import (
        deal_judge_prompt,
        risk_analyst_prompt,
        thrift_advocate_prompt,
    )

    # Typical market context stuffed into the user message alongside system prompts
    market_user = (
        "Item: scented candles wholesale\nLocation: London, United Kingdom\nQty: 100\n"
        + ("LISTING vendor price £12 title scented candle bulk pack\n" * 12)
        + ("FACT unit=1.2 goods=120 landed=355\n" * 8)
    )
    loc = {"currency": "GBP", "country": "UK"}
    by_agent: dict[str, dict[str, int]] = {}
    for name, fn in [
        ("thrift_advocate", thrift_advocate_prompt),
        ("risk_analyst", risk_analyst_prompt),
        ("deal_judge", deal_judge_prompt),
    ]:
        sys_prompt = fn(
            marketplace="local_retailers",
            location_context=loc,
            live_listings_available=True,
            buying_mode="bulk",
            quantity=100,
        )
        in_tok = _tok(sys_prompt) + _tok(market_user)
        out_tok = 1200  # observed mid-length agent JSON/prose
        by_agent[name] = {"in": in_tok, "out": out_tok, "total": in_tok + out_tok}
        print(
            f"{name}: sys+user≈{in_tok} + completion≈{out_tok} → {in_tok + out_tok}"
        )

    # Contextual persona + optional retry / judge refine
    extra = _tok(market_user) + 900 + 1200
    print(f"contextual_persona≈{extra}")
    per_brief = sum(v["total"] for v in by_agent.values()) + extra
    print(f"TOTAL_PER_BRIEF≈{per_brief}")

    tpd = int(os.getenv("GROQ_TPD_LIMIT", "200000"))
    briefs = max(0, tpd // per_brief)
    print(f"GROQ_TPD_LIMIT={tpd}")
    print(f"EST_BRIEFS_PER_DAY≈{briefs} (single model, no retries)")
    print()
    print("Cut proposals:")
    print("  1. Cap market_block to top 6 priced rows + compact fact sheet (−30–40% input).")
    print("  2. One-shot judge; fold thrift/risk into short bullet tools (2 calls → 1).")
    print("  3. Skip contextual persona when kept_priced < 2 / NO_MATCH.")
    print("  4. Fixture-hash cache for --full --replay (0 tokens on re-runs).")
    print("  5. Smaller model for thrift/risk; 120b for judge only.")


if __name__ == "__main__":
    main()
