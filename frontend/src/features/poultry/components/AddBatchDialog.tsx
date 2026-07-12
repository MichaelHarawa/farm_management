"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Plus, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useForm, useWatch, type SubmitHandler } from "react-hook-form";

import { getApiErrorMessage } from "@/lib/errors";
import { createPoultryBatch } from "../api/batches";
import type { CreatePoultryBatchPayload } from "../types";
import {
  batchSchema,
  type BatchFormValues,
} from "../validation/batch";

const birdTypeOptions = [
  { value: "broilers", label: "Broilers" },
  { value: "layers", label: "Layers" },
  { value: "local", label: "Local" },
  { value: "kloilers", label: "Kloilers" },
  { value: "mikolongwe", label: "Mikolongwe" },
] as const;

const sourceOptions = [
  { value: "Proto", label: "Proto" },
  { value: "Central Poultry", label: "Central Poultry" },
  { value: "Others", label: "Others" },
] as const;

type AddBatchDialogProps = {
  buttonClassName?: string;
};

function toDateTimeLocal(date: Date): string {
  const localDate = new Date(date);
  localDate.setMinutes(localDate.getMinutes() - localDate.getTimezoneOffset());

  return localDate.toISOString().slice(0, 16);
}

function getDefaultValues(): BatchFormValues {
  const entryDate = new Date();
  const maturityDate = new Date(entryDate);
  maturityDate.setDate(maturityDate.getDate() + 46);

  return {
    bird_type: "broilers",
    source: "Central Poultry",
    source_other: "",
    entry_date: toDateTimeLocal(entryDate),
    expected_maturity_date: toDateTimeLocal(maturityDate),
    quantity: 200,
  };
}

export function AddBatchDialog({ buttonClassName }: AddBatchDialogProps) {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors, isSubmitting },
  } = useForm<BatchFormValues>({
    resolver: zodResolver(batchSchema),
    defaultValues: getDefaultValues(),
    mode: "onBlur",
  });

  const selectedSource = useWatch({
    control,
    name: "source",
  });

  const openDialog = () => {
    setServerError(null);
    setIsOpen(true);
  };

  const closeDialog = () => {
    if (isSubmitting) {
      return;
    }

    setServerError(null);
    setIsOpen(false);
  };

  const onSubmit: SubmitHandler<BatchFormValues> = async (values) => {
    setServerError(null);

    const payload: CreatePoultryBatchPayload = {
      bird_type: values.bird_type,
      source:
        values.source === "Others"
          ? values.source_other?.trim() ?? ""
          : values.source,
      entry_date: values.entry_date,
      expected_maturity_date: values.expected_maturity_date,
      quantity: values.quantity,
    };

    try {
      await createPoultryBatch(payload);
      reset(getDefaultValues());
      setIsOpen(false);
      router.refresh();
    } catch (error) {
      setServerError(getApiErrorMessage(error));
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={openDialog}
        className={
          buttonClassName ??
          "inline-flex items-center justify-center gap-2 rounded-full bg-[var(--gold)] px-5 py-3 text-[0.7rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)] transition hover:brightness-95"
        }
      >
        <Plus className="h-4 w-4" aria-hidden="true" />
        Add batch
      </button>

      {isOpen ? (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-[rgba(23,36,67,0.72)] px-4 py-6"
          role="presentation"
          onMouseDown={closeDialog}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="add-batch-title"
            className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] shadow-[var(--shadow-card)]"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 border-b border-[var(--line)] px-6 py-5">
              <div>
                <p className="text-label text-[var(--navy-muted)]">
                  New Production Cycle
                </p>
                <h2
                  id="add-batch-title"
                  className="font-display mt-2 text-4xl leading-none text-[var(--navy)]"
                >
                  Add poultry batch.
                </h2>
              </div>

              <button
                type="button"
                onClick={closeDialog}
                disabled={isSubmitting}
                aria-label="Close add batch dialog"
                className="grid h-10 w-10 place-items-center rounded-full border border-[var(--line)] text-[var(--navy)] transition hover:bg-[var(--gold-soft)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>

            <form
              onSubmit={handleSubmit(onSubmit)}
              noValidate
              className="grid gap-6 px-6 py-6"
            >
              <div className="grid gap-5 md:grid-cols-2">
                <FormField label="Bird type" error={errors.bird_type?.message}>
                  <select
                    id="batch-bird-type"
                    {...register("bird_type")}
                    className="form-input"
                  >
                    {birdTypeOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </FormField>

                <FormField
                  label="Initial birds"
                  error={errors.quantity?.message}
                >
                  <input
                    id="batch-quantity"
                    type="number"
                    min="1"
                    step="1"
                    {...register("quantity", {
                      valueAsNumber: true,
                    })}
                    className="form-input"
                  />
                </FormField>

                <FormField label="Source" error={errors.source?.message}>
                  <select
                    id="batch-source"
                    {...register("source")}
                    className="form-input"
                  >
                    {sourceOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </FormField>

                {selectedSource === "Others" ? (
                  <FormField
                    label="Specify source"
                    error={errors.source_other?.message}
                  >
                    <input
                      id="batch-source-other"
                      type="text"
                      placeholder="Enter source name"
                      {...register("source_other")}
                      className="form-input"
                    />
                  </FormField>
                ) : null}

                <FormField
                  label="Entry date"
                  error={errors.entry_date?.message}
                >
                  <input
                    id="batch-entry-date"
                    type="datetime-local"
                    {...register("entry_date")}
                    className="form-input"
                  />
                </FormField>

                <FormField
                  label="Expected maturity"
                  error={errors.expected_maturity_date?.message}
                >
                  <input
                    id="batch-maturity-date"
                    type="datetime-local"
                    {...register("expected_maturity_date")}
                    className="form-input"
                  />
                </FormField>
              </div>

              {serverError ? (
                <p
                  role="alert"
                  className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800"
                >
                  {serverError}
                </p>
              ) : null}

              <div className="flex flex-col gap-3 border-t border-[var(--line)] pt-5 sm:flex-row sm:items-center sm:justify-between">
                <p className="max-w-md text-sm leading-6 text-[var(--navy-muted)]">
                  Batch ID is generated automatically when the record is saved.
                </p>

                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="inline-flex items-center justify-center gap-2 rounded-full bg-[var(--gold)] px-6 py-3 text-[0.7rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  {isSubmitting ? "Saving..." : "Save batch"}
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
    </>
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
