/**
 * Direct marketplace catalog searches (bypass Google ranking).
 * Best-effort HTML / embedded JSON parsing — never invents products.
 */

import { extractPriceFromHtml, isWeakPrice } from "./pagePrice.js";
import { productMatchScore } from "./listingQuality.js";
import {
  formatMoneyAmount,
  maybeUnscaleMarketplacePrice,
  parsePriceNumber,
} from "./priceParse.js";

const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

async function fetchHtml(url, { timeoutMs = 6000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: "GET",
      redirect: "follow",
      signal: controller.signal,
      headers: {
        "User-Agent": BROWSER_UA,
        Accept: "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-PK,en;q=0.9,ur;q=0.8",
        "Cache-Control": "no-cache",
      },
    });
    if (!res.ok) return null;
    return await res.text();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function formatRs(n) {
  return formatMoneyAmount(n, "PKR");
}

function parseDarazPrice(raw, html = "") {
  let n = parsePriceNumber(raw);
  if (n == null) return null;
  n = maybeUnscaleMarketplacePrice(n, raw, { html, url: "https://www.daraz.pk/" });
  return formatRs(n);
}

function decodeBasicEntities(s) {
  return String(s || "")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

/**
 * Parse Daraz catalog HTML / embedded JSON for product cards.
 */
export function parseDarazCatalog(html, query, { limit = 6 } = {}) {
  if (!html) return [];
  const out = [];
  const seen = new Set();

  // Embedded list items often appear as JSON fragments
  const jsonChunks = [
    ...html.matchAll(
      /\{\s*"name"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"\s*,\s*"productUrl"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"[\s\S]{0,400}?"price"\s*:\s*"?([\d,.]+)"?/gi,
    ),
  ];
  for (const m of jsonChunks) {
    const title = decodeBasicEntities(m[1]).replace(/\\"/g, '"');
    let link = decodeBasicEntities(m[2]).replace(/\\u002F/g, "/").replace(/\\\//g, "/");
    if (link.startsWith("//")) link = `https:${link}`;
    if (link.startsWith("/")) link = `https://www.daraz.pk${link}`;
    const price = parseDarazPrice(m[3], html);
    if (!link || seen.has(link)) continue;
    if (query && productMatchScore({ title, link }, query) == null) continue;
    seen.add(link);
    out.push({
      title: title || "Daraz listing",
      price: price || "See listing",
      vendor: "Daraz",
      link,
      price_source: price ? "marketplace" : "pending",
    });
    if (out.length >= limit) return out;
  }

  // Fallback: product links + nearby Rs amounts
  const linkRe =
    /https?:\/\/www\.daraz\.pk\/products\/[a-z0-9-]+-i\d+[^\s"'<>]*/gi;
  const links = [...html.matchAll(linkRe)].map((m) => m[0].split("?")[0]);
  for (const link of links) {
    if (seen.has(link)) continue;
    const idx = html.indexOf(link);
    const window = html.slice(Math.max(0, idx - 200), idx + 500);
    const titleMatch =
      window.match(/"name"\s*:\s*"([^"]{8,120})"/i) ||
      window.match(/alt="([^"]{8,120})"/i) ||
      window.match(/title="([^"]{8,120})"/i);
    const title = titleMatch ? decodeBasicEntities(titleMatch[1]) : "Daraz listing";
    const priceMatch =
      window.match(/"priceShow"\s*:\s*"([^"]+)"/i) ||
      window.match(/Rs\.?\s*([\d,]+(?:\.\d+)?)/i) ||
      window.match(/"price"\s*:\s*"?([\d,.]+)"?/i);
    const price = priceMatch ? parseDarazPrice(priceMatch[1], html) : "See listing";
    if (query && productMatchScore({ title, link }, query) == null) continue;
    seen.add(link);
    out.push({
      title,
      price: price || "See listing",
      vendor: "Daraz",
      link,
      price_source: price && !isWeakPrice(price) ? "marketplace" : "pending",
    });
    if (out.length >= limit) break;
  }
  return out;
}

/**
 * Parse OLX Pakistan search HTML for item cards.
 * Prefer real ad titles + full item URLs; skip placeholder "Listing" rows.
 */
export function parseOlxCatalog(html, query, { limit = 6 } = {}) {
  if (!html) return [];
  const out = [];
  const seen = new Set();

  const pushRow = (title, link, priceRaw) => {
    const cleanLink = normalizeOlxItemUrl(link);
    if (!cleanLink || seen.has(cleanLink)) return false;
    let cleanTitle = cleanOlxTitle(title) || titleFromOlxUrl(cleanLink);
    if (!cleanTitle || isWeakOlxTitle(cleanTitle)) return false;
    if (query && productMatchScore({ title: cleanTitle, link: cleanLink }, query) == null) {
      return false;
    }
    const price = priceRaw
      ? formatMoneyAmount(parsePriceNumber(priceRaw), "PKR")
      : "See listing";
    seen.add(cleanLink);
    out.push({
      title: cleanTitle,
      price: price || "See listing",
      vendor: "OLX",
      link: cleanLink,
      price_source: price && !isWeakPrice(price) ? "marketplace" : "pending",
    });
    return out.length >= limit;
  };

  // 1) Next.js / embedded JSON (best quality when present)
  const nextMatch = html.match(
    /<script[^>]*id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/i,
  );
  if (nextMatch?.[1]) {
    try {
      const data = JSON.parse(nextMatch[1]);
      const ads = collectOlxAds(data).slice(0, limit * 3);
      for (const ad of ads) {
        const link =
          ad.url ||
          ad.link ||
          (ad.externalID || ad.id
            ? `https://www.olx.com.pk/item/${slugifyOlx(ad.title || "ad")}-iid-${ad.externalID || ad.id}`
            : "");
        const price =
          ad.price?.value?.raw ||
          ad.price?.value ||
          ad.price?.label ||
          ad.price ||
          "";
        if (pushRow(ad.title || ad.description || "", link, String(price))) break;
      }
      if (out.length) return out;
    } catch {
      // fall through to HTML parsing
    }
  }

  // 2) Full item hrefs with slug (title often lives in the URL)
  const hrefRe =
    /https:\/\/www\.olx\.com\.pk\/item\/([a-z0-9-]+)-iid-(\d+)/gi;
  const hrefs = [...html.matchAll(hrefRe)];
  for (const m of hrefs) {
    const link = `https://www.olx.com.pk/item/${m[1]}-iid-${m[2]}`;
    const idx = m.index ?? html.indexOf(m[0]);
    const window = html.slice(Math.max(0, idx - 250), idx + 700);
    const titleMatch =
      window.match(/aria-label="([^"]{8,160})"/i) ||
      window.match(/alt="([^"]{8,160})"/i) ||
      window.match(/<h[123][^>]*>\s*([^<]{8,160})\s*<\/h[123]>/i) ||
      window.match(/"title"\s*:\s*"([^"]{8,160})"/i);
    let title = titleMatch ? decodeBasicEntities(titleMatch[1]) : "";
    if (isWeakOlxTitle(title)) title = titleFromOlxUrl(link);
    const priceMatch = window.match(/Rs\.?\s*([\d,]+(?:\.\d+)?)/i);
    if (pushRow(title, link, priceMatch?.[1])) break;
  }

  return out;
}

function isWeakOlxTitle(title) {
  const t = String(title || "").trim().toLowerCase();
  if (!t || t.length < 6) return true;
  return /^(listing|olx(\s+listing)?|ad|photo|image|product|item|null|undefined)$/i.test(t);
}

function cleanOlxTitle(title) {
  let t = decodeBasicEntities(String(title || "")).replace(/\s+/g, " ").trim();
  t = t.replace(/\s*\|\s*OLX.*$/i, "").trim();
  t = t.replace(/\s*-\s*OLX.*$/i, "").trim();
  return t;
}

function normalizeOlxItemUrl(link) {
  const m = String(link || "").match(
    /https:\/\/www\.olx\.com\.pk\/item\/([a-z0-9-]+)-iid-(\d+)/i,
  );
  if (!m) return "";
  return `https://www.olx.com.pk/item/${m[1]}-iid-${m[2]}`;
}

function titleFromOlxUrl(link) {
  const m = String(link || "").match(/\/item\/([a-z0-9-]+)-iid-\d+/i);
  if (!m) return "";
  const slug = m[1]
    .replace(/-/g, " ")
    .replace(/\b\d+\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (isWeakOlxTitle(slug)) return "";
  return slug.replace(/\b\w/g, (c) => c.toUpperCase());
}

function slugifyOlx(title) {
  return String(title || "ad")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80) || "ad";
}

function collectOlxAds(node, out = []) {
  if (!node || out.length > 40) return out;
  if (Array.isArray(node)) {
    for (const item of node) collectOlxAds(item, out);
    return out;
  }
  if (typeof node !== "object") return out;
  const title = node.title || node.name;
  const hasId = node.externalID || node.id || node.uuid;
  if (title && hasId && (node.price || node.url || node.externalID)) {
    out.push(node);
  }
  for (const val of Object.values(node)) {
    if (val && typeof val === "object") collectOlxAds(val, out);
  }
  return out;
}

export async function fetchDarazCatalog(query, { limit = 6 } = {}) {
  const q = encodeURIComponent(String(query || "").trim());
  if (!q) return [];
  const url = `https://www.daraz.pk/catalog/?q=${q}`;
  console.log(`[marketplace] daraz catalog q="${query}"`);
  const html = await fetchHtml(url);
  if (!html) {
    console.warn("[marketplace] daraz catalog fetch failed");
    return [];
  }
  const rows = parseDarazCatalog(html, query, { limit });
  console.log(`[marketplace] daraz kept ${rows.length}`);
  return rows;
}

export async function fetchOlxCatalog(query, { limit = 6, location = "" } = {}) {
  const q = encodeURIComponent(String(query || "").trim());
  if (!q) return [];
  // OLX Pakistan search
  const url = `https://www.olx.com.pk/items/q-${String(query || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "")}`;
  console.log(`[marketplace] olx catalog q="${query}" loc="${location || ""}"`);
  let html = await fetchHtml(url);
  if (!html || html.length < 2000) {
    // Fallback query-string form
    html = await fetchHtml(`https://www.olx.com.pk/?q=${q}`);
  }
  if (!html) {
    console.warn("[marketplace] olx catalog fetch failed");
    return [];
  }
  const rows = parseOlxCatalog(html, query, { limit });
  console.log(`[marketplace] olx kept ${rows.length}`);
  return rows;
}

/**
 * Run direct marketplace searches for countries without Google Shopping (esp. PK).
 */
export async function fetchDirectMarketplaceListings(productName, { gl, limit = 8, location = "" } = {}) {
  const code = String(gl || "").toLowerCase();
  const q = String(productName || "").trim();
  if (!q) return [];

  if (code === "pk") {
    const per = Math.max(3, Math.ceil(limit / 2));
    const [daraz, olx] = await Promise.all([
      fetchDarazCatalog(q, { limit: per }),
      fetchOlxCatalog(q, { limit: per, location }),
    ]);
    return [...daraz, ...olx].slice(0, limit);
  }
  return [];
}

// Re-export for tests that may want HTML price check after catalog
export { extractPriceFromHtml };
