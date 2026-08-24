"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm, type SubmitHandler } from "react-hook-form";
import { z } from "zod";

import { getApiErrorMessage } from "@/lib/errors";
import { createWeightSample } from "../api/weight-sample-mutations";
import { formatNumber } from "../utils/formatters";

const weightSampleSchema = z.object({
  sampled_at: z.string().min(1, "Weigh date/time is required."),
  age_in_days: z
    .number()
    .int("Age must be a whole number.")
    .min(0, "Age cannot be negative."),
  sample_size: z
    .number()
    .int("Sample size must be a whole number.")
    .min(1, "Weigh at least one bird."),
  average_weight_g: z
    .number()
    .int("Weight must be a whole number of grams.")
    .min(1, "Weight must be greater than zero."),
  reported_by_name: z.string().min(1, "Reported by is required."),
  notes: z.string().optional(),
});

type WeightSampleFormValues = z.infer<typeof weightSampleSchema>;

type AddWeightSampleFormProps = {
  batchId: number;
  defaultAge: number;
  onSuccess?: (created: any) => void;
};

function toDateTimeLocal(date: Date): string {
  const localDate = new Date(date);
  localDate.setMinutes(localDate.getMinutes() - localDate.getTimezoneOffset());
  return localDate.toISOString().slice(0, 16);
}

export function AddWeightSampleForm({
  batchId,
  defaultAge,
  onSuccess,
}: AddWeightSampleFormProps) {
  const [serverError, setServerError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<WeightSampleFormValues>({
    resolver: zodResolver(weightSampleSchema),
    defaultValues: {
      sampled_at: toDateTimeLocal(new Date()),
      age_in_days: Math.max(0, Math.floor(defaultAge || 0)),
      sample_size: 10,
      average_weight_g: 0,
      reported_by_name: "",
      notes: "",
    },
    mode: "onBlur",
  });

  const onSubmit: SubmitHandler<WeightSampleFormValues> = async (values) => {
    setServerError(null);
    setSuccessMessage(null);

    try {
      const payload = {
        ...values,
        notes: values.notes ?? "",
      };
      const created = await createWeightSample(batchId, payload);
      setSuccessMessage("Weight sample recorded. Growth status updated.");
      reset({
        sampled_at: toDateTimeLocal(new Date()),
        age_in_days: Math.max(0, Math.floor(defaultAge || 0)),
        sample_size: 10,
        average_weight_g: 0,
        reported_by_name: "",
        notes: "",
      });
      onSuccess?.(created);
    } catch (error) {
      setServerError(getApiErrorMessage(error));
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="grid gap-5" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="grid gap-1">
          <span className="text-xs font-bold uppercase tracking-[0.14em] text-[var(--navy-muted)]">
            Weigh time
          </span>
          <input type="datetime-local" className="form-input" {...register("sampled_at")} />
          {errors.sampled_at ? (
            <span className="text-sm text-red-700">{errors.sampled_at.message}</span>
          ) : null}
        </label>

        <label className="grid gap-1">
          <span className="text-xs font-bold uppercase tracking-[0.14em] text-[var(--navy-muted)]">
            Age (days since placement)
          </span>
          <input
            type="number"
            min={0}
            step={1}
            className="form-input"
            {...register("age_in_days", { valueAsNumber: true })}
          />
          {errors.age_in_days ? (
            <span className="text-sm text-red-700">{errors.age_in_days.message}</span>
          ) : null}
        </label>

        <label className="grid gap-1">
          <span className="text-xs font-bold uppercase tracking-[0.14em] text-[var(--navy-muted)]">
            Birds weighed (sample size)
          </span>
          <input
            type="number"
            min={1}
            step={1}
            className="form-input"
            {...register("sample_size", { valueAsNumber: true })}
          />
          {errors.sample_size ? (
            <span className="text-sm text-red-700">{errors.sample_size.message}</span>
          ) : null}
        </label>

        <label className="grid gap-1">
          <span className="text-xs font-bold uppercase tracking-[0.14em] text-[var(--navy-muted)]">
            Average weight (grams)
          </span>
          <input
            type="number"
            min={1}
            step={1}
            className="form-input"
            placeholder="e.g. 1250"
            {...register("average_weight_g", { valueAsNumber: true })}
          />
          {errors.average_weight_g ? (
            <span className="text-sm text-red-700">{errors.average_weight_g.message}</span>
          ) : null}
        </label>
      </div>

      <label className="grid gap-1">
        <span className="text-xs font-bold uppercase tracking-[0.14em] text-[var(--navy-muted)]">
          Reported by
        </span>
        <input
          type="text"
          className="form-input"
          placeholder="Name of person who weighed"
          {...register("reported_by_name")}
        />
        {errors.reported_by_name ? (
          <span className="text-sm text-red-700">{errors.reported_by_name.message}</span>
        ) : null}
      </label>

      <label className="grid gap-1">
        <span className="text-xs font-bold uppercase tracking-[0.14em] text-[var(--navy-muted)]">
          Notes (optional)
        </span>
        <textarea
          className="form-input min-h-[72px] resize-y"
          placeholder="Any observations (feed, environment, disease signs...)"
          {...register("notes")}
        />
      </label>

      {serverError ? (
        <p role="alert" className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
          {serverError}
        </p>
      ) : null}

      {successMessage ? (
        <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {successMessage}
        </p>
      ) : null}

      <div className="flex justify-end border-t border-[var(--line)] pt-4">
        <button
          type="submit"
          disabled={isSubmitting}
          className="finance-button disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmitting ? "Recording..." : "Record weight sample"}
        </button>
      </div>

      <p className="text-[11px] text-[var(--navy-muted)]">
        Use a representative sample (minimum 8–10 birds). Weigh at consistent time of day when possible.
      </p>
    </form>
  );
}
