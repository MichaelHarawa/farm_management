"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  useForm,
  useWatch,
  type SubmitHandler,
} from "react-hook-form";

import { createBatchInputCost } from "../api/input-costs";
import { formatCurrency } from "../utils/formatters";
import {
  inputCostSchema,
  type InputCostFormValues,
} from "../validation/input-cost";
import { getApiErrorMessage } from "@/lib/errors";

const unitOptions = [
  {
    value: "kg",
    label: "Kilograms (kg)",
  },
  {
    value: "meters",
    label: "Meters",
  },
  {
    value: "inches",
    label: "Inches",
  },
  {
    value: "gauge",
    label: "Gauge",
  },
  {
    value: "other",
    label: "Other",
  },
  {
    value: "na",
    label: "Not Applicable",
  },
] as const;

function toDateTimeLocal(value: Date): string {
  const timezoneOffsetMs = value.getTimezoneOffset() * 60 * 1000;

  return new Date(value.getTime() - timezoneOffsetMs)
    .toISOString()
    .slice(0, 16);
}

function getDefaultValues(): InputCostFormValues {
  return {
    item: "",
    category: "",
    quantity: 1,
    unit: 1,
    unit_measurement: "kg",
    unit_cost: 0,
    purchase_date: toDateTimeLocal(new Date()),
  };
}

type AddInputCostFormProps = {
  batchId: number;
};

export function AddInputCostForm({
  batchId,
}: AddInputCostFormProps) {
  const router = useRouter();

  const [serverError, setServerError] =
    useState<string | null>(null);

  const [successMessage, setSuccessMessage] =
    useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: {
      errors,
      isSubmitting,
    },
  } = useForm<InputCostFormValues>({
    resolver: zodResolver(inputCostSchema),

    defaultValues: getDefaultValues(),

    mode: "onBlur",
  });

  const quantity = useWatch({
    control,
    name: "quantity",
  }) ?? 0;
  const unit = useWatch({
    control,
    name: "unit",
  }) ?? 0;
  const unitCost = useWatch({
    control,
    name: "unit_cost",
  }) ?? 0;

  const estimatedTotal =
    quantity * unit * unitCost;

  const onSubmit: SubmitHandler<
    InputCostFormValues
  > = async (values) => {
    setServerError(null);
    setSuccessMessage(null);

    try {
      await createBatchInputCost(batchId, values);

      reset(getDefaultValues());

      setSuccessMessage(
        "The input cost was recorded successfully."
      );

      router.refresh();
    } catch (error) {
      setServerError(getApiErrorMessage(error));
    }
  };

  return (
    <form
      onSubmit={handleSubmit(onSubmit)}
      noValidate
      className="grid gap-6"
    >
      <div>
        <p className="text-label text-[var(--navy-muted)]">
          New Input Cost
        </p>

        <h3 className="font-display mt-2 text-3xl tracking-[-0.04em] text-[var(--navy)]">
          Add an expense to this batch.
        </h3>
      </div>

      <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
        <FormField label="Item" error={errors.item?.message}>
          <input
            id="input-cost-item"
            type="text"
            placeholder="Example: KDC"
            {...register("item")}
            className="form-input"
          />
        </FormField>

        <FormField
          label="Category"
          error={errors.category?.message}
        >
          <input
            id="input-cost-category"
            type="text"
            placeholder="Example: Feed"
            {...register("category")}
            className="form-input"
          />
        </FormField>

        <FormField
          label="Number of Items"
          error={errors.quantity?.message}
        >
          <input
            id="input-cost-quantity"
            type="number"
            min="1"
            step="1"
            {...register("quantity", {
              valueAsNumber: true,
            })}
            className="form-input"
          />
        </FormField>

        <FormField
          label="Size per Item"
          error={errors.unit?.message}
        >
          <input
            id="input-cost-unit"
            type="number"
            min="1"
            step="1"
            {...register("unit", {
              valueAsNumber: true,
            })}
            className="form-input"
          />
        </FormField>

        <FormField
          label="Unit measurement"
          error={errors.unit_measurement?.message}
        >
          <select
            id="input-cost-unit-measurement"
            {...register("unit_measurement")}
            className="form-input"
          >
            {unitOptions.map((option) => (
              <option
                key={option.value}
                value={option.value}
              >
                {option.label}
              </option>
            ))}
          </select>
        </FormField>

        <FormField
          label="Cost per unit"
          error={errors.unit_cost?.message}
        >
          <input
            id="input-cost-unit-cost"
            type="number"
            min="1"
            step="1"
            {...register("unit_cost", {
              valueAsNumber: true,
            })}
            className="form-input"
          />
        </FormField>

        <FormField
          label="Purchase date"
          error={errors.purchase_date?.message}
        >
          <input
            id="purchase-date"
            type="datetime-local"
            {...register("purchase_date")}
            className="form-input"
          />
        </FormField>
      </div>

      <div className="flex flex-col gap-4 border-t border-[var(--line)] pt-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-label text-[var(--navy-muted)]">
            Estimated Total
          </p>

          <p className="font-display mt-1 text-3xl font-bold text-[var(--navy)]">
            {formatCurrency(estimatedTotal)}
          </p>
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-full bg-[var(--gold)] px-6 py-3 text-[0.7rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmitting
            ? "Saving..."
            : "Record Input Cost"}
        </button>
      </div>

      {serverError ? (
        <p
          role="alert"
          className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800"
        >
          {serverError}
        </p>
      ) : null}

      {successMessage ? (
        <p
          role="status"
          aria-live="polite"
          className="rounded-lg border border-green-300 bg-green-50 px-4 py-3 text-sm text-green-800"
        >
          {successMessage}
        </p>
      ) : null}
    </form>
  );
}

type FormFieldProps = {
  label: string;
  error?: string;
  children: React.ReactNode;
};

function FormField({
  label,
  error,
  children,
}: FormFieldProps) {
  return (
    <label className="grid gap-2">
      <span className="text-xs font-bold uppercase tracking-[0.15em] text-[var(--navy-muted)]">
        {label}
      </span>

      {children}

      {error ? (
        <span className="text-sm text-red-700">
          {error}
        </span>
      ) : null}
    </label>
  );
}
