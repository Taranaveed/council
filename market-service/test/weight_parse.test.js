import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { extractPackageWeight } from "../listingTiers.js";

describe("extractPackageWeight carton vs unit", () => {
  it("leaves unmarked 8 kg as candidate unit (backend may reject)", () => {
    const w = extractPackageWeight("Package Weight: 8 kg");
    assert.ok(w);
    assert.equal(w.kg, 8);
    assert.equal(w.basis, "unknown");
    assert.match(String(w.raw), /8\s*kg/i);
  });

  it("does not use carton/gross weight without pcs as unit kg", () => {
    const w = extractPackageWeight("Gross weight: 8 kg per carton. Material: Alcantara.");
    assert.ok(w);
    assert.equal(w.kg, null);
    assert.equal(w.basis, "carton");
    assert.equal(w.kg_as_parsed, 8);
    assert.match(String(w.note), /not used as per-unit/i);
  });

  it("divides carton weight by pcs/carton when stated", () => {
    const w = extractPackageWeight(
      "Gross weight: 8 kg. Packing: 100 pcs/carton. Phone case wholesale.",
    );
    assert.ok(w);
    assert.equal(w.basis, "carton");
    assert.equal(w.pcs_per_carton, 100);
    assert.equal(w.kg_as_parsed, 8);
    assert.ok(Math.abs(w.kg - 0.08) < 1e-9);
    assert.match(String(w.note), /÷\s*100/i);
  });

  it("keeps explicit unit/net weight", () => {
    const w = extractPackageWeight("Unit weight: 45 g / pc");
    assert.ok(w);
    assert.ok(Math.abs(w.kg - 0.045) < 1e-9);
    assert.equal(w.basis, "unit");
  });
});
