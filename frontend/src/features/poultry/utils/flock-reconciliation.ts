import type { PoultryFlockAdjustment, PoultrySale } from "../types";

export function isValidBirdSale(
  sale: Pick<PoultrySale, "payment_status" | "product_type">
): boolean {
  return sale.payment_status !== "cancelled" &&
    (sale.product_type === "live_chicken" || sale.product_type === "dressed_chicken");
}

// Match Django's bird balance: only approved adjustments affect the cohort.
// Keep additions and removals separate so a net-zero correction is still visible.
export function reconcileFlock({
  initialBirds,
  sales,
  mortality,
  adjustments,
  confirmedRemaining,
}: {
  initialBirds: number;
  sales: Pick<PoultrySale, "payment_status" | "product_type" | "quantity_sold">[];
  mortality: number;
  adjustments: Pick<PoultryFlockAdjustment, "status" | "quantity_change">[];
  confirmedRemaining?: number;
}) {
  const sold = sales.filter(isValidBirdSale).reduce((sum, sale) => sum + sale.quantity_sold, 0);
  const approved = adjustments.filter((record) => record.status === "approved");
  const additions = approved.reduce((sum, record) => sum + Math.max(record.quantity_change, 0), 0);
  const removals = approved.reduce((sum, record) => sum + Math.max(-record.quantity_change, 0), 0);
  const expectedRemaining = initialBirds + additions - removals - sold - mortality;
  const remaining = confirmedRemaining ?? expectedRemaining;
  return {
    sold,
    additions,
    removals,
    netAdjustment: additions - removals,
    population: initialBirds + additions,
    expectedRemaining,
    remaining,
    // Never hide inconsistent records by clamping a negative balance to zero.
    discrepancy: remaining - expectedRemaining,
  };
}
