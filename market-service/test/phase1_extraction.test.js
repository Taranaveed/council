/**
 * Fixture tests: storefront reject, sale vs strike, thousands parse, tier MOQ.
 * Run: node --test test/phase1_extraction.test.js
 */
import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { parsePriceNumber, formatMoneyAmount } from "../priceParse.js";
import {
  annotateListingTiers,
  isProductDetailUrl,
  selectTierForQuantity,
} from "../listingTiers.js";

describe("parsePriceNumber thousands", () => {
  it("parses Rs 1,569 as 1569 not 1", () => {
    assert.equal(parsePriceNumber("Rs 1,569"), 1569);
    assert.equal(parsePriceNumber("1,569"), 1569);
  });
});

describe("storefront homepage", () => {
  it("rejects storefront homepage — no price, not live listing", () => {
    const row = annotateListingTiers({
      title: "Acme Jewelry Store",
      link: "https://www.acmejewel.pk/",
      price: "Rs 1,569",
      snippet: "Shop handbags and jewelry",
    });
    assert.equal(row.is_product_page, false);
    assert.equal(row.counts_as_live_listing, false);
    assert.match(String(row.price), /see listing/i);
    assert.equal(row.price_source, "rejected_storefront");
  });

  it("accepts product-detail URL as product page", () => {
    assert.equal(
      isProductDetailUrl("https://www.alibaba.com/product-detail/USB-Adapter_123.html"),
      true,
    );
    const row = annotateListingTiers({
      title: "USB Adapter",
      link: "https://www.alibaba.com/product-detail/USB-Adapter_123.html",
      price: "Rs 1,569",
      price_source: "page",
      currency: "PKR",
    });
    assert.equal(row.is_product_page, true);
    assert.equal(row.counts_as_live_listing, true);
    assert.equal(parsePriceNumber(row.price), 1569);
  });
});

describe("sale vs strike preference (text scrape)", () => {
  it("formatMoneyAmount keeps sale amount", () => {
    const sale = parsePriceNumber("Rs 1,569");
    const strike = parsePriceNumber("Rs 1,598");
    assert.equal(sale, 1569);
    assert.equal(strike, 1598);
    assert.notEqual(sale, strike);
    assert.equal(formatMoneyAmount(sale, "PKR"), "Rs 1,569");
  });

  it("extractPriceFromHtml prefers sale over struck-through original", async () => {
    const { extractPriceFromHtml } = await import("../pagePrice.js");
    const html = `
      <div class="product">
        <span class="price">Rs 1,569</span>
        <s>Rs 1,598</s>
        <del>Rs 1,598</del>
      </div>
    `;
    const price = extractPriceFromHtml(
      html,
      "https://shop.example/products/adapter-1",
      "PKR",
    );
    assert.ok(price);
    assert.equal(parsePriceNumber(price), 1569);
  });
});

describe("tier MOQ", () => {
  it("603+ tier not applied to quantity 100", () => {
    const sel = selectTierForQuantity(
      [{ min_qty: 603, max_qty: null, unit_price: "Rs 8", currency: "PKR" }],
      100,
    );
    assert.equal(sel.moq_not_met, true);
    assert.equal(sel.tier, null);
    assert.equal(sel.lowest_min_qty, 603);
  });

  it("annotateListingTiers sets moq_not_met for qty 100 vs 603+", () => {
    const row = annotateListingTiers(
      {
        title: "Beads bulk",
        link: "https://www.alibaba.com/product-detail/beads_1.html",
        price: "Rs 50",
        price_source: "page",
        currency: "PKR",
        snippet: "603+ pcs Rs 8",
      },
      { quantity: 100 },
    );
    assert.equal(row.moq_not_met, true);
  });
});

describe("iphone mobile covers match", () => {
  it("accepts phone case titles without literal iphone brand", async () => {
    const { productMatchScore } = await import("../listingQuality.js");
    const q = "iphone mobile covers";
    const softCase = productMatchScore(
      {
        title: "Soft TPU Mobile Phone Cover Protective Case",
        link: "https://www.alibaba.com/product-detail/Soft-TPU-Mobile-Phone-Cover_1600.html",
        price: "$0.35",
      },
      q,
    );
    assert.notEqual(softCase, null);
    const iphoneCase = productMatchScore(
      {
        title: "For iPhone 15 Silicone Case Cover",
        link: "https://www.alibaba.com/product-detail/iPhone-15-Silicone-Case_1601.html",
        price: "$0.55",
      },
      q,
    );
    assert.notEqual(iphoneCase, null);
    assert.ok(iphoneCase > softCase);
  });

  it("rejects craft leather sheets for cover query", async () => {
    const { productMatchScore } = await import("../listingQuality.js");
    const score = productMatchScore(
      {
        title: "Natural Leather Sheets Tooling Crafting Hide",
        link: "https://www.alibaba.com/product-detail/Leather-Sheets_99.html",
        price: "$12",
      },
      "iphone mobile covers",
    );
    assert.equal(score, null);
  });
});

describe("ladies rings query rewrite", () => {
  it("rewrites ladies rings to jewelry intent", async () => {
    const { shortenProductQuery } = await import("../searchQuery.js");
    const q = shortenProductQuery("ladies rings wholesale");
    assert.match(q, /jewel|finger|ring/i);
    assert.doesNotMatch(q, /^ladies rings$/i);
  });

  it("rejects entertainment titles for ring queries", async () => {
    const { productMatchScore } = await import("../listingQuality.js");
    assert.equal(
      productMatchScore(
        {
          title: "Beyoncé - Single Ladies (Put a Ring on It)",
          link: "https://www.youtube.com/watch?v=4m1EFMoRFvY",
          price: "See listing",
        },
        "women jewelry finger rings",
      ),
      null,
    );
  });
});

describe("malformed concatenated prices", () => {
  it("rejects $1.321,000 as unit+MOQ concat and rescues $1.32", async () => {
    const {
      isMalformedPriceString,
      sanitizePriceRaw,
      parsePriceNumber,
      normalizeListingPrice,
    } = await import("../priceParse.js");
    const raw = "$" + "1.321,000";
    assert.equal(isMalformedPriceString(raw), true);
    assert.equal(sanitizePriceRaw(raw), "$1.32");
    assert.equal(parsePriceNumber(raw), 1.32);
    const norm = normalizeListingPrice(raw, "USD");
    assert.equal(norm.price, "$1.32");
    assert.equal(norm.unreliable, true);
    assert.doesNotMatch(String(norm.price), /1\.321,000/);
  });
});
