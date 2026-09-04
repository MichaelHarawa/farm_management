"use client";

import { Badge, DataTable, statusTone } from "@/components/ui";

import type {
  AccountingPeriod,
  AdHocLabourPayment,
  Asset,
  EmployeeProfile,
  PayrollEntry,
  SharedConsumableLot,
  SharedExpense,
  ConsumableUsage,
} from "../types";
import {
  formatCurrency,
  formatDate,
  formatLabel,
  formatNumber,
} from "../utils/formatters";

export function EmployeeTable({ rows }: { rows: EmployeeProfile[] }) {
  return (
    <DataTable
      rows={rows}
      rowKey={(employee) => employee.id}
      exportFileName="employees"
      emptyMessage="No employees have been created yet."
      columns={[
        {
          key: "employee",
          header: "Employee",
          sortValue: (employee) => employee.display_name,
          cell: (employee) => (
            <div>
              <p className="font-extrabold text-[var(--navy)]">
                {employee.display_name}
              </p>
              <p className="text-xs text-[var(--navy-muted)]">
                {employee.employee_number}
              </p>
            </div>
          ),
        },
        {
          key: "role",
          header: "Role",
          sortValue: (employee) => employee.employment_type,
          cell: (employee) => formatLabel(employee.employment_type),
        },
        {
          key: "salary",
          header: "Salary",
          sortValue: (employee) => Number(employee.base_monthly_salary),
          cell: (employee) => formatCurrency(employee.base_monthly_salary),
        },
        {
          key: "split",
          header: "Split",
          sortValue: (employee) =>
            `${employee.production_percentage}/${employee.administration_percentage}/${employee.selling_percentage}`,
          cell: (employee) =>
            `${employee.production_percentage}/${employee.administration_percentage}/${employee.selling_percentage}`,
        },
        {
          key: "start",
          header: "Start",
          sortValue: (employee) => employee.employment_start_date,
          cell: (employee) => formatDate(employee.employment_start_date),
        },
        {
          key: "status",
          header: "Status",
          sortValue: (employee) => (employee.is_active ? "active" : "inactive"),
          cell: (employee) => (
            <Badge tone={statusTone(employee.is_active ? "active" : "inactive")}>
              {employee.is_active ? "Active" : "Inactive"}
            </Badge>
          ),
        },
      ]}
    />
  );
}

export function PayrollTable({ rows }: { rows: PayrollEntry[] }) {
  return (
    <DataTable
      rows={rows}
      rowKey={(entry) => entry.id}
      exportFileName="payroll-entries"
      emptyMessage="No payroll entries have been generated."
      columns={[
        {
          key: "employee",
          header: "Employee",
          sortValue: (entry) => entry.employee_name,
          cell: (entry) => (
            <span className="font-bold text-[var(--navy)]">
              {entry.employee_name}
            </span>
          ),
        },
        {
          key: "gross",
          header: "Gross",
          sortValue: (entry) => Number(entry.gross_salary),
          cell: (entry) => formatCurrency(entry.gross_salary),
        },
        {
          key: "production",
          header: "Production",
          sortValue: (entry) => Number(entry.production_amount),
          cell: (entry) => formatCurrency(entry.production_amount),
        },
        {
          key: "admin",
          header: "Admin",
          sortValue: (entry) => Number(entry.administration_amount),
          cell: (entry) => formatCurrency(entry.administration_amount),
        },
        {
          key: "selling",
          header: "Selling",
          sortValue: (entry) => Number(entry.selling_amount),
          cell: (entry) => formatCurrency(entry.selling_amount),
        },
        {
          key: "status",
          header: "Status",
          sortValue: (entry) => entry.payment_status,
          cell: (entry) => (
            <Badge tone={statusTone(entry.payment_status)}>
              {entry.payment_status}
            </Badge>
          ),
        },
      ]}
    />
  );
}

export function LabourTable({ rows }: { rows: AdHocLabourPayment[] }) {
  return (
    <DataTable
      rows={rows}
      rowKey={(item) => item.id}
      exportFileName="labour-ledger"
      emptyMessage="No ad-hoc labour payments are recorded."
      columns={[
        {
          key: "worker",
          header: "Worker",
          sortValue: (item) => item.worker_name,
          cell: (item) => (
            <span className="font-bold text-[var(--navy)]">{item.worker_name}</span>
          ),
        },
        {
          key: "task",
          header: "Task",
          sortValue: (item) => item.task_description,
          cell: (item) => item.task_description,
        },
        {
          key: "date",
          header: "Date",
          sortValue: (item) => item.work_date,
          cell: (item) => formatDate(item.work_date),
        },
        {
          key: "scope",
          header: "Scope",
          sortValue: (item) => item.cost_scope,
          cell: (item) => <Badge tone="info">{formatLabel(item.cost_scope)}</Badge>,
        },
        {
          key: "status",
          header: "Status",
          sortValue: (item) => item.payment_status,
          cell: (item) => (
            <Badge tone={statusTone(item.payment_status)}>
              {formatLabel(item.payment_status)}
            </Badge>
          ),
        },
        {
          key: "amount",
          header: "Amount",
          sortValue: (item) => Number(item.payment_amount),
          cell: (item) => (
            <span className="font-bold">{formatCurrency(item.payment_amount)}</span>
          ),
        },
      ]}
    />
  );
}

export function ExpenseTable({ rows }: { rows: SharedExpense[] }) {
  return (
    <DataTable
      rows={rows}
      rowKey={(expense) => expense.id}
      exportFileName="expense-ledger"
      emptyMessage="No shared expenses are recorded."
      columns={[
        {
          key: "description",
          header: "Description",
          sortValue: (expense) => expense.description,
          cell: (expense) => (
            <div>
              <p className="font-bold text-[var(--navy)]">{expense.description}</p>
              <p className="text-xs text-[var(--navy-muted)]">{expense.category}</p>
            </div>
          ),
        },
        {
          key: "date",
          header: "Date",
          sortValue: (expense) => expense.expense_date,
          cell: (expense) => formatDate(expense.expense_date),
        },
        {
          key: "scope",
          header: "Scope",
          sortValue: (expense) => expense.scope,
          cell: (expense) => (
            <Badge tone="info">{formatLabel(expense.scope)}</Badge>
          ),
        },
        {
          key: "amount",
          header: "Amount",
          sortValue: (expense) => Number(expense.amount),
          cell: (expense) => (
            <span className="font-bold">{formatCurrency(expense.amount)}</span>
          ),
        },
        {
          key: "status",
          header: "Status",
          sortValue: (expense) =>
            expense.is_capital_expenditure
              ? "capitalized"
              : expense.payment_status,
          cell: (expense) => {
            const label = expense.is_capital_expenditure
              ? "Capitalized"
              : formatLabel(expense.payment_status);
            const tone = expense.is_capital_expenditure
              ? "gold"
              : statusTone(expense.payment_status);
            return <Badge tone={tone}>{label}</Badge>;
          },
        },
      ]}
    />
  );
}

export function ConsumableLotTable({ rows }: { rows: SharedConsumableLot[] }) {
  return (
    <DataTable
      rows={rows}
      rowKey={(lot) => lot.id}
      exportFileName="consumable-lots"
      emptyMessage="No consumable lots have been recorded."
      columns={[
        {
          key: "item",
          header: "Item",
          sortValue: (lot) => lot.item,
          cell: (lot) => (
            <div>
              <p className="font-extrabold text-[var(--navy)]">{lot.item}</p>
              <p className="text-xs text-[var(--navy-muted)]">{lot.category}</p>
            </div>
          ),
        },
        {
          key: "purchased",
          header: "Purchased",
          sortValue: (lot) => lot.purchase_date,
          cell: (lot) => formatDate(lot.purchase_date),
        },
        {
          key: "available",
          header: "Available",
          sortValue: (lot) => Number(lot.quantity_available),
          cell: (lot) =>
            `${formatNumber(lot.quantity_available)} ${lot.unit_of_measurement}`,
        },
        {
          key: "unit_cost",
          header: "Unit cost",
          sortValue: (lot) => Number(lot.unit_cost),
          cell: (lot) => formatCurrency(lot.unit_cost),
        },
        {
          key: "usd",
          header: "USD ref",
          sortValue: (lot) => lot.usd_equivalent ?? "",
          cell: (lot) => (lot.usd_equivalent ? `$${lot.usd_equivalent}` : "—"),
        },
        {
          key: "status",
          header: "Status",
          sortValue: (lot) => (lot.is_expired ? "expired" : lot.payment_status),
          cell: (lot) => (
            <Badge tone={lot.is_expired ? "danger" : statusTone(lot.payment_status)}>
              {lot.is_expired ? "Expired" : formatLabel(lot.payment_status)}
            </Badge>
          ),
        },
      ]}
    />
  );
}

export function ConsumableUsageTable({ rows }: { rows: ConsumableUsage[] }) {
  return (
    <DataTable
      rows={rows}
      rowKey={(usage) => usage.id}
      exportFileName="consumable-usage"
      emptyMessage="No consumable usage has been recognized."
      columns={[
        {
          key: "date",
          header: "Date",
          sortValue: (usage) => usage.usage_date,
          cell: (usage) => formatDate(usage.usage_date),
        },
        {
          key: "scope",
          header: "Scope",
          sortValue: (usage) => usage.usage_scope,
          cell: (usage) => (
            <Badge tone="info">{formatLabel(usage.usage_scope)}</Badge>
          ),
        },
        {
          key: "quantity",
          header: "Quantity",
          sortValue: (usage) => Number(usage.quantity_used),
          cell: (usage) => formatNumber(usage.quantity_used),
        },
        {
          key: "cost",
          header: "Recognized cost",
          sortValue: (usage) => Number(usage.recognized_cost),
          cell: (usage) => (
            <span className="font-bold">
              {formatCurrency(usage.recognized_cost)}
            </span>
          ),
        },
        {
          key: "driver",
          header: "Driver",
          sortValue: (usage) => usage.allocation_driver,
          cell: (usage) => formatLabel(usage.allocation_driver),
        },
      ]}
    />
  );
}

export function AssetTable({ rows }: { rows: Asset[] }) {
  return (
    <DataTable
      rows={rows}
      rowKey={(asset) => asset.id}
      exportFileName="asset-register"
      emptyMessage="No fixed assets have been recorded."
      columns={[
        {
          key: "asset",
          header: "Asset",
          sortValue: (asset) => asset.asset_code || asset.name,
          cell: (asset) => (
            <div>
              <p className="font-extrabold text-[var(--navy)]">
                {asset.asset_code || asset.name}
              </p>
              <p className="text-xs text-[var(--navy-muted)]">{asset.name}</p>
            </div>
          ),
        },
        {
          key: "status",
          header: "Status",
          sortValue: (asset) => asset.status,
          cell: (asset) => (
            <Badge tone={statusTone(asset.status)}>
              {formatLabel(asset.status)}
            </Badge>
          ),
        },
        {
          key: "available",
          header: "Available",
          sortValue: (asset) => asset.available_for_use_date ?? "",
          cell: (asset) =>
            asset.available_for_use_date
              ? formatDate(asset.available_for_use_date)
              : "—",
        },
        {
          key: "cost",
          header: "Capitalized cost",
          sortValue: (asset) => Number(asset.total_capitalized_cost),
          cell: (asset) => (
            <span className="font-bold">
              {formatCurrency(asset.total_capitalized_cost)}
            </span>
          ),
        },
        {
          key: "usd",
          header: "USD ref",
          sortValue: (asset) => asset.usd_equivalent ?? "",
          cell: (asset) =>
            asset.usd_equivalent ? `$${asset.usd_equivalent}` : "—",
        },
        {
          key: "method",
          header: "Method",
          sortValue: (asset) => asset.depreciation_method,
          cell: (asset) => formatLabel(asset.depreciation_method),
        },
      ]}
    />
  );
}

export function PeriodStatusBadge({ period }: { period: AccountingPeriod }) {
  return <Badge tone={statusTone(period.status)}>{period.status}</Badge>;
}
