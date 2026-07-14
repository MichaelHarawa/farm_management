"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMemo, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useForm, useWatch, type SubmitHandler } from "react-hook-form";

import { getApiErrorMessage } from "@/lib/errors";
import { createBatchMortality } from "../api/mortality";
import { formatNumber } from "../utils/formatters";
import {
  createMortalitySchema,
  type MortalityFormValues,
} from "../validation/mortality";

type AddMortalityFormProps = {
  batchId: number;
  availableBirds: number;
  arrivalDate: string;
  defaultAgeInDays: number;
};

function toDateTimeLocal(date: Date): string {
  const localDate = new Date(date);
  localDate.setMinutes(localDate.getMinutes() - localDate.getTimezoneOffset());

  return localDate.toISOString().slice(0, 16);
}

function calculateAgeInDays(arrivalDate: string, mortalityDate: string): number {
  const start = new Date(arrivalDate);
  const end = new Date(mortalityDate);

  if (
    Number.isNaN(start.getTime()) ||
    Number.isNaN(end.getTime())
  ) {
    return 0;
  }

  return Math.max(
    0,
    Math.floor((end.getTime() - start.getTime()) / (24 * 60 * 60 * 1000))
  );
}

export function AddMortalityForm({
  batchId,
  availableBirds,
  arrivalDate,
  defaultAgeInDays,
}: AddMortalityFormProps) {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const defaultMortalityDate = toDateTimeLocal(new Date());
  const schema = useMemo(
    () => createMortalitySchema(availableBirds),
    [availableBirds]
  );

  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors, isSubmitting },
  } = useForm<MortalityFormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      mortality_date: defaultMortalityDate,
      quantity_dead: 1,
      age_in_days: defaultAgeInDays,
      suspected_cause: "",
      description: "",
      action_taken: "",
      reported_by_name: "",
    },
    mode: "onBlur",
  });

  const quantityDead =
    useWatch({
      control,
      name: "quantity_dead",
    }) ?? 0;
  const mortalityDate =
    useWatch({
      control,
      name: "mortality_date",
    }) ?? defaultMortalityDate;

  const projectedAvailableBirds = Math.max(availableBirds - quantityDead, 0);
  const calculatedAgeInDays = calculateAgeInDays(
    arrivalDate,
    mortalityDate
  );

  const onSubmit: SubmitHandler<MortalityFormValues> = async (values) => {
    setServerError(null);
    setSuccessMessage(null);

    try {
      await createBatchMortality(batchId, {
        ...values,
        age_in_days: calculateAgeInDays(
          arrivalDate,
          values.mortality_date
        ),
      });

      reset({
        mortality_date: toDateTimeLocal(new Date()),
        quantity_dead: 1,
        age_in_days: calculateAgeInDays(
          arrivalDate,
          toDateTimeLocal(new Date())
        ),
        suspected_cause: "",
        description: "",
        action_taken: "",
        reported_by_name: "",
      });

      setSuccessMessage("The mortality record was saved.");
      router.refresh();
    } catch (error) {
      setServerError(getApiErrorMessage(error));
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="grid gap-6">
      <div>
        <p className="text-label text-[var(--navy-muted)]">New Mortality</p>

        <h3 className="font-display mt-2 text-3xl text-[var(--navy)]">
          Record flock loss.
        </h3>
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <FormField
          label="Mortality date"
          error={errors.mortality_date?.message}
        >
          <input
            id="mortality-date"
            type="datetime-local"
            {...register("mortality_date")}
            className="form-input"
          />
        </FormField>

        <FormField
          label="Quantity dead"
          error={errors.quantity_dead?.message}
        >
          <input
            id="mortality-quantity-dead"
            type="number"
            min="1"
            max={availableBirds}
            step="1"
            {...register("quantity_dead", {
              valueAsNumber: true,
            })}
            className="form-input"
          />
        </FormField>

        <FormField
          label="Suspected cause"
          error={errors.suspected_cause?.message}
        >
          <input
            id="mortality-cause"
            type="text"
            placeholder="Example: Heat stress"
            {...register("suspected_cause")}
            className="form-input"
          />
        </FormField>

        <FormField
          label="Reported by"
          error={errors.reported_by_name?.message}
        >
          <input
            id="mortality-reported-by"
            type="text"
            placeholder="Reporter name"
            {...register("reported_by_name")}
            className="form-input"
          />
        </FormField>

        <div className="md:col-span-2">
          <FormField label="Description" error={errors.description?.message}>
            <textarea
              id="mortality-description"
              rows={3}
              placeholder="What happened?"
              {...register("description")}
              className="form-input resize-y"
            />
          </FormField>
        </div>

        <div className="md:col-span-2">
          <FormField label="Action taken" error={errors.action_taken?.message}>
            <textarea
              id="mortality-action"
              rows={3}
              placeholder="What was done?"
              {...register("action_taken")}
              className="form-input resize-y"
            />
          </FormField>
        </div>
      </div>

      <div className="grid gap-4 border-t border-[var(--line)] pt-5 sm:grid-cols-[1fr_auto] sm:items-center">
        <div className="grid gap-3 sm:grid-cols-2">
          <SummaryFigure
            label="Available Before"
            value={formatNumber(availableBirds)}
          />
          <SummaryFigure
            label="Available After"
            value={formatNumber(projectedAvailableBirds)}
          />
          <SummaryFigure
            label="Age Recorded"
            value={`${formatNumber(calculatedAgeInDays)} days`}
          />
        </div>

        <button
          type="submit"
          disabled={isSubmitting || availableBirds <= 0}
          className="rounded-full bg-[var(--gold)] px-6 py-3 text-[0.7rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmitting ? "Saving..." : "Record Mortality"}
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

type SummaryFigureProps = {
  label: string;
  value: string;
};

function SummaryFigure({ label, value }: SummaryFigureProps) {
  return (
    <div>
      <p className="text-label text-[var(--navy-muted)]">{label}</p>
      <p className="font-display mt-1 text-3xl font-bold text-[var(--navy)]">
        {value}
      </p>
    </div>
  );
}

type FormFieldProps = {
  label: string;
  error?: string;
  children: ReactNode;
};

function FormField({ label, error, children }: FormFieldProps) {
  return (
    <label className="grid gap-2">
      <span className="text-xs font-bold uppercase tracking-[0.15em] text-[var(--navy-muted)]">
        {label}
      </span>

      {children}

      {error ? <span className="text-sm text-red-700">{error}</span> : null}
    </label>
  );
}
