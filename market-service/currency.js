/**
 * Currency detection + rough FX for comparing international listings to local markets.
 * Rates are approximate display aids — never treat as live FX.
 */

import { parsePriceNumber } from "./priceParse.js";

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

export function expectedCurrencyForGl(gl) {
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
  if (/\$|usd/i.test(text)) return "USD";
  return null;
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
  const rounded = Math.round(amount);
  if (cur === "PKR") return `≈ Rs ${rounded.toLocaleString("en-US")}`;
  if (cur === "INR") return `≈ ₹${rounded.toLocaleString("en-US")}`;
  if (cur === "USD") return `≈ $${rounded.toLocaleString("en-US")}`;
  if (cur === "GBP") return `≈ £${rounded.toLocaleString("en-US")}`;
  if (cur === "EUR") return `≈ €${rounded.toLocaleString("en-US")}`;
  return `≈ ${rounded.toLocaleString("en-US")} ${cur}`;
}

/**
 * Annotate listing with currency match vs expected local market.
 */
export function annotateListingCurrency(listing, gl, preferredCurrency) {
  const expected = String(preferredCurrency || expectedCurrencyForGl(gl) || "USD").toUpperCase();
  const detected = detectCurrency(listing?.price) || null;
  const amount = extractAmount(listing?.price);
  const mismatch = Boolean(detected && detected !== expected);
  let price_local_approx = null;
  if (mismatch && amount != null && detected) {
    const converted = convertAmount(amount, detected, expected);
    price_local_approx = formatLocalApprox(converted, expected);
  }
  return {
    ...listing,
    currency: detected || expected,
    currency_expected: expected,
    currency_mismatch: mismatch,
    price_local_approx,
  };
}

export function annotateListingsCurrency(listings, gl, preferredCurrency) {
  return (listings || []).map((row) => annotateListingCurrency(row, gl, preferredCurrency));
}
