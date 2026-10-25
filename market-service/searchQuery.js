/**
 * Build short, searchable product queries from free-text specs / names.
 * Long marketing copy causes SerpApi timeouts; over-shortening (just "earbuds")
 * returns one random premium listing. Keep product type + useful modifiers.
 */

import { expandSearchSynonyms } from "./synonyms.js";
import { normalizeShopQuery } from "./listingQuality.js";

const STOP = new Set([
  "a", "an", "the", "and", "or", "with", "for", "from", "that", "this", "these",
  "those", "high", "quality", "premium", "look", "looks", "best", "new", "our",
  "product", "item", "features", "feature", "battery", "lasts", "hours", "hour",
  "sleek", "design", "superior", "very", "good", "great", "preminum", "amazing",
  "excellent", "super", "ultra", "worth", "selling", "sell", "price", "range",
]);

const PRODUCT_NOUNS = [
  "earbuds", "earbud", "earphones", "earphone", "headphones", "headphone",
  "headset", "handsfree", "buds", "airpods", "speaker", "speakers", "watch", "smartwatch",
  // Accessory types before bare "leather" so "leather mobile covers" ≠ "leather"
  "covers", "cover", "cases", "case", "phonecase",
  "phone", "smartphone", "iphone", "laptop", "tablet", "camera", "charger",
  "powerbank", "keyboard", "mouse", "monitor", "tv", "router", "console",
  "jacket", "coat", "shoes", "sneakers", "bag", "backpack", "wallet", "belt",
  "purse", "handbag", "tote",
  "ring", "rings", "jewelry", "jewellery", "necklace", "bracelet", "earring", "earrings",
  "pashmina", "shawl", "scarf", "stole", "dupatta", "stole", "wrap",
  "sweater", "hoodie", "dress", "saree", "kurta", "suit",
  "cashmere", "silk", "wool", "leather", "handmade",
];

const KEEP = new Set([
  "wireless", "bluetooth", "noise", "cancelling", "cancellation", "canceling",
  "anc", "tws", "true", "gaming", "sports", "waterproof", "water", "resistant",
  "pro", "max", "mini", "plus", "active", "bass", "stereo", "over", "ear",
  "on", "in", "neckband", "bone", "conduction", "handsfree", "wired",
  "handmade", "hand", "made", "kashmiri", "kashmir", "genuine", "pure",
  "leather", "wool", "silk", "cashmere", "pashmina", "organic", "vintage",
  "mobile", "phone", "cover", "covers", "case", "cases", "flip", "folio",
  "ring", "rings", "jewelry", "jewellery", "ladies", "women", "womens", "silver", "gold",
]);

const MATERIAL_RE =
  /\b(leather|suede|wool|silk|denim|cotton|cashmere|pashmina|linen|velvet)\b/i;

const COMPOUNDS = [
  {
    test: /\bhands?[\s-]*frees?\b|\bhandsfrees?\b/i,
    out: "handsfree earphones",
  },
  // "ladies rings" → jewelry (avoids Beyoncé / Barenaked Ladies SERP noise)
  {
    test: /\b(ladies?|womens?|women'?s?)\b.+\b(rings?|jewellery|jewelry)\b|\b(rings?)\b.+\b(ladies?|womens?|women'?s?)\b/i,
    out: "women jewelry finger rings",
  },
  {
    test: /\bfinger\s+rings?\b/i,
    out: "finger rings jewelry",
  },
  {
    test: /\bleather\b.+\b(mobile|phone)\b.+\b(cover|covers)\b|\b(mobile|phone)\b.+\bleather\b.+\b(cover|covers)\b|\bleather\b.+\b(cover|covers)\b/i,
    out: "leather phone cover",
  },
  {
    test: /\bleather\b.+\b(mobile|phone)\b.+\b(case|cases)\b|\b(mobile|phone)\b.+\bleather\b.+\b(case|cases)\b|\bleather\b.+\b(case|cases)\b/i,
    out: "leather phone case",
  },
  { test: /\bleather\b.+\bjacket\b|\bjacket\b.+\bleather\b/i, out: "leather jacket" },
  { test: /\bwool\b.+\bcoat\b|\bcoat\b.+\bwool\b/i, out: "wool coat" },
  { test: /\bpashmina\b.+\bshawl\b|\bshawl\b.+\bpashmina\b/i, out: "pashmina shawl" },
  { test: /\bcashmere\b.+\bshawl\b|\bshawl\b.+\bcashmere\b/i, out: "cashmere shawl" },
  { test: /\bsilk\b.+\bscarf\b|\bscarf\b.+\bsilk\b/i, out: "silk scarf" },
  { test: /\bleather\b.+\bbag\b|\bbag\b.+\bleather\b/i, out: "leather bag" },
  { test: /\bleather\b.+\bwallet\b|\bwallet\b.+\bleather\b/i, out: "leather wallet" },
  { test: /\bhandmade\b.+\bpashmina\b|\bpashmina\b.+\bhandmade\b/i, out: "handmade pashmina" },
];

export function hasMaterialTerm(text) {
  return MATERIAL_RE.test(String(text || ""));
}

export function shortenProductQuery(raw, { maxLen = 55 } = {}) {
  const original = normalizeShopQuery(
    String(raw || "")
      .replace(/[\r\n]+/g, " ")
      .replace(/\s+/g, " ")
      .trim(),
  );
  if (!original) return "product";

  const cleaned = original
    .replace(/[^\w\s.+%-]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();

  for (const row of COMPOUNDS) {
    if (row.test.test(cleaned)) {
      return row.out.length <= maxLen ? row.out : row.out.slice(0, maxLen).trim();
    }
  }

  const words = cleaned.split(" ").filter(Boolean);
  const noun = PRODUCT_NOUNS.find((n) => words.includes(n) || cleaned.includes(n));
  const modifiers = words.filter((w) => KEEP.has(w));

  // Build: useful modifiers + product noun (e.g. "wireless noise cancelling earbuds")
  const parts = [];
  for (const m of modifiers) {
    if (!parts.includes(m)) parts.push(m);
  }
  if (noun && !parts.includes(noun)) parts.push(noun);

  let built = parts.join(" ").trim();

  // Prefer "leather jacket" over bare "jacket"
  if (/\bleather\b/.test(cleaned) && /\bjacket\b/.test(cleaned) && !/\bleather jacket\b/.test(built)) {
    built = "leather jacket";
  }
  if (/\bwool\b/.test(cleaned) && /\bcoat\b/.test(cleaned) && !/\bwool coat\b/.test(built)) {
    built = "wool coat";
  }
  if (/\bpashmina\b/.test(cleaned) && /\bshawl\b/.test(cleaned) && !/\bpashmina shawl\b/.test(built)) {
    built = "pashmina shawl";
  }
  if (/\bleather\b/.test(cleaned) && /\bbag\b/.test(cleaned) && !/\bleather bag\b/.test(built)) {
    built = "leather bag";
  }
  if (
    /\bleather\b/.test(cleaned) &&
    /\b(cover|covers)\b/.test(cleaned) &&
    !/\bleather phone cover\b/.test(built)
  ) {
    built = "leather phone cover";
  }
  if (
    /\bleather\b/.test(cleaned) &&
    /\b(case|cases)\b/.test(cleaned) &&
    !/\b(cover|covers)\b/.test(cleaned) &&
    !/\bleather phone case\b/.test(built)
  ) {
    built = "leather phone case";
  }

  // Normalize common phrases
  built = built
    .replace(/\bnoise cancellation\b/g, "noise cancelling")
    .replace(/\bnoise canceling\b/g, "noise cancelling")
    .replace(/\btrue wireless\b/g, "wireless")
    .replace(/\bhand made\b/g, "handmade")
    .replace(/\s+/g, " ")
    .trim();

  if (built.length >= 6) {
    return built.length <= maxLen ? built : built.slice(0, maxLen).trim();
  }

  // Fallback: first clause, strip fluff words
  const head = original.split(/[,.;|]/)[0].trim();
  const fallbackWords = head
    .replace(/[^\w\s.+%-]/g, " ")
    .split(/\s+/)
    .filter((w) => {
      const lower = w.toLowerCase();
      if (STOP.has(lower)) return false;
      if (/^\d+\+?(h|hr|hrs|hours)?$/i.test(w)) return false;
      return w.length > 1;
    });

  let out = fallbackWords.join(" ").trim();
  if (!out) out = head || "product";
  if (out.length <= 3 && noun) out = noun;
  return out.length <= maxLen ? out : out.slice(0, maxLen).trim();
}

/**
 * 2–4 alternate search strings — organic-first (like a normal Google search),
 * then country / synonym / site:.pk passes for thin markets.
 */
export function buildSearchVariants(
  productName,
  { gl, currency, location, bulkMode = false, siteTldPass = null, countryHint: countryHintOpt = null } = {},
) {
  const base = shortenProductQuery(productName);
  const code = String(gl || "").toLowerCase();
  const cur = String(currency || "").toUpperCase();
  const place = String(location || "")
    .split(",")[0]
    .trim();
  const countryHint =
    countryHintOpt ||
    (code === "pk" ? "Pakistan" : code === "in" ? "India" : code === "uk" || code === "gb" ? "UK" : place || "");
  const raw = String(productName || "").toLowerCase();
  const wantsHandmade = /\bhandmade\b/i.test(raw) || /\bhandmade\b/i.test(base);

  const organic = wantsHandmade && !/\bhandmade\b/i.test(base)
    ? `handmade ${base}`.replace(/\s+/g, " ").trim()
    : base;

  const variants = [organic];

  const buyVariant = `buy ${organic}`.replace(/\s+/g, " ").trim();
  if (!variants.includes(buyVariant)) variants.push(buyVariant);

  if (bulkMode) {
    // Diversify site: probes — IndiaMART / DHgate / Made-in-China, not Alibaba-only
    for (const extra of [
      `${organic} wholesale`,
      `${organic} site:indiamart.com/proddetail`,
      `${organic} site:dhgate.com/product`,
      `${organic} site:made-in-china.com/product`,
      `${organic} site:alibaba.com/product-detail`,
    ]) {
      const q = extra.replace(/\s+/g, " ").trim();
      if (!variants.includes(q)) variants.push(q);
    }
  }

  // Wired audio: bias SerpApi toward jack/3.5mm product pages, not TWS
  if (/\bwired\b/i.test(organic) && /\b(handsfree|earphone|headphone|headset)\b/i.test(organic)) {
    for (const extra of [
      `${organic} 3.5mm`,
      `wired earphones 3.5mm wholesale`,
      `${organic} -wireless -tws -bluetooth`,
    ]) {
      const q = extra.replace(/\s+/g, " ").trim();
      if (!variants.includes(q)) variants.unshift(q);
    }
  }

  if (countryHint) {
    const withCountry = `${organic} ${countryHint}`.replace(/\s+/g, " ").trim();
    if (!variants.includes(withCountry)) variants.push(withCountry);
  }

  // Local TLD pass from RegionProfile (pk → site:.pk; uk → site:.co.uk)
  const siteTld =
    siteTldPass ||
    (code === "pk" ? ".pk" : code === "uk" || code === "gb" ? ".co.uk" : null);
  if (siteTld) {
    const siteQ = `${organic} site:${siteTld}`.replace(/\s+/g, " ").trim();
    if (!variants.includes(siteQ)) variants.push(siteQ);
  }

  // Synonym expansions (e.g. pashmina → kashmiri shawl)
  for (const syn of expandSearchSynonyms(productName, { max: bulkMode ? 3 : 2 })) {
    const synQ = wantsHandmade && !/\bhandmade\b/i.test(syn)
      ? `handmade ${syn}`
      : syn;
    if (!variants.some((v) => v.toLowerCase() === synQ.toLowerCase())) {
      variants.push(synQ);
    }
  }

  if (code !== "pk" && (cur === "PKR" || cur)) {
    const currencyToken =
      cur === "PKR" ? "Rs" : cur !== "USD" ? cur : "";
    const priced = [organic, "price", currencyToken, place].filter(Boolean).join(" ");
    if (priced && !variants.includes(priced)) variants.push(priced);
  }

  const seen = new Set();
  const out = [];
  const cap = bulkMode ? 4 : 7;
  for (const v of variants) {
    const key = v.toLowerCase();
    if (!v || seen.has(key)) continue;
    seen.add(key);
    out.push(v);
    if (out.length >= cap) break;
  }
  return out;
}

export function isTransientNetworkError(err) {
  const msg = String(err?.message || err?.error || err || "");
  return /ECONNRESET|ETIMEDOUT|ECONNREFUSED|ENOTFOUND|socket hang up|network|TLS|fetch failed|aborted|503|502|429/i.test(
    msg,
  );
}

export async function withRetries(fn, { retries = 3, delayMs = 700, label = "request" } = {}) {
  let lastErr;
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      return await fn(attempt);
    } catch (err) {
      lastErr = err;
      if (!isTransientNetworkError(err) || attempt === retries) break;
      const wait = delayMs * attempt;
      console.warn(
        `[retry] ${label} failed (${err?.message || err}); attempt ${attempt}/${retries}, wait ${wait}ms`,
      );
      await new Promise((r) => setTimeout(r, wait));
    }
  }
  throw lastErr;
}
