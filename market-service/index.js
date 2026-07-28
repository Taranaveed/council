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
import { enrichListingsWithPagePrices, isWeakPrice } from "./pagePrice.js";
import { siteSearchQueries } from "./siteSearch.js";
import {
  filterAndRankListings,
  isBlockedSocialHost,
  isGarbagePrice,
} from "./listingQuality.js";
import { fetchDirectMarketplaceListings } from "./marketplaceDirect.js";
import {
  annotateListingsCurrency,
  detectCurrency,
  expectedCurrencyForGl,
} from "./currency.js";
import {
  buildSearchVariants,
  hasMaterialTerm,
  isTransientNetworkError,
  shortenProductQuery,
  withRetries,
} from "./searchQuery.js";

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

const PRICE_IN_TEXT =
  /(?:Rs\.?|PKR|USD|\$|€|£|INR|AED|SAR)\s*[\d,.]+|\b[\d,.]+\s*(?:Rs\.?|PKR)\b/i;

function mapListing(item, extras = {}) {
  const price =
    item.price ||
    (item.extracted_price != null ? String(item.extracted_price) : null) ||
    item.snippet ||
    "N/A";
  return {
    title: item.title || "Unknown",
    price: typeof price === "string" ? price : String(price),
    vendor: extras.vendor || item.source || item.merchant || item.displayed_link || "Unknown",
    link: item.link || item.product_link || "",
    price_source: extras.price_source || (item.price || item.extracted_price != null ? "serp" : "snippet"),
  };
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
      const aLocal = /\.pk(\/|$)|daraz\.|olx\./i.test(String(a.link || "")) ? 1 : 0;
      const bLocal = /\.pk(\/|$)|daraz\.|olx\./i.test(String(b.link || "")) ? 1 : 0;
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
}) {
  const useShopping = isShoppingGlSupported(gl);
  const engine = useShopping ? "google_shopping" : "google";
  const shortName = shortenProductQuery(productName);
  const placeHint = locale.locationLabel || locale.location || "";
  const cur = String(preferredCurrency || expectedCurrencyForGl(gl) || "").toUpperCase();
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

function countLocalCurrency(listings, preferredCurrency, gl) {
  const expected = String(preferredCurrency || expectedCurrencyForGl(gl) || "").toUpperCase();
  if (!expected) return (listings || []).length;
  let n = 0;
  for (const row of listings || []) {
    const cur = detectCurrency(row.price);
    if (!cur || cur === expected) n += 1;
  }
  return n;
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
}) {
  const shortName = shortenProductQuery(productName);
  const queries = siteSearchQueries(shortName, gl, 3);
  const batches = [];
  let localCount = existingLocalCount;
  let sitesTried = 0;

  // Sequential to avoid SerpApi connection resets from parallel bursts
  for (const { query, vendor, host } of queries) {
    if (localCount >= earlyExitAt) {
      console.log(
        `[serpapi] site search early-exit: ${localCount} local-currency prices (need ${earlyExitAt})`,
      );
      break;
    }
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
        continue;
      }
      const rows = extractListings(response, perSite + 3, {
        vendor,
        price_source: "serp",
        keepNoPrice: true,
        gl,
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
      await new Promise((r) => setTimeout(r, 250));
    } catch (err) {
      console.warn(`[serpapi] site search error (${host}):`, err?.message || err);
      batches.push([]);
    }
  }
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

app.post("/market/prices", async (req, res) => {
  const { productName, location, countryCode, gl, hl, limit, preferredCurrency } = req.body || {};
  const startedAt = Date.now();

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
    const currencyHint = String(preferredCurrency || expectedCurrencyForGl(resolvedGl) || "")
      .trim()
      .toUpperCase();
    const safeLimit = Math.min(Math.max(Number(limit) || 8, 3), 12);
    const shoppingSupported = isShoppingGlSupported(resolvedGl);
    const extractLimit = shoppingSupported ? Math.max(safeLimit, 12) : Math.max(safeLimit, 20);
    const mergeCap = shoppingSupported ? Math.max(safeLimit * 2, 16) : Math.max(safeLimit * 3, 24);
    const shortName = shortenProductQuery(productName);
    const variants = buildSearchVariants(productName, {
      gl: resolvedGl,
      currency: currencyHint,
      location: locale.locationLabel || locale.location,
    });
    console.log(`[serpapi] searchQuery="${shortName}" (from "${String(productName).slice(0, 80)}")`);
    console.log(`[serpapi] preferredCurrency=${currencyHint || "(none)"} gl=${resolvedGl}`);
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
    });

    let primaryListings = primary.listings || [];
    let primaryLocal = countLocalCurrency(primaryListings, currencyHint, resolvedGl);
    let altCount = 0;

    // Multi-angle Google queries when Shopping unavailable or local comps are thin
    const needAlts =
      !shoppingSupported || primaryLocal < 3 || primaryListings.length < 3;
    if (needAlts && variants.length > 1) {
      for (const alt of variants.slice(1, 4)) {
        if (primaryLocal >= 4 && primaryListings.length >= 6) break;
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
        });
        altCount += (extra.listings || []).length;
        primaryListings = mergeListings(
          [primaryListings, extra.listings],
          mergeCap,
        );
        primaryLocal = countLocalCurrency(primaryListings, currencyHint, resolvedGl);
        await new Promise((r) => setTimeout(r, 200));
      }
    }

    const earlyExitAt = Math.min(Math.max(safeLimit, 5), 8);
    const thinLocal = primaryLocal < 3;
    const siteResult = await fetchSiteListings({
      productName: shortName,
      locale,
      gl: resolvedGl,
      hl: hl || locale.hl,
      apiKey: currentKey.key,
      perSite: thinLocal ? 3 : 2,
      preferredCurrency: currencyHint || null,
      earlyExitAt,
      existingLocalCount: primaryLocal,
    });
    const siteListings = siteResult.listings || [];
    const localAfterSites = primaryLocal + countLocalCurrency(siteListings, currencyHint, resolvedGl);

    // Direct Daraz/OLX catalog — only when local comps are still thin (slow + often blocked)
    let directListings = [];
    if (localAfterSites < earlyExitAt && (!shoppingSupported || primaryLocal < 4)) {
      try {
        directListings = await fetchDirectMarketplaceListings(shortName, {
          gl: resolvedGl,
          limit: 8,
          location: locale.locationLabel || "",
        });
        // Also try a synonym phrase against marketplaces when thin
        if (directListings.length < 3 && variants[2]) {
          const more = await fetchDirectMarketplaceListings(variants[2], {
            gl: resolvedGl,
            limit: 6,
            location: locale.locationLabel || "",
          });
          directListings = mergeListings([directListings, more], 12);
        }
      } catch (err) {
        console.warn(`[marketplace] direct fetch failed: ${err?.message || err}`);
      }
    } else if (localAfterSites >= earlyExitAt) {
      console.log(
        `[marketplace] skip direct catalogs — already have ~${localAfterSites} local-currency prices`,
      );
    }

    let listings = mergeListings(
      [primaryListings, siteListings, directListings],
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
        });
        const extraSites = await fetchSiteListings({
          productName: broader,
          locale,
          gl: resolvedGl,
          hl: hl || locale.hl,
          apiKey: currentKey.key,
          perSite: 2,
          preferredCurrency: currencyHint || null,
          earlyExitAt,
          existingLocalCount: countLocalCurrency(listings, currencyHint, resolvedGl),
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

    const localBeforeEnrich = countLocalCurrency(listings, currencyHint, resolvedGl);
    const pendingPrice = listings.filter(
      (l) => isWeakPrice(l.price) || String(l.price_source || "") === "pending",
    ).length;
    // When Serp/site already gave enough priced comps, only enrich a few weak rows.
    const maxFetches =
      localBeforeEnrich >= earlyExitAt && pendingPrice <= 2
        ? Math.min(3, pendingPrice)
        : Math.min(
            8,
            Math.max(localBeforeEnrich < 3 || pendingPrice > 0 ? 6 : 4, Math.min(pendingPrice, 6)),
          );
    if (maxFetches > 0) {
      listings = await enrichListingsWithPagePrices(listings, {
        maxFetches,
        gl: resolvedGl,
        query: shortName,
        preferredCurrency: currencyHint || null,
        concurrency: 3,
      });
    } else {
      console.log("[serpapi] skip page enrich — enough priced local listings already");
    }
    console.log(`[serpapi] after page enrich: ${listings.length}`);
    listings.slice(0, 5).forEach((l, i) => {
      console.log(`  [${i}] ${l.vendor} | ${l.price} | src=${l.price_source}`);
    });
    listings = filterAndRankListings(listings, {
      gl: resolvedGl,
      limit: safeLimit,
      query: shortName,
      preferredCurrency: currencyHint || null,
    });
    listings = annotateListingsCurrency(listings, resolvedGl, currencyHint || null);
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
    if (foreignOnly && currencyHint) {
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

    const elapsedMs = Date.now() - startedAt;
    console.log(
      `[serpapi] summary engine=${primary.engine} primary=${(primary.listings || []).length} ` +
        `alts=${altCount} site=${siteListings.length} sitesTried=${siteResult.sitesTried} ` +
        `direct=${directListings.length} page=${pageEnriched} local=${localFinal} foreign=${foreignFinal} ` +
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
        const currencyHint = String(preferredCurrency || expectedCurrencyForGl(resolvedGl) || "")
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
