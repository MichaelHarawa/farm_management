"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { ClientApiError, clientApiFetch } from "@/lib/client-api";
import type {
  AccountingPeriod,
  EmployeeProfile,
  EmployeeSalaryAdjustment,
} from "../types";
import { formatCurrency, formatDate } from "../utils/formatters";

type Props = {
  employees: EmployeeProfile[];
  periods: AccountingPeriod[];
  adjustments: EmployeeSalaryAdjustment[];
};

function apiErrorMessage(error: unknown): string {
  if (error instanceof ClientApiError && error.details && typeof error.details === "object") {
    const detail = (error.details as { detail?: string | string[] }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.join(" ");
  }
  return error instanceof Error ? error.message : "The salary change could not be saved.";
}

export function SalaryAdjustmentManager({ employees, periods, adjustments }: Props) {
  const router = useRouter();
  const availableEmployees = useMemo(
    () => employees.filter((employee) => employee.is_active && employee.employment_type === "permanent"),
    [employees],
  );
  const openPeriods = useMemo(
    () => [...periods]
      .filter((period) => period.status === "open")
      .sort((left, right) => right.period_start.localeCompare(left.period_start)),
    [periods],
  );
  const [isOpen, setIsOpen] = useState(false);
  const [employeeId, setEmployeeId] = useState("");
  const [periodId, setPeriodId] = useState("");
  const [newSalary, setNewSalary] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const selectedEmployee = availableEmployees.find(
    (employee) => String(employee.id) === employeeId,
  );
  const difference = selectedEmployee && newSalary
    ? Number(newSalary) - Number(selectedEmployee.base_monthly_salary)
    : 0;

  function openDialog() {
    setEmployeeId(availableEmployees[0] ? String(availableEmployees[0].id) : "");
    setPeriodId(openPeriods[0] ? String(openPeriods[0].id) : "");
    setNewSalary("");
    setReason("");
    setError("");
    setIsOpen(true);
  }

  async function submitAdjustment(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await clientApiFetch("/api/finance/salary-adjustments", {
        method: "POST",
        body: JSON.stringify({
          employee: Number(employeeId),
          effective_period: Number(periodId),
          new_salary: newSalary,
          reason,
        }),
      });
      setIsOpen(false);
      router.refresh();
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-extrabold text-[var(--navy)]">Salary rates</p>
          <p className="mt-1 max-w-2xl text-sm text-[var(--navy-muted)]">
            Schedule an increase or reduction from an open payroll period. Generated payroll remains unchanged.
          </p>
        </div>
        <button
          type="button"
          className="finance-button w-full sm:w-auto"
          onClick={openDialog}
        >
          Adjust salary
        </button>
      </div>

      {adjustments.length ? (
        <div className="mt-5 grid gap-3 lg:grid-cols-2">
          {adjustments.slice(0, 6).map((adjustment) => (
            <article
              key={adjustment.id}
              className="rounded-xl border border-[var(--line)] bg-white/65 p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-extrabold text-[var(--navy)]">{adjustment.employee_name}</p>
                  <p className="mt-1 text-xs text-[var(--navy-muted)]">
                    Effective {adjustment.effective_period_label}
                  </p>
                </div>
                <span className={`rounded-full px-2.5 py-1 text-xs font-extrabold capitalize ${adjustment.change_type === "increase" ? "bg-green-100 text-green-800" : "bg-red-50 text-red-800"}`}>
                  {adjustment.change_type}
                </span>
              </div>
              <p className="mt-3 text-sm text-[var(--navy-muted)]">
                {formatCurrency(adjustment.previous_salary)} <span aria-hidden="true">→</span>{" "}
                <strong className="text-[var(--navy)]">{formatCurrency(adjustment.new_salary)}</strong>
              </p>
              <p className="mt-2 text-sm text-[var(--navy)]">{adjustment.reason}</p>
              <p className="mt-3 text-xs text-[var(--navy-muted)]">
                Recorded {formatDate(adjustment.created_at)}{adjustment.created_by_name ? ` by ${adjustment.created_by_name}` : ""}
              </p>
            </article>
          ))}
        </div>
      ) : (
        <p className="mt-5 rounded-xl border border-dashed border-[var(--line)] p-4 text-sm text-[var(--navy-muted)]">
          No salary changes have been recorded yet.
        </p>
      )}

      {isOpen ? (
        <div
          className="fixed inset-0 z-50 grid place-items-end bg-black/60 p-0 sm:place-items-center sm:p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="salary-adjustment-title"
        >
          <form
            onSubmit={submitAdjustment}
            className="max-h-[94dvh] w-full overflow-y-auto rounded-t-3xl border border-[var(--line)] bg-[var(--surface-white)] p-5 shadow-2xl sm:max-w-xl sm:rounded-3xl sm:p-7"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-label text-[var(--navy-muted)]">Payroll salary</p>
                <h2 id="salary-adjustment-title" className="mt-2 text-2xl font-extrabold text-[var(--navy)]">
                  Adjust employee salary
                </h2>
              </div>
              <button
                type="button"
                className="grid size-11 shrink-0 place-items-center rounded-full border border-[var(--line)] text-xl font-bold text-[var(--navy)]"
                onClick={() => setIsOpen(false)}
                aria-label="Close salary adjustment"
              >
                ×
              </button>
            </div>

            <div className="mt-6 grid gap-4">
              <label className="grid gap-2">
                <span className="text-label text-[var(--navy-muted)]">Employee</span>
                <select
                  className="form-input"
                  value={employeeId}
                  onChange={(event) => setEmployeeId(event.target.value)}
                  required
                >
                  <option value="">Select employee</option>
                  {availableEmployees.map((employee) => (
                    <option key={employee.id} value={employee.id}>
                      {employee.display_name} · {employee.employee_number}
                    </option>
                  ))}
                </select>
              </label>

              {selectedEmployee ? (
                <div className="rounded-xl bg-[var(--gold-soft)] p-4">
                  <span className="text-label text-[var(--navy-muted)]">Latest configured salary</span>
                  <strong className="mt-1 block text-xl text-[var(--navy)]">
                    {formatCurrency(selectedEmployee.base_monthly_salary)}
                  </strong>
                </div>
              ) : null}

              <label className="grid gap-2">
                <span className="text-label text-[var(--navy-muted)]">New monthly salary</span>
                <input
                  className="form-input"
                  type="number"
                  inputMode="decimal"
                  min="0.01"
                  step="0.01"
                  value={newSalary}
                  onChange={(event) => setNewSalary(event.target.value)}
                  placeholder="0.00"
                  required
                />
              </label>

              {selectedEmployee && newSalary && difference !== 0 ? (
                <p className={`rounded-xl px-4 py-3 text-sm font-bold ${difference > 0 ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>
                  {difference > 0 ? "Increase" : "Reduction"} of {formatCurrency(Math.abs(difference))}
                </p>
              ) : null}

              <label className="grid gap-2">
                <span className="text-label text-[var(--navy-muted)]">Effective payroll period</span>
                <select
                  className="form-input"
                  value={periodId}
                  onChange={(event) => setPeriodId(event.target.value)}
                  required
                >
                  <option value="">Select open period</option>
                  {openPeriods.map((period) => (
                    <option key={period.id} value={period.id}>
                      {formatDate(period.period_start)} to {formatDate(period.period_end)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="grid gap-2">
                <span className="text-label text-[var(--navy-muted)]">Reason for change</span>
                <textarea
                  className="form-input min-h-24 resize-y"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  maxLength={500}
                  placeholder="For example: annual salary review or role change"
                  required
                />
              </label>
            </div>

            {!openPeriods.length ? (
              <p className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
                Create or reopen an accounting period before adjusting a salary.
              </p>
            ) : null}
            {error ? <p className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p> : null}

            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              <button
                type="button"
                className="min-h-12 rounded-xl border border-[var(--navy)] px-5 font-extrabold text-[var(--navy)]"
                onClick={() => setIsOpen(false)}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={busy || !availableEmployees.length || !openPeriods.length || difference === 0}
                className="min-h-12 rounded-xl bg-[var(--gold)] px-5 font-extrabold text-[var(--navy)] disabled:cursor-not-allowed disabled:opacity-45"
              >
                {busy ? "Saving…" : "Save salary change"}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </>
  );
}
