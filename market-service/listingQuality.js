/**
 * Quality gates for market listings — drop social junk, category pages, garbage prices.
 */

import { detectCurrency, expectedCurrencyForGl } from "./currency.js";
import { parsePriceNumber } from "./priceParse.js";

const BLOCKED_HOST_RE =
  /\b(instagram\.com|tiktok\.com|facebook\.com|fb\.com|youtube\.com|youtu\.be|x\.com|twitter\.com|threads\.net|pinterest\.com|reddit\.com|linkedin\.com|whatsapp\.com|t\.me|telegram\.|snapchat\.com)\b/i;

const LISTICLE_TITLE_RE =
  /\b(top\s+\d+|best\s+\d+|best .+ under\s+\d+|price list of|pakistan'?s?\s+best|vs\.?|compared?|unboxing|review|haul)\b/i;

const WEAK_TITLE_RE =
  /^(listing|olx(\s+listing)?|daraz(\s+listing)?|ad|photo|image|product|item|unknown|null|undefined|see listing)$/i;

function recoverTitleFromLink(row) {
  const title = String(row?.title || "").trim();
  if (title && !WEAK_TITLE_RE.test(title) && title.length >= 6) return null;
  const link = String(row?.link || "");
  const slug =
    link.match(/\/item\/([a-z0-9-]+)-iid-\d+/i)?.[1] ||
    link.match(/\/products\/([a-z0-9-]+)/i)?.[1] ||
    "";
  if (!slug) return null;
  const words = slug
    .replace(/-/g, " ")
    .replace(/\b\d+\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!words || WEAK_TITLE_RE.test(words) || words.length < 6) return null;
  return words.replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Hard anchors — listing must include these if present in the query. */
const HARD_MATCH_TERMS = [
  "leather",
  "suede",
  "denim",
  "wool",
  "cotton",
  "silk",
  "linen",
  "cashmere",
  "pashmina",
  "velvet",
  "fur",
  "wireless",
  "bluetooth",
  "anc",
  "iphone",
  "samsung",
  "macbook",
];

/** Soft terms — boost score if present, but do not hard-reject when missing. */
const SOFT_MATCH_TERMS = ["handmade", "shawl", "scarf", "stole", "dupatta", "bag", "jacket"];

/** Material / type words that must usually appear in a comparable listing title. */
const MUST_MATCH_TERMS = HARD_MATCH_TERMS;

/** If the query is about X, reject titles that clearly sell a different product type. */
const CONFLICT_PAIRS = [
  {
    required: /\bleather\b/i,
    reject: /\b(travel|rain|raincoat|puffer|parka|windbreaker|bomber|denim|varsity|track|sports?|gym|hoodie|blazer)\b/i,
    unless: /\bleather\b/i,
  },
  {
    required: /\b(earbuds?|earphones?|headphones?)\b/i,
    reject: /\b(speaker|soundbar|neckband|watch|phone|case only)\b/i,
    unless: /\b(earbud|earphone|headphone|tws|anc)\b/i,
  },
  // Phone/mobile covers must not match craft leather, vinyl LPs, games, etc.
  {
    required: /\b(cover|covers|case|cases|phone|mobile)\b/i,
    reject:
      /\b(tooling|crafting|craft\b|sheets?|hide\b|backgammon|vinyl|lp\b|album|games?\b|sports expert|fabricla|natural leather)\b/i,
    unless: /\b(phone|mobile|iphone|samsung|cover|covers|case|cases|flip|folio|protective)\b/i,
  },
];

/** When the query names a product type, listings must include that type family. */
const TYPE_REQUIREMENTS = [
  {
    when: /\b(cover|covers|case|cases)\b/i,
    // Accept common phone-case wording (case/cover/folio) OR phone model + leather accessory cues
    need: /\b(cover|covers|case|cases|phonecase|flip\s*cover|back\s*cover|folio|protective\s+case|iphone|samsung|pixel|magSafe|magsafe)\b/i,
  },
  {
    when: /\b(earbuds?|earphones?|headphones?)\b/i,
    need: /\b(earbud|earbuds|earphone|earphones|headphone|headphones|tws|anc)\b/i,
  },
  {
    when: /\bjacket\b/i,
    need: /\bjacket\b/i,
  },
];

export function queryTerms(query) {
  return String(query || "")
    .toLowerCase()
    .replace(/[^\w\s+-]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length > 2);
}

/**
 * Score how well a listing title matches the product the user is selling.
 * Returns null when the listing should be hard-rejected as the wrong product.
 */
function titleBlobForMatch(listing) {
  let title = String(listing.title || "").toLowerCase();
  const link = String(listing.link || "").toLowerCase();
  // Placeholder SERP/catalog titles — use OLX/Daraz slug as the real name signal
  if (/^(listing|olx(\s+listing)?|daraz(\s+listing)?|unknown|see listing)$/i.test(title.trim())) {
    const slug =
      link.match(/\/item\/([a-z0-9-]+)-iid-\d+/i)?.[1] ||
      link.match(/\/products\/([a-z0-9-]+)/i)?.[1] ||
      "";
    if (slug) title = slug.replace(/-/g, " ");
  }
  return { title, link, blob: `${title} ${link}` };
}

export function productMatchScore(listing, query) {
  const { title, link, blob } = titleBlobForMatch(listing);
  const q = String(query || "").toLowerCase();
  if (!q.trim()) return 0;

  for (const pair of CONFLICT_PAIRS) {
    if (pair.required.test(q) && pair.reject.test(blob) && !pair.unless.test(blob)) {
      return null; // hard reject — e.g. travel jacket for a leather jacket search
    }
  }

  for (const req of TYPE_REQUIREMENTS) {
    if (req.when.test(q) && !req.need.test(blob)) {
      return null; // e.g. "leather mobile covers" must not match craft leather sheets
    }
  }

  let score = 0;
  const terms = queryTerms(q);
  let hits = 0;
  for (const term of terms) {
    if (title.includes(term) || link.includes(term)) {
      hits += 1;
      score += term.length >= 6 ? 12 : 8;
    }
  }

  // Soften material hard-match for phone cases: titles often say "iPhone Case"
  // without repeating "leather" even when the Shopping query was leather phone cover.
  const phoneCaseQuery = /\b(cover|covers|case|cases)\b/i.test(q);
  for (const must of HARD_MATCH_TERMS) {
    if (new RegExp(`\\b${must}\\b`, "i").test(q)) {
      const inBlob = new RegExp(`\\b${must}\\b`, "i").test(blob);
      if (!inBlob) {
        if (must === "leather" && phoneCaseQuery && /\b(case|cover|iphone|samsung|pixel)\b/i.test(blob)) {
          score -= 8; // soft penalty, still allow
        } else {
          return null;
        }
      } else {
        score += 20;
      }
    }
  }
  for (const soft of SOFT_MATCH_TERMS) {
    if (new RegExp(`\\b${soft}\\b`, "i").test(q) && new RegExp(`\\b${soft}\\b`, "i").test(blob)) {
      score += 10;
    }
  }

  // Soft requirement: at least one meaningful query term should hit
  if (terms.length >= 2 && hits === 0) return null;
  // Craft/fashion: one strong hit is enough — unless this is a typed accessory (cover/case)
  const typedAccessory = /\b(cover|covers|case|cases|earbuds?|earphones?|headphones?|jacket)\b/i.test(q);
  const craftQuery =
    !typedAccessory && /\b(pashmina|shawl|scarf|handmade|cashmere|leather|silk|wool)\b/i.test(q);
  if (!craftQuery && terms.length >= 2 && hits < Math.min(2, terms.length)) score -= 15;
  if (craftQuery && hits >= 1) score += 5;
  if (typedAccessory && hits >= 2) score += 10;

  return score;
}

export function extractNumericPrice(price) {
  return parsePriceNumber(price);
}

/** Infer a sensible minimum for this currency/market so we drop 500 Rs noise on earbuds etc. */
export function minCrediblePrice(priceText, gl) {
  const text = String(priceText || "").toLowerCase();
  const code = String(gl || "").toLowerCase();
  if (/rs\.?|pkr/.test(text) || code === "pk") return 1000;
  if (/₹|inr/.test(text) || code === "in") return 400;
  if (/\$|usd/.test(text) || code === "us" || code === "ca") return 5;
  if (/£|gbp/.test(text) || code === "uk" || code === "gb") return 5;
  if (/€|eur/.test(text)) return 5;
  if (/aed/.test(text) || code === "ae") return 20;
  return 1;
}

export function isGarbagePrice(price, gl) {
  const text = String(price ?? "").trim();
  if (!text) return true;
  if (/^(rs\.?|pkr|usd|\$|£|€)[\s,.…]*$/i.test(text)) return true;
  if (!/\d/.test(text)) return true;
  const n = extractNumericPrice(text);
  if (n == null) return true;
  if (n < minCrediblePrice(text, gl)) return true;
  if (n > 50_000_000) return true;
  return false;
}

export function hostFromUrl(url) {
  try {
    return (new URL(url).hostname || "").toLowerCase();
  } catch {
    return "";
  }
}

export function isBlockedSocialHost(urlOrHost) {
  const host = urlOrHost.includes("/") ? hostFromUrl(urlOrHost) : String(urlOrHost || "");
  return BLOCKED_HOST_RE.test(host);
}

export function looksLikeCategoryOrSearchUrl(url) {
  const u = String(url || "").toLowerCase();
  if (!u) return true;
  if (/\/tag\//i.test(u)) return true;
  if (/[?&](q=|query=|search=)/i.test(u) && !/\/(product|item|dp|gp\/|mobiles\/[a-z0-9-]+\/[a-z0-9-]+)/i.test(u)) {
    return true;
  }
  if (/\/(category|categories)(\/|$)/i.test(u)) return true;
  // Brand collection hubs are OK if they still carry a usable price snippet
  if (/olx\.[a-z.]+\/.+_c\d+\/q-/i.test(u)) return true;
  return false;
}

export function listingQualityScore(listing, gl, query = "", preferredCurrency = null) {
  let score = 0;
  const link = String(listing.link || "");
  const title = String(listing.title || "");
  const price = listing.price;
  const expected = String(preferredCurrency || expectedCurrencyForGl(gl) || "").toUpperCase();
  const detected = detectCurrency(price);

  if (isBlockedSocialHost(link) || isBlockedSocialHost(listing.vendor || "")) return -100;
  if (LISTICLE_TITLE_RE.test(title)) score -= 25;
  if (looksLikeCategoryOrSearchUrl(link)) score -= 40;
  else score += 20;

  if (isGarbagePrice(price, gl)) {
    // Local shops often lack snippet prices — keep them for page enrich instead of burying them
    if (isLocalMarketHost(link, gl)) score -= 5;
    else score -= 50;
  } else {
    score += 30;
    if (listing.price_source === "page") score += 15;
  }

  // Prefer prices already in the seller's local currency (e.g. PKR for Pakistan)
  if (expected && detected) {
    if (detected === expected) score += 25;
    else score -= 35;
  }

  if (/daraz\.|olx\.|priceoye|amazon\.|bestbuy|walmart|flipkart|noon\.|argos|charcoal\./i.test(link)) score += 10;
  if (isLocalMarketHost(link, gl)) score += 12;
  if (/verified/i.test(String(listing.vendor_status || ""))) score += 5;

  const match = productMatchScore(listing, query);
  if (match == null) return -100;
  score += match;

  return score;
}

export function isLocalMarketHost(urlOrHost, gl) {
  const link = String(urlOrHost || "").toLowerCase();
  const code = String(gl || "").toLowerCase();
  if (code === "pk") {
    return (
      /\.pk(\/|$)/i.test(link) ||
      /daraz\.|olx\.|priceoye\.|homeshopping\.|telemart\.|shophive\.|mega\.pk|symbios\./i.test(link)
    );
  }
  if (code === "in") {
    return /amazon\.in|flipkart\.|indiamart\.|\.in(\/|$)/i.test(link);
  }
  return /amazon\.|ebay\.|walmart\.|bestbuy\.|noon\./i.test(link);
}

/**
 * Drop junk, keep strongest comparable seller prices.
 * Prefer local-currency comps; keep foreign ones only as a fallback.
 * Local hosts without a snippet price are kept so page enrichment can read PKR later.
 */
export function filterAndRankListings(listings, { gl, limit = 8, query = "", preferredCurrency = null } = {}) {
  const expected = String(preferredCurrency || expectedCurrencyForGl(gl) || "").toUpperCase();
  const baseOk = (row) => {
    if (!row) return false;
    const link = String(row.link || "");
    const vendor = String(row.vendor || "");
    if (isBlockedSocialHost(link) || isBlockedSocialHost(vendor)) return false;
    if (/instagram|tiktok|facebook|youtube/i.test(vendor)) return false;
    if (/\/tag\//i.test(link)) return false;
    if (LISTICLE_TITLE_RE.test(String(row.title || ""))) return false;
    // Recover placeholder titles from marketplace URL slugs before match/display
    const recovered = recoverTitleFromLink(row);
    if (recovered) row.title = recovered;
    if (productMatchScore(row, query) == null) return false;
    if (isGarbagePrice(row.price, gl)) {
      // Keep local / known shop links with weak prices for page scrape
      if (
        isLocalMarketHost(link, gl) ||
        /priceoye\.|daraz\.|olx\.|amazon\.|flipkart\.|telemart\.|shophive\.|homeshopping\.|charcoal\./i.test(link)
      ) {
        return true;
      }
      return false;
    }
    return true;
  };

  const cleaned = (listings || [])
    .filter(baseOk)
    .map((row) => ({
      ...row,
      _score: listingQualityScore(row, gl, query, preferredCurrency),
    }))
    .filter((row) => row._score > -80)
    .sort((a, b) => b._score - a._score);

  const localCurrency = expected
    ? cleaned.filter((row) => {
        const cur = detectCurrency(row.price);
        return !cur || cur === expected;
      })
    : cleaned;
  const prefer = (localCurrency.length ? localCurrency : cleaned).filter((row) => row._score > -30);
  const pool = prefer.length ? prefer : localCurrency.length ? localCurrency : cleaned;

  const seen = new Set();
  const deduped = [];
  for (const row of pool) {
    const rawLink = String(row.link || "").trim().toLowerCase();
    const isGoogleShop =
      /google\.[^/\s]+\/search/i.test(rawLink) &&
      /(?:[?&](?:ibp=oshop|tbm=shop)|\/shopping\/)/i.test(rawLink);
    const link = isGoogleShop ? "" : rawLink.replace(/[?#].*$/, "");
    const key = isGoogleShop
      ? `offer:${String(row.vendor || "").toLowerCase().slice(0, 40)}|${String(row.title || "")
          .toLowerCase()
          .slice(0, 60)}|${String(row.price || "").toLowerCase()}`
      : link ||
        `${String(row.vendor || "").toLowerCase()}|${String(row.title || "").toLowerCase().slice(0, 60)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const { _score, ...rest } = row;
    deduped.push(rest);
    if (deduped.length >= limit) break;
  }

  // If we only kept foreign-currency rows, still return them (thin market) but caller will annotate.
  if (deduped.length) {
    const nums = deduped
      .map((row) => extractNumericPrice(row.price))
      .filter((n) => n != null && n > 0)
      .sort((a, b) => a - b);
    // Only outlier-filter within the same currency family
    const sameCurrencyNums = deduped
      .map((row) => {
        const cur = detectCurrency(row.price);
        if (expected && cur && cur !== expected) return null;
        return extractNumericPrice(row.price);
      })
      .filter((n) => n != null && n > 0)
      .sort((a, b) => a - b);
    const basis = sameCurrencyNums.length >= 3 ? sameCurrencyNums : nums;
    if (basis.length >= 3) {
      const mid = basis[Math.floor(basis.length / 2)];
      const filtered = deduped.filter((row) => {
        const cur = detectCurrency(row.price);
        if (expected && cur && cur !== expected) return true; // keep foreign as secondary
        const n = extractNumericPrice(row.price);
        if (n == null) return true;
        return n >= mid * 0.25 && n <= mid * 3.5;
      });
      if (filtered.length >= 2) return filtered.slice(0, limit);
    }
    return deduped;
  }

  // Last resort: still require product match when we have a query
  return (listings || [])
    .filter((row) => {
      if (!row) return false;
      if (isBlockedSocialHost(row.link) || isBlockedSocialHost(row.vendor || "")) return false;
      if (/\/tag\//i.test(String(row.link || ""))) return false;
      if (query && productMatchScore(row, query) == null) return false;
      const n = extractNumericPrice(row.price);
      if (n != null && n >= 500) return true;
      const link = String(row.link || "").toLowerCase();
      return /priceoye\.|daraz\.|olx\.|amazon\.|flipkart\.|telemart\.|shophive\.|charcoal\./i.test(link)
        && /^https?:\/\//i.test(link);
    })
    .slice(0, limit);
}
