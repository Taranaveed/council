import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  checkMarketServiceSecret,
  MARKET_SECRET_MIN_LEN,
} from "../prodGuard.js";

describe("prodGuard MARKET_SERVICE_SECRET", () => {
  it("allows missing secret outside production", () => {
    const r = checkMarketServiceSecret({});
    assert.equal(r.ok, true);
  });

  it("refuses missing secret when RENDER is set", () => {
    const r = checkMarketServiceSecret({ RENDER: "true" });
    assert.equal(r.ok, false);
    assert.match(r.message, /MARKET_SERVICE_SECRET/);
    assert.match(r.message, /Refusing to start/);
  });

  it("refuses short secret when ENV=production", () => {
    const r = checkMarketServiceSecret({
      ENV: "production",
      MARKET_SERVICE_SECRET: "too-short",
    });
    assert.equal(r.ok, false);
  });

  it("allows long secret in production", () => {
    const secret = "x".repeat(MARKET_SECRET_MIN_LEN);
    const r = checkMarketServiceSecret({
      RENDER: "1",
      MARKET_SERVICE_SECRET: secret,
    });
    assert.equal(r.ok, true);
  });
});
