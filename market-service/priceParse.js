/**
 * Shared money parsing — never treat decimal points as thousands separators.
 */

/**
 * Parse a free-text / JSON price into a number.
 * "9500.00" → 9500, "9,500.00" → 9500, "9.500,00" → 9500.
 * Does NOT strip '.' digits (that bug turns 9500.00 into 950000).
 */
export function parsePriceNumber(raw) {
  let s = String(raw ?? "").trim();
  if (!s) return null;
  // Strip currency labels first so "Rs." doesn't leave a stray "."
  s = s
    .replace(
      /(?:Rs\.?|PKR|USD|INR|AED|SAR|EUR|GBP|\$|€|£|₹)/gi,
      " ",
    )
    .trim();
  s = s.replace(/[^\d.,]/g, "");
  if (!s) return null;
  // Leading separator junk from "Rs. 9,500" → ".9,500"
  s = s.replace(/^[.,]+/, "");
  if (!s) return null;

  const lastDot = s.lastIndexOf(".");
  const lastComma = s.lastIndexOf(",");

  // US / PK grouping with optional decimals: 1,234.56 or 9,500
  if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(s)) {
    const n = Number(s.replace(/,/g, ""));
    return Number.isFinite(n) && n > 0 ? n : null;
  }
  // Plain decimal or integer: 9500.00 / 9500
  if (/^\d+(\.\d+)?$/.test(s)) {
    const n = Number(s);
    return Number.isFinite(n) && n > 0 ? n : null;
  }
  // EU grouping: 1.234,56
  if (/^\d{1,3}(\.\d{3})+(,\d+)?$/.test(s)) {
    const n = Number(s.replace(/\./g, "").replace(",", "."));
    return Number.isFinite(n) && n > 0 ? n : null;
  }
  // EU decimal without grouping: 9500,00
  if (/^\d+,\d{1,2}$/.test(s)) {
    const n = Number(s.replace(",", "."));
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  // Fallback: last separator wins as decimal
  if (lastDot > lastComma) {
    const n = Number(s.replace(/,/g, ""));
    return Number.isFinite(n) && n > 0 ? n : null;
  }
  if (lastComma > lastDot) {
    // Ambiguous "9,500" already handled above; remaining likely EU
    const n = Number(s.replace(/\./g, "").replace(",", "."));
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  const n = Number(s.replace(/,/g, ""));
  return Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * Daraz/Lazada often store integer minor units (paisa): 950000 means Rs 9500.00.
 * Only apply when the raw token had no decimal point.
 */
export function maybeUnscaleMarketplacePrice(n, raw, { html = "", url = "" } = {}) {
  if (!Number.isFinite(n) || n <= 0) return n;
  const rawStr = String(raw ?? "");
  const cleaned = rawStr.replace(/[^\d.,]/g, "");
  // Source already had an explicit decimal — trust it
  if (/\.\d{1,2}$/.test(cleaned) || /,\d{1,2}$/.test(cleaned)) return n;

  const isMarketplace = /daraz\.|lazada\.|aliexpress\./i.test(String(url || "") + String(html || "").slice(0, 2000));
  if (!isMarketplace && !html) return n;

  // Integer minor units: divisible by 100, looks like cents
  if (!Number.isInteger(n) || n < 10000 || n % 100 !== 0) return n;

  const major = n / 100;
  const majorInt = Math.round(major);
  const hay = String(html || "");
  const majorFixed = major.toFixed(2); // "9500.00"
  const majorComma = majorInt.toLocaleString("en-US"); // "9,500"

  const displayHints =
    hay.includes(majorFixed) ||
    new RegExp(`Rs\\.?\\s*${majorComma}\\b`, "i").test(hay) ||
    new RegExp(`Rs\\.?\\s*${majorInt}\\b`, "i").test(hay) ||
    new RegExp(`"priceShow"\\s*:\\s*"[^"]*${majorInt}`, "i").test(hay);

  if (displayHints || (isMarketplace && major >= 50 && major <= 5_000_000)) {
    // For marketplace JSON integers, prefer unscaled when in a sane retail range
    if (displayHints) return major;
    if (isMarketplace && n >= 100_000) return major;
  }
  return n;
}

export function formatMoneyAmount(amount, currency = "PKR") {
  const n = typeof amount === "number" ? amount : parsePriceNumber(amount);
  if (n == null || !Number.isFinite(n)) return null;
  const cur = String(currency || "PKR").toUpperCase();
  const rounded = Math.round(n);
  if (cur === "PKR" || cur === "RS") return `Rs ${rounded.toLocaleString("en-US")}`;
  if (cur === "USD" || cur === "$") return `$${rounded.toLocaleString("en-US")}`;
  if (cur === "GBP" || cur === "£") return `£${rounded.toLocaleString("en-US")}`;
  if (cur === "EUR" || cur === "€") return `€${rounded.toLocaleString("en-US")}`;
  if (cur === "INR") return `₹${rounded.toLocaleString("en-US")}`;
  return `${cur} ${rounded.toLocaleString("en-US")}`;
}
