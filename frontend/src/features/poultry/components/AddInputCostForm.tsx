"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useFieldArray, useForm, useWatch, type SubmitHandler } from "react-hook-form";

import type { FundingSource } from "@/features/finance/types";
import { clientApiFetch } from "@/lib/client-api";
import { getApiErrorMessage } from "@/lib/errors";

import { createBatchInputCost } from "../api/input-costs";
import { formatCurrency } from "../utils/formatters";
import { inputCostSchema, type InputCostFormValues } from "../validation/input-cost";

type FinanceCategory = {
  id: number;
  name: string;
  default_accounting_nature: string;
  requires_item_details: boolean;
  requires_batch_beneficiary: boolean;
};

const unitOptions = [
  { value: "kg", label: "Kilograms (kg)" },
  { value: "g", label: "Grams (g)" },
  { value: "litres", label: "Litres" },
  { value: "items", label: "Individual items" },
  { value: "meters", label: "Meters" },
  { value: "other", label: "Other" },
  { value: "na", label: "Not applicable" },
] as const;

function toDateTimeLocal(value: Date): string {
  const timezoneOffsetMs = value.getTimezoneOffset() * 60 * 1000;
  return new Date(value.getTime() - timezoneOffsetMs).toISOString().slice(0, 16);
}

function submissionKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `cost-${Date.now()}-${Math.random()}`;
}

function getDefaultValues(): InputCostFormValues {
  return {
    item: "",
    category_id: 0,
    quantity: 1,
    unit: 1,
    unit_measurement: "kg",
    unit_cost: 0,
    purchase_date: toDateTimeLocal(new Date()),
    notes: "Recorded through Farmnotes.",
    payment_status: "paid",
    funding_allocations: [{
      funding_source: 0,
      source_query: "",
      amount: 0,
      classification: "reinvestment",
    }],
    idempotency_key: submissionKey(),
  };
}

function fundingSourceLabel(source: FundingSource): string {
  const sourceName = source.display_name || source.description || source.source_type;
  const typeLabel = source.source_type.replaceAll("_", " ");
  return `${sourceName} — ${typeLabel} — ${formatCurrency(Number(source.available_balance || 0))} available`;
}

type AddInputCostFormProps = {
  batchId: number;
  onSuccess?: () => void;
};

export function AddInputCostForm({ batchId, onSuccess }: AddInputCostFormProps) {
  const router = useRouter();
  const [categories, setCategories] = useState<FinanceCategory[]>([]);
  const [fundingSources, setFundingSources] = useState<FundingSource[]>([]);
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    control,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<InputCostFormValues>({
    resolver: zodResolver(inputCostSchema),
    defaultValues: getDefaultValues(),
    mode: "onBlur",
  });

  const { fields, append, remove, replace } = useFieldArray({
    control,
    name: "funding_allocations",
  });

  const quantity = useWatch({ control, name: "quantity" }) ?? 0;
  const unit = useWatch({ control, name: "unit" }) ?? 0;
  const unitCost = useWatch({ control, name: "unit_cost" }) ?? 0;
  const paymentStatus = useWatch({ control, name: "payment_status" });
  const fundingRows = useWatch({ control, name: "funding_allocations" }) ?? [];
  const estimatedTotal = quantity * unit * unitCost;
  const fundingTotal = fundingRows.reduce(
    (sum, row) => sum + (Number(row.amount) || 0),
    0,
  );

  useEffect(() => {
    void Promise.all([
      clientApiFetch<FinanceCategory[]>("/api/finance/expenditure-categories"),
      clientApiFetch<FundingSource[]>("/api/finance/funding-sources"),
    ]).then(([categoryRows, sourceRows]) => {
      setCategories(categoryRows);
      setFundingSources(sourceRows);
    }).catch((error) => setServerError(getApiErrorMessage(error)));
  }, []);

  useEffect(() => {
    if (paymentStatus === "paid" && fields.length === 1 && estimatedTotal > 0) {
      setValue("funding_allocations.0.amount", estimatedTotal, { shouldValidate: true });
    }
  }, [estimatedTotal, fields.length, paymentStatus, setValue]);

  const onSubmit: SubmitHandler<InputCostFormValues> = async (values) => {
    setServerError(null);
    try {
      await createBatchInputCost(batchId, values);
      reset(getDefaultValues());
      router.refresh();
      onSuccess?.();
    } catch (error) {
      setServerError(getApiErrorMessage(error));
    }
  };

  const paymentRegistration = register("payment_status");

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="grid gap-7">
      <div>
        <p className="text-label text-[var(--navy-muted)]">New batch cost</p>
        <h3 className="font-display mt-2 text-3xl tracking-[-0.04em] text-[var(--navy)]">
          Record the cost once.
        </h3>
        <p className="mt-2 text-sm leading-6 text-[var(--navy-muted)]">
          This batch is automatically charged with the cost. The transaction will also appear in Finance Expenditures.
        </p>
      </div>

      <section className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
        <FormField label="Item or service" error={errors.item?.message}>
          <input id="input-cost-item" placeholder="Example: Starter feed" {...register("item")} className="form-input" />
        </FormField>

        <FormField label="Shared finance category" error={errors.category_id?.message}>
          <select id="input-cost-category" {...register("category_id", { valueAsNumber: true })} className="form-input">
            <option value={0}>Select category</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>{category.name}</option>
            ))}
          </select>
        </FormField>

        <FormField label="Purchase date" error={errors.purchase_date?.message}>
          <input id="purchase-date" type="datetime-local" {...register("purchase_date")} className="form-input" />
        </FormField>

        <FormField label="Number of packages/items" error={errors.quantity?.message}>
          <input id="input-cost-quantity" type="number" min="1" step="1" {...register("quantity", { valueAsNumber: true })} className="form-input" />
        </FormField>

        <FormField label="Size or units per package" error={errors.unit?.message}>
          <input id="input-cost-unit" type="number" min="1" step="1" {...register("unit", { valueAsNumber: true })} className="form-input" />
        </FormField>

        <FormField label="Measurement unit" error={errors.unit_measurement?.message}>
          <select id="input-cost-unit-measurement" {...register("unit_measurement")} className="form-input">
            {unitOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </FormField>

        <FormField label="Price per measurement unit" error={errors.unit_cost?.message}>
          <input id="input-cost-unit-cost" type="number" min="0.01" step="0.01" {...register("unit_cost", { valueAsNumber: true })} className="form-input" />
        </FormField>

        <div className="md:col-span-2">
          <FormField label="Notes" error={errors.notes?.message}>
            <textarea id="input-cost-notes" rows={3} placeholder="Supplier, invoice, or purchase context" {...register("notes")} className="form-input resize-y" />
          </FormField>
        </div>
      </section>

      <section className="rounded-xl border border-[var(--line)] bg-[#f8f4e8] p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-label text-[var(--navy-muted)]">Cash ledger</p>
            <h4 className="mt-1 text-xl font-extrabold text-[var(--navy)]">How was this cost paid?</h4>
            <p className="mt-1 text-sm text-[var(--navy-muted)]">
              The payment source can belong to a different batch. It never changes which batch bears this cost.
            </p>
          </div>
          <p className="font-display text-2xl font-bold text-[var(--navy)]">{formatCurrency(estimatedTotal)}</p>
        </div>

        <label className="mt-5 grid gap-2">
          <span className="text-xs font-bold uppercase tracking-[0.15em] text-[var(--navy-muted)]">Payment status</span>
          <select
            {...paymentRegistration}
            onChange={(event) => {
              paymentRegistration.onChange(event);
              if (event.target.value === "credit") replace([]);
              if (event.target.value === "paid" && fields.length === 0) {
                replace([{ funding_source: 0, source_query: "", amount: estimatedTotal, classification: "reinvestment" }]);
              }
            }}
            className="form-input"
          >
            <option value="paid">Paid now</option>
            <option value="credit">Bought on credit / payment still due</option>
          </select>
        </label>

        {paymentStatus === "paid" ? (
          <div className="mt-5 grid gap-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h5 className="font-bold">Paid from</h5>
              <span className={Math.abs(fundingTotal - estimatedTotal) < 0.01 ? "text-sm font-bold text-green-700" : "text-sm font-bold text-amber-700"}>
                {formatCurrency(fundingTotal)} / {formatCurrency(estimatedTotal)}
              </span>
            </div>
            {fields.map((field, index) => (
              <div key={field.id} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_10rem_auto] sm:items-center">
                <input
                  aria-label={`Funding source ${index + 1}`}
                  list={`input-cost-funding-${index}`}
                  placeholder="Search batch revenue, equity, farm cash, or loan…"
                  {...register(`funding_allocations.${index}.source_query`)}
                  onChange={(event) => {
                    const selected = fundingSources.find((source) => fundingSourceLabel(source) === event.target.value);
                    setValue(`funding_allocations.${index}.source_query`, event.target.value);
                    setValue(`funding_allocations.${index}.funding_source`, selected?.id || 0, { shouldValidate: true });
                  }}
                  className="form-input"
                />
                <datalist id={`input-cost-funding-${index}`}>
                  {fundingSources.map((source) => <option key={source.id} value={fundingSourceLabel(source)} />)}
                </datalist>
                <input
                  aria-label={`Funding amount ${index + 1}`}
                  type="number"
                  min="0.01"
                  step="0.01"
                  {...register(`funding_allocations.${index}.amount`, { valueAsNumber: true })}
                  className="form-input"
                />
                {fields.length > 1 ? (
                  <button type="button" onClick={() => remove(index)} className="text-sm font-bold text-red-700">Remove</button>
                ) : null}
                <input type="hidden" {...register(`funding_allocations.${index}.classification`)} />
              </div>
            ))}
            <button
              type="button"
              onClick={() => append({ funding_source: 0, source_query: "", amount: 0, classification: "reinvestment" })}
              className="w-fit text-sm font-bold underline"
            >
              Split across funding sources
            </button>
            {errors.funding_allocations?.message ? (
              <p className="text-sm text-red-700">{errors.funding_allocations.message}</p>
            ) : null}
            {fundingSources.length === 0 ? (
              <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
                No active source has available cash. Record a sale payment or add owner, farm, loan, or grant funds in Finance.
              </p>
            ) : null}
          </div>
        ) : (
          <p className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
            The cost will affect this batch immediately and appear as an outstanding payable. No cash balance changes until payment is recorded.
          </p>
        )}
      </section>

      <div className="flex flex-col gap-4 border-t border-[var(--line)] pt-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-label text-[var(--navy-muted)]">Calculated total</p>
          <p className="font-display mt-1 text-3xl font-bold text-[var(--navy)]">{formatCurrency(estimatedTotal)}</p>
          <p className="mt-1 text-xs text-[var(--navy-muted)]">Packages/items × size per package × price per measurement unit</p>
        </div>
        <button type="submit" disabled={isSubmitting} className="rounded-full bg-[var(--gold)] px-6 py-3 text-[0.7rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60">
          {isSubmitting ? "Saving…" : paymentStatus === "credit" ? "Record payable cost" : "Record paid cost"}
        </button>
      </div>

      {serverError ? <p role="alert" className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">{serverError}</p> : null}
    </form>
  );
}

type FormFieldProps = { label: string; error?: string; children: React.ReactNode };

function FormField({ label, error, children }: FormFieldProps) {
  return (
    <label className="grid gap-2">
      <span className="text-xs font-bold uppercase tracking-[0.15em] text-[var(--navy-muted)]">{label}</span>
      {children}
      {error ? <span className="text-sm text-red-700">{error}</span> : null}
    </label>
  );
}
