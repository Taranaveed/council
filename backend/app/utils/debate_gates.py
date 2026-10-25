"""Post-debate gates: Risk hard signal, unverified-price scrub, disagreement prose."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from app.utils.money import parse_money
from app.utils.verdict_verify import clear_best_pick


_PASS_RE = re.compile(
    r"\b(?:recommend(?:ing)?|argue|arguing|prefer|advise|suggest(?:ing)?|"
    r"verdict|conclusion)\s*(?:is|:)?\s*(?:a\s+)?(?:PASS|SKIP|do\s+not\s+buy|"
    r"don't\s+buy|pass\s+on|skip\s+this)\b"
    r"|\b(?:PASS|SKIP)\s*[—\-:]|\bpass\s+on\s+(?:this|the)\b"
    r"|\b(?:not\s+safe\s+to\s+buy|too\s+risky\s+to\s+buy)\b",
    re.I,
)
_PASS_ON_PICK_RE = re.compile(
    r"\b(?:pass|skip|reject|avoid|do\s+not\s+(?:buy|recommend))\b.{0,80}\b"
    r"(?:thrift|cheapest|best\s+value|ranked\s+pick|best_pick|top\s+pick)\b"
    r"|\b(?:thrift|cheapest|best\s+value|ranked\s+pick).{0,80}\b"
    r"(?:pass|skip|reject|avoid|too\s+risky|unverified)\b",
    re.I,
)
_UNVERIFIED_JUSTIFY_RE = re.compile(
    r"(?:best\s+value|cheapest|unit\s+cost|after\s+\d+\+|tier|at\s+(?:only\s+)?)"
    r".{0,40}"
    r"(?:\$|Rs\.?|PKR|USD)\s*[\d,.]+",
    re.I,
)


def _norm_url(value: Any) -> str:
    text = str(value or "").strip()
    try:
        p = urlparse(text)
    except Exception:
        return ""
    if p.scheme not in ("http", "https") or not p.netloc:
        return ""
    return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/")


def risk_recommends_pass(risk_text: str) -> bool:
    t = str(risk_text or "")
    if not t.strip():
        return False
    if _PASS_RE.search(t) or _PASS_ON_PICK_RE.search(t):
        return True
    # Explicit closing PASS
    if re.search(r"\bPASS\b", t) and re.search(
        r"\b(recommend|prefer|advise|conclusion|verdict|therefore)\b", t, re.I
    ):
        return True
    return False


def listing_price_unverified(listing: dict[str, Any] | None) -> bool:
    if not listing or not isinstance(listing, dict):
        return False
    src = str(listing.get("price_source") or "").lower()
    if src in ("serp", "snippet"):
        return True
    if listing.get("unit_price_verified") is False:
        return True
    if listing.get("unit_price_rejected"):
        return True
    return False


def apply_risk_hard_signal(
    verdict: dict[str, Any],
    transcript: dict[str, str],
    listings: list[dict[str, Any]],
    *,
    risk_flags: list[dict[str, str]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """
    If Risk explicitly recommends PASS/SKIP on the thrift/top pick (esp. with
    unverified price / high-risk flags), do not silently keep that listing as
    Best pick under Maybe/Buy. Surface disagreement in the summary.
    """
    out = dict(verdict or {})
    rows = [dict(x) for x in (listings or [])]
    notes: list[str] = []
    risk_text = str((transcript or {}).get("risk_analyst") or "")
    thrift_text = str((transcript or {}).get("thrift_advocate") or "")
    tag = str(out.get("verdict") or "").upper()
    if tag in ("PASS", "SKIP", "NO_MATCH"):
        return out, rows, notes

    if not risk_recommends_pass(risk_text):
        return out, rows, notes

    winner = dict(out.get("winner") or {}) if isinstance(out.get("winner"), dict) else {}
    w_link = _norm_url(winner.get("link"))
    pick = None
    for row in rows:
        if w_link and _norm_url(row.get("link")) == w_link:
            pick = row
            break
    if not pick:
        pick = next((r for r in rows if r.get("best_pick")), rows[0] if rows else None)

    flags = [
        f
        for f in (risk_flags or [])
        if not w_link or _norm_url(f.get("link")) == w_link or not f.get("link")
    ]
    high_on_pick = [f for f in flags if f.get("severity") == "high"]
    unverified = listing_price_unverified(pick) or any(
        f.get("code") == "price_not_verified" for f in flags
    )

    # Hard signal: Risk says PASS + (unverified price or high flags on pick)
    if unverified or high_on_pick or _PASS_ON_PICK_RE.search(risk_text):
        notes.append("risk_hard_signal_pass")
        issues = []
        if unverified:
            issues.append("unverified / SERP-only unit price")
        for f in high_on_pick[:3]:
            issues.append(str(f.get("message") or f.get("code")))
        issue_txt = "; ".join(issues) if issues else "trust / fraud risk"

        # Prefer a safer alternative if Risk or listings suggest one
        alt_link = ""
        for row in rows:
            if pick and _norm_url(row.get("link")) == _norm_url(pick.get("link")):
                continue
            if listing_price_unverified(row):
                continue
            if row.get("is_product_page") is False:
                continue
            alt_link = str(row.get("link") or "")
            break

        if not alt_link:
            rows = clear_best_pick(rows)
            reason = (
                f"Skip — Risk Analyst recommended PASS on the thrift pick "
                f"({issue_txt}). Agents disagree: Best Deal pushed the cheap option; "
                "Safety & Risk rejected it. No safer verified product page remains."
            )
            out["verdict"] = "PASS"
            out["winner"] = {
                "title": "",
                "vendor": "",
                "price": "",
                "link": "",
                "reason": reason,
            }
            out["summary"] = reason
            out["agent_disagreement"] = {
                "thrift": "pushed cheapest / best-value pick",
                "risk": "recommended PASS/SKIP",
                "judge_sided_with": "risk_analyst",
            }
            return out, rows, notes

        # Safer alt exists → Maybe on that alt, with disagreement prose
        alt = next(
            (r for r in rows if _norm_url(r.get("link")) == _norm_url(alt_link)),
            None,
        )
        rows = clear_best_pick(rows)
        if alt:
            for r in rows:
                r["best_pick"] = _norm_url(r.get("link")) == _norm_url(alt.get("link"))
        reason = (
            f"Maybe, high risk — Risk Analyst recommended PASS on the thrift pick "
            f"({issue_txt}). Best Deal disagreed. Judge sided with Risk on the cheap "
            f"option and moved to a safer listing to verify: "
            f"{str((alt or {}).get('vendor') or 'seller')} at {str((alt or {}).get('price') or 'n/a')}."
        )
        out["verdict"] = "MAYBE"
        out["winner"] = {
            "title": str((alt or {}).get("title") or ""),
            "vendor": str((alt or {}).get("vendor") or (alt or {}).get("source") or ""),
            "price": str((alt or {}).get("price") or ""),
            "link": str((alt or {}).get("link") or ""),
            "reason": reason,
        }
        out["summary"] = reason
        out["agent_disagreement"] = {
            "thrift": "pushed cheapest / best-value pick",
            "risk": "recommended PASS/SKIP on that pick",
            "judge_sided_with": "risk_analyst",
            "safer_alternative": str((alt or {}).get("link") or ""),
        }
        return out, rows, notes

    # Soft disagreement acknowledgment when Risk says PASS but pick looks page-verified
    if thrift_text and risk_recommends_pass(risk_text):
        summary = str(out.get("summary") or winner.get("reason") or "")
        if "disagree" not in summary.lower() and "risk" not in summary.lower():
            note = (
                " Agents disagree: Risk leans PASS while Best Deal pushes this pick — "
                "treat as Maybe and verify on the seller page."
            )
            out["verdict"] = "MAYBE" if tag == "BUY" else tag
            w = dict(out.get("winner") or {})
            w["reason"] = (str(w.get("reason") or summary) + note).strip()
            out["winner"] = w
            out["summary"] = w["reason"]
            out["agent_disagreement"] = {
                "thrift": "buy / best value",
                "risk": "leans PASS",
                "judge_sided_with": "cautious_maybe",
            }
            notes.append("risk_soft_disagreement")
    return out, rows, notes


def scrub_unverified_price_claims(
    transcript: dict[str, str],
    listings: list[dict[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    """
    If Thrift (or others) justify Best Value using a number that only appears on
    unverified SERP/snippet rows, append a forced caveat (or strip the claim).
    """
    out = dict(transcript or {})
    notes: list[str] = []
    unverified_amounts: set[float] = set()
    verified_amounts: set[float] = set()
    for row in listings or []:
        amt = parse_money(row.get("price"))
        if amt is None:
            continue
        if listing_price_unverified(row):
            unverified_amounts.add(round(amt, 4))
            # Also tier unit prices on unverified rows
            for t in row.get("price_tiers") or []:
                if isinstance(t, dict):
                    ta = parse_money(t.get("unit_price"))
                    if ta is not None:
                        unverified_amounts.add(round(ta, 4))
        elif str(row.get("price_source") or "").lower() in ("page", "tier", "tier_selected", "page_scalar"):
            verified_amounts.add(round(amt, 4))

    only_unverified = unverified_amounts - verified_amounts
    if not only_unverified:
        return out, notes

    caveat = (
        " [Caveat: a claimed unit/tier price used above is marked unverified SERP/snippet "
        "in the listings block — do not treat it as confirmed page pricing; confirm on the "
        "product page before ordering.]"
    )
    for agent in ("thrift_advocate", "contextual_persona"):
        text = str(out.get(agent) or "")
        if not text:
            continue
        hits = False
        for amt in only_unverified:
            # match $1 / Rs 1 / 1.00 style
            pat = re.compile(
                rf"(?:\$|Rs\.?|PKR|USD)?\s*{re.escape(str(int(amt)) if amt == int(amt) else str(amt))}"
                rf"(?:\.\d+)?\b"
            )
            if pat.search(text) and (
                _UNVERIFIED_JUSTIFY_RE.search(text)
                or re.search(r"\b(best\s+value|cheapest|per\s+unit|tier|after\s+\d+)\b", text, re.I)
            ):
                hits = True
                break
        if hits and caveat not in text:
            out[agent] = text.rstrip() + caveat
            notes.append(f"unverified_price_caveat:{agent}")
    return out, notes


def scrub_and_clear_listings(
    transcript: dict[str, str],
    listings: list[dict[str, Any]],
) -> tuple[dict[str, str], list[dict[str, Any]], list[str]]:
    """Scrub unverified price claims and clear Best-pick when they were used as justification."""
    scrubbed, notes = scrub_unverified_price_claims(transcript, listings)
    rows = listings
    if any(n.startswith("unverified_price_caveat") for n in notes):
        rows = clear_best_pick(listings)
        notes.append("best_pick_cleared_unverified_claim")
    return scrubbed, rows, notes
