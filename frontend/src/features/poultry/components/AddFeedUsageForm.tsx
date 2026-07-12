"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useForm, useWatch, type SubmitHandler } from "react-hook-form";

import { getApiErrorMessage } from "@/lib/errors";
import { createBatchFeedUsage } from "../api/feed-usage";
import { formatNumber } from "../utils/formatters";
import {
  feedUsageSchema,
  type FeedUsageFormValues,
} from "../validation/feed-usage";

const feedTypeOptions = [
  { value: "pre_starter", label: "Pre-Starter" },
  { value: "starter", label: "Starter" },
  { value: "grower", label: "Grower" },
  { value: "finisher", label: "Finisher" },
  { value: "pullet_starter", label: "Pullet Starter" },
  { value: "pullet_grower", label: "Pullet Grower" },
  { value: "layers_marsh", label: "Layers Marsh" },
  { value: "layers_finisher", label: "Layers Finisher" },
] as const;

const feedSourceOptions = [
  { value: "cp_feed", label: "CP Feed" },
  { value: "proto_feed", label: "Proto Feed" },
  { value: "concentrates_feed", label: "Concentrates Feed" },
  { value: "self_made", label: "Self Made" },
] as const;

const unitOptions = [
  { value: "kg", label: "Kilograms (kg)" },
  { value: "g", label: "Grams (g)" },
] as const;

type AddFeedUsageFormProps = {
  batchId: number;
  currentBirds: number;
  defaultAgeInDays: number;
};

function toDateTimeLocal(date: Date): string {
  const localDate = new Date(date);
  localDate.setMinutes(localDate.getMinutes() - localDate.getTimezoneOffset());

  return localDate.toISOString().slice(0, 16);
}

export function AddFeedUsageForm({
  batchId,
  currentBirds,
  defaultAgeInDays,
}: AddFeedUsageFormProps) {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const now = toDateTimeLocal(new Date());

  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors, isSubmitting },
  } = useForm<FeedUsageFormValues>({
    resolver: zodResolver(feedUsageSchema),
    defaultValues: {
      initial_age: defaultAgeInDays,
      feeding_start_date: now,
      feeding_end_date: now,
      feed_type: "starter",
      feed_source: "cp_feed",
      quantity_given: 1,
      unit_of_measurement: "kg",
      current_number_of_birds: currentBirds,
      notes: "Recorded through Farmnotes.",
      reported_by_name: "",
    },
    mode: "onBlur",
  });

  const quantityGiven =
    useWatch({
      control,
      name: "quantity_given",
    }) ?? 0;
  const currentNumberOfBirds =
    useWatch({
      control,
      name: "current_number_of_birds",
    }) ?? 0;
  const unitOfMeasurement =
    useWatch({
      control,
      name: "unit_of_measurement",
    }) ?? "kg";

  const feedPerBird =
    currentNumberOfBirds > 0 ? quantityGiven / currentNumberOfBirds : 0;

  const onSubmit: SubmitHandler<FeedUsageFormValues> = async (values) => {
    setServerError(null);
    setSuccessMessage(null);

    try {
      await createBatchFeedUsage(batchId, values);

      const nextNow = toDateTimeLocal(new Date());
      reset({
        initial_age: defaultAgeInDays,
        feeding_start_date: nextNow,
        feeding_end_date: nextNow,
        feed_type: "starter",
        feed_source: "cp_feed",
        quantity_given: 1,
        unit_of_measurement: "kg",
        current_number_of_birds: currentBirds,
        notes: "Recorded through Farmnotes.",
        reported_by_name: "",
      });

      setSuccessMessage("The feed usage record was saved.");
      router.refresh();
    } catch (error) {
      setServerError(getApiErrorMessage(error));
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="grid gap-6">
      <div>
        <p className="text-label text-[var(--navy-muted)]">New Feed Usage</p>

        <h3 className="font-display mt-2 text-3xl text-[var(--navy)]">
          Record feed issued to this flock.
        </h3>
      </div>

      <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
        <FormField label="Initial age" error={errors.initial_age?.message}>
          <input
            id="feed-initial-age"
            type="number"
            min="0"
            step="1"
            {...register("initial_age", {
              valueAsNumber: true,
            })}
            className="form-input"
          />
        </FormField>

        <FormField
          label="Feeding start"
          error={errors.feeding_start_date?.message}
        >
          <input
            id="feed-start"
            type="datetime-local"
            {...register("feeding_start_date")}
            className="form-input"
          />
        </FormField>

        <FormField
          label="Feeding end"
          error={errors.feeding_end_date?.message}
        >
          <input
            id="feed-end"
            type="datetime-local"
            {...register("feeding_end_date")}
            className="form-input"
          />
        </FormField>

        <FormField label="Feed type" error={errors.feed_type?.message}>
          <select
            id="feed-type"
            {...register("feed_type")}
            className="form-input"
          >
            {feedTypeOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FormField>

        <FormField label="Feed source" error={errors.feed_source?.message}>
          <select
            id="feed-source"
            {...register("feed_source")}
            className="form-input"
          >
            {feedSourceOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FormField>

        <FormField
          label="Unit measurement"
          error={errors.unit_of_measurement?.message}
        >
          <select
            id="feed-unit"
            {...register("unit_of_measurement")}
            className="form-input"
          >
            {unitOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FormField>

        <FormField
          label="Quantity given"
          error={errors.quantity_given?.message}
        >
          <input
            id="feed-quantity"
            type="number"
            min="1"
            step="1"
            {...register("quantity_given", {
              valueAsNumber: true,
            })}
            className="form-input"
          />
        </FormField>

        <FormField
          label="Current birds"
          error={errors.current_number_of_birds?.message}
        >
          <input
            id="feed-current-birds"
            type="number"
            min="0"
            step="1"
            {...register("current_number_of_birds", {
              valueAsNumber: true,
            })}
            className="form-input"
          />
        </FormField>

        <FormField
          label="Reported by"
          error={errors.reported_by_name?.message}
        >
          <input
            id="feed-reported-by"
            type="text"
            placeholder="Reporter name"
            {...register("reported_by_name")}
            className="form-input"
          />
        </FormField>

        <div className="lg:col-span-3">
          <FormField label="Notes" error={errors.notes?.message}>
            <textarea
              id="feed-notes"
              rows={3}
              {...register("notes")}
              className="form-input resize-y"
            />
          </FormField>
        </div>
      </div>

      <div className="grid gap-4 border-t border-[var(--line)] pt-5 sm:grid-cols-[1fr_auto] sm:items-center">
        <div className="grid gap-3 sm:grid-cols-2">
          <SummaryFigure
            label="Current Birds"
            value={formatNumber(currentNumberOfBirds)}
          />
          <SummaryFigure
            label="Feed Per Bird"
            value={`${formatNumber(feedPerBird)} ${unitOfMeasurement}`}
          />
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-full bg-[var(--gold)] px-6 py-3 text-[0.7rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmitting ? "Saving..." : "Record Feed Usage"}
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
