import test from "node:test";
import assert from "node:assert/strict";
import { isValidBirdSale, reconcileFlock } from "../src/features/poultry/utils/flock-reconciliation.ts";

const baseline = { initialBirds: 100, sales: [], mortality: 2, adjustments: [] };

test("actual arrivals and the approved native -3 reconcile to 95", () => {
  const result = reconcileFlock({ ...baseline, adjustments: [{ status: "approved", quantity_change: -3 }] });
  assert.equal(result.remaining, 95);
  assert.equal(result.population, 100);
  assert.equal(result.removals, 3);
  assert.equal(result.discrepancy, 0);
});

test("only valid bird sales remove birds; cancelled, eggs and manure do not", () => {
  const sales = [
    { product_type: "live_chicken", payment_status: "partial", quantity_sold: 4 },
    { product_type: "dressed_chicken", payment_status: "paid", quantity_sold: 5 },
    { product_type: "live_chicken", payment_status: "cancelled", quantity_sold: 80 },
    { product_type: "eggs", payment_status: "paid", quantity_sold: 30 },
    { product_type: "manure", payment_status: "paid", quantity_sold: 60 },
  ];
  assert.equal(sales.filter(isValidBirdSale).length, 2);
  assert.equal(reconcileFlock({ ...baseline, sales }).remaining, 89);
});

test("additions enlarge the population; reversed records do not count", () => {
  const result = reconcileFlock({ ...baseline, adjustments: [
    { status: "approved", quantity_change: 8 },
    { status: "approved", quantity_change: -3 },
    { status: "reversed", quantity_change: -50 },
  ] });
  assert.equal(result.population, 108);
  assert.equal(result.remaining, 103);
  assert.equal(result.netAdjustment, 5);
});

test("opposite approved changes remain visible even when their net is zero", () => {
  const result = reconcileFlock({ ...baseline, adjustments: [
    { status: "approved", quantity_change: 3 },
    { status: "approved", quantity_change: -3 },
  ] });
  assert.equal(result.additions, 3);
  assert.equal(result.removals, 3);
  assert.equal(result.netAdjustment, 0);
});

test("a server/history mismatch is explicit, not an invented adjustment", () => {
  const result = reconcileFlock({ ...baseline, confirmedRemaining: 95 });
  assert.equal(result.expectedRemaining, 98);
  assert.equal(result.remaining, 95);
  assert.equal(result.removals, 0);
  assert.equal(result.discrepancy, -3);
});

test("invalid negative history is not disguised as a healthy zero balance", () => {
  assert.equal(reconcileFlock({ ...baseline, mortality: 101 }).remaining, -1);
});
