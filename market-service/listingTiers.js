/**
 * Parse MOQ, unit price tiers, and package weight from titles, snippets, and product HTML.
 * Best-effort — never invents numbers when patterns are missing.
 */

import { formatMoneyAmount, parsePriceNumber } from "./priceParse.js";

const MOQ_RE =
  /(?:MOQ|Min(?:imum)?\.?\s*Order(?:\s*Qty)?|Min\.?\s*Order)\s*[:\-]?\s*(\d[\d,]*)/i;

const TIER_PAIR_RE =
  /(\d[\d,]*)\s*[–\-~]\s*(\d[\d,]*)\s*(?:pcs?|pieces?|units?)?\s*[:\-]?\s*((?:US\s*)?\$|USD|Rs\.?|PKR|₹|INR|€|£)?\s*([\d,]+(?:\.\d+)?)/gi;

const TIER_PLUS_RE =
  /(\d[\d,]*)\s*\+\s*(?:pcs?|pieces?|units?)?\s*[:\-]?\s*((?:US\s*)?\$|USD|Rs\.?|PKR|₹|INR|€|£)?\s*([\d,]+(?:\.\d+)?)/gi;

const UNIT_PRICE_RE =
  /(?:unit\s*price|price)\s*[:\-]?\s*((?:US\s*)?\$|USD|Rs\.?|PKR|₹|INR|€|£)?\s*([\d,]+(?:\.\d+)?)/i;

/** Package / shipping weight — prefer kg, convert g → kg. */
const WEIGHT_RE = [
  /(?:package|shipping|gross|net|item|unit)?\s*weight\s*[:\-]?\s*([\d,.]+)\s*(kg|kilograms?|g|grams?|lb|lbs|pounds?)/i,
  /([\d,.]+)\s*(kg|kilograms?)\s*(?:\/\s*(?:pc|pcs|piece|unit))?/i,
  /"weight"\s*:\s*"?([\d,.]+)"?\s*(?:,|\})/i,
  /"shippingWeight"\s*:\s*"?([\d,.]+)\s*(kg|g|lb)?"?/i,
];

const CARTON_GROSS_RE =
  /\b(per\s*carton|carton\s*weight|gross\s*weight|shipping\s*weight|master\s*carton|outer\s*carton|箱重)\b/i;
const UNIT_WEIGHT_HINT_RE =
  /\b(per\s*(?:pc|pcs|piece|unit)|unit\s*weight|net\s*weight|item\s*weight|\/\s*(?:pc|pcs|piece|unit))\b/i;
const PCS_PER_CARTON_RE =
  /(?:pcs?|pieces?|units?)\s*[\/\s]*carton|carton\s*[:=]?\s*(\d[\d,]*)\s*(?:pcs?|pieces?|units?)|(\d[\d,]*)\s*(?:pcs?|pieces?|units?)\s*(?:per|\/)\s*carton|pack(?:ing)?(?:\s*quantity)?\s*[:=]?\s*(\d[\d,]*)/i;

function currencyFromSymbol(sym, fallback = "USD") {
  const s = String(sym || "").toUpperCase();
  if (!s) return fallback;
  if (s.includes("RS") || s.includes("PKR")) return "PKR";
  if (s.includes("₹") || s.includes("INR")) return "INR";
  if (s.includes("€") || s.includes("EUR")) return "EUR";
  if (s.includes("£") || s.includes("GBP")) return "GBP";
  if (s.includes("$") || s.includes("USD")) return "USD";
  return fallback;
}

function toInt(raw) {
  const n = Number(String(raw || "").replace(/,/g, ""));
  return Number.isFinite(n) && n > 0 ? Math.round(n) : null;
}

function toKg(amount, unit) {
  const n = parsePriceNumber(amount);
  if (n == null || n <= 0) return null;
  const u = String(unit || "kg").toLowerCase();
  if (u.startsWith("g") && !u.startsWith("kg")) return n / 1000;
  if (u.startsWith("lb") || u.startsWith("pound")) return n * 0.453592;
  return n; // kg
}

export function extractMoq(text) {
  const m = String(text || "").match(MOQ_RE);
  if (!m) return null;
  return toInt(m[1]);
}

function findPcsPerCarton(blob, aroundIndex = 0) {
  const start = Math.max(0, aroundIndex - 220);
  const window = String(blob || "").slice(start, aroundIndex + 220);
  const m = window.match(PCS_PER_CARTON_RE);
  if (!m) return null;
  const n = toInt(m[1] || m[2] || m[3]);
  return n && n > 1 ? n : null;
}

/**
 * Extract package weight and resolve to per-unit kg when possible.
 * Carton/gross weights without pcs/carton are NOT treated as unit weight.
 *
 * @returns {{
 *   kg: number|null,
 *   raw: string,
 *   source: string,
 *   basis: 'unit'|'carton'|'gross'|'unknown',
 *   pcs_per_carton: number|null,
 *   kg_as_parsed: number,
 *   note: string|null
 * } | null}
 */
export function extractPackageWeight(text) {
  const blob = String(text || "");
  if (!blob) return null;
  for (const re of WEIGHT_RE) {
    const m = blob.match(re);
    if (!m) continue;
    const unit = m[2] || "kg";
    const kg = toKg(m[1], unit);
    if (kg == null || kg <= 0 || kg > 500) continue;
    const raw = m[0].trim().slice(0, 120);
    const idx = typeof m.index === "number" ? m.index : blob.indexOf(m[0]);
    const ctxStart = Math.max(0, idx - 80);
    const ctx = blob.slice(ctxStart, idx + raw.length + 80);
    const isCartonOrGross = CARTON_GROSS_RE.test(ctx) || CARTON_GROSS_RE.test(raw);
    const unitHint = UNIT_WEIGHT_HINT_RE.test(ctx) || UNIT_WEIGHT_HINT_RE.test(raw);
    const pcs = findPcsPerCarton(blob, idx);

    if (isCartonOrGross && !unitHint) {
      if (pcs) {
        const perUnit = Math.round((kg / pcs) * 1000) / 1000;
        return {
          kg: perUnit,
          raw,
          source: "page_or_snippet",
          basis: "carton",
          pcs_per_carton: pcs,
          kg_as_parsed: Math.round(kg * 1000) / 1000,
          note: `carton/gross ${kg} kg ÷ ${pcs} pcs/carton → ${perUnit} kg/unit`,
        };
      }
      return {
        kg: null,
        raw,
        source: "page_or_snippet",
        basis: "carton",
        pcs_per_carton: null,
        kg_as_parsed: Math.round(kg * 1000) / 1000,
        note: "carton/gross weight without pcs/carton — not used as per-unit",
      };
    }

    // Explicit /pc or unit weight, or unmarked (treated as unit — backend plausibility may reject)
    return {
      kg: Math.round(kg * 1000) / 1000,
      raw,
      source: "page_or_snippet",
      basis: unitHint ? "unit" : "unknown",
      pcs_per_carton: pcs,
      kg_as_parsed: Math.round(kg * 1000) / 1000,
      note: unitHint ? "explicit unit/net weight" : "unmarked weight treated as candidate unit weight",
    };
  }
  return null;
}

export function extractPriceTiers(text, { defaultCurrency = "USD" } = {}) {
  const blob = String(text || "");
  if (!blob) return [];
  const tiers = [];
  const seen = new Set();

  for (const m of blob.matchAll(TIER_PAIR_RE)) {
    const minQty = toInt(m[1]);
    const amount = parsePriceNumber(m[4]);
    if (minQty == null || amount == null) continue;
    const currency = currencyFromSymbol(m[3], defaultCurrency);
    const key = `${minQty}:${amount}:${currency}`;
    if (seen.has(key)) continue;
    seen.add(key);
    tiers.push({
      min_qty: minQty,
      max_qty: toInt(m[2]),
      unit_price: formatMoneyAmount(amount, currency) || `${currency} ${amount}`,
      currency,
      source: "extracted",
    });
  }

  for (const m of blob.matchAll(TIER_PLUS_RE)) {
    const minQty = toInt(m[1]);
    const amount = parsePriceNumber(m[3]);
    if (minQty == null || amount == null) continue;
    const currency = currencyFromSymbol(m[2], defaultCurrency);
    const key = `${minQty}:${amount}:${currency}`;
    if (seen.has(key)) continue;
    seen.add(key);
    tiers.push({
      min_qty: minQty,
      max_qty: null,
      unit_price: formatMoneyAmount(amount, currency) || `${currency} ${amount}`,
      currency,
      source: "extracted",
    });
  }

  if (!tiers.length) {
    const unit = blob.match(UNIT_PRICE_RE);
    if (unit) {
      const amount = parsePriceNumber(unit[2]);
      if (amount != null) {
        const currency = currencyFromSymbol(unit[1], defaultCurrency);
        tiers.push({
          min_qty: 1,
          max_qty: null,
          unit_price: formatMoneyAmount(amount, currency) || `${currency} ${amount}`,
          currency,
          source: "extracted",
        });
      }
    }
  }

  tiers.sort((a, b) => a.min_qty - b.min_qty);
  return tiers;
}

/**
 * Detect unit basis from text: per_piece | per_lot | per_kg.
 */
export function detectUnitBasis(text, { lotHint = false } = {}) {
  const blob = String(text || "").toLowerCase();
  if (/\bper\s*kg\b|\b\/\s*kg\b|\bkg\b/.test(blob) && /\bprice\b|\brs\.?\b|\$/.test(blob)) {
    if (/\bper\s*kg\b|\b\/kg\b/.test(blob)) return "per_kg";
  }
  if (
    lotHint ||
    /\bper\s*lot\b|\b\/\s*lot\b|\blot\s+of\b|\bmystery\s*box\b|\b\d+\s*[-–]\s*\d+\s*pcs?\b/.test(blob)
  ) {
    return "per_lot";
  }
  return "per_piece";
}

/**
 * Validate tiers: duplicates, non-monotonic unit prices (should drop or stay flat as qty rises).
 * Returns { reliable: boolean, reasons: string[] }.
 */
export function assessTiersReliability(tiers) {
  const reasons = [];
  const list = (tiers || []).filter((t) => t && Number(t.min_qty) > 0);
  if (list.length <= 1) return { reliable: true, reasons: [] };

  const mins = list.map((t) => Number(t.min_qty));
  if (new Set(mins).size !== mins.length) {
    reasons.push("duplicate_min_qty");
  }

  const sorted = [...list].sort((a, b) => Number(a.min_qty) - Number(b.min_qty));
  let prevAmt = null;
  let prevMin = null;
  for (const t of sorted) {
    const amt = parsePriceNumber(t.unit_price);
    const minQ = Number(t.min_qty);
    if (amt == null) {
      reasons.push("unparseable_tier_price");
      break;
    }
    if (prevAmt != null && prevMin != null && minQ > prevMin && amt > prevAmt * 1.05) {
      // Unit price rising with quantity is contradictory for wholesale tiers
      reasons.push("non_monotonic_rising");
      break;
    }
    prevAmt = amt;
    prevMin = minQ;
  }

  // Contradictory: same min_qty different prices already caught; also wild spreads
  if (sorted.length >= 2) {
    const amounts = sorted.map((t) => parsePriceNumber(t.unit_price)).filter((n) => n != null);
    if (amounts.length >= 2) {
      const hi = Math.max(...amounts);
      const lo = Math.min(...amounts);
      if (lo > 0 && hi / lo > 50) reasons.push("wild_price_spread");
    }
  }

  return { reliable: reasons.length === 0, reasons };
}

/**
 * Select the tier where min_qty <= quantity (highest such min_qty).
 * If quantity < lowest min_qty → moq_not_met, do not apply that tier's price.
 *
 * @returns {{
 *   tier: object|null,
 *   moq_not_met: boolean,
 *   lowest_min_qty: number|null,
 *   tiers_reliable: boolean,
 *   reliability_reasons: string[],
 *   unit_price_range: {low:number, high:number}|null,
 * }}
 */
export function selectTierForQuantity(tiers, quantity) {
  const qty = Number(quantity);
  const assessment = assessTiersReliability(tiers);
  const list = (tiers || [])
    .filter((t) => t && Number(t.min_qty) > 0 && parsePriceNumber(t.unit_price) != null)
    .sort((a, b) => Number(a.min_qty) - Number(b.min_qty));

  if (!list.length || !Number.isFinite(qty) || qty <= 0) {
    return {
      tier: null,
      moq_not_met: false,
      lowest_min_qty: null,
      tiers_reliable: assessment.reliable,
      reliability_reasons: assessment.reasons,
      unit_price_range: null,
    };
  }

  const amounts = list.map((t) => parsePriceNumber(t.unit_price));
  const unit_price_range = {
    low: Math.min(...amounts),
    high: Math.max(...amounts),
  };

  const lowest = Number(list[0].min_qty);
  if (qty < lowest) {
    return {
      tier: null,
      moq_not_met: true,
      lowest_min_qty: lowest,
      tiers_reliable: assessment.reliable,
      reliability_reasons: assessment.reasons,
      unit_price_range,
    };
  }

  // If unreliable, do not pick a single tier — caller should use the range
  if (!assessment.reliable) {
    return {
      tier: null,
      moq_not_met: false,
      lowest_min_qty: lowest,
      tiers_reliable: false,
      reliability_reasons: assessment.reasons,
      unit_price_range,
    };
  }

  let chosen = list[0];
  for (const t of list) {
    if (qty >= Number(t.min_qty)) chosen = t;
  }
  return {
    tier: chosen,
    moq_not_met: false,
    lowest_min_qty: lowest,
    tiers_reliable: true,
    reliability_reasons: [],
    unit_price_range,
  };
}

/**
 * Annotate a listing with moq + price_tiers + package weight from title/snippet/page html.
 * Does NOT invent unit prices from storefronts. Synthetic single-unit tiers only when
 * price_source is "page" on a real product-detail URL.
 */
function isGoogleShoppingOfferUrl(url) {
  const u = String(url || "").toLowerCase();
  return (
    /google\.[^/]+\/search/i.test(u) &&
    (u.includes("ibp=oshop") || u.includes("tbm=shop"))
  );
}

export function annotateListingTiers(listing, { html = "", defaultCurrency = "USD", quantity = null } = {}) {
  const row = { ...(listing || {}) };
  const link = String(row.link || "");
  const productPage = isProductDetailUrl(link);

  // Google Shopping offer cards: keep merchant/source + any SERP price for review.
  // Never Best-pick / never counts as verified product-page wholesale.
  if (!productPage && isGoogleShoppingOfferUrl(link)) {
    row.is_product_page = false;
    row.is_shopping_offer = true;
    row.counts_as_live_listing = false;
    row.best_pick_eligible = false;
    row.price_review_only = true;
    row.channel = row.channel || "uk_retail_shopping";
    row.sourcing_action = "verify_bulk_discount";
    row.sourcing_note = "UK seller, unit price; verify bulk discount";
    // Do NOT wipe a real SERP price — leave for display/review
    if (!row.price || /^(see listing)/i.test(String(row.price))) {
      row.price_source = row.price_source || "shopping_offer_unpriced";
    } else {
      row.price_source = row.price_source || "serp_shopping";
    }
    row.price_tiers = row.price_tiers || [];
    row.has_price_tier = false;
    row.tiers_reliable = false;
    return row;
  }

  // Storefront / homepage — never trust a unit price; do not count as live priced listing
  if (!productPage) {
    row.is_product_page = false;
    row.counts_as_live_listing = false;
    row.unit_price_rejected = "storefront_or_non_product_url";
    if (row.price && !/^(see listing)/i.test(String(row.price))) {
      row.price_rejected = row.price;
      row.price = "See listing";
      row.price_source = "rejected_storefront";
    }
    row.price_tiers = [];
    row.has_price_tier = false;
    row.tiers_reliable = false;
    row.unit_basis = null;
    row.has_moq = row.moq != null && Number(row.moq) > 0;
    return row;
  }

  row.is_product_page = true;
  const blob = [
    row.title,
    row.snippet,
    row.price,
    html ? String(html).slice(0, 80_000) : "",
  ]
    .filter(Boolean)
    .join("\n");

  const moq = extractMoq(blob);
  const tiers = extractPriceTiers(blob, { defaultCurrency });
  const weight = extractPackageWeight(blob);
  row.unit_basis = detectUnitBasis(blob);

  if (moq != null) {
    row.moq = moq;
    row.moq_source = html ? "page" : "snippet";
  }
  if (weight) {
    row.package_weight_raw = weight.raw;
    row.package_weight_source = html ? "page" : "snippet";
    row.package_weight_basis = weight.basis || "unknown";
    row.package_weight_pcs_per_carton = weight.pcs_per_carton ?? null;
    row.package_weight_kg_as_parsed = weight.kg_as_parsed ?? null;
    row.package_weight_note = weight.note || null;
    if (weight.kg != null && weight.kg > 0) {
      row.package_weight_kg = weight.kg;
    } else {
      // Carton/gross without pcs — keep raw for diagnostics, do not use as unit
      delete row.package_weight_kg;
    }
  }

  if (tiers.length) {
    row.price_tiers = tiers;
    row.tiers_source = html ? "page" : "snippet";
    const assessment = assessTiersReliability(tiers);
    row.tiers_reliable = assessment.reliable;
    row.tiers_reliability_reasons = assessment.reasons;
    const first = tiers[0];
    if (first?.unit_price && (!row.price || /^(see listing|n\/?a)/i.test(String(row.price)))) {
      row.price = first.unit_price;
      row.price_source = row.price_source || "tier";
    }
    if (row.moq == null && first?.min_qty) {
      row.moq = first.min_qty;
      row.moq_source = row.moq_source || "tier_min";
    }
    if (quantity != null) {
      const sel = selectTierForQuantity(tiers, quantity);
      row.moq_not_met = sel.moq_not_met;
      row.selected_tier = sel.tier;
      row.unit_price_range = sel.unit_price_range;
      if (sel.moq_not_met) {
        row.moq_gate = `quantity ${quantity} < MOQ ${sel.lowest_min_qty}`;
      } else if (sel.tier && assessment.reliable) {
        row.price = sel.tier.unit_price;
        row.price_source = row.price_source || "tier_selected";
      }
    }
  } else {
    row.tiers_reliable = true;
  }

  // Only invent a 1-unit tier when we already have a page-extracted product price
  const pagePriced =
    String(row.price_source || "").toLowerCase() === "page" &&
    /\d/.test(String(row.price || "")) &&
    !/^(see listing)/i.test(String(row.price || ""));

  if ((!row.price_tiers || !row.price_tiers.length) && pagePriced) {
    const cur = String(row.currency || defaultCurrency || "USD").toUpperCase();
    const amt = parsePriceNumber(row.price);
    if (amt != null && amt > 0) {
      const formatted = formatMoneyAmount(amt, cur) || String(row.price);
      row.price = formatted;
      row.price_tiers = [
        {
          min_qty: row.moq != null && Number(row.moq) > 0 ? Number(row.moq) : 1,
          max_qty: null,
          unit_price: formatted,
          currency: cur,
          source: "page_scalar",
        },
      ];
      row.tiers_source = "page_scalar";
      row.tiers_reliable = true;
      if (row.moq == null) {
        row.moq = row.price_tiers[0].min_qty;
        row.moq_source = "assumed_1_from_page_price";
      }
    }
  }

  // Never display a specific MOQ alongside a missing/assumed source
  const moqSrc = String(row.moq_source || "").toLowerCase();
  if (
    moqSrc === "not_on_snippet" ||
    moqSrc === "not_verified" ||
    moqSrc === "assumed_1_from_page_price" ||
    moqSrc === "missing" ||
    moqSrc.startsWith("not_")
  ) {
    row.moq = null;
    row.moq_display = "MOQ not confirmed — verify on seller page";
    row.has_moq = false;
  }

  if (
    /\d/.test(String(row.price || "")) &&
    !/^(see listing)/i.test(String(row.price || "")) &&
    !["page", "tier", "page_scalar", "tier_selected"].includes(String(row.price_source || "").toLowerCase())
  ) {
    row.unit_price_verified = false;
  } else if (/\d/.test(String(row.price || ""))) {
    row.unit_price_verified = true;
  }

  row.has_price_tier = Boolean(row.price_tiers?.length);
  row.has_moq = row.moq != null && Number(row.moq) > 0;
  row.page_facts_fetched = Boolean(html && html.length > 200) || Boolean(row.page_facts_fetched);
  // Live listing = product page + parseable unit price
  row.counts_as_live_listing =
    productPage &&
    Boolean(parsePriceNumber(row.price)) &&
    !/^(see listing)/i.test(String(row.price || ""));
  return row;
}

export function annotateListingsTiers(listings, opts = {}) {
  return (listings || []).map((row) => annotateListingTiers(row, opts));
}

/** True when URL looks like a real product-detail page for known wholesale hosts. */
export function isProductDetailUrl(url) {
  const u = String(url || "").toLowerCase();
  if (!u) return false;
  if (/[?&](srsltid|gclid|fbclid)=/i.test(u) && !/\/products?\//i.test(u) && !/\/product-detail\//i.test(u)) {
    return false;
  }
  if (/\/(collections|catalog|category|categories|search|archives?|products-search|hot-china-products)(\/|$)/i.test(u)) {
    return false;
  }
  if (/made-in-china\.com\/products-search/i.test(u)) return false;
  if (/pinterest\.|wikipedia\.|unwomen\.|sciencedirect\.|flickr\./i.test(u)) return false;
  try {
    const path = new URL(u).pathname.replace(/\/+$/, "") || "/";
    if (path === "/" || path === "") return false;
  } catch {
    /* ignore */
  }
  if (/alibaba\.com\/product-detail\//i.test(u)) return true;
  if (/indiamart\.com\/(proddetail|product)/i.test(u)) return true;
  if (/tradeindia\.com\/products\//i.test(u)) return true;
  // Made-in-China: real product pages only (not search hubs)
  if (/made-in-china\.com\/product\//i.test(u)) return true;
  if (/[a-z0-9-]+\.en\.made-in-china\.com\/product\//i.test(u)) return true;
  if (/dhgate\.com\/product\//i.test(u)) return true;
  if (/aliexpress\.com\/item\//i.test(u)) return true;
  if (/faire\.com\/product/i.test(u)) return true;
  if (/globalsources\.com\/.*(product|si\/|gsol\/product)/i.test(u)) return true;
  if (/amazon\.[^/]+\/.*(dp|gp\/product)\//i.test(u)) return true;
  if (/daraz\.[^/]+\/products\//i.test(u)) return true;
  if (/ebay\.[^/]+\/itm\//i.test(u)) return true;
  if (/laam\.com\/(products?|nodes)\//i.test(u)) return true;
  if (/\/products\/[a-z0-9][\w-]*/i.test(u)) return true;
  if (/\/product\/[a-z0-9][\w-]*/i.test(u)) return true;
  if (/\/item\/[a-z0-9][\w-]*/i.test(u)) return true;
  if (/\/proddetail\//i.test(u)) return true;
  return false;
}

/** True when URL is not a single-SKU product page (storefront, collection, blog, homepage). */
export function isStorefrontOrHomepage(url) {
  const u = String(url || "").toLowerCase();
  if (!u) return true;
  return !isProductDetailUrl(u);
}
