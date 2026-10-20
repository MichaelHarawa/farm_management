import type { PoultrySale } from "../types/index.ts";

export function saleSellingCostTotal(sales: Pick<PoultrySale, "payment_status" | "total_selling_cost">[]) {
  return sales.reduce((total, sale) =>
    sale.payment_status === "cancelled" ? total : total + Number(sale.total_selling_cost || 0), 0);
}
