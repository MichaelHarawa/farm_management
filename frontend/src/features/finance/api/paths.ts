const FINANCE_ROOT = "/finance";

export const financeApiPaths = {
  dashboard: `${FINANCE_ROOT}/dashboard`,
  employees: `${FINANCE_ROOT}/employees`,
  employee: (id: number) => `${FINANCE_ROOT}/employees/${id}`,
  employeeActivate: (id: number) => `${FINANCE_ROOT}/employees/${id}/activate`,
  employeeDeactivate: (id: number) => `${FINANCE_ROOT}/employees/${id}/deactivate`,
  accountingPeriods: `${FINANCE_ROOT}/accounting-periods`,
  accountingPeriod: (id: number) => `${FINANCE_ROOT}/accounting-periods/${id}`,
  generatePayroll: (id: number) =>
    `${FINANCE_ROOT}/accounting-periods/${id}/generate-payroll`,
  recalculatePeriod: (id: number) =>
    `${FINANCE_ROOT}/accounting-periods/${id}/recalculate`,
  closePeriod: (id: number) => `${FINANCE_ROOT}/accounting-periods/${id}/close`,
  payrollEntries: `${FINANCE_ROOT}/payroll-entries`,
  adHocLabour: `${FINANCE_ROOT}/ad-hoc-labour`,
  expenses: `${FINANCE_ROOT}/expenses`,
  consumableLots: `${FINANCE_ROOT}/consumable-lots`,
  consumableUsages: `${FINANCE_ROOT}/consumable-usages`,
  stockMovements: `${FINANCE_ROOT}/stock-movements`,
  assetCategories: `${FINANCE_ROOT}/asset-categories`,
  assets: `${FINANCE_ROOT}/assets`,
  asset: (id: string) => `${FINANCE_ROOT}/assets/${id}`,
  assetHistory: (id: string) => `${FINANCE_ROOT}/assets/${id}/history`,
  assetDepreciationSchedule: (id: string) => `${FINANCE_ROOT}/assets/${id}/depreciation-schedule`,
  assetDepreciation: `${FINANCE_ROOT}/asset-depreciation`,
  generateDepreciation: (id: number) =>
    `${FINANCE_ROOT}/accounting-periods/${id}/generate-depreciation`,
  allocateDepreciation: (id: number) =>
    `${FINANCE_ROOT}/accounting-periods/${id}/allocate-depreciation`,
  monthlyReport: (period?: string) =>
    period
      ? `${FINANCE_ROOT}/reports/monthly?period=${encodeURIComponent(period)}`
      : `${FINANCE_ROOT}/reports/monthly`,
  batchProfitability: (batchId: number) =>
    `${FINANCE_ROOT}/reports/batches/${batchId}`,
  batchPortfolio: (batchIds: number[]) => {
    const searchParams = new URLSearchParams();
    batchIds.forEach((batchId) => searchParams.append("batch", String(batchId)));
    return `${FINANCE_ROOT}/reports/batches?${searchParams.toString()}`;
  },
  receivables: `${FINANCE_ROOT}/receivables`,
  expenditures: `${FINANCE_ROOT}/expenditures`,
  fundingSources: `${FINANCE_ROOT}/funding-sources`,
  batchRevenueUtilization: (batchId: number) =>
    `${FINANCE_ROOT}/reports/batches/${batchId}/revenue-utilization`,
  crossBatchFinancing: `${FINANCE_ROOT}/reports/cross-batch-financing`,
} as const;
