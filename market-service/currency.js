/**
 * Currency detection + rough FX for comparing international listings to local markets.
 * Rates are approximate display aids — never treat as live FX.
 */

import { formatMoneyAmount, parsePriceNumber } from "./priceParse.js";

const TO_USD = {
  USD: 1,
  PKR: 1 / 278,
  INR: 1 / 83,
  AED: 1 / 3.67,
  SAR: 1 / 3.75,
  GBP: 1.27,
  EUR: 1.08,
  CAD: 0.74,
};

const GL_CURRENCY = {
  pk: "PKR",
  in: "INR",
  us: "USD",
  ca: "CAD",
  uk: "GBP",
  gb: "GBP",
  ae: "AED",
  sa: "SAR",
  fr: "EUR",
  de: "EUR",
  es: "EUR",
  it: "EUR",
  nl: "EUR",
  ie: "EUR",
};

export function expectedCurrencyForGl(gl, profile = null) {
  if (profile?.currency) return String(profile.currency).toUpperCase();
  return GL_CURRENCY[String(gl || "").toLowerCase()] || "USD";
}

export function detectCurrency(priceText) {
  const text = String(priceText || "");
  if (/rs\.?|pkr/i.test(text)) return "PKR";
  if (/₹|inr/i.test(text)) return "INR";
  if (/aed/i.test(text)) return "AED";
  if (/sar/i.test(text)) return "SAR";
  if (/£|gbp/i.test(text)) return "GBP";
  if (/€|eur/i.test(text)) return "EUR";
  if (/c\$|cad/i.test(text)) return "CAD";
  if (/\$|usd|us\s*\$/i.test(text)) return "USD";
  return null;
}

const FACTORY_USD_HOST =
  /alibaba\.|dhgate\.|made-in-china\.|globalsources\.|aliexpress\.|1688\./i;

/**
 * Factory/B2B pages quote USD even when the snippet has no $ sign ("0.59").
 * Treating that as PKR makes $0.59 look like "Rs 1".
 * Also: SERP sometimes mislabels factory amounts as "Rs 4" — reinterpret as USD.
 */
export function inferListingCurrency(listing, gl, preferredCurrency) {
  const link = `${listing?.link || ""} ${listing?.vendor || ""}`;
  const factory =
    FACTORY_USD_HOST.test(link) ||
    Boolean(listing?.wholesale) ||
    listing?.supplier_origin === "CN";
  const price = String(listing?.price || "");
  const amount = extractAmount(price);
  const detected = detectCurrency(price);

  // Explicit $ always wins
  if (detected === "USD") return "USD";
  // Factory/B2B quotes are USD; buyer-locale £/Rs/€ rewrites are scrape bugs
  if (factory) {
    if (detected === "PKR" && amount != null && amount < 100) return "USD";
    return "USD";
  }
  if (detected) return detected;
  return String(preferredCurrency || expectedCurrencyForGl(gl) || "USD").toUpperCase();
}

export function extractAmount(priceText) {
  return parsePriceNumber(priceText);
}

export function convertAmount(amount, fromCur, toCur) {
  const from = String(fromCur || "").toUpperCase();
  const to = String(toCur || "").toUpperCase();
  if (!Number.isFinite(amount) || amount <= 0) return null;
  if (from === to) return amount;
  const fromRate = TO_USD[from];
  const toRate = TO_USD[to];
  if (!fromRate || !toRate) return null;
  const usd = amount * fromRate;
  return usd / toRate;
}

export function formatLocalApprox(amount, currency) {
  if (amount == null || !Number.isFinite(amount)) return null;
  const cur = String(currency || "").toUpperCase();
  if (cur === "PKR") {
    const n = amount >= 50 ? Math.round(amount) : Math.round(amount * 100) / 100;
    return `≈ Rs ${n.toLocaleString("en-US")}`;
  }
  if (cur === "INR") {
    const n = amount >= 50 ? Math.round(amount) : Math.round(amount * 100) / 100;
    return `≈ ₹${n.toLocaleString("en-US")}`;
  }
  if (cur === "USD") {
    return amount >= 10
      ? `≈ $${Math.round(amount).toLocaleString("en-US")}`
      : `≈ $${amount.toFixed(2)}`;
  }
  if (cur === "GBP") {
    return amount >= 10 ? `≈ £${Math.round(amount)}` : `≈ £${amount.toFixed(2)}`;
  }
  if (cur === "EUR") {
    return amount >= 10 ? `≈ €${Math.round(amount)}` : `≈ €${amount.toFixed(2)}`;
  }
  return `≈ ${Math.round(amount).toLocaleString("en-US")} ${cur}`;
}

/**
 * Annotate listing with currency match vs expected local market.
 * Also normalize bare factory digits ("0.65") to "$0.65" so the UI doesn't look like a score.
 */
export function annotateListingCurrency(listing, gl, preferredCurrency) {
  const expected = String(preferredCurrency || expectedCurrencyForGl(gl) || "USD").toUpperCase();
  let price = String(listing?.price || "").trim();
  if (/^(rs\.?|pkr|usd|\$|£|€|inr|₹)[\s,.…]*$/i.test(price)) {
    price = "See listing";
  }
  const link = `${listing?.link || ""} ${listing?.vendor || ""}`;
  const factory = FACTORY_USD_HOST.test(link) || Boolean(listing?.wholesale);
  let amount = extractAmount(price);
  // Mis-tagged factory "Rs 4" → treat as USD 4 and rewrite the display string
  if (factory && /rs\.?|pkr/i.test(price) && amount != null && amount < 100) {
    const formatted = formatMoneyAmount(amount, "USD");
    if (formatted) price = formatted;
  }
  const detected = inferListingCurrency({ ...listing, price }, gl, preferredCurrency);
  amount = extractAmount(price);
  if (
    amount != null &&
    amount > 0 &&
    detected === "USD" &&
    price &&
    !/^(see\s+listing)/i.test(price) &&
    !/\$|usd/i.test(price)
  ) {
    const formatted = formatMoneyAmount(amount, "USD");
    if (formatted) price = formatted;
  }
  const mismatch = Boolean(detected && detected !== expected);
  let price_local_approx = listing?.price_local_approx || null;
  if (mismatch && amount != null && detected) {
    const converted = convertAmount(amount, detected, expected);
    price_local_approx = formatLocalApprox(converted, expected);
  } else if (!mismatch) {
    price_local_approx = null;
  }
  return {
    ...listing,
    price,
    currency: detected || expected,
    currency_expected: expected,
    currency_mismatch: mismatch,
    price_local_approx,
  };
}

export function annotateListingsCurrency(listings, gl, preferredCurrency) {
  return (listings || []).map((row) => annotateListingCurrency(row, gl, preferredCurrency));
}
