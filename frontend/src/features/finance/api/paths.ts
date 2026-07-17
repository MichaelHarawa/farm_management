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
  monthlyReport: (period?: string) =>
    period
      ? `${FINANCE_ROOT}/reports/monthly?period=${encodeURIComponent(period)}`
      : `${FINANCE_ROOT}/reports/monthly`,
  batchProfitability: (batchId: number) =>
    `${FINANCE_ROOT}/reports/batches/${batchId}`,
  receivables: `${FINANCE_ROOT}/receivables`,
} as const;
