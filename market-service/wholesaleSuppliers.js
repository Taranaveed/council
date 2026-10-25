/**
 * Global B2B / wholesale suppliers. Bulk mode searches a region-fit mix,
 * then ranks cheapest + nearest for the buyer's quantity and budget.
 */

import {
  convertAmount,
  expectedCurrencyForGl,
  extractAmount,
  formatLocalApprox,
  inferListingCurrency,
} from "./currency.js";
import { hostFromUrl, isLocalMarketHost, mixLocalAndForeign } from "./listingQuality.js";

/** Buyer GL → preferred supplier origin codes (same-country / nearby first). */
const BUYER_ORIGIN = {
  us: ["US"],
  ca: ["US", "CA"],
  uk: ["EU", "UK"],
  gb: ["EU", "UK"],
  in: ["IN"],
  pk: ["PK", "IN"], // Pakistan first; India regional is next-best nearby
  ae: ["AE", "CN"],
};

function isLocalListingHost(urlOrHost, gl, profile = null) {
  return isLocalMarketHost(urlOrHost, gl, profile);
}

function itemOrigin(row, supplier) {
  const fromRow = String(row?.supplier_origin || "").toUpperCase();
  if (fromRow) return fromRow;
  return String(supplier?.origin || "").toUpperCase();
}

function matchesBuyerOrigin(origin, gl) {
  const code = String(gl || "").toLowerCase();
  const wanted = BUYER_ORIGIN[code];
  if (!wanted?.length || !origin) return false;
  return wanted.includes(String(origin).toUpperCase());
}

/** Product-page patterns — skip category hubs. */
export const WHOLESALE_SUPPLIERS = [
  {
    id: "alibaba",
    host: "alibaba.com",
    vendor: "Alibaba",
    type: "factory",
    origin: "CN",
    regions: ["global", "pk", "in", "ae", "us", "uk", "gb", "ca", "asia"],
    productRe: /alibaba\.com\/product-detail\//i,
    query: (q) => `${q} site:alibaba.com/product-detail`,
  },
  {
    id: "made-in-china",
    host: "made-in-china.com",
    vendor: "Made-in-China",
    type: "factory",
    origin: "CN",
    regions: ["global", "pk", "in", "ae", "us", "asia"],
    productRe: /made-in-china\.com\/product\//i,
    query: (q) => `${q} wholesale site:made-in-china.com/product`,
  },
  {
    id: "dhgate",
    host: "dhgate.com",
    vendor: "DHgate",
    type: "small-lot",
    origin: "CN",
    regions: ["global", "pk", "in", "us", "uk", "gb", "ca", "ae", "eu", "asia"],
    productRe: /dhgate\.com\/product\//i,
    query: (q) => `${q} wholesale site:dhgate.com/product`,
  },
  {
    id: "globalsources",
    host: "globalsources.com",
    vendor: "Global Sources",
    type: "factory",
    origin: "CN",
    regions: ["global", "us", "asia", "ae"],
    productRe: /globalsources\.com\/.*(product|si\/|gsol\/product)/i,
    query: (q) => `${q} product site:globalsources.com`,
  },
  {
    id: "indiamart",
    host: "indiamart.com",
    vendor: "IndiaMART",
    type: "regional",
    origin: "IN",
    regions: ["in", "pk", "asia", "ae"],
    productRe: /indiamart\.com\/(proddetail|product)/i,
    query: (q) => `${q} wholesale site:indiamart.com/proddetail`,
  },
  {
    id: "tradeindia",
    host: "tradeindia.com",
    vendor: "TradeIndia",
    type: "regional",
    origin: "IN",
    regions: ["in", "pk", "asia"],
    productRe: /tradeindia\.com/i,
    query: (q) => `${q} wholesale site:tradeindia.com`,
  },
  {
    id: "aliexpress",
    host: "aliexpress.com",
    vendor: "AliExpress",
    type: "small-lot",
    origin: "CN",
    regions: ["global", "pk", "in", "ae", "us", "uk", "gb", "ca", "asia"],
    productRe: /aliexpress\.com\/item\//i,
    query: (q) => `${q} wholesale site:aliexpress.com/item`,
  },
  {
    id: "europages",
    host: "europages.com",
    vendor: "Europages",
    type: "regional",
    origin: "EU",
    regions: ["uk", "gb", "eu", "fr", "de", "es", "it", "nl"],
    productRe: /europages\.com/i,
    query: (q) => `${q} manufacturer site:europages.com`,
  },
  {
    id: "thomasnet",
    host: "thomasnet.com",
    vendor: "ThomasNet",
    type: "regional",
    origin: "US",
    regions: ["us", "ca"],
    productRe: /thomasnet\.com/i,
    query: (q) => `${q} wholesale manufacturer site:thomasnet.com`,
  },
  {
    id: "faire",
    host: "faire.com",
    vendor: "Faire",
    type: "wholesale",
    origin: "US",
    regions: ["us", "ca", "uk", "gb"],
    productRe: /faire\.com\/product/i,
    query: (q) => `${q} wholesale site:faire.com`,
  },
];

const GL_TO_REGION = {
  pk: "pk",
  in: "in",
  ae: "ae",
  sa: "ae",
  us: "us",
  ca: "ca",
  uk: "uk",
  gb: "gb",
  ie: "uk",
  fr: "eu",
  de: "eu",
  es: "eu",
  it: "eu",
  nl: "eu",
};

export function supplierFromUrl(url) {
  const host = hostFromUrl(url) || String(url || "").toLowerCase();
  return WHOLESALE_SUPPLIERS.find((s) => host.includes(s.host.replace(/^www\./, ""))) || null;
}

export function isKnownWholesaleHost(urlOrHost) {
  return Boolean(supplierFromUrl(urlOrHost));
}

export function pickSuppliersForGl(gl, { max = 5 } = {}) {
  const code = String(gl || "").toLowerCase();
  const region = GL_TO_REGION[code] || "global";
  // Same-country / nearby suppliers first; China factories only after that
  const preferOrder =
    code === "pk"
      ? ["indiamart", "tradeindia", "dhgate", "alibaba", "made-in-china", "aliexpress"]
      : code === "in"
        ? ["indiamart", "tradeindia", "dhgate", "made-in-china", "alibaba", "aliexpress"]
        : code === "us" || code === "ca"
          ? ["thomasnet", "faire", "alibaba", "dhgate", "globalsources", "aliexpress"]
          : code === "uk" || code === "gb"
            ? ["europages", "alibaba", "dhgate", "globalsources", "aliexpress"]
            : code === "ae"
              ? ["alibaba", "dhgate", "made-in-china", "aliexpress", "globalsources"]
              : ["alibaba", "dhgate", "made-in-china", "aliexpress", "globalsources", "europages"];

  const byId = Object.fromEntries(WHOLESALE_SUPPLIERS.map((s) => [s.id, s]));
  const out = [];
  const seen = new Set();
  for (const id of preferOrder) {
    const s = byId[id];
    if (!s) continue;
    if (!(s.regions.includes(code) || s.regions.includes(region) || s.regions.includes("global"))) {
      continue;
    }
    if (seen.has(s.id)) continue;
    seen.add(s.id);
    out.push(s);
    if (out.length >= max) break;
  }
  // Fill remaining slots by region score — prefer matching origin country
  if (out.length < max) {
    const originWanted =
      code === "us" || code === "ca"
        ? "US"
        : code === "in"
          ? "IN"
          : code === "uk" || code === "gb"
            ? "EU"
            : null;
    const scored = WHOLESALE_SUPPLIERS.map((s) => {
      let score = 0;
      if (s.regions.includes(code) || s.regions.includes(region)) score += 20;
      if (originWanted && s.origin === originWanted) score += 30;
      if (s.regions.includes("global")) score += 6;
      return { s, score };
    })
      .filter((row) => row.score > 0 && !seen.has(row.s.id))
      .sort((a, b) => b.score - a.score);
    for (const row of scored) {
      out.push(row.s);
      if (out.length >= max) break;
    }
  }
  return out.slice(0, max);
}

export function wholesaleSearchJobs(productName, gl, { max = 4 } = {}) {
  const q = String(productName || "").trim();
  if (!q) return [];
  return pickSuppliersForGl(gl, { max }).map((site) => ({
    ...site,
    query: site.query(q),
  }));
}

export function decorateWholesaleListings(rows, fallbackSupplier = null) {
  return (rows || []).map((row) => {
    const supplier = supplierFromUrl(row.link) || fallbackSupplier;
    if (!supplier) {
      return { ...row, wholesale: Boolean(row.wholesale) };
    }
    const vendor =
      row.vendor && !/^web result$/i.test(row.vendor) ? row.vendor : supplier.vendor;
    return {
      ...row,
      vendor,
      wholesale: true,
      supplier_id: supplier.id,
      supplier_type: supplier.type,
      supplier_origin: supplier.origin,
    };
  });
}

function parseBudgetNumber(raw) {
  if (raw == null || raw === "") return null;
  const n = extractAmount(String(raw));
  return n != null && n > 0 ? n : null;
}

/**
 * Reorder bulk listings: cheapest comparable unit, region-fit, qty-appropriate.
 * Drops clear non-product hubs; annotates best_pick on the winner.
 */
export function rankBulkListings(
  listings,
  { gl, quantity = null, budget = null, preferredCurrency = null, profile = null } = {},
) {
  const expected = String(
    preferredCurrency || expectedCurrencyForGl(gl, profile) || "USD",
  ).toUpperCase();
  const qty = Number(quantity);
  const qtyN = Number.isFinite(qty) && qty > 0 ? qty : null;
  const budgetN = parseBudgetNumber(budget);
  const code = String(gl || "").toLowerCase();
  const region = GL_TO_REGION[code] || "global";

  const usdAmounts = [];
  const scored = (listings || [])
    .filter((row) => {
      const supplier = supplierFromUrl(row.link);
      if (!supplier?.productRe) return true;
      // Known wholesale host but not a product URL → drop directory/search hubs
      return supplier.productRe.test(String(row.link || ""));
    })
    .map((row, index) => {
    const supplier = supplierFromUrl(row.link);
    const detected = inferListingCurrency(row, gl, preferredCurrency);
    const amount = extractAmount(row.price);
    let unitUsd = null;
    if (amount != null) {
      unitUsd = convertAmount(amount, detected, "USD");
    }
    if (unitUsd != null && unitUsd > 0) usdAmounts.push(unitUsd);

    let score = 40 - index * 0.4;
    const localHost = isLocalListingHost(row.link, code, profile);
    const originMatch = matchesBuyerOrigin(itemOrigin(row, supplier), code);

    // Same-country first (hard priority over cheap foreign quotes)
    if (localHost) score += 48;
    if (originMatch) score += 36;
    if (detected === expected) score += 28;
    else if (detected) score -= 8;

    // Soft locality boost already in score — demote CN factories slightly when qty is tiny
    if (supplier) {
      score += 18;
      if (supplier.regions.includes(code) || supplier.regions.includes(region)) score += 22;
      else if (supplier.regions.includes("global")) score += 4;
      if (qtyN != null) {
        if (qtyN >= 50 && supplier.type === "factory") score += 16;
        else if (qtyN >= 20 && (supplier.type === "factory" || supplier.type === "wholesale")) score += 10;
        else if (qtyN < 20 && supplier.type === "regional") score += 16;
        else if (qtyN < 12 && supplier.type === "factory" && !localHost) score -= 12;
        else if (qtyN < 20 && supplier.type === "small-lot") score += 10;
      }
      // Mild demote for far factories — still keep them in the foreign lane
      if (!localHost && !originMatch && supplier.origin === "CN") score -= 4;
    }

    if (unitUsd != null && unitUsd > 0) {
      // Cheaper unit price wins, with a floor so $0.01 spam doesn't dominate.
      const cheap = Math.max(0, 36 - Math.log10(Math.max(unitUsd, 0.2)) * 14);
      score += cheap;
      if (budgetN != null && qtyN != null) {
        const totalLocal = convertAmount(unitUsd * qtyN, "USD", expected);
        if (totalLocal != null && totalLocal > budgetN * 1.15) score -= 25;
        else if (totalLocal != null && totalLocal <= budgetN) score += 10;
      }
    } else {
      score -= 4; // unpriced still usable, but not "cheapest"
    }

    const productPage = supplier?.productRe ? supplier.productRe.test(String(row.link || "")) : false;
    if (productPage) score += 10;

    return { row, score, unitUsd, supplier };
  });

  // Soft diversity: demote later duplicates from the same host so IndiaMART/DHgate
  // still surface when Alibaba already filled the top slots.
  const hostSeen = new Map();
  for (const item of scored) {
    const h = hostFromUrl(item.row.link) || "";
    const n = hostSeen.get(h) || 0;
    if (n >= 2) item.score -= 12 * (n - 1);
    hostSeen.set(h, n + 1);
  }
  // Soft locality boost already in score — sort by score, then mix local + foreign slots
  scored.sort((a, b) => b.score - a.score);

  const medianUsd =
    usdAmounts.length >= 2
      ? usdAmounts.sort((a, b) => a - b)[Math.floor(usdAmounts.length / 2)]
      : null;

  // Drop absurd foreign outliers vs median (keep reasonable importable quotes)
  const reasonable = scored.filter((item) => {
    if (isLocalListingHost(item.row.link, code, profile)) return true;
    if (item.unitUsd == null || medianUsd == null || medianUsd <= 0) return true;
    // Keep foreign within ~0.15×–6× of median unit — extreme junk out, real deals in
    return item.unitUsd >= medianUsd * 0.15 && item.unitUsd <= medianUsd * 6;
  });

  const rankedRows = (reasonable.length >= 3 ? reasonable : scored).map((item) => ({
    ...item.row,
    _score: item.score,
    _unitUsd: item.unitUsd,
    _supplier: item.supplier,
  }));

  const mixed = mixLocalAndForeign(rankedRows, {
    gl: code,
    limit: Math.max(rankedRows.length, 16),
    bulkMode: true,
    profile,
  });

  // Re-attach score metadata for reasons / best_pick
  const byLink = new Map(
    (reasonable.length >= 3 ? reasonable : scored).map((item) => [
      String(item.row.link || "").toLowerCase().replace(/[?#].*$/, ""),
      item,
    ]),
  );

  return mixed.map((row, i) => {
    const key = String(row.link || "").toLowerCase().replace(/[?#].*$/, "");
    const item = byLink.get(key) || {
      row,
      score: 0,
      unitUsd: null,
      supplier: supplierFromUrl(row.link),
    };
    const reasons = [];
    const localHost = isLocalListingHost(row.link, code);
    const originMatch = matchesBuyerOrigin(itemOrigin(row, item.supplier), code);
    if (i === 0) {
      const bits = localHost || originMatch
        ? ["best same-country / nearby option"]
        : ["best available (limited local supply)"];
      if (qtyN != null) bits.push("quantity");
      if (budgetN != null) bits.push("budget");
      reasons.push(bits.length > 1 ? bits.join(", ").replace(/,([^,]*)$/, " and$1") : bits[0]);
    }
    if (localHost) reasons.push("seller in the buyer's country");
    else if (originMatch) reasons.push("ships / sources from a nearby market");
    else if (item.supplier?.regions.includes(code) || item.supplier?.regions.includes(region)) {
      reasons.push("ships / sources closer to the buyer");
    }
    if (item.unitUsd != null && medianUsd != null && item.unitUsd <= medianUsd * 0.85) {
      reasons.push("among the cheaper unit quotes");
    }
    if (item.supplier?.type === "factory" && qtyN != null && qtyN >= 50) {
      reasons.push("factory quote fits larger MOQ");
    }
    const unitLocal =
      item.unitUsd != null ? formatLocalApprox(convertAmount(item.unitUsd, "USD", expected), expected) : null;
    return {
      ...row,
      wholesale: Boolean(row.wholesale || item.supplier),
      supplier_id: row.supplier_id || item.supplier?.id || null,
      supplier_type: row.supplier_type || item.supplier?.type || null,
      supplier_origin: row.supplier_origin || item.supplier?.origin || null,
      unit_usd: item.unitUsd != null ? Number(item.unitUsd.toFixed(4)) : null,
      best_pick: i === 0,
      pick_reason: reasons[0] || null,
      price_local_approx: row.price_local_approx || unitLocal,
    };
  });
}
