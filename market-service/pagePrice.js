/**
 * Fetch a seller listing page and extract a product price from JSON-LD / meta / HTML.
 * Best-effort only — never invents sellers or prices when extraction fails.
 */

import { productMatchScore } from "./listingQuality.js";
import { detectCurrency } from "./currency.js";
import {
  formatMoneyAmount,
  maybeUnscaleMarketplacePrice,
  parsePriceNumber,
} from "./priceParse.js";

const PRICE_RE =
  /(?:Rs\.?|PKR|USD|INR|AED|SAR|EUR|GBP)\s*[\d,]+(?:\.\d+)?|\$\s*[\d,]+(?:\.\d+)?|£\s*[\d,]+(?:\.\d+)?|€\s*[\d,]+(?:\.\d+)?|\b[\d,]+(?:\.\d+)?\s*(?:Rs\.?|PKR)\b/i;

const WEAK_PRICE_RE =
  /^(n\/?a|see listing|unknown|\.?\s*rs\.?|null|undefined|-|—)?$/i;

const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

const BROWSER_HEADERS = {
  "User-Agent": BROWSER_UA,
  Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
  "Accept-Language": "en-PK,en-US;q=0.9,en;q=0.8,ur;q=0.7",
  "Cache-Control": "no-cache",
  Pragma: "no-cache",
  "Upgrade-Insecure-Requests": "1",
  "Sec-Fetch-Dest": "document",
  "Sec-Fetch-Mode": "navigate",
  "Sec-Fetch-Site": "none",
  "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
  "Sec-Ch-Ua-Mobile": "?0",
  "Sec-Ch-Ua-Platform": '"Windows"',
};

/** Once Chromium is missing, skip Playwright for the rest of the process. */
let playwrightUnavailable = false;

export function isWeakPrice(price) {
  const text = String(price ?? "").trim();
  if (!text) return true;
  if (WEAK_PRICE_RE.test(text)) return true;
  if (/^(rs\.?|pkr|usd|\$|£|€)[\s,.…]*$/i.test(text)) return true;
  if (!/\d/.test(text)) return true;
  return false;
}

function formatMoney(amount, currency) {
  return formatMoneyAmount(amount, currency);
}

function walkJsonLd(node, out) {
  if (!node) return;
  if (Array.isArray(node)) {
    for (const item of node) walkJsonLd(item, out);
    return;
  }
  if (typeof node !== "object") return;

  const type = node["@type"];
  const types = Array.isArray(type) ? type : type ? [type] : [];
  const isProductish = types.some((t) =>
    /product|offer|aggregateoffer/i.test(String(t)),
  );

  if (isProductish || node.offers || node.price) {
    out.push(node);
  }
  if (node.offers) walkJsonLd(node.offers, out);
  if (node["@graph"]) walkJsonLd(node["@graph"], out);
}

function priceFromOfferLike(obj, { html = "", url = "", defaultCurrency = "USD" } = {}) {
  if (!obj || typeof obj !== "object") return null;
  const offer = Array.isArray(obj.offers) ? obj.offers[0] : obj.offers || obj;
  const currency =
    (offer && offer.priceCurrency) || obj.priceCurrency || obj.currency || defaultCurrency;

  const fromVal = (val) => {
    if (val == null) return null;
    let n = parsePriceNumber(val);
    if (n == null && typeof val === "number") n = val;
    if (n == null) return null;
    n = maybeUnscaleMarketplacePrice(n, String(val), { html, url });
    return formatMoney(n, currency);
  };

  if (!offer || typeof offer !== "object") {
    return fromVal(obj.price);
  }
  if (offer.lowPrice != null) return fromVal(offer.lowPrice);
  if (offer.price != null) return fromVal(offer.price);
  if (Array.isArray(offer) && offer[0]) {
    return priceFromOfferLike(offer[0], { html, url, defaultCurrency });
  }
  return null;
}

function extractFromJsonLd(html, url = "", defaultCurrency = "USD") {
  const scripts = [
    ...html.matchAll(
      /<script[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi,
    ),
  ];
  for (const match of scripts) {
    try {
      const raw = match[1].trim();
      if (!raw) continue;
      const data = JSON.parse(raw);
      const nodes = [];
      walkJsonLd(data, nodes);
      for (const node of nodes) {
        const price = priceFromOfferLike(node, { html, url, defaultCurrency });
        if (price) return price;
      }
    } catch {
      // ignore malformed JSON-LD
    }
  }
  return null;
}

function metaContent(html, key) {
  const patterns = [
    new RegExp(
      `<meta[^>]+(?:property|name)=["']${key}["'][^>]+content=["']([^"']+)["']`,
      "i",
    ),
    new RegExp(
      `<meta[^>]+content=["']([^"']+)["'][^>]+(?:property|name)=["']${key}["']`,
      "i",
    ),
  ];
  for (const re of patterns) {
    const m = html.match(re);
    if (m?.[1]) return m[1].trim();
  }
  return null;
}

function extractFromMeta(html, url = "", defaultCurrency = "USD") {
  const amount =
    metaContent(html, "product:price:amount") ||
    metaContent(html, "og:price:amount") ||
    metaContent(html, "twitter:data1");
  const currency =
    metaContent(html, "product:price:currency") ||
    metaContent(html, "og:price:currency") ||
    "";
  if (amount && /\d/.test(amount)) {
    if (/[Rs$£€₹]|PKR|USD|INR|AED|SAR|EUR|GBP/i.test(amount)) return amount;
    let n = parsePriceNumber(amount);
    if (n == null) return null;
    n = maybeUnscaleMarketplacePrice(n, amount, { html, url });
    return formatMoney(n, currency || defaultCurrency) || amount;
  }
  return null;
}

function extractFromDataAttrs(html, url = "", defaultCurrency = "USD") {
  // Prefer human-facing priceShow / display fields before raw integer "price" (often ×100 on Daraz)
  const preferPatterns = [
    /"priceShow"\s*:\s*"([^"]+)"/i,
    /"displayPrice"\s*:\s*"([^"]+)"/i,
    /"priceDisp"\s*:\s*"([^"]+)"/i,
    /data-price-show=["']([^"']+)["']/i,
  ];
  for (const re of preferPatterns) {
    const m = html.match(re);
    if (m?.[1] && /\d/.test(m[1])) {
      let n = parsePriceNumber(m[1]);
      if (n == null) continue;
      n = maybeUnscaleMarketplacePrice(n, m[1], { html, url });
      const cur = /rs|pkr/i.test(m[1]) ? "PKR" : defaultCurrency;
      return formatMoney(n, cur);
    }
  }

  const patterns = [
    /data-price=["']([\d,.]+)["']/i,
    /data-price-amount=["']([\d,.]+)["']/i,
    /itemprop=["']price["'][^>]*content=["']([\d,.]+)["']/i,
    /content=["']([\d,.]+)["'][^>]*itemprop=["']price["']/i,
    /"price"\s*:\s*"?([\d,.]+)"?/i,
  ];
  for (const re of patterns) {
    const m = html.match(re);
    if (m?.[1] && /\d/.test(m[1])) {
      let n = parsePriceNumber(m[1]);
      if (n == null) continue;
      n = maybeUnscaleMarketplacePrice(n, m[1], { html, url });
      if (/rs|pkr/i.test(m[0])) return formatMoney(n, "PKR");
      return formatMoney(n, defaultCurrency);
    }
  }
  return null;
}

function extractFromHtmlText(html, defaultCurrency = "USD") {
  const text = html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .slice(0, 25000);
  const matches = [...text.matchAll(new RegExp(PRICE_RE.source, "gi"))]
    .map((m) => m[0].trim())
    .filter(Boolean);
  if (!matches.length) return null;

  const scored = matches
    .map((raw) => {
      const n = parsePriceNumber(raw);
      let score = 0;
      if (n == null) return null;
      if (n >= 1500 && n <= 500000) score += 5;
      else if (n >= 50 && n < 1500) score += 1;
      else score -= 3;
      if (/rs\.?|pkr|\$|£|€|inr|aed/i.test(raw)) score += 2;
      // Prefer tokens that already look like normal decimals, not inflated integers
      if (/\.\d{2}\b/.test(raw) && n < 100000) score += 3;
      return { raw, n, score };
    })
    .filter(Boolean)
    .sort((a, b) => b.score - a.score || a.n - b.n);
  const best = scored[0];
  if (!best) return null;
  const cur = /rs|pkr/i.test(best.raw)
    ? "PKR"
    : /\$|usd/i.test(best.raw)
      ? "USD"
      : /£|gbp/i.test(best.raw)
        ? "GBP"
        : /€|eur/i.test(best.raw)
          ? "EUR"
          : defaultCurrency;
  return formatMoney(best.n, cur);
}

export function extractPriceFromHtml(html, url = "", defaultCurrency = "USD") {
  if (!html || typeof html !== "string") return null;
  const cur = String(defaultCurrency || "USD").toUpperCase() || "USD";
  return (
    extractFromJsonLd(html, url, cur) ||
    extractFromMeta(html, url, cur) ||
    extractFromDataAttrs(html, url, cur) ||
    extractFromHtmlText(html, cur)
  );
}

function needsBrowser(url) {
  return /daraz\.|olx\.com\.pk|priceoye\.|homeshopping\./i.test(String(url || ""));
}

async function fetchHtmlSimple(url, { timeoutMs = 8000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, {
      method: "GET",
      redirect: "follow",
      signal: controller.signal,
      headers: BROWSER_HEADERS,
    });
    if (!res.ok) return { ok: false, status: res.status, html: null };
    const contentType = String(res.headers.get("content-type") || "");
    if (contentType && !/html|text|json/i.test(contentType)) {
      return { ok: false, status: res.status, html: null };
    }
    const html = await res.text();
    return { ok: true, status: res.status, html };
  } catch {
    return { ok: false, status: 0, html: null };
  } finally {
    clearTimeout(timer);
  }
}

async function fetchHtmlWithPlaywright(url, { timeoutMs = 15000 } = {}) {
  if (playwrightUnavailable) return null;
  let playwright;
  try {
    playwright = await import("playwright");
  } catch {
    playwrightUnavailable = true;
    return null;
  }
  let browser;
  try {
    browser = await playwright.chromium.launch({
      headless: true,
      args: ["--disable-blink-features=AutomationControlled"],
    });
    const page = await browser.newPage({
      userAgent: BROWSER_UA,
      locale: "en-PK",
      extraHTTPHeaders: {
        "Accept-Language": "en-PK,en;q=0.9",
      },
    });
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: timeoutMs });
    // Give SPAs a moment to hydrate price
    await page.waitForTimeout(1200);
    const html = await page.content();
    return html;
  } catch (err) {
    const msg = String(err?.message || err || "");
    if (/Executable doesn't exist|browserType\.launch/i.test(msg)) {
      playwrightUnavailable = true;
      console.warn(
        "[pagePrice] Playwright browser missing — skipping browser enrich. Run: npx playwright install chromium",
      );
    } else {
      console.warn(`[pagePrice] playwright failed: ${err?.message || err}`);
    }
    return null;
  } finally {
    if (browser) {
      try {
        await browser.close();
      } catch {
        /* ignore */
      }
    }
  }
}

function cleanPageTitle(raw) {
  let t = String(raw || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  t = t.replace(/\s*\|\s*OLX.*$/i, "").trim();
  t = t.replace(/\s*-\s*OLX.*$/i, "").trim();
  t = t.replace(/\s*\|\s*Daraz.*$/i, "").trim();
  t = t.replace(/\s*-\s*Buy Online.*$/i, "").trim();
  return t;
}

export function isWeakTitle(title) {
  const t = String(title || "").trim().toLowerCase();
  if (!t || t.length < 6) return true;
  return /^(listing|olx(\s+listing)?|daraz(\s+listing)?|ad|photo|image|product|item|unknown|null|undefined|see listing)$/i.test(
    t,
  );
}

function extractPageTitle(html) {
  if (!html) return "";
  const og =
    html.match(/property=["']og:title["'][^>]*content=["']([^"']{6,200})["']/i) ||
    html.match(/content=["']([^"']{6,200})["'][^>]*property=["']og:title["']/i);
  if (og?.[1]) {
    const t = cleanPageTitle(og[1]);
    if (!isWeakTitle(t)) return t;
  }
  const titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  const fromTitle = cleanPageTitle(titleMatch?.[1] || "");
  if (!isWeakTitle(fromTitle)) return fromTitle;
  const h1 = html.match(/<h1[^>]*>\s*([^<]{6,200})\s*<\/h1>/i);
  return cleanPageTitle(h1?.[1] || "");
}

function pageMatchesQuery(html, url, query) {
  if (!query) return true;
  const pageTitle = extractPageTitle(html);
  const head = html.slice(0, 8000);
  const probe = { title: pageTitle, link: url };
  if (productMatchScore(probe, query) == null) {
    if (productMatchScore({ title: head, link: url }, query) == null) {
      return false;
    }
  }
  return true;
}

/**
 * Fetch listing page details (price + title). Returns null when page doesn't match query.
 */
export async function fetchPageDetails(
  url,
  { timeoutMs = 8000, query = "", allowPlaywright = true, defaultCurrency = "USD" } = {},
) {
  if (!url || !/^https?:\/\//i.test(url)) return null;

  const tryHtml = (html) => {
    if (!html || !pageMatchesQuery(html, url, query)) return null;
    const title = extractPageTitle(html);
    const price = extractPriceFromHtml(html, url, defaultCurrency);
    if ((!price || isWeakPrice(price)) && isWeakTitle(title)) return null;
    return {
      price: price && !isWeakPrice(price) ? price : null,
      title: title && !isWeakTitle(title) ? title : null,
    };
  };

  let html = null;
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    const result = await fetchHtmlSimple(url, { timeoutMs });
    if (result.html && result.html.length > 400) {
      html = result.html;
      break;
    }
    if (attempt < 2) await new Promise((r) => setTimeout(r, 400 * attempt));
  }

  let details = tryHtml(html);
  if (details && (details.price || details.title)) return details;

  if (allowPlaywright && needsBrowser(url)) {
    const pwHtml = await fetchHtmlWithPlaywright(url, { timeoutMs: Math.max(timeoutMs, 12000) });
    details = tryHtml(pwHtml);
    if (details && (details.price || details.title)) return details;
  }

  return null;
}

export async function fetchPagePrice(url, opts = {}) {
  const details = await fetchPageDetails(url, opts);
  return details?.price || null;
}

/**
 * Enrich listings by opening seller pages when price is weak (or for top N).
 * Prefers local-marketplace hosts and weak prices; fetches with a small semaphore.
 */
export async function enrichListingsWithPagePrices(
  listings,
  { maxFetches = 6, gl, query = "", preferredCurrency = null, concurrency = 3 } = {},
) {
  if (!Array.isArray(listings) || !listings.length) return listings || [];

  const code = String(gl || "").toLowerCase();
  const localHostRe =
    code === "pk"
      ? /daraz\.|olx\.|priceoye\.|homeshopping\.|telemart\.|shophive\.|\.pk(\/|$)/i
      : code === "in"
        ? /amazon\.in|flipkart\.|indiamart\./i
        : /amazon\.|ebay\.|walmart\.|bestbuy\.|noon\./i;

  const ranked = listings.map((item, index) => {
    const link = String(item.link || "");
    const weak = isWeakPrice(item.price);
    const weakTitle = isWeakTitle(item.title);
    const localHost = localHostRe.test(link);
    const foreignHint = /\$|usd|£|€/i.test(String(item.price || ""));
    let priority = 0;
    if (weak) priority += 40;
    if (weakTitle) priority += 45;
    if (localHost) priority += 30;
    if (String(item.price_source || "") === "pending") priority += 15;
    if (foreignHint && preferredCurrency && String(preferredCurrency).toUpperCase() === "PKR") {
      priority -= 20;
    }
    if (item.price_source === "snippet") priority += 10;
    return { item, index, weak, priority };
  });
  ranked.sort((a, b) => b.priority - a.priority || a.index - b.index);

  const toFetch = ranked.slice(0, maxFetches);
  const updates = new Map();
  const drop = new Set();
  const concurrencyLimit = Math.max(1, Math.min(concurrency, toFetch.length || 1));

  let cursor = 0;
  async function worker() {
    while (cursor < toFetch.length) {
      const my = cursor;
      cursor += 1;
      const job = toFetch[my];
      if (!job) return;
      const { item, index } = job;
      const link = String(item.link || "");
      if (/\/tag\//i.test(link) || /instagram|tiktok|facebook|youtube/i.test(link)) {
        continue;
      }
      // Google Shopping intermediate pages are not real product pages — keep SERP price
      if (/google\.[^/\s]+\/search/i.test(link) && /(?:ibp=oshop|tbm=shop)/i.test(link)) {
        continue;
      }
      // Weak titles skip pre-check — page title is the real match signal
      if (!isWeakTitle(item.title) && query && productMatchScore(item, query) == null) {
        continue;
      }
      const defaultCurrency =
        String(preferredCurrency || "").toUpperCase() ||
        (code === "pk" ? "PKR" : code === "uk" || code === "gb" ? "GBP" : "USD");
      const details = await fetchPageDetails(item.link, {
        query,
        defaultCurrency,
      });
      if (!details) {
        if (isWeakTitle(item.title)) drop.add(index);
        continue;
      }
      const pagePrice = details.price;
      const pageTitle = details.title;
      if (pagePrice && !isWeakPrice(pagePrice)) {
        const digits = Number(String(pagePrice).replace(/,/g, "").replace(/[^\d.]/g, ""));
        if (code === "pk" && digits > 0 && digits < 1000) continue;
        const title = String(pageTitle || item.title || "");
        if (digits && new RegExp(`under\\s*${Math.round(digits)}`, "i").test(title)) continue;

        // Never replace a good snippet price with a wrong-currency page scrape
        const expected = String(preferredCurrency || "").toUpperCase();
        const snippetOk = !isWeakPrice(item.price);
        const pageCur = detectCurrency(pagePrice);
        const snippetCur = detectCurrency(item.price);
        if (
          snippetOk &&
          expected &&
          pageCur &&
          pageCur !== expected &&
          (!snippetCur || snippetCur === expected)
        ) {
          if (pageTitle && isWeakTitle(item.title)) {
            updates.set(index, { title: pageTitle });
          }
          continue;
        }

        updates.set(index, {
          price: pagePrice,
          price_source: "page",
          ...(pageTitle ? { title: pageTitle } : {}),
        });
      } else if (pageTitle && isWeakTitle(item.title)) {
        updates.set(index, { title: pageTitle });
      } else if (isWeakTitle(item.title) && !pageTitle) {
        drop.add(index);
      }
    }
  }

  await Promise.all(Array.from({ length: concurrencyLimit }, () => worker()));

  return listings
    .map((item, index) => {
      if (drop.has(index)) return null;
      const patch = updates.get(index);
      let next = patch ? { ...item, ...patch } : { ...item };
      if (isWeakTitle(next.title)) {
        const fromLink = titleFromMarketplaceUrl(next.link);
        if (fromLink) next = { ...next, title: fromLink };
      }
      if (isWeakTitle(next.title)) return null;
      if (query && productMatchScore(next, query) == null) return null;
      if (!patch) {
        next.price_source = isWeakPrice(next.price)
          ? next.price_source || "snippet"
          : next.price_source || "serp";
      }
      return next;
    })
    .filter(Boolean);
}

function titleFromMarketplaceUrl(link) {
  const slug =
    String(link || "").match(/\/item\/([a-z0-9-]+)-iid-\d+/i)?.[1] ||
    String(link || "").match(/\/products\/([a-z0-9-]+)/i)?.[1] ||
    "";
  if (!slug) return "";
  const words = slug
    .replace(/-/g, " ")
    .replace(/\b\d+\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!words || isWeakTitle(words) || words.length < 6) return "";
  return words.replace(/\b\w/g, (c) => c.toUpperCase());
}
