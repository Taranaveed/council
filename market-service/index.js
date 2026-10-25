import "dotenv/config";
import cors from "cors";
import express from "express";
import { getJson } from "serpapi";
import {
  getRegionConfig,
  isShoppingGlSupported,
  isUnsupportedLocationError,
  normalizeSerpLocation,
  resolveSearchLocale,
} from "./regionConfig.js";
import { getProfile, RegionNotSupportedError } from "./regionProfile.js";
import {
  enrichListingsWithPagePrices,
  fetchPageDetails,
  isWeakPrice,
} from "./pagePrice.js";
import { siteSearchQueries } from "./siteSearch.js";
import {
  filterAndRankListings,
  isBlockedSocialHost,
  isGarbagePrice,
  isLocalMarketHost,
  productMatchScore,
  hostFromUrl,
} from "./listingQuality.js";
import { fetchDirectMarketplaceListings } from "./marketplaceDirect.js";
import {
  decorateAlibabaListings,
  fetchAlibabaCatalog,
  isAlibabaHost,
} from "./alibabaSearch.js";
import {
  decorateWholesaleListings,
  isKnownWholesaleHost,
  rankBulkListings,
  wholesaleSearchJobs,
} from "./wholesaleSuppliers.js";
import {
  annotateListingsCurrency,
  detectCurrency,
  expectedCurrencyForGl,
} from "./currency.js";
import { annotateListingsTiers, isProductDetailUrl } from "./listingTiers.js";
import {
  buildSearchVariants,
  hasMaterialTerm,
  isTransientNetworkError,
  shortenProductQuery,
  withRetries,
} from "./searchQuery.js";
import {
  isMalformedPriceString,
  normalizeListingPrice,
  sanitizePriceRaw,
} from "./priceParse.js";

const app = express();
const PORT = process.env.PORT || 3001;
const regionConfig = getRegionConfig();

app.use(cors());
app.use(express.json());

/** SerpApi private keys are long opaque strings — UUID-shaped values are almost never valid. */
function inspectSerpApiKey(raw) {
  const key = String(raw || "").trim();
  if (!key) {
    return {
      present: false,
      looksValid: false,
      warning: "SERPAPI_KEY is missing in market-service/.env",
    };
  }
  const uuidLike =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(key);
  if (uuidLike) {
    return {
      present: true,
      looksValid: false,
      warning:
        "SERPAPI_KEY looks like a UUID (invalid for SerpApi). Paste the API key from https://serpapi.com/manage-api-key",
    };
  }
  if (key.length < 20 || key.includes("your_serpapi") || key === "changeme") {
    return {
      present: true,
      looksValid: false,
      warning: "SERPAPI_KEY looks like a placeholder — replace with a real SerpApi key",
    };
  }
  return { present: true, looksValid: true, warning: null, key };
}

const keyInfo = inspectSerpApiKey(process.env.SERPAPI_KEY);

// First price token only — do not greedily eat "$1.32" + ",000" MOQ glued together
const PRICE_IN_TEXT =
  /(?:Rs\.?|PKR|USD|\$|€|£|INR|AED|SAR)\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?|\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:Rs\.?|PKR)\b/i;

function mapListing(item, extras = {}) {
  const price =
    item.price ||
    (item.extracted_price != null ? String(item.extracted_price) : null) ||
    null;
  // Never fall back to the full SERP snippet — it produces bare "rs." / junk labels.
  const snippetPrice =
    !price && item.snippet ? String(item.snippet).match(PRICE_IN_TEXT)?.[0] : null;
  let resolved = price || snippetPrice || "See listing";
  resolved = typeof resolved === "string" ? resolved : String(resolved);
  // Normalize / reject concatenated scrapes like "$1.321,000"
  const norm = normalizeListingPrice(sanitizePriceRaw(resolved), "USD");
  const out = {
    title: item.title || "Unknown",
    price: norm.price || "See listing",
    vendor: extras.vendor || item.source || item.merchant || item.displayed_link || "Unknown",
    link: item.link || item.product_link || "",
    price_source:
      extras.price_source ||
      (item.price || item.extracted_price != null ? "serp" : snippetPrice ? "snippet" : "pending"),
  };
  if (norm.rejected || norm.unreliable || isMalformedPriceString(resolved)) {
    out.unit_price_unreliable = true;
    out.price_outlier = Boolean(norm.rejected);
    out.price_outlier_reason =
      norm.reason === "malformed_price_string" || isMalformedPriceString(resolved)
        ? `Malformed price “${String(resolved).slice(0, 40)}” — likely unit+MOQ concat; check listing directly.`
        : out.price_outlier_reason;
    if (norm.rejected) {
      out.price = "See listing";
      out.needs_price_confirm = true;
      out.counts_as_live_listing = false;
    }
  }
  return out;
}

function extractListings(response, limit, extras = {}) {
  const shopping = [
    ...(response.shopping_results || []),
    ...(response.inline_shopping_results || []),
  ];
  const mappedShopping = shopping.map((item) => mapListing(item, extras));
  if (mappedShopping.length) {
    return mappedShopping
      .filter((row) => !isBlockedSocialHost(row.link) && !isBlockedSocialHost(row.vendor))
      .slice(0, limit);
  }

  const organic = response.organic_results || [];
  const keepNoPrice = extras.keepNoPrice !== false; // default: keep organic without prices
  const gl = extras.gl || "";

  const mapOrganic = (item) => {
    const extPrice = item.rich_snippet?.top?.detected_extensions?.price;
    const snippetPrice = (item.snippet || "").match(PRICE_IN_TEXT)?.[0];
    const price = extPrice != null ? String(extPrice) : snippetPrice || "See listing";
    return {
      title: item.title || "Unknown",
      price,
      vendor: extras.vendor || item.source || item.displayed_link || "Web result",
      link: item.link || "",
      price_source: extPrice != null ? "serp" : snippetPrice ? "snippet" : "pending",
    };
  };

  const usable = organic.filter((row) => {
    const link = row.link || "";
    if (isBlockedSocialHost(link)) return false;
    return true;
  });

  const withPrice = [];
  const withoutPrice = [];
  for (const row of usable) {
    const blob = [row.title, row.snippet, row.rich_snippet?.top?.detected_extensions?.price]
      .filter(Boolean)
      .join(" ");
    const hasPrice =
      PRICE_IN_TEXT.test(blob) || row.rich_snippet?.top?.detected_extensions?.price;
    if (hasPrice) withPrice.push(row);
    else withoutPrice.push(row);
  }

  // Prefer priced results, but always mix in no-price organic (esp. local .pk shops)
  // so page enrichment can read Rs from the seller site — like a human Google search.
  const ordered = [];
  const seen = new Set();
  const push = (row) => {
    const key = String(row.link || row.title || "")
      .toLowerCase()
      .replace(/[?#].*$/, "");
    if (!key || seen.has(key)) return;
    seen.add(key);
    ordered.push(row);
  };
  for (const row of withPrice) push(row);
  if (keepNoPrice) {
    // Prefer local TLD / known shops among no-price rows
    const localFirst = [...withoutPrice].sort((a, b) => {
      // Phase 1: prefer RegionProfile.local_host_patterns (extras.profile); PK golden list if absent
      const profile = extras.profile || null;
      const aLocal = isLocalMarketHost(String(a.link || ""), gl, profile) ? 1 : 0;
      const bLocal = isLocalMarketHost(String(b.link || ""), gl, profile) ? 1 : 0;
      return bLocal - aLocal;
    });
    for (const row of localFirst) push(row);
  }

  const pool = ordered.length ? ordered : usable;
  if (pool.length && organic.length) {
    console.log(
      `[serpapi] organic extract: ${organic.length} raw → ${withPrice.length} priced + ${withoutPrice.length} no-price (keepNoPrice=${keepNoPrice}) gl=${gl || "?"}`,
    );
    organic.slice(0, 5).forEach((r, i) => {
      console.log(
        `  organic[${i}] ${String(r.title || "").slice(0, 50)} | ${String(r.link || "").slice(0, 70)}`,
      );
    });
  }

  return pool
    .map(mapOrganic)
    .filter((row) => !isBlockedSocialHost(row.link) && !isBlockedSocialHost(row.vendor))
    .slice(0, limit);
}

function isUnsupportedShoppingGlError(detail) {
  const msg = String(detail || "");
  return /unsupported\s+[`']?\w{2}[`']?\s+country\s*-\s*gl/i.test(msg);
}

function normalizeKey(listing) {
  const rawLink = String(listing.link || "").trim().toLowerCase();
  // Google Shopping intermediate URLs all become google.com/search after stripping ?q=…
  // which collapsed 12 real offers into 1 and wiped US comps.
  const isGoogleShop =
    /google\.[^/\s]+\/search/i.test(rawLink) &&
    /(?:[?&](?:ibp=oshop|tbm=shop)|\/shopping\/)/i.test(rawLink);
  if (isGoogleShop || !rawLink) {
    const vendor = String(listing.vendor || "").trim().toLowerCase().slice(0, 48);
    const title = String(listing.title || "").trim().toLowerCase().slice(0, 80);
    const price = String(listing.price || "").trim().toLowerCase();
    return `offer:${vendor}|${title}|${price}`;
  }
  const link = rawLink.replace(/[?#].*$/, "");
  if (link) return `link:${link}`;
  const vendor = String(listing.vendor || "").trim().toLowerCase();
  const title = String(listing.title || "").trim().toLowerCase().slice(0, 80);
  return `vt:${vendor}|${title}`;
}

function mergeListings(batches, limit) {
  const seen = new Set();
  const out = [];
  for (const batch of batches) {
    for (const item of batch || []) {
      if (!item) continue;
      const key = normalizeKey(item);
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(item);
      if (out.length >= limit) return out;
    }
  }
  return out;
}

async function serpGetJson(params, label = "serpapi") {
  return withRetries(() => getJson(params), {
    retries: 3,
    delayMs: 800,
    label,
  });
}

async function serpGoogleSearch({ q, locale, gl, hl, apiKey, num = 20 }) {
  const params = {
    engine: "google",
    q,
    location: locale.location,
    gl,
    hl: hl || locale.hl,
    num: Math.min(Math.max(Number(num) || 20, 10), 30),
    api_key: apiKey,
  };

  let response = await serpGetJson(params, `google:${String(q).slice(0, 40)}`);

  // Free-text city strings often fail — retry with country, then without location
  if (response?.error && isUnsupportedLocationError(response.error)) {
    const country = normalizeSerpLocation("", gl).location;
    console.warn(
      `[serpapi] unsupported location "${locale.location}"; retrying with "${country}"`,
    );
    response = await serpGetJson(
      { ...params, location: country },
      `google-country:${String(q).slice(0, 40)}`,
    );
  }
  if (response?.error && isUnsupportedLocationError(response.error)) {
    console.warn(`[serpapi] location still unsupported; retrying without location`);
    const { location: _drop, ...noLoc } = params;
    response = await serpGetJson(noLoc, `google-noloc:${String(q).slice(0, 40)}`);
  }
  return response;
}

async function fetchSerpListings({
  productName,
  locale,
  gl,
  hl,
  apiKey,
  limit,
  preferredCurrency,
  rawQuery = null,
  profile = null,
}) {
  const useShopping = isShoppingGlSupported(gl);
  const engine = useShopping ? "google_shopping" : "google";
  const shortName = shortenProductQuery(productName);
  const placeHint = locale.locationLabel || locale.location || "";
  const cur = String(
    preferredCurrency || expectedCurrencyForGl(gl, profile) || "",
  ).toUpperCase();
  const currencyHint =
    cur === "PKR" ? "Rs OR PKR" : cur && cur !== "USD" ? cur : "";
  // rawQuery = prebuilt variant (already includes currency/place); don't re-shorten
  const query =
    rawQuery
      ? String(rawQuery).replace(/\s+/g, " ").trim()
      : engine === "google"
        ? `${shortName} price ${currencyHint} ${placeHint}`.replace(/\s+/g, " ").trim()
        : shortName;

  const params = {
    engine,
    q: query,
    location: locale.location,
    gl,
    hl: hl || locale.hl,
    api_key: apiKey,
  };
  // Ask SerpApi for more organic hits — local shops often sit below the first 8
  if (engine === "google") {
    params.num = Math.min(Math.max(Number(limit) || 20, 15), 30);
  }
  if (engine === "google_shopping") {
    params.num = Math.min(Math.max(Number(limit) || 12, 10), 20);
  }

  console.log(
    `[serpapi] engine=${engine} gl=${gl} location="${locale.location}" q="${query}"`,
  );

  let response;
  try {
    response = await serpGetJson(params, `primary:${engine}`);
  } catch (err) {
    if (isTransientNetworkError(err)) {
      console.warn(`[serpapi] primary search failed transiently: ${err.message || err}`);
      return {
        listings: [],
        warning: `Live search briefly failed (${err.message || "network error"}); trying shop sites…`,
        engine,
        gl,
        transientFailure: true,
      };
    }
    throw err;
  }

  let usedEngine = engine;
  let usedLocation = locale.location;

  if (response?.error && isUnsupportedLocationError(response.error)) {
    const country = normalizeSerpLocation("", gl).location;
    console.warn(`[serpapi] unsupported location; retrying primary with "${country}"`);
    usedLocation = country;
    try {
      response = await serpGetJson(
        { ...params, location: country },
        `primary-country:${engine}`,
      );
    } catch (err) {
      if (isTransientNetworkError(err)) {
        return {
          listings: [],
          warning: `Live search briefly failed (${err.message || "network error"}); trying shop sites…`,
          engine,
          gl,
          transientFailure: true,
        };
      }
      throw err;
    }
  }

  if (response?.error && isUnsupportedLocationError(response.error)) {
    console.warn(`[serpapi] retrying primary without location param`);
    usedLocation = "";
    const { location: _drop, ...noLoc } = params;
    response = await serpGetJson(noLoc, `primary-noloc:${engine}`);
  }

  if (
    useShopping &&
    (response?.error || response?.search_metadata?.status === "Error") &&
    isUnsupportedShoppingGlError(response?.error)
  ) {
    console.warn(`[serpapi] Shopping rejected gl=${gl}; retrying with engine=google`);
    usedEngine = "google";
    try {
      response = await serpGoogleSearch({
        q: `${shortName} price ${placeHint}`.replace(/\s+/g, " ").trim(),
        locale: { ...locale, location: usedLocation || locale.location },
        gl,
        hl,
        apiKey,
      });
    } catch (err) {
      if (isTransientNetworkError(err)) {
        return {
          listings: [],
          warning: `Live search briefly failed (${err.message || "network error"}); trying shop sites…`,
          engine: usedEngine,
          gl,
          transientFailure: true,
        };
      }
      throw err;
    }
  }

  if (response?.error) {
    return { listings: [], warning: String(response.error), engine: usedEngine, gl };
  }

  const listings = extractListings(response, limit, {
    keepNoPrice: !useShopping || usedEngine === "google",
    gl,
    profile,
  });
  return {
    listings,
    warning:
      listings.length === 0
        ? `SerpApi returned zero results for this query (engine=${usedEngine}, gl=${gl})`
        : usedEngine === "google" && !useShopping
          ? `Using Google Search + local shops for ${gl.toUpperCase()} (Google Shopping isn't available there).`
          : undefined,
    engine: usedEngine,
    gl,
  };
}

function countLocalCurrency(listings, preferredCurrency, gl, profile = null) {
  const expected = String(
    preferredCurrency || expectedCurrencyForGl(gl, profile) || "",
  ).toUpperCase();
  let n = 0;
  for (const row of listings || []) {
    const price = String(row.price || "");
    // Do not count "See listing" / bare currency as a local price hit
    if (!/\d/.test(price) || /^(see\s+listing|n\/?a)/i.test(price.trim())) continue;
    const cur = detectCurrency(price);
    if (!expected) {
      if (cur) n += 1;
      continue;
    }
    if (cur === expected) n += 1;
  }
  return n;
}

function countUsableProductPages(listings, query) {
  let n = 0;
  for (const row of listings || []) {
    if (!isProductDetailUrl(row.link)) continue;
    if (productMatchScore(row, query) == null) continue;
    const price = String(row.price || "");
    const hasPrice =
      Boolean(row.has_price_tier) ||
      (/\d/.test(price) && !/^(see\s+listing|n\/?a)/i.test(price.trim()));
    if (!hasPrice) continue;
    n += 1;
  }
  return n;
}

/** Run async work over items with a fixed concurrency limit. */
async function mapPool(items, concurrency, fn) {
  const list = items || [];
  const results = new Array(list.length);
  let next = 0;
  const workers = Math.max(1, Math.min(concurrency || 1, list.length || 1));
  await Promise.all(
    Array.from({ length: workers }, async () => {
      while (next < list.length) {
        const i = next++;
        results[i] = await fn(list[i], i);
      }
    }),
  );
  return results;
}

async function fetchWholesaleSupplierListings({
  productName,
  locale,
  gl,
  hl,
  apiKey,
  limit = 12,
  maxSuppliers = 3,
  profile = null,
}) {
  const shortName = shortenProductQuery(productName);
  const jobs = wholesaleSearchJobs(shortName, gl, { max: maxSuppliers });
  console.log(`[wholesale] suppliers=${jobs.map((j) => j.vendor).join(", ")}`);

  const batches = await mapPool(jobs, 3, async (job) => {
    try {
      console.log(`[wholesale] serp ${job.vendor} q="${job.query}"`);
      const response = await serpGoogleSearch({
        q: job.query,
        locale: { ...locale, location: locale.location || "United States" },
        gl: job.origin === "US" ? "us" : job.origin === "IN" ? "in" : "us",
        hl: hl || "en",
        apiKey,
        num: 10,
      });
      if (response?.error) {
        console.warn(`[wholesale] ${job.vendor} failed:`, response.error);
        return [];
      }
      const rows = decorateWholesaleListings(
        extractListings(response, 5, {
          vendor: job.vendor,
          price_source: "serp",
          keepNoPrice: true,
          gl,
          profile,
        }),
        job,
      ).filter((row) => isKnownWholesaleHost(row.link) || isAlibabaHost(row.link));
      console.log(`[wholesale] ${job.vendor} kept ${rows.length}`);
      return rows;
    } catch (err) {
      console.warn(`[wholesale] ${job.vendor} error: ${err?.message || err}`);
      return [];
    }
  });

  let listings = mergeListings(batches, Math.max(limit, 16));
  const aliCount = listings.filter((r) => isAlibabaHost(r.link)).length;
  // Only hit Alibaba HTML catalog when SERP returned almost nothing
  if (listings.length < 3 || aliCount < 1) {
    try {
      const catalog = decorateAlibabaListings(
        await fetchAlibabaCatalog(shortName, { limit: 8 }),
      );
      listings = mergeListings([listings, catalog], Math.max(limit, 16));
    } catch (err) {
      console.warn(`[wholesale] alibaba catalog error: ${err?.message || err}`);
    }
  }
  console.log(`[wholesale] supplier listings=${listings.length}`);
  return listings;
}

async function fetchSiteListings({
  productName,
  locale,
  gl,
  hl,
  apiKey,
  perSite = 2,
  preferredCurrency = null,
  earlyExitAt = 5,
  existingLocalCount = 0,
  bulkMode = false,
  profile = null,
}) {
  const shortName = shortenProductQuery(productName);
  // Fewer site probes = faster; local hosts are ordered first in siteSearch
  const queries = siteSearchQueries(shortName, gl, bulkMode ? 3 : 4, { bulkMode });
  let localCount = existingLocalCount;
  const batches = [];
  let sitesTried = 0;

  // Parallel site probes (cap 2) — big latency win vs sequential SerpApi
  await mapPool(queries, 2, async ({ query, vendor, host }) => {
    if (localCount >= earlyExitAt) return;
    sitesTried += 1;
    try {
      console.log(`[serpapi] site search gl=${gl} q="${query}"`);
      const response = await serpGoogleSearch({
        q: query,
        locale,
        gl,
        hl,
        apiKey,
      });
      if (response?.error) {
        console.warn(`[serpapi] site search failed (${host}):`, response.error);
        batches.push([]);
        return;
      }
      const rows = extractListings(response, perSite + 3, {
        vendor,
        price_source: "serp",
        keepNoPrice: true,
        gl,
        profile,
      })
        .filter((row) => {
          const link = String(row.link || "").toLowerCase();
          const disp = String(row.vendor || "").toLowerCase();
          if (!link && !disp) return false;
          const hostKey = host.replace(/^www\./, "");
          if (
            link &&
            !link.includes(hostKey) &&
            !disp.includes(hostKey.split(".")[0])
          ) {
            if (String(row.vendor || "").toLowerCase() !== String(vendor).toLowerCase()) {
              return false;
            }
          }
          if (/\/tag\//i.test(link)) return false;
          return true;
        })
        .slice(0, perSite);
      console.log(`[serpapi] site ${host}: kept ${rows.length}`);
      batches.push(rows);
      localCount += countLocalCurrency(rows, preferredCurrency, gl);
    } catch (err) {
      console.warn(`[serpapi] site search error (${host}):`, err?.message || err);
      batches.push([]);
    }
  });
  return { listings: batches.flat(), sitesTried };
}

app.get("/health", (_req, res) => {
  res.json({
    status: "ok",
    service: "market-service",
    region: regionConfig,
    serpapi: {
      keyPresent: keyInfo.present,
      keyLooksValid: keyInfo.looksValid,
      warning: keyInfo.warning,
    },
  });
});

/** Fetch page facts for one or more listing URLs (top-pick refresh). */
app.post("/market/page-facts", async (req, res) => {
  try {
    const { listings = [], query = "", preferredCurrency = null, gl = "us" } = req.body || {};
    if (!Array.isArray(listings) || !listings.length) {
      return res.json({ listings: [] });
    }
    const enriched = await enrichListingsWithPagePrices(listings.slice(0, 5), {
      maxFetches: Math.min(5, listings.length),
      gl,
      query,
      preferredCurrency,
      concurrency: 2,
      preferIndexes: listings.map((_, i) => i),
    });
    return res.json({ listings: enriched });
  } catch (err) {
    console.warn("[page-facts]", err?.message || err);
    return res.status(500).json({ error: String(err?.message || err), listings: [] });
  }
});

/** Refresh one saved listing URL without substituting another search result. */
app.post("/market/watch-price", async (req, res) => {
  try {
    const {
      url = "",
      query = "",
      nativeCurrency = "USD",
    } = req.body || {};
    if (!/^https?:\/\//i.test(String(url))) {
      return res.status(400).json({ error: "A valid listing URL is required" });
    }
    const details = await fetchPageDetails(String(url), {
      query: String(query || ""),
      defaultCurrency: String(nativeCurrency || "USD").toUpperCase(),
      allowPlaywright: true,
      timeoutMs: 8000,
    });
    if (!details) {
      return res.json({
        available: false,
        url: String(url),
        reason: "listing_unavailable",
      });
    }
    const pagePrice =
      details.price && !isWeakPrice(details.price) ? details.price : null;
    return res.json({
      available: true,
      url: String(url),
      title: details.title || null,
      price: pagePrice,
      currency: pagePrice
        ? detectCurrency(pagePrice) || String(nativeCurrency || "USD").toUpperCase()
        : String(nativeCurrency || "USD").toUpperCase(),
      price_source: pagePrice ? "page" : null,
      page_price_verified: Boolean(pagePrice),
    });
  } catch (err) {
    console.warn("[watch-price]", err?.message || err);
    return res.status(502).json({
      available: false,
      reason: "fetch_error",
      error: String(err?.message || err),
    });
  }
});

app.post("/market/prices", async (req, res) => {
  const { productName, location, countryCode, gl, hl, limit, preferredCurrency, bulkMode, quantity, budget } =
    req.body || {};
  const startedAt = Date.now();
  const isBulk = Boolean(bulkMode);

  if (!productName || typeof productName !== "string") {
    return res.status(400).json({ error: "productName is required" });
  }

  const currentKey = inspectSerpApiKey(process.env.SERPAPI_KEY);
  if (!currentKey.present || !currentKey.looksValid) {
    console.warn(currentKey.warning);
    return res.json({
      listings: [],
      warning: currentKey.warning,
    });
  }

  try {
    const locale = resolveSearchLocale({
      location,
      countryCode: countryCode || gl,
    });
    const resolvedGl = (gl || locale.gl).toLowerCase();
    let profile;
    try {
      profile = getProfile({
        location: locale.locationLabel || locale.location || location,
        countryCode: resolvedGl,
        currency: preferredCurrency,
      });
    } catch (err) {
      if (err instanceof RegionNotSupportedError || err?.code === "region_not_supported") {
        return res.status(422).json({
          error: "region_not_supported",
          message: err.message,
          profile_id: err.profileId || resolvedGl,
          supported: ["pk", "uk"],
          listings: [],
        });
      }
      throw err;
    }
    const currencyHint = String(
      preferredCurrency || expectedCurrencyForGl(resolvedGl, profile) || "",
    )
      .trim()
      .toUpperCase();
    const safeLimit = Math.min(Math.max(Number(limit) || 8, 3), 16);
    const shoppingSupported = isShoppingGlSupported(resolvedGl);
    const extractLimit = shoppingSupported
      ? Math.max(safeLimit + 4, 16)
      : Math.max(safeLimit + 8, 24);
    const mergeCap = shoppingSupported
      ? Math.max(safeLimit * 3, 32)
      : Math.max(safeLimit * 4, 40);
    const shortName = shortenProductQuery(productName);
    const variants = buildSearchVariants(productName, {
      gl: resolvedGl,
      currency: currencyHint,
      location: locale.locationLabel || locale.location,
      bulkMode: isBulk,
      siteTldPass: profile?.serp?.site_tld_pass || null,
      countryHint: profile?.display_name || null,
    });
    console.log(`[serpapi] searchQuery="${shortName}" (from "${String(productName).slice(0, 80)}")`);
    console.log(`[serpapi] preferredCurrency=${currencyHint || "(none)"} gl=${resolvedGl} profile=${profile?.id || "?"}`);
    console.log(`[serpapi] variants=${JSON.stringify(variants)}`);

    // Primary search with first variant
    const primary = await fetchSerpListings({
      productName: shortName,
      locale,
      gl: resolvedGl,
      hl: hl || locale.hl,
      apiKey: currentKey.key,
      limit: extractLimit,
      preferredCurrency: currencyHint || null,
      rawQuery: shoppingSupported ? null : variants[0] || null,
      profile,
    });

    let primaryListings = primary.listings || [];
    let primaryLocal = countLocalCurrency(primaryListings, currencyHint, resolvedGl, profile);
    let altCount = 0;

    // Cap alts hard — each is a full SerpApi round-trip (~2–8s).
    const altCap = isBulk ? 1 : shoppingSupported ? 1 : 2;
    const needAlts =
      !shoppingSupported || primaryLocal < 4 || primaryListings.length < 4;
    if (needAlts && variants.length > 1) {
      for (const alt of variants.slice(1, 1 + altCap)) {
        if (primaryLocal >= 5 && primaryListings.length >= 8) break;
        if (isBulk && primaryListings.length >= 6) break;
        console.log(`[serpapi] alternate query="${alt}"`);
        const extra = await fetchSerpListings({
          productName: shortName,
          locale,
          gl: resolvedGl,
          hl: hl || locale.hl,
          apiKey: currentKey.key,
          limit: extractLimit,
          preferredCurrency: currencyHint || null,
          rawQuery: alt,
          profile,
        });
        altCount += (extra.listings || []).length;
        primaryListings = mergeListings(
          [primaryListings, extra.listings],
          mergeCap,
        );
        primaryLocal = countLocalCurrency(
          primaryListings,
          currencyHint,
          resolvedGl,
          profile,
        );
      }
    }

    const earlyExitAt = Math.min(Math.max(safeLimit, 5), 8);
    const thinLocal = primaryLocal < 3;
    const usablePrimary = countUsableProductPages(primaryListings, shortName);
    // Enough local for early site skip — but bulk still fetches a foreign lane
    const haveEnoughLocal = primaryLocal >= earlyExitAt && usablePrimary >= 4;

    let siteListings = [];
    let siteResult = { listings: [], sitesTried: 0 };
    let wholesaleListings = [];

    // Always probe local sites unless primary already has a strong live set
    const needSites = !haveEnoughLocal && !(isBulk && usablePrimary >= 6);
    // Bulk always pulls some foreign wholesale so the list isn't local-only
    const needWholesale = isBulk;

    // Run local site probes + foreign wholesale in parallel when both needed
    if (needSites || needWholesale) {
      const sitePromise = needSites
        ? fetchSiteListings({
            productName: shortName,
            locale,
            gl: resolvedGl,
            hl: hl || locale.hl,
            apiKey: currentKey.key,
            perSite: thinLocal ? 3 : isBulk ? 2 : 2,
            preferredCurrency: currencyHint || null,
            earlyExitAt,
            existingLocalCount: primaryLocal,
            bulkMode: isBulk,
            profile,
          })
        : Promise.resolve({ listings: [], sitesTried: 0 });
      const wholesalePromise = needWholesale
        ? fetchWholesaleSupplierListings({
            productName: shortName,
            locale,
            gl: resolvedGl,
            hl: hl || locale.hl,
            apiKey: currentKey.key,
            limit: Math.max(8, safeLimit),
            // Fewer suppliers when local is already strong — keep foreign lane light but present
            maxSuppliers: haveEnoughLocal ? 2 : 3,
            profile,
          }).catch((err) => {
            console.warn(`[wholesale] supplier search failed: ${err?.message || err}`);
            return [];
          })
        : Promise.resolve([]);

      const [siteRes, wholesaleRes] = await Promise.all([sitePromise, wholesalePromise]);
      siteResult = siteRes;
      siteListings = siteRes.listings || [];
      wholesaleListings = wholesaleRes || [];
    } else {
      console.log(
        `[serpapi] skip site/wholesale — already have ${primaryLocal} local-currency prices`,
      );
    }
    const localAfterSites =
      primaryLocal +
      countLocalCurrency(siteListings, currencyHint, resolvedGl, profile);

    // Direct Daraz/OLX catalog — only when local comps are still thin
    let directListings = [];
    const needDirect =
      localAfterSites < earlyExitAt ||
      (!shoppingSupported && usablePrimary < 3);
    if (needDirect && (!shoppingSupported || primaryLocal < 4)) {
      try {
        directListings = await fetchDirectMarketplaceListings(shortName, {
          gl: resolvedGl,
          limit: isBulk ? 10 : 8,
          location: locale.locationLabel || "",
        });
        // One synonym pass max when still thin
        if (directListings.length < 4 && variants[2]) {
          const more = await fetchDirectMarketplaceListings(variants[2], {
            gl: resolvedGl,
            limit: 6,
            location: locale.locationLabel || "",
          });
          directListings = mergeListings([directListings, more], 14);
        }
      } catch (err) {
        console.warn(`[marketplace] direct fetch failed: ${err?.message || err}`);
      }
    } else {
      console.log(
        `[marketplace] skip direct catalogs — already have ~${localAfterSites} local-currency prices`,
      );
    }

    // Same-country first in merge order so foreign wholesale doesn't crowd out locals in the cap
    let listings = mergeListings(
      [directListings, siteListings, primaryListings, wholesaleListings],
      mergeCap,
    );

    // Legacy broader fallback if still thin — never drop material words
    if (listings.length < 3) {
      const words = shortName.split(/\s+/).filter(Boolean);
      const broader =
        words.length >= 3
          ? words.slice(-2).join(" ")
          : words.length === 1
            ? `buy ${words[0]}`
            : "";
      const dropsMaterial =
        hasMaterialTerm(shortName) && broader && !hasMaterialTerm(broader);
      if (broader && broader !== shortName && !dropsMaterial && !variants.includes(broader)) {
        console.log(`[serpapi] thin results (${listings.length}); broader q="${broader}"`);
        const extra = await fetchSerpListings({
          productName: broader,
          locale,
          gl: resolvedGl,
          hl: hl || locale.hl,
          apiKey: currentKey.key,
          limit: safeLimit,
          preferredCurrency: currencyHint || null,
          profile,
        });
        const extraSites = await fetchSiteListings({
          productName: broader,
          locale,
          gl: resolvedGl,
          hl: hl || locale.hl,
          apiKey: currentKey.key,
          perSite: 3,
          preferredCurrency: currencyHint || null,
          earlyExitAt,
          existingLocalCount: countLocalCurrency(
            listings,
            currencyHint,
            resolvedGl,
            profile,
          ),
          bulkMode: isBulk,
          profile,
        });
        listings = mergeListings(
          [listings, extra.listings, extraSites.listings],
          mergeCap,
        );
      }
    }

    listings = listings.filter(
      (row) => !isBlockedSocialHost(row.link) && !isBlockedSocialHost(row.vendor),
    );
    const afterMerge = listings.length;
    console.log(`[serpapi] after merge+social filter: ${afterMerge} (direct=${directListings.length})`);
    listings.slice(0, 5).forEach((l, i) => {
      console.log(
        `  [${i}] ${l.vendor} | ${l.price} | ${String(l.title || "").slice(0, 40)} | ${String(l.link || "").slice(0, 60)}`,
      );
    });

    const localBeforeEnrich = countLocalCurrency(
      listings,
      currencyHint,
      resolvedGl,
      profile,
    );
    const pendingPrice = listings.filter(
      (l) => isWeakPrice(l.price) || String(l.price_source || "") === "pending",
    ).length;
    // Prefer same-country / weak-price rows for the limited enrich budget
    listings = [...listings].sort((a, b) => {
      const aLocal = isLocalMarketHost(a.link, resolvedGl, profile) ? 1 : 0;
      const bLocal = isLocalMarketHost(b.link, resolvedGl, profile) ? 1 : 0;
      if (aLocal !== bLocal) return bLocal - aLocal;
      const aWeak = isWeakPrice(a.price) ? 1 : 0;
      const bWeak = isWeakPrice(b.price) ? 1 : 0;
      return bWeak - aWeak;
    });
    // Cap page fetches hard — each can take 5–15s (Playwright fallback).
    const maxFetches =
      localBeforeEnrich >= earlyExitAt && pendingPrice <= 2
        ? Math.min(3, pendingPrice)
        : Math.min(
            isBulk ? 4 : 5,
            Math.max(
              localBeforeEnrich < 3 || pendingPrice > 0 ? (isBulk ? 3 : 4) : 2,
              Math.min(pendingPrice, isBulk ? 4 : 5),
            ),
          );
    if (maxFetches > 0) {
      listings = await enrichListingsWithPagePrices(listings, {
        maxFetches,
        gl: resolvedGl,
        query: shortName,
        preferredCurrency: currencyHint || null,
        concurrency: isBulk ? 3 : 3,
        allowPlaywright: !isBulk,
      });
    } else {
      console.log("[serpapi] skip page enrich — enough priced local listings already");
    }
    console.log(`[serpapi] after page enrich: ${listings.length}`);
    listings.slice(0, 5).forEach((l, i) => {
      console.log(`  [${i}] ${l.vendor} | ${l.price} | src=${l.price_source}`);
    });
    listings = annotateListingsTiers(listings, {
      defaultCurrency:
        currencyHint || expectedCurrencyForGl(resolvedGl, profile) || "USD",
      quantity: quantity != null ? Number(quantity) : null,
    });
    // Fix mis-tagged factory "Rs 4" → USD before quality filter drops them
    listings = annotateListingsCurrency(listings, resolvedGl, currencyHint || null);
    listings = filterAndRankListings(listings, {
      gl: resolvedGl,
      limit: isBulk ? Math.max(safeLimit, 16) : safeLimit,
      query: shortName,
      preferredCurrency: currencyHint || null,
      bulkMode: isBulk,
      profile,
    });
    // Re-annotate after filter (approx / mismatch on survivors)
    listings = annotateListingsCurrency(listings, resolvedGl, currencyHint || null);
    if (isBulk) {
      listings = rankBulkListings(listings, {
        gl: resolvedGl,
        quantity,
        budget,
        preferredCurrency: currencyHint || null,
        profile,
      });
    }
    // Top-pick page facts — only if enrich didn't already land them (avoid 2nd round-trip)
    if (listings.length) {
      const needFacts = listings
        .slice(0, isBulk ? 1 : 2)
        .map((row, i) => ({ row, i }))
        .filter(({ row }) => !row.page_facts_fetched);
      if (needFacts.length) {
        listings = await enrichListingsWithPagePrices(listings, {
          maxFetches: needFacts.length,
          gl: resolvedGl,
          query: shortName,
          preferredCurrency: currencyHint || null,
          concurrency: 2,
          preferIndexes: needFacts.map((x) => x.i),
          allowPlaywright: false,
        });
        listings = annotateListingsCurrency(listings, resolvedGl, currencyHint || null);
      }
    }
    console.log(`[serpapi] after quality filter: ${listings.length}`);

    const pageEnriched = listings.filter((l) => l.price_source === "page").length;
    const weakLeft = listings.filter(
      (l) => isWeakPrice(l.price) || isGarbagePrice(l.price, resolvedGl),
    ).length;
    const localFinal = listings.filter((l) => !l.currency_mismatch).length;
    const foreignFinal = listings.filter((l) => l.currency_mismatch).length;
    const foreignOnly = listings.length > 0 && localFinal === 0;

    let warning = primary.warning;
    if (listings.length === 0) {
      warning =
        primary.warning ||
        `SerpApi returned zero usable seller prices for this query (gl=${resolvedGl})`;
    } else if (primary.transientFailure) {
      warning = `${primary.warning || "Primary search failed briefly."} Recovered ${listings.length} price(s) from shop sites.`;
    } else if (pageEnriched > 0) {
      const base = warning ? `${warning} ` : "";
      warning = `${base}Opened ${pageEnriched} seller page(s) to read live prices.`.trim();
    }
    if (foreignOnly && currencyHint && !isBulk) {
      const note =
        `No local ${currencyHint} prices found — only international listings. ` +
        `Treat them as reference only, not a local ${currencyHint} market median. ` +
        `Try a clearer product name or another city.`;
      warning = warning ? `${warning} ${note}` : note;
    } else if (localFinal === 0 && listings.length === 0 && currencyHint) {
      warning =
        warning ||
        `No usable local ${currencyHint} seller prices for this query. Try a shorter product name.`;
    }
    if (isBulk && wholesaleListings.length) {
      const hosts = [...new Set(wholesaleListings.map((r) => r.vendor).filter(Boolean))];
      const pick = listings.find((r) => r.best_pick);
      const aliNote =
        `Compared ${wholesaleListings.length} wholesale supplier listing(s) ` +
        `(${hosts.slice(0, 5).join(", ") || "global B2B"}). ` +
        (pick
          ? `Best cheap pick for this region: ${pick.vendor || "supplier"} — ${pick.pick_reason || "ranked for unit price and location"}.`
          : "USD factory quotes are not local retail prices.");
      warning = warning ? `${warning} ${aliNote}` : aliNote;
    }

    const elapsedMs = Date.now() - startedAt;
    console.log(
      `[serpapi] summary engine=${primary.engine} primary=${(primary.listings || []).length} ` +
        `alts=${altCount} site=${siteListings.length} sitesTried=${siteResult.sitesTried} ` +
        `direct=${directListings.length} wholesale=${wholesaleListings.length} page=${pageEnriched} local=${localFinal} foreign=${foreignFinal} ` +
        `total=${listings.length} ms=${elapsedMs}`,
    );

    return res.json({
      listings,
      warning:
        weakLeft === listings.length && listings.length > 0
          ? `${warning || ""} Some listing pages blocked price reading.`.trim()
          : warning,
      locale: {
        location: locale.location,
        gl: resolvedGl,
        hl: hl || locale.hl,
        defaultRegion: locale.defaultRegion,
        engine: primary.engine,
        shoppingSupported,
        searchQuery: shortName,
        searchVariants: variants,
        preferredCurrency: currencyHint || null,
        foreignCurrencyOnly: foreignOnly,
        localListingCount: localFinal,
        foreignListingCount: foreignFinal,
        siteSearches: siteSearchQueries(shortName, resolvedGl, 3).map((s) => s.host),
        pageEnriched,
        elapsedMs,
      },
    });
  } catch (error) {
    const detail =
      error?.error ||
      error?.message ||
      (typeof error === "string" ? error : "Market search failed");

    // Last chance: still try shop site searches alone on network failure
    if (isTransientNetworkError(detail) || isUnsupportedShoppingGlError(detail)) {
      try {
        const locale = resolveSearchLocale({
          location,
          countryCode: countryCode || gl,
        });
        const resolvedGl = (gl || locale.gl).toLowerCase();
        let profile;
        try {
          profile = getProfile({
            location: locale.locationLabel || locale.location || location,
            countryCode: resolvedGl,
            currency: preferredCurrency,
          });
        } catch (err) {
          if (err instanceof RegionNotSupportedError || err?.code === "region_not_supported") {
            return res.status(422).json({
              error: "region_not_supported",
              message: err.message,
              profile_id: err.profileId || resolvedGl,
              supported: ["pk", "uk"],
              listings: [],
            });
          }
          throw err;
        }
        const currencyHint = String(
          preferredCurrency || expectedCurrencyForGl(resolvedGl, profile) || "",
        )
          .trim()
          .toUpperCase();
        const safeLimit = Math.min(Math.max(Number(limit) || 8, 3), 12);
        const current = inspectSerpApiKey(process.env.SERPAPI_KEY);
        const shortName = shortenProductQuery(productName);
        const siteResult = await fetchSiteListings({
          productName: shortName,
          locale,
          gl: resolvedGl,
          hl: hl || locale.hl,
          apiKey: current.key,
          perSite: 3,
          preferredCurrency: currencyHint || null,
          earlyExitAt: 5,
          existingLocalCount: 0,
          profile,
        });
        let listings = (siteResult.listings || []).filter(
          (row) => !isBlockedSocialHost(row.link) && !isBlockedSocialHost(row.vendor),
        );
        listings = await enrichListingsWithPagePrices(listings, {
          maxFetches: 6,
          gl: resolvedGl,
          query: shortName,
          preferredCurrency: currencyHint || null,
          concurrency: 3,
        });
        listings = filterAndRankListings(listings, {
          gl: resolvedGl,
          limit: safeLimit,
          query: shortName,
          preferredCurrency: currencyHint || null,
          profile,
        });
        listings = annotateListingsCurrency(listings, resolvedGl, currencyHint || null);
        return res.json({
          listings,
          warning:
            listings.length === 0
              ? `Live price lookup failed (${detail}). Try again in a moment.`
              : `Network hiccup on main search; recovered ${listings.length} price(s) from shop sites.`,
          locale: {
            location: locale.location,
            gl: resolvedGl,
            hl: hl || locale.hl,
            defaultRegion: locale.defaultRegion,
            engine: "google",
            shoppingSupported: isShoppingGlSupported(resolvedGl),
            searchQuery: shortName,
            preferredCurrency: currencyHint || null,
          },
        });
      } catch (retryErr) {
        const retryDetail =
          retryErr?.error || retryErr?.message || "Market search failed";
        console.error("Market search fallback failed", retryDetail);
        return res.json({
          listings: [],
          warning: `Live price lookup failed (${retryDetail}). Try again in a moment.`,
        });
      }
    }

    console.error("Market search failed", detail);
    return res.json({
      listings: [],
      warning: `Live price lookup failed (${detail}). Try again in a moment.`,
    });
  }
});

app.listen(PORT, () => {
  console.log(`Market service listening on http://localhost:${PORT}`);
  console.log(
    `Region defaults: DEFAULT_REGION=${regionConfig.DEFAULT_REGION} ` +
      `DEFAULT_COUNTRY_CODE=${regionConfig.DEFAULT_COUNTRY_CODE} ` +
      `DEFAULT_LOCATION=${regionConfig.DEFAULT_LOCATION}`,
  );
  if (!keyInfo.looksValid) {
    console.warn(`[serpapi] ${keyInfo.warning}`);
  } else {
    console.log("[serpapi] SERPAPI_KEY loaded (format looks OK)");
  }
});
