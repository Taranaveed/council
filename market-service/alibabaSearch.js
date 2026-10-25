/**
 * Direct Alibaba B2B supplier search for bulk / wholesale mode.
 * Uses Google (SerpApi) product-detail hits first; HTML catalog is a best-effort backup.
 */

import { productMatchScore } from "./listingQuality.js";
import { isWeakPrice } from "./pagePrice.js";
import { normalizeListingPrice, sanitizePriceRaw } from "./priceParse.js";

const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

const PRODUCT_URL_RE =
  /https?:\/\/(?:www\.)?alibaba\.com\/product-detail\/([A-Za-z0-9-]+)[_-](\d+)\.html/gi;

const PRICE_RE =
  /(?:US\s*)?\$\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:\s*[-–]\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?)?|\bUSD\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?/i;

export function isAlibabaHost(urlOrHost) {
  return /alibaba\.com/i.test(String(urlOrHost || ""));
}

export function isAlibabaProductUrl(url) {
  return /alibaba\.com\/product-detail\//i.test(String(url || ""));
}

export function alibabaSerpQueries(productName) {
  const q = String(productName || "").trim();
  if (!q) return [];
  return [
    `${q} site:alibaba.com/product-detail`,
    `${q} wholesale MOQ site:alibaba.com`,
  ];
}

function slugToTitle(slug) {
  const words = String(slug || "")
    .replace(/-/g, " ")
    .replace(/\b\d+\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!words || words.length < 4) return "";
  return words.replace(/\b\w/g, (c) => c.toUpperCase());
}

export function normalizeAlibabaProductUrl(url) {
  const m = String(url || "").match(
    /https?:\/\/(?:www\.)?alibaba\.com\/product-detail\/([A-Za-z0-9-]+)[_-](\d+)\.html/i,
  );
  if (!m) return "";
  return `https://www.alibaba.com/product-detail/${m[1]}_${m[2]}.html`;
}

function titleFromAlibabaUrl(url) {
  const m = String(url || "").match(/\/product-detail\/([A-Za-z0-9-]+)[_-]\d+\.html/i);
  return m ? slugToTitle(m[1]) : "";
}

async function fetchHtml(url, { timeoutMs = 5000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: "GET",
      redirect: "follow",
      signal: controller.signal,
      headers: {
        "User-Agent": BROWSER_UA,
        Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
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

export function parseAlibabaCatalog(html, query, { limit = 10 } = {}) {
  if (!html) return [];
  const seen = new Set();
  const out = [];
  const q = String(query || "").trim();

  for (const match of html.matchAll(PRODUCT_URL_RE)) {
    const link = normalizeAlibabaProductUrl(match[0]);
    if (!link || seen.has(link)) continue;
    seen.add(link);
    const start = Math.max(0, match.index - 180);
    const around = html.slice(start, match.index + match[0].length + 280);
    const priceHit = around.match(PRICE_RE)?.[0];
    const title =
      titleFromAlibabaUrl(link) ||
      String(around.match(/title="([^"]{8,120})"/i)?.[1] || "").trim() ||
      "Alibaba listing";
    const norm = priceHit
      ? normalizeListingPrice(sanitizePriceRaw(priceHit), "USD")
      : { price: "See listing", rejected: false };
    const row = {
      title,
      price: norm.price || "See listing",
      vendor: "Alibaba",
      link,
      price_source: priceHit && !norm.rejected ? "snippet" : "pending",
      wholesale: true,
    };
    if (norm.rejected || norm.unreliable) {
      row.unit_price_unreliable = true;
      row.needs_price_confirm = true;
      if (norm.rejected) {
        row.price = "See listing";
        row.counts_as_live_listing = false;
      }
    }
    if (q && productMatchScore(row, q) == null) continue;
    out.push(row);
    if (out.length >= limit) break;
  }
  return out;
}

export async function fetchAlibabaCatalog(query, { limit = 10 } = {}) {
  const q = String(query || "").trim();
  if (!q) return [];
  const encoded = encodeURIComponent(q);
  const urls = [
    `https://www.alibaba.com/trade/search?fsb=y&IndexArea=product_en&SearchText=${encoded}`,
    `https://www.alibaba.com/trade/search?SearchText=${encoded}`,
  ];
  console.log(`[alibaba] catalog q="${q}"`);
  for (const url of urls) {
    const html = await fetchHtml(url);
    if (!html || html.length < 1500) continue;
    const rows = parseAlibabaCatalog(html, q, { limit });
    if (rows.length) {
      console.log(`[alibaba] catalog kept ${rows.length}`);
      return rows;
    }
  }
  console.warn("[alibaba] catalog fetch returned no product-detail links");
  return [];
}

/**
 * Prefer real product pages over Alibaba category / search hubs.
 */
export function decorateAlibabaListings(rows) {
  return (rows || [])
    .map((row) => {
      const link = normalizeAlibabaProductUrl(row.link) || String(row.link || "");
      const title =
        String(row.title || "").trim() &&
        !/^(listing|alibaba|unknown|see listing)$/i.test(String(row.title || "").trim())
          ? row.title
          : titleFromAlibabaUrl(link) || row.title;
      return {
        ...row,
        title,
        link,
        vendor: row.vendor && !/^web result$/i.test(row.vendor) ? row.vendor : "Alibaba",
        wholesale: true,
      };
    })
    .filter((row) => isAlibabaProductUrl(row.link) || isAlibabaHost(row.link));
}

export function alibabaListingsNeedPrice(row) {
  return isAlibabaHost(row?.link) && isWeakPrice(row?.price);
}
