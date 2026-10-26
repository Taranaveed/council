/**
 * INR / ₹ snippet parsing + Rs vs ₹ ambiguity for PK buyers.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  annotateListingCurrency,
  convertAmount,
  detectCurrency,
  extractAmount,
} from "../currency.js";
import { normalizeListingPrice, parsePriceNumber } from "../priceParse.js";

// Mirrors market-service/index.js PRICE_IN_TEXT (must stay in sync).
const PRICE_IN_TEXT =
  /(?:Rs\.?|PKR|USD|\$|€|£|₹|INR|AED|SAR)\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?|\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:Rs\.?|PKR|INR)\b/i;

function priceTokenFromText(...parts) {
  const blob = parts.filter(Boolean).map(String).join(" ");
  if (!blob) return null;
  const m = blob.match(PRICE_IN_TEXT);
  return m ? m[0] : null;
}

describe("₹ / INR snippet extract", () => {
  it("extracts ₹ 90/piece from IndiaMART-style title", () => {
    const title = "Export Quality Hand Towel at ₹ 90/piece";
    assert.equal(priceTokenFromText(title), "₹ 90");
    assert.equal(parsePriceNumber("₹ 90"), 90);
    const norm = normalizeListingPrice("₹ 90", "INR");
    assert.equal(norm.rejected, false);
    assert.match(norm.price, /₹\s*90/);
  });

  it("extracts ₹ 1,200 per kg", () => {
    const title = "Cotton Yarn Soft Towel Grade at ₹ 1,200 per kg";
    assert.equal(priceTokenFromText(title), "₹ 1,200");
    assert.equal(parsePriceNumber("₹ 1,200"), 1200);
    assert.equal(extractAmount("₹ 1,200"), 1200);
  });

  it("Rs vs ₹ ambiguity: Rs → PKR, ₹ → INR", () => {
    assert.equal(detectCurrency("Rs. 1,200 Soft Hand Towel Pack"), "PKR");
    assert.equal(detectCurrency("₹ 1,200 Soft Hand Towel Pack"), "INR");
    // Same digits, different currency tags — critical for PK Unit column
    const rs = annotateListingCurrency(
      { title: "Pack", price: "Rs. 1,200", link: "https://example.pk/x" },
      "pk",
      "PKR",
    );
    // IndiaMART regional (not CN factory host) — must keep INR, not coerce to USD
    const inr = annotateListingCurrency(
      {
        title: "Pack",
        price: "₹ 1,200",
        link: "https://www.indiamart.com/proddetail/x.html",
        supplier_origin: "IN",
      },
      "pk",
      "PKR",
    );
    assert.equal(rs.currency, "PKR");
    assert.equal(rs.currency_mismatch, false);
    assert.equal(rs.price_local_approx, null);
    assert.equal(inr.currency, "INR");
    assert.equal(inr.currency_mismatch, true);
    // Static market FX: INR 1/83, PKR 1/278 → 1200 * (278/83) ≈ 4019
    const expected = convertAmount(1200, "INR", "PKR");
    assert.ok(expected != null && expected > 3000);
    assert.match(String(inr.price_local_approx || ""), /≈ Rs/);
    assert.ok(
      Math.abs(extractAmount(inr.price_local_approx) - expected) < 2,
      `Unit approx ${inr.price_local_approx} vs convertAmount ${expected}`,
    );
  });

  it("wholesale:true keeps ₹ / £ / Rs symbols (no USD coerce)", () => {
    const inr = annotateListingCurrency(
      {
        title: "Pack",
        price: "₹ 90",
        link: "https://www.indiamart.com/proddetail/x.html",
        wholesale: true,
        supplier_origin: "IN",
      },
      "pk",
      "PKR",
    );
    assert.equal(inr.currency, "INR");
    const gbp = annotateListingCurrency(
      {
        title: "Pack",
        price: "£12.50",
        link: "https://www.alibaba.com/product-detail/x.html",
        wholesale: true,
      },
      "uk",
      "GBP",
    );
    assert.equal(gbp.currency, "GBP");
  });
});


