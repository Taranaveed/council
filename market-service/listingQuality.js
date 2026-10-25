/**
 * Quality gates for market listings — drop social junk, category pages, garbage prices.
 */

import { detectCurrency, expectedCurrencyForGl } from "./currency.js";
import { parsePriceNumber } from "./priceParse.js";
import { isProductDetailUrl, isStorefrontOrHomepage } from "./listingTiers.js";

const BLOCKED_HOST_RE =
  /\b(instagram\.com|tiktok\.com|facebook\.com|fb\.com|youtube\.com|youtu\.be|x\.com|twitter\.com|threads\.net|pinterest\.com|reddit\.com|linkedin\.com|whatsapp\.com|t\.me|telegram\.|snapchat\.com)\b/i;

const LISTICLE_TITLE_RE =
  /\b(top\s+\d+|best\s+\d+|best .+ under\s+\d+|price list of|pakistan'?s?\s+best|vs\.?|compared?|unboxing|review|haul)\b/i;

const JUNK_TITLE_RE =
  /^(videos?\s+about\b)|(\d+\s+wholesale\s+(?:["']?.+["']?\s+)?suppliers?\b)|(\bsuppliers?\s+&\s+manufacturers?\b)|(\bwhat\s+is\b.+\b(body|mist|spray|perfume)\b)/i;

const ENTERTAINMENT_HOST_RE =
  /\b(youtube\.com|youtu\.be|imdb\.com|spotify\.com|soundcloud\.com|barenakedladies\.com|ladieseuropeantour\.com|dinnerladies\.com|fitflop\.com|vimeo\.com|rottentomatoes\.com|pinterest\.com|wikipedia\.org|unwomen\.org|sciencedirect\.com|flickr\.com)\b/i;

const ENTERTAINMENT_TITLE_RE =
  /\b(put a ring on it|single ladies|barenaked|music video|official video|imdb|podcast|meal delivery|european tour|footwear|film\b|movie\b|album\b)\b/i;

const THIN_CATEGORY_TITLE_RE =
  /^(wholesale\s+)?body\s+mists?(\s+price)?$|^(body\s+mist|body\s+spray|perfume)\s+price$/i;

const WEAK_TITLE_RE =
  /^(listing|olx(\s+listing)?|daraz(\s+listing)?|ad|photo|image|product|item|unknown|null|undefined|see listing)$/i;

function slugToTitle(slug) {
  const words = String(slug || "")
    .replace(/-/g, " ")
    .replace(/(\d+(?:\.\d+)?\s*mm)(?=\d)/gi, "$1 ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\d+\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!words || WEAK_TITLE_RE.test(words) || words.length < 6) return null;
  return words.replace(/\b\w/g, (c) => c.toUpperCase());
}

export function tidyListingTitle(title) {
  let t = String(title || "").trim();
  if (!t) return t;
  t = t.replace(/(\d+(?:\.\d+)?\s*mm)(?=\d)/gi, "$1 ");
  t = t.replace(/([a-z])([A-Z])/g, "$1 $2");
  t = t.replace(/\s+/g, " ").trim();
  return t;
}

function recoverTitleFromLink(row) {
  const title = String(row?.title || "").trim();
  if (title && !WEAK_TITLE_RE.test(title) && title.length >= 6) return null;
  const link = String(row?.link || "");
  const slug =
    link.match(/\/item\/([a-z0-9-]+)-iid-\d+/i)?.[1] ||
    link.match(/\/products\/([a-z0-9-]+)/i)?.[1] ||
    link.match(/alibaba\.com\/product-detail\/([a-z0-9-]+)[_-]\d+/i)?.[1] ||
    link.match(/amazon\.[^/]+\/([a-z0-9-]{6,})\/dp\//i)?.[1] ||
    link.match(/\/itm\/([a-z0-9-]+)/i)?.[1] ||
    link.match(/flipkart\.com\/[^/]+\/[^/]+\/p\/([a-z0-9-]+)/i)?.[1] ||
    link.match(/\/p\/([a-z0-9-]{8,})/i)?.[1] ||
    "";
  return slugToTitle(slug);
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
    required: /\b(earbuds?|earphones?|headphones?|hands?\s*-?\s*frees?|handsfrees?)\b/i,
    reject:
      /\b(scanner|barcode|sink|marble|pedestal|dildo|sex\s*toy|crystal|blown|archives?|hand\s*carved|hand\s*blown)\b/i,
    unless: /\b(earbud|earphone|headphone|tws|anc|headset|earpiece)\b/i,
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
  // USB / wall adapters must not match phones, trucks, random "mobile" SKUs
  {
    required: /\b(adapter|adapters|charger|otg|usb)\b/i,
    reject:
      /\b(smartphone|mobile\s+phone|cell\s+phone|android\s+phone|global\s+version|food\s*truck|street\s*truck|drivable\s+mobile|bakery|16\s*g\+|1\s*tb)\b/i,
    unless: /\b(adapter|charger|otg|usb|dongle|hub|wall\s*plug|cable)\b/i,
  },
  // Wired handsfree / earphones must not match Bluetooth TWS / earbuds
  {
    required: /\bwired\b/i,
    reject: /\b(wireless|bluetooth|tws|true\s*wireless|earbuds?)\b/i,
    unless: /\bwired\b|\b3\.5\s*mm\b|\baux\b/i,
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
    when: /\b(earbuds?|earphones?|headphones?|hands?\s*-?\s*frees?|handsfrees?)\b/i,
    need: /\b(earbud|earbuds|earphone|earphones|headphone|headphones|hands?\s*-?\s*free|handsfree|tws|anc|headset|earpiece)\b/i,
  },
  {
    when: /\b(adapter|adapters|charger|otg)\b/i,
    need: /\b(adapter|adapters|charger|otg|usb|dongle|hub|wall\s*plug|power\s*adapter|plug\s*adapter)\b/i,
  },
  {
    when: /\b(rings?|jewellery|jewelry|necklace|bracelet|earring)\b/i,
    need: /\b(ring|rings|jewellery|jewelry|jewel|necklace|bracelet|earring|earrings|925|silver|gold|zircon|cubic)\b/i,
  },
  {
    when: /\bjacket\b/i,
    need: /\bjacket\b/i,
  },
];

/**
 * Normalize shopper typos / shorthand so matching and search agree
 * ("hand frees" → handsfree earphones).
 */
export function normalizeShopQuery(query) {
  let q = String(query || "").trim();
  if (!q) return q;
  q = q.replace(/\bhand[\s-]*frees?\b/gi, "handsfree");
  q = q.replace(/\bhands[\s-]*frees?\b/gi, "handsfree");
  q = q.replace(/\bhandsfrees?\b/gi, "handsfree");
  // Bare "handsfree" without audio product words → earphones intent
  if (/\bhandsfree\b/i.test(q) && !/\b(earbud|earphone|headphone|headset|tws|bluetooth|wired|wireless)\b/i.test(q)) {
    q = `${q} earphones`;
  }
  // Wired handsfree → keep wired + add earphones/3.5mm so search doesn't drift to TWS
  if (/\bwired\b/i.test(q) && /\bhandsfree\b/i.test(q)) {
    if (!/\b(earphone|headphone|headset)\b/i.test(q)) {
      q = `${q} earphones`;
    }
    if (!/\b3\.5\b/i.test(q)) {
      q = `${q} 3.5mm`;
    }
  }
  // Ladies/women rings → jewelry intent (not entertainment SERP)
  if (
    /\b(ladies?|womens?|women'?s?)\b/i.test(q) &&
    /\brings?\b/i.test(q) &&
    !/\b(jewel|jewellery|jewelry|finger|silver|gold|zircon)\b/i.test(q)
  ) {
    q = q.replace(/\bladies?\b/gi, "women").replace(/\brings?\b/i, "jewelry finger rings");
  }
  return q.replace(/\s+/g, " ").trim();
}

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
      link.match(/alibaba\.com\/product-detail\/([a-z0-9-]+)[_-]\d+/i)?.[1] ||
      link.match(/amazon\.[^/]+\/([a-z0-9-]{6,})\/dp\//i)?.[1] ||
      link.match(/\/itm\/([a-z0-9-]+)/i)?.[1] ||
      "";
    if (slug) title = slug.replace(/-/g, " ");
  }
  return { title, link, blob: `${title} ${link}` };
}

/** Soften brand hard-match for phone accessories (case/cover/cable/…). */
const BRAND_SOFT_FOR_ACCESSORY = new Set(["iphone", "samsung", "macbook"]);
const ACCESSORY_QUERY_RE =
  /\b(cover|covers|case|cases|cable|cables|charger|chargers|adapter|adapters|screen\s*protector|tempered\s*glass|folio|flip)\b/i;
const ACCESSORY_BLOB_OK_RE =
  /\b(cover|covers|case|cases|phonecase|phone\s*case|mobile\s*cover|flip|folio|protective|silicone|tpu|tempered|protector|cable|charger|adapter|iphone|samsung|pixel|huawei|xiaomi|oppo|vivo|oneplus)\b/i;

export function productMatchScore(listing, query) {
  const { title, link, blob } = titleBlobForMatch(listing);
  const q = normalizeShopQuery(query).toLowerCase();
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
  const phoneCaseQuery = ACCESSORY_QUERY_RE.test(q);
  for (const must of HARD_MATCH_TERMS) {
    if (new RegExp(`\\b${must}\\b`, "i").test(q)) {
      const inBlob = new RegExp(`\\b${must}\\b`, "i").test(blob);
      if (!inBlob) {
        if (must === "leather" && phoneCaseQuery && /\b(case|cover|iphone|samsung|pixel)\b/i.test(blob)) {
          score -= 8; // soft penalty, still allow
        } else if (
          BRAND_SOFT_FOR_ACCESSORY.has(must) &&
          phoneCaseQuery &&
          ACCESSORY_BLOB_OK_RE.test(blob)
        ) {
          // "iphone mobile covers" may match "Phone Case Soft TPU" / "Mobile Cover" URLs
          score -= 6;
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
  if (terms.length >= 2 && hits === 0) {
    // Accessory queries: URL/slug often has cover/case even when title is thin
    if (!(phoneCaseQuery && ACCESSORY_BLOB_OK_RE.test(blob))) {
      return null;
    }
    score -= 10;
  }
  // Craft/fashion: one strong hit is enough — unless this is a typed accessory (cover/case)
  const typedAccessory =
    /\b(cover|covers|case|cases|earbuds?|earphones?|headphones?|handsfree|jacket)\b/i.test(q);
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
export function minCrediblePrice(priceText, gl, { bulkMode = false } = {}) {
  const text = String(priceText || "").toLowerCase();
  const code = String(gl || "").toLowerCase();
  // Prefer currency markers on the price string over buyer country floors
  // (so INR 80 on IndiaMART isn't judged against a PKR retail minimum).
  if (/\$|usd/.test(text)) return bulkMode ? 0.05 : 5;
  if (/£|gbp/.test(text)) return bulkMode ? 0.05 : 5;
  if (/€|eur/.test(text)) return bulkMode ? 0.05 : 5;
  if (/₹|inr/.test(text)) return bulkMode ? 20 : 400;
  if (/rs\.?|pkr/.test(text)) return bulkMode ? 150 : 1000;
  if (/aed/.test(text)) return bulkMode ? 5 : 20;
  // No marker — use buyer market floors
  if (code === "us" || code === "ca") return bulkMode ? 0.05 : 5;
  if (code === "uk" || code === "gb") return bulkMode ? 0.05 : 5;
  // PKR "Rs 1"–"Rs 20" are almost always scrape junk (currency label + digit), not real retail.
  if (code === "pk") return bulkMode ? 150 : 1000;
  if (code === "in") return bulkMode ? 50 : 400;
  if (code === "ae") return bulkMode ? 5 : 20;
  return bulkMode ? 0.05 : 1;
}

export function isGarbagePrice(price, gl, { bulkMode = false, link = "" } = {}) {
  const text = String(price ?? "").trim();
  if (!text) return true;
  if (/^(rs\.?|pkr|usd|\$|£|€|inr|₹)[\s,.…]*$/i.test(text)) return true;
  if (/^(see\s+listing|n\/?a|na|null|undefined)$/i.test(text)) return true;
  if (!/\d/.test(text)) return true;
  const n = extractNumericPrice(text);
  if (n == null) return true;
  // Mis-tagged factory quotes: "Rs 4" on Alibaba is almost never real PKR.
  if (
    /alibaba\.|dhgate\.|made-in-china\.|globalsources\.|aliexpress\./i.test(String(link || "")) &&
    /rs\.?|pkr/i.test(text) &&
    n < 100
  ) {
    return true;
  }
  if (n < minCrediblePrice(text, gl, { bulkMode })) return true;
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
  if (/alibaba\.com\/product-detail\//i.test(u)) return false;
  if (/indiamart\.com\/(proddetail|product)/i.test(u)) return false;
  if (/tradeindia\.com\/products\//i.test(u)) return false;
  if (/made-in-china\.com\/.+(product|item)/i.test(u)) return false;
  if (/made-in-china\.com\/product\//i.test(u)) return false;
  if (/dhgate\.com\/product\//i.test(u)) return false;
  if (/aliexpress\.com\/item\//i.test(u)) return false;
  if (/faire\.com\/product/i.test(u)) return false;
  if (/globalsources\.com\/.*(product|si\/|gsol)/i.test(u)) return false;
  if (/alibaba\.com\/(trade\/search|catalog|wholesale|premium|showroom)/i.test(u)) return true;
  if (/indiamart\.com\/(impcat|city|search\.php|india\/)/i.test(u)) return true;
  if (/globalsources\.com\/(suppliers|manufacturers|search|gsol\/supplier)/i.test(u)) return true;
  if (/made-in-china\.com\/(manufacturers|videos?|video)\b/i.test(u)) return true;
  if (/\/(archives?|category|categories|catalog|wholesale|showroom|tag)(\/|$)/i.test(u)) return true;
  if (/\/tag\//i.test(u)) return true;
  if (/[?&](q=|query=|search=)/i.test(u) && !/\/(product|item|dp|gp\/|mobiles\/[a-z0-9-]+\/[a-z0-9-]+)/i.test(u)) {
    return true;
  }
  if (/\/(category|categories|catalog|wholesale|showroom|archives?)(\/|$)/i.test(u)) return true;
  // Brand collection hubs are OK if they still carry a usable price snippet
  if (/olx\.[a-z.]+\/.+_c\d+\/q-/i.test(u)) return true;
  return false;
}

export function isWholesaleHost(urlOrHost) {
  return /alibaba\.|indiamart\.|made-in-china\.|tradeindia\.|dhgate\.|globalsources\.|aliexpress\.|europages\.|thomasnet\.|faire\./i.test(
    String(urlOrHost || ""),
  );
}

export function listingQualityScore(
  listing,
  gl,
  query = "",
  preferredCurrency = null,
  { bulkMode = false, profile = null } = {},
) {
  let score = 0;
  const link = String(listing.link || "");
  const title = String(listing.title || "");
  const price = listing.price;
  const expected = String(
    preferredCurrency || expectedCurrencyForGl(gl, profile) || "",
  ).toUpperCase();
  const detected = detectCurrency(price);
  const wholesale = isWholesaleHost(link) || Boolean(listing.wholesale);

  if (isBlockedSocialHost(link) || isBlockedSocialHost(listing.vendor || "")) return -100;
  if (LISTICLE_TITLE_RE.test(title) || JUNK_TITLE_RE.test(title) || THIN_CATEGORY_TITLE_RE.test(title)) {
    score -= 25;
  }
  if (looksLikeCategoryOrSearchUrl(link)) score -= 40;
  else score += 20;

  if (isGarbagePrice(price, gl, { bulkMode, link }) && !(wholesale && /\d/.test(String(price || "")) && !/rs\.?|pkr/i.test(String(price || "")))) {
    // Local shops often lack snippet prices — keep them for page enrich instead of burying them
    if (isLocalMarketHost(link, gl, profile) || wholesale) score -= 5;
    else score -= 50;
  } else {
    score += 30;
    if (listing.price_source === "page") score += 15;
  }

  // Prefer prices already in the buyer's local currency
  if (expected && detected) {
    if (detected === expected) score += 40;
    else if (bulkMode && wholesale) {
      score += 8; // foreign factory quote — keep, but below local
      if (detected === "INR" && expected === "PKR") score += 10; // nearby region
      if (detected === "USD") score += 4;
    } else score -= 35;
  }

  if (/daraz\.|olx\.|priceoye|amazon\.|bestbuy|walmart|flipkart|noon\.|argos|charcoal\.|target\.|costco|ebay\.|laam\.|tjwholesale\.|abwholesale\.|imwholesale\.|meerzah\./i.test(link)) {
    score += 10;
  }
  if (/indiamart\.|tradeindia\.|dhgate\./i.test(link)) {
    score += bulkMode ? 22 : 8;
  }
  if (/alibaba\.|made-in-china\.|globalsources\.|aliexpress\.|faire\.|thomasnet\.|europages\./i.test(link)) {
    score += bulkMode ? 14 : 8;
  }
  if (isLocalMarketHost(link, gl, profile) && !bulkMode) score += 28;
  // Same-country first for bulk too — local wholesale/retail before foreign factories
  if (isLocalMarketHost(link, gl, profile) && bulkMode) score += 36;
  if (wholesale && !isLocalMarketHost(link, gl, profile) && bulkMode) score -= 6;
  if (/verified|known marketplace/i.test(String(listing.vendor_status || ""))) score += 5;

  const match = productMatchScore(listing, query);
  if (match == null) return -100;
  score += match;

  return score;
}

export function isLocalMarketHost(urlOrHost, gl, profile = null) {
  const link = String(urlOrHost || "").toLowerCase();
  const code = String(gl || "").toLowerCase();
  // Prefer RegionProfile.local_host_patterns when provided (Phase 1)
  const parts = profile?.local_host_patterns?.filter(Boolean);
  if (parts?.length) {
    return new RegExp(parts.map((p) => `(?:${p})`).join("|"), "i").test(link);
  }
  if (code === "pk") {
    // Golden PK host list — must match shared/region_profiles/pk.json
    return (
      /\.pk(\/|$)/i.test(link) ||
      /daraz\.|olx\.|priceoye\.|homeshopping\.|telemart\.|shophive\.|mega\.pk|symbios\.|tjwholesale\.|abwholesale\.|imwholesale\.|meerzah\.|laam\./i.test(
        link,
      )
    );
  }
  if (code === "in") {
    return /amazon\.in|flipkart\.|indiamart\.|meesho\.|tradeindia\.|\.in(\/|$)/i.test(link);
  }
  if (code === "us") {
    return /amazon\.com(?!\.)|walmart\.|bestbuy\.com|target\.|costco\.|ebay\.com(?!\.)|thomasnet\.|faire\./i.test(
      link,
    );
  }
  if (code === "ca") {
    return /amazon\.ca|bestbuy\.ca|walmart\.ca|ebay\.ca|\.ca(\/|$)/i.test(link);
  }
  if (code === "uk" || code === "gb") {
    return /amazon\.co\.uk|ebay\.co\.uk|argos\.|johnlewis\.|currys\.|ao\.com|tesco\.|sainsbury\.|diy\.com|screwfix\.|toolstation\.|europages\.|\.co\.uk(\/|$)/i.test(
      link,
    );
  }
  if (code === "ae") {
    return /amazon\.ae|noon\.com|namshi\./i.test(link);
  }
  return /amazon\.|ebay\.|walmart\.|bestbuy\.|noon\./i.test(link);
}

/**
 * Drop junk, keep strongest comparable seller prices.
 * Prefer local-currency comps; keep foreign ones only as a fallback.
 * Local hosts without a snippet price are kept so page enrichment can read PKR later.
 */
function hostCapFor(host, bulkMode) {
  // Cap per host so one factory marketplace cannot dominate the seller list
  if (/alibaba\.com/i.test(host)) return bulkMode ? 3 : 3;
  if (/made-in-china\./i.test(host)) return bulkMode ? 3 : 2;
  if (/indiamart\.|tradeindia\.|dhgate\.|globalsources\.|aliexpress\.|faire\.|thomasnet\.|europages\./i.test(host)) {
    return bulkMode ? 4 : 2;
  }
  return 2;
}

/**
 * Mix live same-country listings with reasonable foreign options.
 * Guarantees foreign slots when imports exist (never local-only when foreign comps are available).
 */
export function mixLocalAndForeign(rankedRows, { gl, limit = 8, bulkMode = false, profile = null } = {}) {
  const rows = rankedRows || [];
  if (!rows.length) return [];

  const isLocal = (row) => isLocalMarketHost(row.link, gl, profile);
  const local = rows.filter(isLocal);
  const foreign = rows.filter((row) => !isLocal(row));

  let foreignSlots;
  let localSlots;
  if (bulkMode) {
    foreignSlots = Math.min(Math.max(3, Math.ceil(limit * 0.4)), Math.max(0, limit - 2));
    localSlots = Math.max(2, limit - foreignSlots);
  } else {
    foreignSlots = Math.min(Math.max(2, Math.ceil(limit * 0.3)), Math.max(0, limit - 3));
    localSlots = Math.max(3, limit - foreignSlots);
  }

  if (local.length < localSlots) {
    foreignSlots = Math.min(foreign.length, limit - local.length);
    localSlots = local.length;
  }
  if (foreign.length < foreignSlots) {
    localSlots = Math.min(local.length, limit - foreign.length);
    foreignSlots = foreign.length;
  }

  const take = (source, max, seen, seenHosts) => {
    const out = [];
    for (const row of source) {
      if (out.length >= max) break;
      const rawLink = String(row.link || "").trim().toLowerCase();
      const isGoogleShop =
        /google\.[^/\s]+\/search/i.test(rawLink) &&
        /(?:[?&](?:ibp=oshop|tbm=shop)|\/shopping\/)/i.test(rawLink);
      const link = isGoogleShop ? "" : rawLink.replace(/[?#].*$/, "");
      const host = hostFromUrl(link || rawLink);
      const titleKey = String(row.title || "")
        .toLowerCase()
        .replace(/[^\w\s]/g, " ")
        .slice(0, 48);
      const key = isGoogleShop
        ? `offer:${String(row.vendor || "").toLowerCase().slice(0, 40)}|${titleKey}|${String(row.price || "").toLowerCase()}`
        : link || `${String(row.vendor || "").toLowerCase()}|${titleKey}`;
      if (seen.has(key)) continue;
      const hostCount = seenHosts.get(host) || 0;
      if (host && hostCount >= hostCapFor(host, bulkMode) && !isGoogleShop) continue;
      seen.add(key);
      if (host) seenHosts.set(host, hostCount + 1);
      const { _score, ...rest } = row;
      out.push(rest);
    }
    return out;
  };

  const seen = new Set();
  const seenHosts = new Map();
  const localPick = take(local, localSlots, seen, seenHosts);
  const foreignPick = take(foreign, foreignSlots, seen, seenHosts);

  // Fill leftover capacity from either side
  const leftover = take(rows, Math.max(0, limit - localPick.length - foreignPick.length), seen, seenHosts);
  return [...localPick, ...foreignPick, ...leftover].slice(0, limit);
}

export function filterAndRankListings(
  listings,
  { gl, limit = 8, query = "", preferredCurrency = null, bulkMode = false, profile = null } = {},
) {
  const expected = String(
    preferredCurrency || expectedCurrencyForGl(gl, profile) || "",
  ).toUpperCase();
  const baseOk = (row) => {
    if (!row) return false;
    const link = String(row.link || "");
    const vendor = String(row.vendor || "");
    const title = String(row.title || "");
    if (isBlockedSocialHost(link) || isBlockedSocialHost(vendor)) return false;
    if (ENTERTAINMENT_HOST_RE.test(link) || ENTERTAINMENT_HOST_RE.test(vendor)) return false;
    if (/instagram|tiktok|facebook|youtube/i.test(vendor)) return false;
    if (/\/tag\//i.test(link)) return false;
    if (LISTICLE_TITLE_RE.test(title)) return false;
    if (JUNK_TITLE_RE.test(title)) return false;
    if (ENTERTAINMENT_TITLE_RE.test(title)) return false;
    if (THIN_CATEGORY_TITLE_RE.test(title)) return false;
    if (looksLikeCategoryOrSearchUrl(link)) return false;
    if (isStorefrontOrHomepage(link)) return false;
    // Title that is clearly a storefront banner, not a SKU
    if (/jewelry\s*&\s*bags|big discounts|archives?\b|shop\s+all/i.test(title)) return false;
    // Bulk wholesale: prefer product-detail pages with a parseable unit price.
    // Unpriced product pages are kept as "See listing" so a thin Serp snippet
    // does not wipe an otherwise valid Alibaba/IndiaMART result set.
    if (bulkMode && isWholesaleHost(link)) {
      if (!isProductDetailUrl(link)) return false;
      const hasPrice =
        Boolean(row.has_price_tier) ||
        (Array.isArray(row.price_tiers) && row.price_tiers.length > 0) ||
        (/\d/.test(String(row.price || "")) &&
          !/^(see listing|n\/?a)/i.test(String(row.price || "")) &&
          !/^(rs\.?|pkr|usd|\$|£|€|inr|₹)[\s,.…]*$/i.test(String(row.price || "").trim()));
      if (!hasPrice) {
        row.price = "See listing";
        row.price_source = row.price_source || "snippet_missing";
        row.needs_price_confirm = true;
      }
      const hasMoq =
        Boolean(row.has_moq) ||
        (row.moq != null && Number(row.moq) > 0) ||
        (Array.isArray(row.price_tiers) && row.price_tiers.some((t) => Number(t?.min_qty) > 1));
      if (!hasMoq) {
        row.moq = null;
        row.moq_source = row.moq_source || "not_on_snippet";
        row.has_moq = false;
        row.moq_display = "MOQ not confirmed — verify on seller page";
      }
    }
    // Recover placeholder titles from marketplace URL slugs before match/display
    const recovered = recoverTitleFromLink(row);
    if (recovered) row.title = recovered;
    row.title = tidyListingTitle(row.title);
    if (productMatchScore(row, query) == null) return false;
      if (isGarbagePrice(row.price, gl, { bulkMode, link })) {
      const currencyOnly = /^(rs\.?|pkr|usd|\$|£|€|inr|₹)[\s,.…]*$/i.test(String(row.price || "").trim());
      // Never keep bare "rs." / "rs," — show See listing or drop
      if (currencyOnly || !/\d/.test(String(row.price || ""))) {
        // Bulk wholesale product page without digits — keep for seller link review
        if (bulkMode && isWholesaleHost(link) && isProductDetailUrl(link)) {
          row.price = "See listing";
          row.needs_price_confirm = true;
          return true;
        }
        // Absurd PKR stubs on local shops (Rs 1) — drop, don't keep as See listing
        if (isLocalMarketHost(link, gl, profile)) return false;
        if (isWholesaleHost(link) && !looksLikeCategoryOrSearchUrl(link)) {
          row.price = "See listing";
          return true;
        }
        return false;
      }
      // Digits present but below retail min — keep only credible factory USD quotes
      if (bulkMode && isWholesaleHost(link) && !/rs\.?|pkr/i.test(String(row.price || ""))) {
        return true;
      }
      if (
        isLocalMarketHost(link, gl, profile) ||
        /priceoye\.|daraz\.|olx\.|amazon\.|flipkart\.|telemart\.|shophive\.|homeshopping\.|charcoal\./i.test(link)
      ) {
        // Local Rs 1–149 is noise
        return false;
      }
      return false;
    }
    return true;
  };

  const cleaned = (listings || [])
    .filter(baseOk)
    .map((row) => ({
      ...row,
      _score: listingQualityScore(row, gl, query, preferredCurrency, { bulkMode, profile }),
    }))
    .filter((row) => row._score > -80)
    .sort((a, b) => b._score - a._score);

  const localCurrency = expected
    ? cleaned.filter((row) => {
        const cur = detectCurrency(row.price);
        return !cur || cur === expected;
      })
    : cleaned;
  // Same-country first, but keep foreign in the ranked pool for mixLocalAndForeign
  let basePool;
  if (bulkMode) {
    // Score-sorted cleaned already prefers local via listingQualityScore boosts
    basePool = cleaned;
  } else {
    // Retail: local-currency first, then foreign as secondary lane (do not drop imports)
    if (localCurrency.length) {
      const rest = cleaned.filter((r) => !localCurrency.includes(r));
      basePool = [...localCurrency, ...rest];
    } else {
      basePool = cleaned;
    }
  }
  const strong = basePool.filter((row) => row._score > -30);
  const goodEnough = basePool.filter((row) => row._score > -55 && row._score <= -30);
  const pool = [...strong, ...goodEnough];
  const ranked =
    pool.length >= Math.min(3, limit) ? pool : basePool.length ? basePool : cleaned;

  let deduped = mixLocalAndForeign(ranked, { gl, limit, bulkMode, profile });

  // If we only kept foreign-currency rows, still return them (thin market) but caller will annotate.
  if (deduped.length) {
    const sameCurrencyNums = deduped
      .map((row) => {
        const cur = detectCurrency(row.price);
        if (expected && cur && cur !== expected) return null;
        return extractNumericPrice(row.price);
      })
      .filter((n) => n != null && n > 0)
      .sort((a, b) => a - b);
    // Need enough same-currency comps; otherwise skip outlier trim (protects local PKR vs cheap USD)
    if (sameCurrencyNums.length >= 3) {
      const mid = sameCurrencyNums[Math.floor(sameCurrencyNums.length / 2)];
      const filtered = deduped.filter((row) => {
        const cur = detectCurrency(row.price);
        if (expected && cur && cur !== expected) return true; // keep foreign as secondary
        if (isLocalMarketHost(row.link, gl, profile)) return true; // never drop same-country as outlier
        const n = extractNumericPrice(row.price);
        if (n == null) return true;
        return n >= mid * 0.2 && n <= mid * 4;
      });
      // Keep outliers when the pool is thin — better to show more comps than drop to 1–2
      if (filtered.length >= Math.min(3, limit)) return filtered.slice(0, limit);
      if (filtered.length >= 2 && deduped.length <= limit) return filtered;
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
      return /priceoye\.|daraz\.|olx\.|amazon\.|flipkart\.|telemart\.|shophive\.|charcoal\.|alibaba\./i.test(link)
        && /^https?:\/\//i.test(link);
    })
    .slice(0, limit);
}
