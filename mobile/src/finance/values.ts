import { Decimal } from 'decimal.js';
import { z } from 'zod';

// Existing ledger is MWK only. USD reference values are not spendable currency.
export const financialCurrency = z.literal('MWK');
export const moneyString = z.string().regex(/^(?:0|[1-9]\d{0,11})\.\d{2}$/);
const Exact = Decimal.clone({ precision: 40, rounding: Decimal.ROUND_HALF_EVEN });

/** Prepare user-entered cents before freezing an operation, never round them. */
export function moneyInput(value: string, positive = true): string {
  if (typeof value !== 'string' || !/^(?:0|[1-9]\d{0,11})(?:\.\d{1,2})?$/.test(value.trim())) {
    throw new Error('Enter an exact amount with at most two decimal places; no rounding or currency conversion.');
  }
  const amount = new Exact(value.trim());
  if (positive && amount.isZero()) throw new Error('Amount must be greater than zero.');
  return moneyString.parse(amount.toFixed(2));
}

export interface FundingSplit { fundingSourceId: string; amount: string }
export interface CostShare { batchId: string; amount: string }
export function exactSplitTotal(rows: readonly { amount: string }[]): string {
  if (rows.length > 50) throw new Error('At most 50 split rows are supported.');
  const total = rows.reduce((sum, row) => sum.plus(moneyInput(row.amount)), new Exact(0));
  return moneyString.parse(total.toFixed(2));
}

export function validateCostShares(amount: string, rows: readonly CostShare[]): void {
  if (!rows.length || rows.some(row => !row.batchId) || new Set(rows.map(row => row.batchId)).size !== rows.length) {
    throw new Error('Choose each beneficiary batch once. Funding origin is a separate choice.');
  }
  if (moneyInput(amount) !== exactSplitTotal(rows)) throw new Error('Cost shares must equal the expenditure amount exactly.');
}

export function validatePaymentSplits(paymentAmount: string, rows: readonly FundingSplit[]): void {
  if (!rows.length || moneyInput(paymentAmount) !== exactSplitTotal(rows)) {
    throw new Error('Funding splits must equal this dated payment amount exactly.');
  }
  if (rows.some(row => !row.fundingSourceId)) throw new Error('Choose a funding source for each dated split; Django checks confirmed availability.');
}

/** This preview never changes confirmed availability, cash, profit or authority. */
export function provisionalSalePreview(quantity: string, unitPrice: string,
    sellingCosts: readonly string[], initialReceipt = '0.00') {
  if (!/^[1-9]\d{0,9}$/.test(quantity) || new Exact(quantity).greaterThan('2147483647')) {
    throw new Error('Enter a positive whole-bird/product-unit quantity.');
  }
  const revenue = new Exact(moneyInput(unitPrice)).times(quantity);
  const total = moneyString.parse(revenue.toFixed(2));
  if (sellingCosts.length > 50) throw new Error('At most 50 selling costs are supported.');
  const costs = sellingCosts.reduce((sum, amount) => sum.plus(moneyInput(amount)), new Exact(0));
  const receipt = new Exact(moneyInput(initialReceipt, false));
  if (receipt.greaterThan(revenue)) throw new Error('Receipt exceeds the provisional sale total; Django rechecks outstanding balances.');
  return { authority: 'local-provisional' as const, currency: 'MWK' as const,
    saleTotal: total, sellingCostTotal: moneyString.parse(costs.toFixed(2)),
    receiptAmount: receipt.toFixed(2), receivable: revenue.minus(receipt).toFixed(2),
    afterSellingCosts: revenue.minus(costs).toFixed(2) };
}
