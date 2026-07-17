"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { AccountingPeriod } from "../types";

type SubmitState = {
  status: "idle" | "loading" | "error";
  message: string;
};

const initialState: SubmitState = {
  status: "idle",
  message: "",
};

const STANDARD_WORKING_DAYS_PER_WEEK = 6;

const DEPARTMENT_OPTIONS = [
  ["production", "Production"],
  ["administration", "Administration"],
  ["sales_distribution", "Sales And Distribution"],
  ["finance", "Finance"],
  ["management", "Management"],
  ["other", "Other"],
] as const;

const ROLE_JOB_OPTIONS = [
  ["general_worker", "General Worker", "general_worker"],
  ["farm_supervisor", "Farm Supervisor", "farm_supervisor"],
  ["farm_manager", "Farm Manager", "farm_manager"],
  ["director", "Director", "director"],
  ["stake_holder", "Stake Holder", "stake_holder"],
  ["admin", "Admin", "admin"],
  ["other", "Other", ""],
] as const;

async function postJson(path: string, payload: unknown) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const details = await response.json().catch(() => null);
    throw new Error(details?.detail ?? details?.message ?? "Request failed.");
  }
}

export function EmployeeCreateForm() {
  const router = useRouter();
  const [state, setState] = useState(initialState);
  const [departmentChoice, setDepartmentChoice] = useState("production");
  const [roleChoice, setRoleChoice] = useState("general_worker");
  const [hoursPerDay, setHoursPerDay] = useState("8.00");
  const weeklyHours =
    (Number(hoursPerDay) || 0) * STANDARD_WORKING_DAYS_PER_WEEK;

  async function onSubmit(formData: FormData) {
    setState({ status: "loading", message: "" });
    const selectedRole = ROLE_JOB_OPTIONS.find(([value]) => value === roleChoice);
    const manualRole = String(formData.get("role_other") ?? "").trim();
    const roleSlug = selectedRole?.[2] ?? "";
    const jobTitle = roleChoice === "other" ? manualRole : selectedRole?.[1] ?? "";
    const department =
      departmentChoice === "other"
        ? String(formData.get("department_other") ?? "").trim()
        : DEPARTMENT_OPTIONS.find(([value]) => value === departmentChoice)?.[1] ?? "";
    const payload = {
      username: formData.get("username"),
      email: formData.get("email"),
      first_name: formData.get("first_name"),
      last_name: formData.get("last_name"),
      password: formData.get("password"),
      role_slugs: roleSlug ? [roleSlug] : [],
      employee_number: formData.get("employee_number"),
      employment_type: formData.get("employment_type"),
      job_title: jobTitle,
      department,
      employment_start_date: formData.get("employment_start_date"),
      base_monthly_salary: formData.get("base_monthly_salary"),
      standard_working_hours_per_day: hoursPerDay,
      standard_working_days_per_week: STANDARD_WORKING_DAYS_PER_WEEK.toFixed(2),
      production_percentage: formData.get("production_percentage"),
      administration_percentage: formData.get("administration_percentage"),
      selling_percentage: formData.get("selling_percentage"),
      is_active: true,
    };

    try {
      await postJson("/api/finance/employees", payload);
      setState(initialState);
      router.refresh();
    } catch (error) {
      setState({
        status: "error",
        message: error instanceof Error ? error.message : "Request failed.",
      });
    }
  }

  return (
    <form action={onSubmit} className="grid gap-4 md:grid-cols-2">
      <TextInput label="Username" name="username" required />
      <TextInput label="Email" name="email" type="email" required />
      <TextInput label="First name" name="first_name" />
      <TextInput label="Last name" name="last_name" />
      <TextInput label="Temporary password" name="password" type="password" required />
      <TextInput label="Employee number" name="employee_number" required />
      <label className="grid gap-2 text-sm font-bold text-[var(--navy)]">
        System role/job title
        <select
          name="role_choice"
          className="form-input"
          value={roleChoice}
          onChange={(event) => setRoleChoice(event.target.value)}
        >
          {ROLE_JOB_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {roleChoice === "other" ? (
        <TextInput
          label="Other system role/job title"
          name="role_other"
          required
        />
      ) : null}
      <label className="grid gap-2 text-sm font-bold text-[var(--navy)]">
        Department
        <select
          name="department_choice"
          className="form-input"
          value={departmentChoice}
          onChange={(event) => setDepartmentChoice(event.target.value)}
        >
          {DEPARTMENT_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {departmentChoice === "other" ? (
        <TextInput label="Other department" name="department_other" required />
      ) : null}
      <SelectInput
        label="Employment type"
        name="employment_type"
        options={[
          ["permanent", "Permanent"],
          ["contract", "Contract"],
          ["temporary", "Temporary"],
        ]}
      />
      <TextInput label="Start date" name="employment_start_date" type="date" required />
      <TextInput
        label="Monthly salary"
        name="base_monthly_salary"
        type="number"
        step="0.01"
        required
      />
      <label className="grid gap-2 text-sm font-bold text-[var(--navy)]">
        Hours per day
        <input
          className="form-input"
          name="standard_working_hours_per_day"
          type="number"
          step="0.01"
          value={hoursPerDay}
          onChange={(event) => setHoursPerDay(event.target.value)}
        />
      </label>
      <div className="rounded-lg border border-[var(--line)] bg-white/50 px-4 py-3">
        <p className="text-label text-[var(--navy-muted)]">Weekly hours</p>
        <p className="mt-2 text-lg font-extrabold text-[var(--navy)]">
          {weeklyHours.toFixed(2)}
        </p>
      </div>
      <TextInput
        label="Production %"
        name="production_percentage"
        type="number"
        step="0.01"
        defaultValue="70.00"
      />
      <TextInput
        label="Administration %"
        name="administration_percentage"
        type="number"
        step="0.01"
        defaultValue="20.00"
      />
      <TextInput
        label="Selling %"
        name="selling_percentage"
        type="number"
        step="0.01"
        defaultValue="10.00"
      />
      <FormFooter state={state} label="Create employee" />
    </form>
  );
}

export function EmployeeCreateDialog() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        className="finance-button"
      >
        Create Employee
      </button>
      {isOpen ? (
        <div
          className="fixed inset-0 z-[100] overflow-y-auto bg-[#e9ecf3]/80 px-4 py-8 backdrop-blur-[7px]"
          role="presentation"
          onMouseDown={() => setIsOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-employee-title"
            className="mx-auto w-full max-w-5xl rounded-lg border border-white/90 bg-white p-6 shadow-[0_30px_90px_rgba(21,31,54,0.24)] sm:p-8"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-label text-[var(--navy-muted)]">
                  Workforce
                </p>
                <h2
                  id="create-employee-title"
                  className="mt-2 text-2xl font-extrabold text-[var(--navy)]"
                >
                  Create employee
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="rounded-full border border-[var(--line)] px-4 py-2 text-xs font-extrabold uppercase tracking-[0.14em] text-[var(--navy-muted)] transition hover:bg-[var(--gold-soft)] hover:text-[var(--navy)]"
              >
                Close
              </button>
            </div>
            <div className="mt-6">
              <EmployeeCreateForm />
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

export function PeriodActionButtons({ period }: { period: AccountingPeriod }) {
  const router = useRouter();
  const [state, setState] = useState(initialState);

  async function runAction(action: "generate-payroll" | "recalculate" | "close") {
    if (action === "close" && !confirm("Close this accounting period?")) {
      return;
    }

    setState({ status: "loading", message: "" });
    try {
      await postJson(`/api/finance/accounting-periods/${period.id}/${action}`, {});
      setState(initialState);
      router.refresh();
    } catch (error) {
      setState({
        status: "error",
        message: error instanceof Error ? error.message : "Request failed.",
      });
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button type="button" onClick={() => runAction("generate-payroll")} className="finance-button">
        Generate Payroll
      </button>
      <button type="button" onClick={() => runAction("recalculate")} className="finance-button">
        Recalculate
      </button>
      <button
        type="button"
        onClick={() => runAction("close")}
        disabled={period.status === "closed"}
        className="finance-button disabled:cursor-not-allowed disabled:opacity-50"
      >
        Close Period
      </button>
      {state.status === "error" ? (
        <span className="text-sm font-semibold text-[var(--danger)]">
          {state.message}
        </span>
      ) : null}
    </div>
  );
}

export function AccountingPeriodCreateForm() {
  const router = useRouter();
  const [state, setState] = useState(initialState);

  async function onSubmit(formData: FormData) {
    setState({ status: "loading", message: "" });
    try {
      await postJson("/api/finance/accounting-periods", {
        period_start: formData.get("period_start"),
        period_end: formData.get("period_end"),
        notes: formData.get("notes") || "",
      });
      setState(initialState);
      router.refresh();
    } catch (error) {
      setState({
        status: "error",
        message: error instanceof Error ? error.message : "Request failed.",
      });
    }
  }

  return (
    <form action={onSubmit} className="grid gap-4 md:grid-cols-[1fr_1fr_1.2fr_auto] md:items-end">
      <TextInput
        label="Period start"
        name="period_start"
        type="date"
        placeholder="2026-07-01"
        hint="Example: 2026-07-01"
        required
      />
      <TextInput
        label="Period end"
        name="period_end"
        type="date"
        placeholder="2026-07-31"
        hint="Example: 2026-07-31"
        required
      />
      <TextInput
        label="Notes"
        name="notes"
        placeholder="Example: July 2026 payroll and operating period"
      />
      <div>
        <button
          type="submit"
          disabled={state.status === "loading"}
          className="finance-button w-full disabled:cursor-wait disabled:opacity-60"
        >
          {state.status === "loading" ? "Saving..." : "Create Period"}
        </button>
      </div>
      {state.status === "error" ? (
        <p className="text-sm font-semibold text-[var(--danger)] md:col-span-4">
          {state.message}
        </p>
      ) : null}
    </form>
  );
}

export function LabourPaymentForm({ periods }: { periods: AccountingPeriod[] }) {
  const router = useRouter();
  const [state, setState] = useState(initialState);

  async function onSubmit(formData: FormData) {
    setState({ status: "loading", message: "" });
    try {
      await postJson("/api/finance/ad-hoc-labour", {
        worker_name: formData.get("worker_name"),
        task_description: formData.get("task_description"),
        work_date: formData.get("work_date"),
        hours_worked: formData.get("hours_worked") || "0.00",
        payment_amount: formData.get("payment_amount"),
        cost_scope: formData.get("cost_scope"),
        accounting_period: Number(formData.get("accounting_period")),
        payment_status: formData.get("payment_status"),
      });
      setState(initialState);
      router.refresh();
    } catch (error) {
      setState({
        status: "error",
        message: error instanceof Error ? error.message : "Request failed.",
      });
    }
  }

  return (
    <form action={onSubmit} className="grid gap-4 md:grid-cols-2">
      <TextInput label="Worker name" name="worker_name" required />
      <TextInput label="Task" name="task_description" required />
      <TextInput label="Work date" name="work_date" type="date" required />
      <TextInput label="Hours" name="hours_worked" type="number" step="0.01" />
      <TextInput label="Payment amount" name="payment_amount" type="number" step="0.01" required />
      <SelectInput
        label="Cost scope"
        name="cost_scope"
        options={[
          ["shared_production", "Shared Production"],
          ["batch_direct", "Batch Direct"],
          ["farm_administration", "Farm Administration"],
          ["selling_and_distribution", "Selling And Distribution"],
        ]}
      />
      <PeriodSelect periods={periods} />
      <SelectInput
        label="Payment status"
        name="payment_status"
        options={[
          ["unpaid", "Unpaid"],
          ["paid", "Paid"],
          ["partial", "Partial"],
          ["pending", "Pending"],
        ]}
      />
      <FormFooter state={state} label="Record labour" />
    </form>
  );
}

export function ExpenseForm({ periods }: { periods: AccountingPeriod[] }) {
  const router = useRouter();
  const [state, setState] = useState(initialState);

  async function onSubmit(formData: FormData) {
    setState({ status: "loading", message: "" });
    try {
      await postJson("/api/finance/expenses", {
        description: formData.get("description"),
        category: formData.get("category"),
        expense_date: formData.get("expense_date"),
        accounting_period: Number(formData.get("accounting_period")),
        amount: formData.get("amount"),
        scope: formData.get("scope"),
        payment_status: formData.get("payment_status"),
        allocation_method: "none",
      });
      setState(initialState);
      router.refresh();
    } catch (error) {
      setState({
        status: "error",
        message: error instanceof Error ? error.message : "Request failed.",
      });
    }
  }

  return (
    <form action={onSubmit} className="grid gap-4 md:grid-cols-2">
      <TextInput label="Description" name="description" required />
      <TextInput label="Category" name="category" required />
      <TextInput label="Expense date" name="expense_date" type="date" required />
      <TextInput label="Amount" name="amount" type="number" step="0.01" required />
      <SelectInput
        label="Scope"
        name="scope"
        options={[
          ["shared_production", "Shared Production"],
          ["admin_overhead", "Admin Overhead"],
          ["selling_expense", "Selling Expense"],
          ["finance_cost", "Finance Cost"],
          ["capital_expenditure", "Capital Expenditure"],
          ["tax", "Tax"],
          ["other", "Other"],
        ]}
      />
      <PeriodSelect periods={periods} />
      <SelectInput
        label="Payment status"
        name="payment_status"
        options={[
          ["unpaid", "Unpaid"],
          ["paid", "Paid"],
          ["partial", "Partial"],
          ["pending", "Pending"],
        ]}
      />
      <FormFooter state={state} label="Record expense" />
    </form>
  );
}

function PeriodSelect({ periods }: { periods: AccountingPeriod[] }) {
  return (
    <label className="grid gap-2 text-sm font-bold text-[var(--navy)]">
      Accounting period
      <select name="accounting_period" className="form-input" required>
        {periods.map((period) => (
          <option key={period.id} value={period.id}>
            {period.period_start} to {period.period_end}
          </option>
        ))}
      </select>
    </label>
  );
}

function TextInput({
  label,
  name,
  type = "text",
  step,
  placeholder,
  hint,
  required = false,
  defaultValue,
}: {
  label: string;
  name: string;
  type?: string;
  step?: string;
  placeholder?: string;
  hint?: string;
  required?: boolean;
  defaultValue?: string;
}) {
  return (
    <label className="grid gap-2 text-sm font-bold text-[var(--navy)]">
      {label}
      <input
        className="form-input"
        name={name}
        type={type}
        step={step}
        placeholder={placeholder}
        required={required}
        defaultValue={defaultValue}
      />
      {hint ? (
        <span className="text-xs font-semibold text-[var(--navy-muted)]">
          {hint}
        </span>
      ) : null}
    </label>
  );
}

function SelectInput({
  label,
  name,
  options,
}: {
  label: string;
  name: string;
  options: Array<[string, string]>;
}) {
  return (
    <label className="grid gap-2 text-sm font-bold text-[var(--navy)]">
      {label}
      <select name={name} className="form-input">
        {options.map(([value, optionLabel]) => (
          <option key={value} value={value}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  );
}

function FormFooter({ state, label }: { state: SubmitState; label: string }) {
  return (
    <div className="md:col-span-2">
      <button
        type="submit"
        disabled={state.status === "loading"}
        className="finance-button disabled:cursor-wait disabled:opacity-60"
      >
        {state.status === "loading" ? "Saving..." : label}
      </button>
      {state.status === "error" ? (
        <p className="mt-3 text-sm font-semibold text-[var(--danger)]">
          {state.message}
        </p>
      ) : null}
    </div>
  );
}
