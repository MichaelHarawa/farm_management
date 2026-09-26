import "server-only";

import {
  authenticatedBackendFetch,
} from "@/features/auth/server/authenticated-backend";

import type {
  AccountingPeriod,
  AdHocLabourPayment,
  Asset,
  AssetCategory,
  AssetLifecycleEvent,
  AssetDepreciationEntry,
  BatchPortfolioReport,
  BatchProfitabilityReport,
  ConsumableUsage,
  Customer,
  CustomerContributionReport,
  CustomerCostSource,
  CustomerUnlinkedSale,
  EmployeeProfile,
  EmployeeSalaryAdjustment,
  FinanceDashboard,
  MonthlyReport,
  OwnerContributionReport,
  OwnerContributor,
  PaginatedResponse,
  PayrollEntry,
  ReceivablesReport,
  SharedExpense,
  SharedConsumableLot,
  StockMovement,
} from "../types";

import { financeApiPaths } from "./paths";

function normalizeList<T>(data: T[] | PaginatedResponse<T>): T[] {
  return Array.isArray(data) ? data : data.results;
}

export async function getFinanceDashboard(returnTo: string, query = ""): Promise<FinanceDashboard> {
  return authenticatedBackendFetch<FinanceDashboard>(financeApiPaths.dashboard + query, {
    returnTo,
    cache: "no-store",
  });
}

export async function getEmployees(returnTo: string): Promise<EmployeeProfile[]> {
  const data = await authenticatedBackendFetch<
    EmployeeProfile[] | PaginatedResponse<EmployeeProfile>
  >(financeApiPaths.employees, {
    returnTo,
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function getAccountingPeriods(returnTo: string): Promise<AccountingPeriod[]> {
  const data = await authenticatedBackendFetch<
    AccountingPeriod[] | PaginatedResponse<AccountingPeriod>
  >(financeApiPaths.accountingPeriods, {
    returnTo,
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function getSalaryAdjustments(
  returnTo: string,
): Promise<EmployeeSalaryAdjustment[]> {
  const data = await authenticatedBackendFetch<
    EmployeeSalaryAdjustment[] | PaginatedResponse<EmployeeSalaryAdjustment>
  >(financeApiPaths.salaryAdjustments, {
    returnTo,
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function getPayrollEntries(returnTo: string): Promise<PayrollEntry[]> {
  const data = await authenticatedBackendFetch<
    PayrollEntry[] | PaginatedResponse<PayrollEntry>
  >(financeApiPaths.payrollEntries, {
    returnTo,
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function getAdHocLabour(returnTo: string): Promise<AdHocLabourPayment[]> {
  const data = await authenticatedBackendFetch<
    AdHocLabourPayment[] | PaginatedResponse<AdHocLabourPayment>
  >(financeApiPaths.adHocLabour, {
    returnTo,
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function getSharedExpenses(returnTo: string): Promise<SharedExpense[]> {
  const data = await authenticatedBackendFetch<
    SharedExpense[] | PaginatedResponse<SharedExpense>
  >(financeApiPaths.expenses, {
    returnTo,
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function getConsumableLots(returnTo: string): Promise<SharedConsumableLot[]> {
  const data = await authenticatedBackendFetch<
    SharedConsumableLot[] | PaginatedResponse<SharedConsumableLot>
  >(financeApiPaths.consumableLots, {
    returnTo,
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function getConsumableUsages(returnTo: string): Promise<ConsumableUsage[]> {
  const data = await authenticatedBackendFetch<
    ConsumableUsage[] | PaginatedResponse<ConsumableUsage>
  >(financeApiPaths.consumableUsages, {
    returnTo,
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function getStockMovements(returnTo: string): Promise<StockMovement[]> {
  const data = await authenticatedBackendFetch<StockMovement[] | PaginatedResponse<StockMovement>>(
    financeApiPaths.stockMovements,
    { returnTo, cache: "no-store" }
  );
  return normalizeList(data);
}

export async function getAssetCategories(returnTo: string): Promise<AssetCategory[]> {
  const data = await authenticatedBackendFetch<
    AssetCategory[] | PaginatedResponse<AssetCategory>
  >(financeApiPaths.assetCategories, {
    returnTo,
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function getAssets(returnTo: string): Promise<Asset[]> {
  const data = await authenticatedBackendFetch<
    Asset[] | PaginatedResponse<Asset>
  >(financeApiPaths.assets, {
    returnTo,
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function getAsset(id: string, returnTo: string): Promise<Asset> {
  return authenticatedBackendFetch<Asset>(financeApiPaths.asset(id), { returnTo, cache: "no-store" });
}

export async function getAssetHistory(id: string, returnTo: string): Promise<AssetLifecycleEvent[]> {
  return authenticatedBackendFetch<AssetLifecycleEvent[]>(financeApiPaths.assetHistory(id), { returnTo, cache: "no-store" });
}

export async function getAssetDepreciationSchedule(id: string, returnTo: string): Promise<AssetDepreciationEntry[]> {
  return authenticatedBackendFetch<AssetDepreciationEntry[]>(financeApiPaths.assetDepreciationSchedule(id), { returnTo, cache: "no-store" });
}

export async function getAssetDepreciation(returnTo: string): Promise<AssetDepreciationEntry[]> {
  const data = await authenticatedBackendFetch<
    AssetDepreciationEntry[] | PaginatedResponse<AssetDepreciationEntry>
  >(financeApiPaths.assetDepreciation, {
    returnTo,
    cache: "no-store",
  });

  return normalizeList(data);
}

export async function getOwnerContributors(
  returnTo: string
): Promise<OwnerContributor[]> {
  const data = await authenticatedBackendFetch<
    OwnerContributor[] | PaginatedResponse<OwnerContributor>
  >(`${financeApiPaths.owners}?page_size=100`, { returnTo, cache: "no-store" });
  return normalizeList(data);
}

export async function getOwnerContributionReport(
  returnTo: string,
  query = ""
): Promise<OwnerContributionReport> {
  return authenticatedBackendFetch<OwnerContributionReport>(
    `${financeApiPaths.ownerContributionReport}${query}`,
    { returnTo, cache: "no-store" }
  );
}

export async function getCustomers(returnTo: string): Promise<Customer[]> {
  const data = await authenticatedBackendFetch<Customer[] | PaginatedResponse<Customer>>(
    `${financeApiPaths.customers}?page_size=100`,
    { returnTo, cache: "no-store" }
  );
  return normalizeList(data);
}

export async function getCustomer(id: number, returnTo: string): Promise<Customer> {
  return authenticatedBackendFetch<Customer>(financeApiPaths.customer(id), {
    returnTo,
    cache: "no-store",
  });
}

export async function getCustomerContributionReport(
  returnTo: string,
  query = ""
): Promise<CustomerContributionReport> {
  return authenticatedBackendFetch<CustomerContributionReport>(
    `${financeApiPaths.customerContributionReport}${query}`,
    { returnTo, cache: "no-store" }
  );
}

export async function getCustomerCostSources(
  returnTo: string,
  search = ""
): Promise<CustomerCostSource[]> {
  const query = search ? `?search=${encodeURIComponent(search)}` : "";
  return authenticatedBackendFetch<CustomerCostSource[]>(
    `${financeApiPaths.customerCostSources}${query}`,
    { returnTo, cache: "no-store" }
  );
}

export async function getCustomerUnlinkedSales(
  returnTo: string,
  search = ""
): Promise<CustomerUnlinkedSale[]> {
  const query = search ? `?search=${encodeURIComponent(search)}` : "";
  return authenticatedBackendFetch<CustomerUnlinkedSale[]>(
    `${financeApiPaths.customerUnlinkedSales}${query}`,
    { returnTo, cache: "no-store" }
  );
}

export async function getMonthlyReport(
  returnTo: string,
  period?: string
): Promise<MonthlyReport> {
  return authenticatedBackendFetch<MonthlyReport>(financeApiPaths.monthlyReport(period), {
    returnTo,
    cache: "no-store",
  });
}

export async function getBatchProfitability(
  batchId: number,
  returnTo: string
): Promise<BatchProfitabilityReport> {
  return authenticatedBackendFetch<BatchProfitabilityReport>(
    financeApiPaths.batchProfitability(batchId),
    {
      returnTo,
      cache: "no-store",
    }
  );
}

export async function getBatchPortfolioReport(
  batchIds: number[],
  returnTo: string
): Promise<BatchPortfolioReport> {
  return authenticatedBackendFetch<BatchPortfolioReport>(
    financeApiPaths.batchPortfolio(batchIds),
    {
      returnTo,
      cache: "no-store",
    }
  );
}

export async function getReceivables(
  returnTo: string
): Promise<ReceivablesReport> {
  return authenticatedBackendFetch<ReceivablesReport>(financeApiPaths.receivables, {
    returnTo,
    cache: "no-store",
  });
}

export async function getFinanceExpenditures(
  returnTo: string
): Promise<import("../types").Expenditure[]> {
  return authenticatedBackendFetch<import("../types").Expenditure[]>(
    financeApiPaths.expenditures,
    { returnTo, cache: "no-store" }
  );
}

export async function getBatchRevenueUtilization(
  batchId: number,
  returnTo: string
): Promise<import("../types").BatchRevenueUtilization> {
  return authenticatedBackendFetch<import("../types").BatchRevenueUtilization>(
    financeApiPaths.batchRevenueUtilization(batchId),
    { returnTo, cache: "no-store" }
  );
}

export async function getCrossBatchFinancing(
  returnTo: string
): Promise<{ flows: import("../types").CrossBatchFlow[] }> {
  return authenticatedBackendFetch<{ flows: import("../types").CrossBatchFlow[] }>(
    financeApiPaths.crossBatchFinancing,
    { returnTo, cache: "no-store" }
  );
}
