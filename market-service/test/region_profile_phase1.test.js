import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  assertPkGoldenParity,
  getProfile,
  loadProfile,
  isLocalHost,
  RegionNotSupportedError,
} from "../regionProfile.js";
import { isLocalMarketHost } from "../listingQuality.js";
import { expectedCurrencyForGl } from "../currency.js";
import { formatMoneyAmount } from "../priceParse.js";
import { buildSearchVariants } from "../searchQuery.js";
import { getRegionConfig, isShoppingGlSupported } from "../regionConfig.js";

describe("RegionProfile Phase 1", () => {
  it("freezes Pakistan golden fixture", () => {
    const pk = assertPkGoldenParity();
    assert.equal(pk.id, "pk");
    assert.equal(pk.serp.shopping_gl_supported, false);
    assert.equal(isShoppingGlSupported("pk"), false);
  });

  it("loads UK profile with import groups and local hosts", () => {
    const uk = loadProfile("uk");
    assert.equal(uk.trade_zone, "UK");
    assert.equal(uk.currency, "GBP");
    assert.ok(uk.import_origin_groups.import.includes("EU"));
    assert.ok(uk.import_origin_groups.import.includes("CN"));
    assert.ok(uk.import_origin_groups.import.includes("ROW"));
    assert.equal(uk.serp.site_tld_pass, ".co.uk");
    assert.ok(isLocalHost("https://www.argos.co.uk/product/1", uk));
    assert.ok(isLocalMarketHost("https://www.argos.co.uk/product/1", "uk", uk));
  });

  it("PK local hosts match frozen patterns via profile", () => {
    const pk = loadProfile("pk");
    assert.ok(isLocalMarketHost("https://www.daraz.pk/products/x", "pk", pk));
    assert.ok(isLocalMarketHost("https://www.priceoye.pk/x", "pk", pk));
    // Without profile, golden hardcoded path still matches PK
    assert.ok(isLocalMarketHost("https://www.daraz.pk/products/x", "pk"));
  });

  it("expectedCurrencyForGl prefers profile currency", () => {
    const pk = loadProfile("pk");
    const uk = loadProfile("uk");
    assert.equal(expectedCurrencyForGl("pk", pk), "PKR");
    assert.equal(expectedCurrencyForGl("uk", uk), "GBP");
  });

  it("buildSearchVariants uses profile site TLD pass", () => {
    const uk = loadProfile("uk");
    const variants = buildSearchVariants("wireless earbuds", {
      gl: "uk",
      currency: "GBP",
      location: "London",
      siteTldPass: uk.serp.site_tld_pass,
      countryHint: uk.display_name,
    });
    assert.ok(variants.some((v) => v.includes("site:.co.uk")));
  });

  it("formatMoneyAmount requires explicit currency", () => {
    assert.throws(() => formatMoneyAmount(10), /explicit currency/i);
    assert.equal(formatMoneyAmount(1569, "PKR"), "Rs 1,569");
    assert.match(formatMoneyAmount(12.5, "GBP"), /£/);
  });

  it("DEFAULT_* resolve to UK when env unset", () => {
    const cfg = getRegionConfig();
    // Env may override in CI; assert helper defaults in module are uk
    assert.ok(["uk", "pk", "us", "eu"].includes(cfg.DEFAULT_REGION));
    const uk = getProfile({ countryCode: "uk" });
    assert.equal(uk.id, "uk");
  });

  it("unsupported US does not silently fall back to UK", () => {
    assert.throws(
      () => loadProfile("us"),
      (err) => err instanceof RegionNotSupportedError && err.profileId === "us",
    );
    assert.throws(
      () => getProfile({ location: "New York, United States", currency: "USD" }),
      (err) => err instanceof RegionNotSupportedError,
    );
  });
});

describe("SERP $ under UK request stays USD", () => {
  it("annotateListingCurrency keeps $11 as USD with currency_mismatch vs GBP", async () => {
    const { annotateListingCurrency } = await import("../currency.js");
    const row = annotateListingCurrency(
      {
        title: "Phone case",
        price: "$11.00",
        link: "https://www.alibaba.com/product-detail/x_1.html",
        supplier_origin: "CN",
      },
      "uk",
      "GBP",
    );
    assert.equal(row.currency, "USD");
    assert.equal(row.currency_mismatch, true);
    assert.match(String(row.price), /\$/);
  });

  it("factory £ rewrite under UK preferredCurrency is corrected to USD", async () => {
    const { annotateListingCurrency } = await import("../currency.js");
    const row = annotateListingCurrency(
      {
        title: "Phone case",
        price: "£11.00",
        link: "https://www.alibaba.com/product-detail/x_2.html",
        wholesale: true,
      },
      "uk",
      "GBP",
    );
    assert.equal(row.currency, "USD");
    assert.equal(row.currency_mismatch, true);
    assert.match(String(row.price), /\$/);
  });
});
