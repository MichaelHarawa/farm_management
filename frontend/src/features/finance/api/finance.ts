import "server-only";

import {
  authenticatedBackendFetch,
} from "@/features/auth/server/authenticated-backend";

import type {
  AccountingPeriod,
  AdHocLabourPayment,
  BatchProfitabilityReport,
  EmployeeProfile,
  FinanceDashboard,
  MonthlyReport,
  PaginatedResponse,
  PayrollEntry,
  SharedExpense,
} from "../types";

import { financeApiPaths } from "./paths";

function normalizeList<T>(data: T[] | PaginatedResponse<T>): T[] {
  return Array.isArray(data) ? data : data.results;
}

export async function getFinanceDashboard(returnTo: string): Promise<FinanceDashboard> {
  return authenticatedBackendFetch<FinanceDashboard>(financeApiPaths.dashboard, {
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
