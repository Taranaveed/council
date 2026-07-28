"""Build seller launch-pack action items, creatives, and export text."""
from __future__ import annotations

import re
from typing import Any


def _s(v: Any, fallback: str = "") -> str:
    t = str(v or "").strip()
    return t or fallback


def _short_problem(problem: str, *, product_name: str = "", max_len: int = 72) -> str:
    """First short clause for ad hooks — avoid dumping long feature lists."""
    t = _s(problem, "")
    t = re.split(r"[:.;]|include\b|such as\b", t, maxsplit=1, flags=re.I)[0].strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(
        r"^(the\s+)?(leather\s+)?(mobile\s+)?(phone\s+)?(covers?|cases?)\s+(include|are|have)\s+",
        "",
        t,
        flags=re.I,
    ).strip()
    product = _s(product_name).lower()
    if product and (
        t.lower() == product
        or t.lower().rstrip("s") == product.rstrip("s")
        or (product in t.lower() and len(t) <= len(product) + 8)
    ):
        t = ""
    # Feature/benefit pasted into "problem" → fall back to product cues
    # (e.g. "absorbs moisture: It is non-porous…" is a claim, not a buyer pain)
    if re.search(
        r"(?i)\b(non-porous|won't|will not|does not|doesn't|unique designs|"
        r"easy to clean|premium look|holds seasoning)\b",
        _s(problem),
    ) or re.match(
        r"(?i)^(absorbs|repels|prevents|resists|features|includes|made (of|from)|is |are )\b",
        t,
    ):
        t = ""
    if len(t) > max_len:
        cut = t[: max_len - 1].rsplit(" ", 1)[0].strip()
        t = f"{cut}…" if cut else t[:max_len]
    return t


_GENERIC_HOOK_RE = re.compile(
    r"(?i)("
    r"tired of .+meet |"
    r"cleaner everyday fix|"
    r"why locals pick |"
    r"^new drop:|"
    r"^solves:\s*$|"
    r"made for people who need|"
    r"everyday drop protection|"
    r"premium look and (feel|durability)(?!\s+from)|"
    r"limited intro offer$|"
    r"message us for today.?s? price$|"
    r"^still (putting up with|dealing with) [a-z]+s? moisture"
    r")"
)


def _is_generic_hook(hook: str, product_name: str = "") -> bool:
    h = _s(hook)
    if len(h) < 18:
        return True
    if _GENERIC_HOOK_RE.search(h):
        return True
    # Broken grammar from benefit-as-problem paste
    if re.search(r"(?i)putting up with (absorbs|is |won't|non-porous)", h):
        return True
    if re.search(r"(?i)without the the\b", h):
        return True
    product = _s(product_name)
    if product and re.match(
        rf"(?i)^tired of\s+{re.escape(product)}\??\s*meet\s+{re.escape(product)}",
        h,
    ):
        return True
    if product and h.lower().rstrip(".") == product.lower():
        return True
    return False


def _product_cue(product_name: str) -> dict[str, str]:
    """Light product-type cues for fallback hooks (no LLM)."""
    p = _s(product_name).lower()
    if re.search(r"\b(cover|case|phonecase)\b", p):
        return {
            "pain": "phones that scratch and plastic cases that crack",
            "proof": "real leather feel with everyday drop protection",
            "ask": "phone model / size",
        }
    if re.search(r"\b(earbud|earphone|headphone|tws)\b", p):
        return {
            "pain": "noisy commutes and weak battery earbuds",
            "proof": "clearer calls and all-day battery",
            "ask": "wired vs wireless / color",
        }
    if re.search(r"\b(jacket|coat)\b", p):
        return {
            "pain": "thin jackets that look worn after one season",
            "proof": "heavier material and a cut meant for daily wear",
            "ask": "size chart",
        }
    if re.search(r"\b(bag|backpack|wallet)\b", p):
        return {
            "pain": "bags that sag and zippers that fail",
            "proof": "sturdy build for daily carry",
            "ask": "color / size",
        }
    if re.search(r"\b(crock|crocker|crockpot|pottery|ceramic|stoneware|earthenware)\b", p):
        return {
            "pain": "porous crocks that stain, smell, and trap bacteria",
            "proof": "non-porous ceramic that stays cleaner and holds seasoning better",
            "ask": "size / capacity",
        }
    if re.search(r"\b(pan|pot|cookware|kitchen)\b", p):
        return {
            "pain": "cookware that warps and sticks after a few months",
            "proof": "steady heat and a surface you can clean fast",
            "ask": "size / set",
        }
    return {
        "pain": "cheap options that wear out fast",
        "proof": "clear quality you can check before buying",
        "ask": "size / variant",
    }


def _persona_bits(audience_verdict: dict[str, Any]) -> tuple[str, str]:
    personas = audience_verdict.get("personas") if isinstance(audience_verdict.get("personas"), list) else []
    trigger = ""
    objection = ""
    for p in personas:
        if not isinstance(p, dict):
            continue
        if not trigger:
            trigger = _s(p.get("buying_trigger") or p.get("motivation"))
        if not objection:
            objection = _s(p.get("main_objection"))
        if trigger and objection:
            break

    def _clip_phrase(raw: str, max_len: int) -> str:
        t = re.split(r"[.;]", _s(raw), maxsplit=1)[0].strip()
        t = re.sub(r"(?i)^(the\s+)?(fact that\s+)?", "", t).strip()
        # Compress long budget objections into a short caption phrase
        if re.search(r"(?i)\b(price|budget|expensive|cost|afford)\b", t) and len(t) > 42:
            t = "price pushing past their budget"
        if len(t) > max_len:
            t = t[: max_len - 1].rsplit(" ", 1)[0].strip() + "…"
        return t

    return _clip_phrase(trigger, 56), _clip_phrase(objection, 48)


def _lc_first(s: str) -> str:
    t = _s(s)
    if not t:
        return t
    return t[0].lower() + t[1:]


def _channel_hooks(
    *,
    channel: str,
    product: str,
    problem: str,
    list_price: str | None,
    trigger: str,
    objection: str,
    cues: dict[str, str],
) -> list[str]:
    ch = channel.lower()
    pain = _lc_first(problem or cues["pain"]).rstrip(".")
    proof = cues["proof"]
    ask = cues["ask"]
    price_bit = f" at {list_price}" if list_price else ""
    price_line = (
        f"Intro{price_bit} — reply with your {ask}."
        if list_price
        else f"Reply with your {ask} for today’s price."
    )
    trig = _lc_first(trigger).rstrip(".")
    obj = _lc_first(objection).rstrip(".") or "quality vs price doubts"
    # Avoid "without the the high-end price…"
    obj_no_article = re.sub(r"^(the|a|an)\s+", "", obj, flags=re.I)
    price_hook = (
        f"Listed{price_bit} — confirm {ask} before you pay."
        if list_price
        else f"Ask for today’s price and confirm {ask} first."
    )

    if "whatsapp" in ch or "wa " in ch or ch == "wa":
        return [
            f"Still dealing with {pain}? {product} is built for that{price_bit}.",
            f"{product}: {proof}. {price_line}",
            f"Common worry — {obj_no_article}. We show material/finish before you pay.",
            (
                f"If you want {trig}, this is the short version: {proof}."
                if trig
                else f"Short version: {proof}."
            ),
            f"Reply with your {ask} and we’ll confirm fit in one message.",
        ]
    if "amazon" in ch or "daraz" in ch or "ebay" in ch or "noon" in ch:
        return [
            f"{product} — {proof} for shoppers tired of {pain}.",
            f"Daily-use focus: {proof}. Confirm {ask} before you order.",
            price_hook,
            f"Pre-answer: {obj_no_article}? Check the material notes and return window before checkout.",
            f"Search tip: match your {ask}, then compare build — not just the lowest listing.",
        ]
    if "instagram" in ch or "tiktok" in ch or "reel" in ch or "facebook" in ch:
        return [
            f"Still putting up with {pain}? Swap to {product}.",
            f"{product}: {proof}" + (f" · {list_price}" if list_price else "."),
            (
                f"For buyers who want {trig} — without {obj_no_article}."
                if trig
                else f"Save this if you care about {proof}."
            ),
            f"Close-up proof > hype: {proof}.",
            f"DM your {ask} — we’ll tell you if it fits before you pay"
            + (f" ({list_price})" if list_price else "."),
        ]
    return [
        f"Stop settling for {pain}. Try {product}.",
        f"{product}: {proof}" + (f" · from {list_price}" if list_price else "."),
        f"Ask about {ask} before you buy — we’ll confirm fit first.",
        f"If {obj} is your hesitation, ask for a detail photo / spec check first.",
        price_hook,
    ]


def _default_offer(list_price: str | None, ask: str) -> str:
    if list_price:
        return f"Intro price {list_price} — confirm {ask} before payment"
    return f"Message to confirm {ask} and today’s price"


def build_channel_creatives(
    audience_verdict: dict[str, Any],
    *,
    product_name: str,
    problem_solved: str,
    list_price: str | None,
    location: str | None = None,
) -> list[dict[str, Any]]:
    product = _s(product_name, "This product")
    problem = _short_problem(problem_solved, product_name=product)
    cues = _product_cue(product)
    trigger, objection = _persona_bits(audience_verdict)
    _ = location  # reserved for future geo-specific idioms

    # Prefer LLM creatives only when hooks pass the specificity gate
    from_llm = audience_verdict.get("channel_creatives")
    out: list[dict[str, Any]] = []
    if isinstance(from_llm, list):
        for row in from_llm[:3]:
            if not isinstance(row, dict):
                continue
            hooks = row.get("hooks") if isinstance(row.get("hooks"), list) else []
            clean = [
                str(h).strip()
                for h in hooks
                if str(h).strip() and not _is_generic_hook(str(h), product)
            ][:5]
            channel = _s(row.get("channel"))
            if not channel:
                continue
            regenerated = False
            if len(clean) < 3:
                regenerated = True
                clean = _channel_hooks(
                    channel=channel,
                    product=product,
                    problem=problem,
                    list_price=list_price,
                    trigger=trigger,
                    objection=objection,
                    cues=cues,
                )
            elif len(clean) < 5:
                # Pad with generated angles the model skipped
                pad = _channel_hooks(
                    channel=channel,
                    product=product,
                    problem=problem,
                    list_price=list_price,
                    trigger=trigger,
                    objection=objection,
                    cues=cues,
                )
                for extra in pad:
                    if len(clean) >= 5:
                        break
                    if extra.lower() not in {c.lower() for c in clean}:
                        clean.append(extra)
            offer = _s(row.get("offer"))
            if regenerated or not offer or _is_generic_hook(offer, product) or re.match(
                r"(?i)^intro price from\b", offer
            ):
                offer = _default_offer(list_price, cues["ask"])
            out.append({"channel": channel, "hooks": clean[:5], "offer": offer})
        if len(out) >= 2:
            return out[:2]

    top = _s(audience_verdict.get("top_channel_recommendation"), "Instagram")
    if re.match(r"^(your best local channel|social media|online|ads)$", top, re.I):
        top = "Instagram"
    plan = audience_verdict.get("channel_plan") if isinstance(audience_verdict.get("channel_plan"), list) else []
    channels = [top]
    for c in plan:
        if isinstance(c, dict) and c.get("channel"):
            name = str(c["channel"]).strip()
            if name and name.lower() not in {x.lower() for x in channels}:
                if re.match(r"^(your best local channel|social media)$", name, re.I):
                    continue
                channels.append(name)
        if len(channels) >= 2:
            break
    if len(channels) < 2:
        channels.append("WhatsApp")

    used = {str(r["channel"]).lower() for r in out}
    for ch in channels:
        if ch.lower() in used:
            continue
        out.append(
            {
                "channel": ch,
                "hooks": _channel_hooks(
                    channel=ch,
                    product=product,
                    problem=problem,
                    list_price=list_price,
                    trigger=trigger,
                    objection=objection,
                    cues=cues,
                ),
                "offer": _default_offer(list_price, cues["ask"]),
            }
        )
        if len(out) >= 2:
            break
    return out[:2]


def build_action_pack(
    *,
    price_verdict: dict[str, Any],
    audience_verdict: dict[str, Any],
    explanation: dict[str, Any],
    product_name: str,
    condition: str | None = None,
) -> dict[str, Any]:
    list_price = (
        explanation.get("list_price_suggestion")
        or _s(price_verdict.get("recommended_price"))
        or None
    )
    promo = explanation.get("promo_floor")
    top_channel = _s(audience_verdict.get("top_channel_recommendation"), "Instagram")
    if re.match(r"^(your best local channel|social media|online|ads)$", top_channel, re.I):
        top_channel = "Instagram"
    personas = audience_verdict.get("personas") if isinstance(audience_verdict.get("personas"), list) else []
    angles: list[str] = []
    for p in personas[:3]:
        if not isinstance(p, dict):
            continue
        name = _s(p.get("name"), "Buyers")
        trigger = _s(p.get("buying_trigger") or p.get("motivation"))
        if trigger:
            angles.append(f"{name}: {trigger}")
    if not angles:
        angles = [
            _s(price_verdict.get("key_argument_for"), "Lead with clear product proof"),
            "Show real use, not feature dumps",
            f"Push first orders via {top_channel}",
        ]

    dont: list[str] = []
    if explanation.get("data_quality") in {"empty", "thin_foreign", "thin_local"}:
        dont.append("Don’t claim ‘#1 in the city’ or guaranteed market price without more local comps.")
    if condition and "handmade" in condition.lower():
        dont.append("Don’t imply factory mass production — say handmade / small batch clearly.")
    dont.append("Don’t undercut your cost floor on ‘sale’ posts without a margin plan.")
    if explanation.get("cost_floor"):
        dont.append(f"Don’t list below cost floor ({explanation['cost_floor']}) unless intentional loss-leader.")

    actions = [
        f"Set list price near {list_price or 'your band'} and a promo floor at {promo or 'your low end'}.",
        f"Post first offer on {top_channel} with one clear problem → product line.",
        "Pin 2–3 proof points (material, size, delivery, return) before price objections pile up.",
    ]
    if personas:
        first = personas[0] if isinstance(personas[0], dict) else {}
        obj = _s(first.get("main_objection"))
        if obj:
            actions.append(f"Pre-answer top objection: {obj}")

    return {
        "list_price": list_price,
        "promo_floor": promo,
        "messaging_angles": angles[:3],
        "first_actions": actions[:4],
        "dont_claim": dont[:4],
        "top_channel": top_channel or None,
        "product_name": product_name,
    }


def build_export_text(
    *,
    product_name: str,
    location: str | None,
    action_pack: dict[str, Any],
    explanation: dict[str, Any],
    audience_verdict: dict[str, Any],
    creatives: list[dict[str, Any]],
) -> str:
    lines = [
        f"Launch pack — {product_name}",
        f"Market: {location or 'not set'}",
        "",
        "PRICING",
        f"List: {action_pack.get('list_price') or '—'}",
        f"Promo floor: {action_pack.get('promo_floor') or '—'}",
        f"Why: {explanation.get('why') or '—'}",
        f"Vs your band: {explanation.get('vs_your_band') or '—'}",
        "",
        "CHANNEL",
        f"Primary: {action_pack.get('top_channel') or '—'}",
        "",
        "DO NEXT",
    ]
    for a in action_pack.get("first_actions") or []:
        lines.append(f"- {a}")
    if action_pack.get("dont_claim"):
        lines.append("")
        lines.append("DON'T CLAIM")
        for d in action_pack["dont_claim"]:
            lines.append(f"- {d}")
    if creatives:
        lines.append("")
        lines.append("HOOKS")
        for c in creatives:
            lines.append(f"[{c.get('channel')}]")
            for h in c.get("hooks") or []:
                lines.append(f"  - {h}")
            if c.get("offer"):
                lines.append(f"  Offer: {c['offer']}")
    summary = _s(audience_verdict.get("summary"))
    if summary:
        lines.extend(["", "BUYERS", summary])
    return "\n".join(lines)


def empty_state_note(explanation: dict[str, Any], market_warning: str | None) -> str | None:
    quality = explanation.get("data_quality")
    if quality == "empty":
        return (
            "Live local prices unavailable. Pricing leans on your band and product details — "
            "not a verified market median. Focus on channels and proof, then re-check prices later."
        )
    if quality == "thin_foreign":
        return (
            "Only foreign-currency listings came back. Use your local band as the anchor; "
            "treat overseas prices as rough reference only."
        )
    if quality == "thin_local":
        return (
            "Very few local comps. Treat the suggested price as directional and validate with "
            "a few more seller checks before locking a public list price."
        )
    if market_warning and not explanation.get("local_listing_count"):
        return market_warning
    return None
