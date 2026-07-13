"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useForm, useWatch, type SubmitHandler } from "react-hook-form";

import { getApiErrorMessage } from "@/lib/errors";
import { createBatchVaccination } from "../api/vaccinations";
import type { DrugVaccinationType } from "../types";
import { formatDisplayDateFromValue } from "../utils/vaccinations";
import {
  vaccinationSchema,
  type VaccinationFormValues,
} from "../validation/vaccination";

type AddVaccinationFormProps = {
  batchId: number;
  arrivalDate: string;
  currentBirds: number;
};

const drugVaccinationOptions: Array<{
  value: DrugVaccinationType;
  label: string;
}> = [
  { value: "hitchner", label: "Hitchner" },
  { value: "gumbolo", label: "Gumbolo" },
  { value: "lasota", label: "Lasota" },
  { value: "other", label: "Other" },
];

const scheduledOffsets: Partial<Record<DrugVaccinationType, number>> = {
  hitchner: 7,
  gumbolo: 14,
  lasota: 21,
};

function toDateTimeLocal(value: Date): string {
  const timezoneOffsetMs = value.getTimezoneOffset() * 60 * 1000;

  return new Date(value.getTime() - timezoneOffsetMs)
    .toISOString()
    .slice(0, 16);
}

function startOfLocalDay(value: string | Date): Date {
  const date = new Date(value);

  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(value: string | Date, days: number): Date {
  const date = startOfLocalDay(value);
  date.setDate(date.getDate() + days);

  return date;
}

function getDaysBetween(start: string | Date, end: string | Date): number {
  return Math.round(
    (startOfLocalDay(end).getTime() - startOfLocalDay(start).getTime()) /
      (24 * 60 * 60 * 1000)
  );
}

function calculateTimelyStatus(
  arrivalDate: string,
  vaccinationDate: string,
  drugVaccinationType: DrugVaccinationType
): string {
  const offset = scheduledOffsets[drugVaccinationType];

  if (offset === undefined) {
    return "ontime";
  }

  const expectedDate = addDays(arrivalDate, offset);
  const differenceInDays = getDaysBetween(expectedDate, vaccinationDate);
  const absoluteDifference = Math.abs(differenceInDays);
  const suffix = absoluteDifference === 1 ? "day" : "days";

  if (differenceInDays === 0) {
    return "ontime";
  }

  if (differenceInDays > 0) {
    return `delayed by ${absoluteDifference} ${suffix}`;
  }

  return `early administration by ${absoluteDifference} ${suffix}`;
}

function getExpectedDate(
  arrivalDate: string,
  drugVaccinationType: DrugVaccinationType
): Date | null {
  const offset = scheduledOffsets[drugVaccinationType];

  if (offset === undefined) {
    return null;
  }

  return addDays(arrivalDate, offset);
}

function getDefaultValues(currentBirds: number): VaccinationFormValues {
  return {
    vaccination_date: toDateTimeLocal(new Date()),
    drug_vaccination_type: "hitchner",
    other_drug_vaccination: "",
    quantity: Math.max(currentBirds, 1),
    description: "",
    reported_by_name: "",
  };
}

export function AddVaccinationForm({
  batchId,
  arrivalDate,
  currentBirds,
}: AddVaccinationFormProps) {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors, isSubmitting },
  } = useForm<VaccinationFormValues>({
    resolver: zodResolver(vaccinationSchema),
    defaultValues: getDefaultValues(currentBirds),
    mode: "onBlur",
  });

  const drugVaccinationType = useWatch({
    control,
    name: "drug_vaccination_type",
  });
  const vaccinationDate = useWatch({
    control,
    name: "vaccination_date",
  });

  const expectedDate = getExpectedDate(arrivalDate, drugVaccinationType);
  const timelyStatus = calculateTimelyStatus(
    arrivalDate,
    vaccinationDate,
    drugVaccinationType
  );
  const showOtherDrug = drugVaccinationType === "other";

  const onSubmit: SubmitHandler<VaccinationFormValues> = async (values) => {
    setServerError(null);
    setSuccessMessage(null);

    try {
      await createBatchVaccination(batchId, {
        ...values,
        other_drug_vaccination:
          values.drug_vaccination_type === "other"
            ? values.other_drug_vaccination.trim()
            : "N/A",
        timely_status: calculateTimelyStatus(
          arrivalDate,
          values.vaccination_date,
          values.drug_vaccination_type
        ),
      });

      reset(getDefaultValues(currentBirds));
      setSuccessMessage("The vaccination record was saved.");
      router.refresh();
    } catch (error) {
      setServerError(getApiErrorMessage(error));
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="grid gap-6">
      <div>
        <p className="text-label text-[var(--navy-muted)]">New Vaccination</p>
        <h3 className="font-display mt-2 text-3xl text-[var(--navy)]">
          Record drug or vaccine administration.
        </h3>
      </div>

      <div className="grid gap-5 md:grid-cols-2">
        <FormField
          label="Administration date"
          error={errors.vaccination_date?.message}
        >
          <input
            id="vaccination-date"
            type="datetime-local"
            {...register("vaccination_date")}
            className="form-input"
          />
        </FormField>

        <FormField
          label="Drug / vaccination"
          error={errors.drug_vaccination_type?.message}
        >
          <select
            id="drug-vaccination-type"
            {...register("drug_vaccination_type")}
            className="form-input"
          >
            {drugVaccinationOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FormField>

        {showOtherDrug ? (
          <FormField
            label="Other drug / vaccination"
            error={errors.other_drug_vaccination?.message}
          >
            <input
              id="other-drug-vaccination"
              type="text"
              placeholder="Enter drug or vaccine name"
              {...register("other_drug_vaccination")}
              className="form-input"
            />
          </FormField>
        ) : null}

        <FormField label="Quantity" error={errors.quantity?.message}>
          <input
            id="vaccination-quantity"
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
          label="Reported by"
          error={errors.reported_by_name?.message}
        >
          <input
            id="vaccination-reported-by"
            type="text"
            placeholder="Reporter name"
            {...register("reported_by_name")}
            className="form-input"
          />
        </FormField>

        <div className="md:col-span-2">
          <FormField label="Description" error={errors.description?.message}>
            <textarea
              id="vaccination-description"
              rows={3}
              placeholder="What was administered and any follow-up notes."
              {...register("description")}
              className="form-input resize-y"
            />
          </FormField>
        </div>
      </div>

      <div className="grid gap-4 border-t border-[var(--line)] pt-5 sm:grid-cols-[1fr_auto] sm:items-center">
        <div className="grid gap-3 sm:grid-cols-2">
          <SummaryFigure
            label="Expected Date"
            value={
              expectedDate
                ? formatDisplayDateFromValue(expectedDate)
                : "Custom record"
            }
          />
          <SummaryFigure label="Timely Status" value={timelyStatus} />
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-full bg-[var(--gold)] px-6 py-3 text-[0.7rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmitting ? "Saving..." : "Record Vaccination"}
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
      <p className="font-display mt-1 text-2xl font-bold text-[var(--navy)]">
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
