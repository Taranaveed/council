/**
 * Shared money parsing — never treat decimal points as thousands separators.
 */

/**
 * Detect concatenated / ambiguous scrapes like "$1.321,000" (unit + MOQ glued)
 * or "$1.32-1,000" stored as a single token. These are not valid unit prices.
 */
export function isMalformedPriceString(raw) {
  const s = String(raw ?? "").trim();
  if (!s) return false;
  // Range stored as one price without normalization
  if (/[-–—]\s*[\d$]/.test(s) && /\$|USD|Rs|PKR/i.test(s)) return true;
  const digits = s
    .replace(/(?:Rs\.?|PKR|USD|INR|AED|SAR|EUR|GBP|\$|€|£|₹)/gi, " ")
    .replace(/[^\d.,]/g, "")
    .replace(/^[.,]+/, "");
  if (!digits) return false;
  // Both `.` and `,` with 3 digits after the comma → classic "$1.321,000" concat
  if (/^\d+\.\d+,\d{3}$/.test(digits)) return true;
  // More than one comma AND a decimal point (ambiguous)
  if ((digits.match(/,/g) || []).length > 1 && digits.includes(".")) return true;
  // Trailing ,000 after a decimal amount often means MOQ glued on
  if (/^\d+\.\d{1,2},000$/.test(digits)) return true;
  return false;
}

/**
 * If a range like "$1.32-1.55" or concat "$1.321,000", keep the first sane unit token.
 */
export function sanitizePriceRaw(raw) {
  const s = String(raw ?? "").trim();
  if (!s) return s;
  // Prefer first side of an explicit range
  const range = s.match(
    /^((?:US\s*)?(?:\$|USD|Rs\.?|PKR|€|£)\s*[\d,.]+)\s*[-–—]\s*[\d,.]+/i,
  );
  if (range) return range[1].trim();
  if (!isMalformedPriceString(s)) return s;
  // "$1.321,000" → take "$1.32" (drop glued thousands that look like MOQ)
  const m = s.match(
    /((?:US\s*)?(?:\$|USD|Rs\.?|PKR|€|£)\s*\d+\.\d{1,2})(?:,\d{3})/i,
  );
  if (m) return m[1].trim();
  const m2 = s.match(/((?:US\s*)?(?:\$|USD)\s*\d+\.\d{1,2})/i);
  if (m2) return m2[1].trim();
  return s;
}

/**
 * Parse a free-text / JSON price into a number.
 * "9500.00" → 9500, "9,500.00" → 9500, "9.500,00" → 9500.
 * Does NOT strip '.' digits (that bug turns 9500.00 into 950000).
 */
export function parsePriceNumber(raw) {
  const cleaned = sanitizePriceRaw(raw);
  let s = String(cleaned ?? "").trim();
  if (!s) return null;
  // After sanitize, still reject residual malformations rather than invent a number
  const digitOnly = s
    .replace(/(?:Rs\.?|PKR|USD|INR|AED|SAR|EUR|GBP|\$|€|£|₹)/gi, "")
    .replace(/[^\d.,]/g, "");
  if (/^\d+\.\d+,\d{3}$/.test(digitOnly)) {
    const first = s.match(/\d+\.\d{1,2}/);
    if (first) s = first[0];
    else return null;
  }
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

  // US / PK grouping with optional decimals: 1,234.56 or 9,500 or 1,569
  if (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(s)) {
    const n = Number(s.replace(/,/g, ""));
    return Number.isFinite(n) && n > 0 ? n : null;
  }
  // Also accept looser thousands: 12,34,567 (rare) — strip commas if every group is 3 digits after first
  if (/^\d{1,3}(,\d{3})+$/.test(s)) {
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

  // Reject ambiguous "1.321,000" rather than inventing 1321
  if (/^\d+\.\d+,\d{3}$/.test(s)) return null;

  // Fallback: last separator wins as decimal — but NEVER treat "1,569" as 1.569
  if (lastDot > lastComma) {
    const n = Number(s.replace(/,/g, ""));
    return Number.isFinite(n) && n > 0 ? n : null;
  }
  if (lastComma > lastDot) {
    // ",XXX" thousand groups → strip commas; short ",XX" → EU decimal
    if (/^\d{1,3}(,\d{3})+$/.test(s) || /^\d+,\d{3}(,\d{3})*$/.test(s)) {
      const n = Number(s.replace(/,/g, ""));
      return Number.isFinite(n) && n > 0 ? n : null;
    }
    const n = Number(s.replace(/\./g, "").replace(",", "."));
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  // Strip all commas — never stop at the first comma
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

export function formatMoneyAmount(amount, currency) {
  if (currency == null || String(currency).trim() === "") {
    throw new Error("formatMoneyAmount requires an explicit currency (no PKR default)");
  }
  const n = typeof amount === "number" ? amount : parsePriceNumber(amount);
  if (n == null || !Number.isFinite(n)) return null;
  const cur = String(currency).toUpperCase();
  if (cur === "USD" || cur === "$") {
    return n >= 10 ? `$${Math.round(n).toLocaleString("en-US")}` : `$${n.toFixed(2)}`;
  }
  if (cur === "GBP" || cur === "£") {
    return n >= 10 ? `£${Math.round(n).toLocaleString("en-US")}` : `£${n.toFixed(2)}`;
  }
  if (cur === "EUR" || cur === "€") {
    return n >= 10 ? `€${Math.round(n).toLocaleString("en-US")}` : `€${n.toFixed(2)}`;
  }
  const rounded = Math.round(n);
  if (cur === "PKR" || cur === "RS") return `Rs ${rounded.toLocaleString("en-US")}`;
  if (cur === "INR") return `₹${rounded.toLocaleString("en-US")}`;
  return `${cur} ${rounded.toLocaleString("en-US")}`;
}

/**
 * Normalize a listing price field: reject malformed concatenations, re-format cleanly.
 */
export function normalizeListingPrice(raw, currency = "USD") {
  const original = String(raw ?? "").trim();
  if (!original || /^(see listing|n\/?a)/i.test(original)) {
    return { price: original || "See listing", rejected: false };
  }
  if (isMalformedPriceString(original)) {
    const sanitized = sanitizePriceRaw(original);
    const n = parsePriceNumber(sanitized);
    if (n == null) {
      return {
        price: "See listing",
        rejected: true,
        reason: "malformed_price_string",
        original,
      };
    }
    const cur =
      /rs\.?|pkr/i.test(original) ? "PKR" :
      /₹|inr/i.test(original) ? "INR" :
      currency || "USD";
    const formatted = formatMoneyAmount(n, cur) || formatMoneyAmount(n, "USD");
    return {
      price: formatted,
      rejected: false,
      unreliable: true,
      reason: "malformed_price_rescued",
      original,
    };
  }
  const n = parsePriceNumber(original);
  if (n == null) {
    return { price: "See listing", rejected: true, reason: "unparseable", original };
  }
  const cur =
    /\$|usd|us\s*\$/i.test(original) ? "USD" :
    /rs\.?|pkr/i.test(original) ? "PKR" :
    /₹|inr/i.test(original) ? "INR" :
    /£|gbp/i.test(original) ? "GBP" :
    /€|eur/i.test(original) ? "EUR" :
    currency || "USD";
  return {
    price: formatMoneyAmount(n, cur) || original,
    rejected: false,
  };
}
