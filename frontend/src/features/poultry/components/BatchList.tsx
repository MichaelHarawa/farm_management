"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { CalendarDays, CheckCircle2, Eye, Table2, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createPortal } from "react-dom";
import {
  useMemo,
  useState,
  type FormEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { useForm, type SubmitHandler } from "react-hook-form";

import { getApiErrorMessage } from "@/lib/errors";
import {
  confirmPoultryBatchDelivery,
  markPoultryBatchDelivered,
} from "../api/batch-mutations";
import type { PoultryBatch } from "../types";
import {
  deliverySchema,
  type DeliveryFormValues,
} from "../validation/batch";

type BatchListProps = {
  batches: PoultryBatch[];
  addBatchAction?: ReactNode;
};

const DEFAULT_MATURITY_DAYS = 46;

function formatDate(value?: string | null): string {
  if (!value) {
    return "-";
  }

  const normalized = value.includes("T") ? value : `${value}T00:00:00`;

  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "2-digit",
  }).format(new Date(normalized));
}

function formatBirdType(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function getDaysToMaturity(value: string): number {
  const today = new Date();
  const maturityDate = new Date(value);
  const dayInMs = 24 * 60 * 60 * 1000;

  return Math.ceil((maturityDate.getTime() - today.getTime()) / dayInMs);
}

function toDateTimeLocal(date: Date): string {
  const localDate = new Date(date);
  localDate.setMinutes(localDate.getMinutes() - localDate.getTimezoneOffset());

  return localDate.toISOString().slice(0, 16);
}

function valueToDateTimeLocal(value?: string | null): string {
  if (!value) {
    return toDateTimeLocal(new Date());
  }

  if (!value.includes("T")) {
    return `${value}T08:00`;
  }

  return toDateTimeLocal(new Date(value));
}

function addDaysToDateTimeLocal(value: string, days: number): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "";
  }

  date.setDate(date.getDate() + days);
  return toDateTimeLocal(date);
}

function getBatchTimelineDate(batch: PoultryBatch): Date {
  if (batch.status === "booked" && batch.booking_date) {
    return new Date(`${batch.booking_date}T00:00:00`);
  }

  if (batch.status === "delivered" && batch.delivery_confirmed_at) {
    return new Date(batch.delivery_confirmed_at);
  }

  return new Date(batch.entry_date);
}

function getStatusLabel(batch: PoultryBatch, isMature: boolean): string {
  if (batch.status === "booked") {
    return "Booked";
  }

  if (batch.status === "delivered") {
    return "Delivered";
  }

  if (batch.status === "closed") {
    return "Closed";
  }

  return isMature ? "Review" : "Active";
}

function getStatusPillClass(batch: PoultryBatch, isMature: boolean): string {
  if (batch.status === "booked") {
    return "bg-[#eef2ff] text-[#43518f]";
  }

  if (batch.status === "delivered") {
    return "bg-[var(--gold-soft)] text-[var(--navy)]";
  }

  if (batch.status === "closed") {
    return "bg-[#f3f5fa] text-[var(--navy-muted)]";
  }

  return isMature
    ? "bg-[var(--gold-soft)] text-[var(--navy)]"
    : "bg-[#e7f4e7] text-[#4e8b61]";
}

export function BatchList({ batches, addBatchAction }: BatchListProps) {
  const [showLastThreeMonths, setShowLastThreeMonths] = useState(false);
  const [selectedBatch, setSelectedBatch] =
    useState<PoultryBatch | null>(null);
  const visibleBatches = useMemo(() => {
    if (!showLastThreeMonths) {
      return batches;
    }

    const startDate = new Date();
    startDate.setMonth(startDate.getMonth() - 3);

    return batches.filter((batch) => getBatchTimelineDate(batch) >= startDate);
  }, [batches, showLastThreeMonths]);

  function exportView() {
    const columns = [
      "Batch ID",
      "Bird Type",
      "Quantity",
      "Booking Date",
      "Expected Delivery",
      "Entry Date",
      "Maturity Date",
      "Status",
    ];
    const rows = visibleBatches.map((batch) => {
      const daysToMaturity = getDaysToMaturity(batch.expected_maturity_date);

      return [
        batch.batch_id,
        formatBirdType(batch.bird_type),
        batch.quantity.toString(),
        formatDate(batch.booking_date),
        formatDate(batch.estimated_chick_arrival_date),
        formatDate(batch.entry_date),
        formatDate(batch.expected_maturity_date),
        getStatusLabel(batch, daysToMaturity <= 0),
      ];
    });
    const csvRows = [columns, ...rows].map((row) =>
      row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(",")
    );
    const blob = new Blob([csvRows.join("\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = url;
    link.download = "poultry-batch-register.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  if (batches.length === 0) {
    return (
      <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-10 text-center shadow-[var(--shadow-card)]">
        <span className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-[var(--gold-soft)] text-[var(--navy)]">
          <Table2 className="h-5 w-5" aria-hidden="true" />
        </span>

        <p className="text-label mt-5 text-[var(--navy-muted)]">
          Batch Register / Empty
        </p>

        <h2 className="font-display mt-4 text-4xl text-[var(--navy)]">
          No production cycles yet.
        </h2>

        <p className="mx-auto mt-3 max-w-md text-sm leading-6 text-[var(--navy-muted)]">
          Book incoming chicks first. Once delivery is confirmed, the record
          can become a normal production batch.
        </p>

        {addBatchAction ? (
          <div className="mt-6 flex justify-center">{addBatchAction}</div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] shadow-[var(--shadow-card)]">
      <div className="grid gap-5 border-b border-[var(--line)] px-5 py-6 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
        <div className="min-w-0">
          <p className="text-label text-[var(--navy-muted)]">
            Executive Register / Poultry
          </p>

          <h2 className="font-display mt-3 text-4xl leading-none text-[var(--navy)]">
            Batch portfolio.
          </h2>

          <p className="mt-3 max-w-2xl text-sm leading-6 text-[var(--navy-muted)]">
            Scan bookings, flock size, delivery timing, and production status
            before opening the full batch workspace.
          </p>
        </div>

        <div className="flex min-w-0 flex-wrap justify-start gap-2 xl:justify-end">
          {addBatchAction}

          <button
            type="button"
            onClick={() => setShowLastThreeMonths((current) => !current)}
            className={`inline-flex h-10 items-center justify-center whitespace-nowrap rounded-full border border-[var(--line)] px-4 text-[0.65rem] font-bold uppercase tracking-[0.12em] text-[var(--navy)] transition ${
              showLastThreeMonths
                ? "bg-[var(--gold-soft)]"
                : "bg-white/40 hover:bg-white"
            }`}
          >
            Last 3 Months
          </button>

          <button
            type="button"
            onClick={exportView}
            disabled={visibleBatches.length === 0}
            className="inline-flex h-10 items-center justify-center whitespace-nowrap rounded-full bg-[var(--gold)] px-4 text-[0.65rem] font-bold uppercase tracking-[0.12em] text-[var(--navy)] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Export View
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse">
          <thead>
            <tr className="border-b border-[var(--line)] bg-[var(--surface-cream-soft)]">
              <TableHead label="Batch" />
              <TableHead label="Flock" />
              <TableHead label="Placement" />
              <TableHead label="Maturity" />
              <TableHead label="Status" />
              <TableHead label="Readout" align="right" />
            </tr>
          </thead>

          <tbody>
            {visibleBatches.length === 0 ? (
              <tr>
                <td
                  colSpan={6}
                  className="px-6 py-10 text-center text-sm text-[var(--navy-muted)]"
                >
                  No batches match the selected time window.
                </td>
              </tr>
            ) : null}

            {visibleBatches.map((batch) => {
              const daysToMaturity = getDaysToMaturity(
                batch.expected_maturity_date
              );
              const isMature = daysToMaturity <= 0;
              const isBooked = batch.status === "booked";
              const isDelivered = batch.status === "delivered";
              const statusLabel = getStatusLabel(batch, isMature);
              const statusClass = getStatusPillClass(batch, isMature);

              return (
                <tr
                  key={batch.id}
                  onClick={() => setSelectedBatch(batch)}
                  tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedBatch(batch);
                    }
                  }}
                  className="cursor-pointer border-b border-[var(--line)] transition hover:bg-[var(--gold-soft)]/45 focus:bg-[var(--gold-soft)]/45 focus:outline-none"
                >
                  <td className="min-w-64 px-6 py-5">
                    <p className="text-sm font-extrabold text-[var(--navy)]">
                      {batch.batch_id}
                    </p>
                    <p className="mt-2 text-xs font-bold uppercase tracking-[0.14em] text-[var(--navy-muted)]">
                      {formatBirdType(batch.bird_type)} cycle
                    </p>
                  </td>

                  <td className="min-w-48 px-6 py-5">
                    <p className="font-display text-3xl font-bold leading-none text-[var(--navy)]">
                      {batch.quantity.toLocaleString()}
                    </p>
                    <div className="mt-3 h-2 w-32 overflow-hidden rounded-full bg-[var(--surface-cream-soft)]">
                      <div className="h-full w-full rounded-full bg-[var(--gold)]" />
                    </div>
                  </td>

                  <td className="min-w-44 px-6 py-5 text-sm text-[var(--navy-soft)]">
                    <div className="flex items-center gap-2">
                      <CalendarDays className="h-4 w-4 text-[var(--navy-muted)]" />
                      {isBooked
                        ? formatDate(batch.estimated_chick_arrival_date)
                        : formatDate(batch.entry_date)}
                    </div>
                    <p className="mt-2 text-xs font-bold uppercase tracking-[0.12em] text-[var(--navy-muted)]">
                      {isBooked
                        ? "Expected delivery"
                        : isDelivered
                          ? "Delivered"
                          : "Placement"}
                    </p>
                  </td>

                  <td className="min-w-48 px-6 py-5">
                    <p className="text-sm font-semibold text-[var(--navy)]">
                      {formatDate(batch.expected_maturity_date)}
                    </p>
                    <p className="mt-2 text-xs font-bold uppercase tracking-[0.14em] text-[var(--navy-muted)]">
                      {isBooked
                        ? "Projected after arrival"
                        : isDelivered
                          ? "Add batch details"
                          : isMature
                            ? "Maturity reached"
                            : `${daysToMaturity} days remaining`}
                    </p>
                  </td>

                  <td className="min-w-40 px-6 py-5">
                    <span
                      className={`inline-flex rounded-full px-3 py-1 text-[0.68rem] font-bold uppercase tracking-[0.12em] ${statusClass}`}
                    >
                      {statusLabel}
                    </span>
                  </td>

                  <td className="min-w-44 px-6 py-5 text-right">
                    <div className="inline-flex justify-end">
                      {isBooked ? (
                        <MarkDeliveredDialog batch={batch} />
                      ) : isDelivered ? (
                        <ConfirmDeliveryDialog batch={batch} />
                      ) : (
                        <Link
                          href={`/poultry/batches/${batch.id}`}
                          onClick={(event) => event.stopPropagation()}
                          aria-label={`View ${batch.batch_id}`}
                          title={`View ${batch.batch_id}`}
                          className="inline-grid h-10 w-14 place-items-center rounded-full bg-[var(--gold)] text-[var(--navy)] transition hover:bg-[var(--gold-soft)]"
                        >
                          <Eye className="h-5 w-5" aria-hidden="true" />
                        </Link>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-col gap-3 border-t border-[var(--line)] px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]">
          {visibleBatches.length} of {batches.length} records shown
          {showLastThreeMonths ? " / last 3 months" : ""}
        </p>

        <p className="text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]">
          Updated live
        </p>
      </div>

      <BatchRecordModal
        batch={selectedBatch}
        onClose={() => setSelectedBatch(null)}
      />
    </div>
  );
}

type MarkDeliveredDialogProps = {
  batch: PoultryBatch;
};

function MarkDeliveredDialog({ batch }: MarkDeliveredDialogProps) {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const [selectedStatus, setSelectedStatus] = useState<"booked" | "delivered">(
    "booked"
  );
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const openDialog = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    setSelectedStatus("booked");
    setServerError(null);
    setIsOpen(true);
  };

  const closeDialog = () => {
    if (!isSubmitting) {
      setIsOpen(false);
    }
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setServerError(null);

    if (selectedStatus !== "delivered") {
      setServerError("Change the status to delivered before saving.");
      return;
    }

    setIsSubmitting(true);

    try {
      await markPoultryBatchDelivered(batch.id);
      setIsOpen(false);
      router.refresh();
    } catch (error) {
      setServerError(getApiErrorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={openDialog}
        className="inline-flex h-10 items-center justify-center whitespace-nowrap rounded-full border border-[var(--line)] bg-white/60 px-4 text-[0.65rem] font-bold uppercase tracking-[0.1em] text-[var(--navy)] transition hover:bg-[var(--gold-soft)]"
      >
        Mark Delivered
      </button>

      {isOpen && typeof document !== "undefined"
        ? createPortal(
            <DialogBackdrop onClose={closeDialog}>
              <section
                role="dialog"
                aria-modal="true"
                aria-labelledby="mark-delivered-title"
                className="w-full max-w-md rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] shadow-[var(--shadow-card)]"
                onMouseDown={(event) => event.stopPropagation()}
              >
                <DialogHeader
                  title="Confirm delivery."
                  eyebrow={batch.batch_id}
                  labelId="mark-delivered-title"
                  onClose={closeDialog}
                  disabled={isSubmitting}
                />

                <form onSubmit={onSubmit} className="grid gap-5 px-6 py-6">
                  <FormField label="Status">
                    <select
                      value={selectedStatus}
                      onChange={(event) =>
                        setSelectedStatus(
                          event.target.value as "booked" | "delivered"
                        )
                      }
                      className="form-input"
                    >
                      <option value="booked">Booked</option>
                      <option value="delivered">Delivered at farm</option>
                    </select>
                  </FormField>

                  {serverError ? <ErrorMessage message={serverError} /> : null}

                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="inline-flex items-center justify-center gap-2 rounded-full bg-[var(--gold)] px-5 py-3 text-[0.7rem] font-bold uppercase tracking-[0.12em] text-[var(--navy)] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                    {isSubmitting ? "Saving..." : "Save status"}
                  </button>
                </form>
              </section>
            </DialogBackdrop>,
            document.body
          )
        : null}
    </>
  );
}

type ConfirmDeliveryDialogProps = {
  batch: PoultryBatch;
};

function getDefaultDeliveryValues(batch: PoultryBatch): DeliveryFormValues {
  const entryDate = valueToDateTimeLocal(
    batch.delivery_confirmed_at ?? batch.estimated_chick_arrival_date
  );

  return {
    entry_date: entryDate,
    expected_maturity_date: addDaysToDateTimeLocal(
      entryDate,
      DEFAULT_MATURITY_DAYS
    ),
    quantity: batch.quantity || 1,
  };
}

function ConfirmDeliveryDialog({ batch }: ConfirmDeliveryDialogProps) {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<DeliveryFormValues>({
    resolver: zodResolver(deliverySchema),
    defaultValues: getDefaultDeliveryValues(batch),
    mode: "onBlur",
  });

  const openDialog = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    setServerError(null);
    reset(getDefaultDeliveryValues(batch));
    setIsOpen(true);
  };

  const closeDialog = () => {
    if (!isSubmitting) {
      setIsOpen(false);
    }
  };

  const onSubmit: SubmitHandler<DeliveryFormValues> = async (values) => {
    setServerError(null);

    try {
      await confirmPoultryBatchDelivery(batch.id, {
        entry_date: values.entry_date,
        expected_maturity_date: values.expected_maturity_date,
        quantity: values.quantity,
      });
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
        className="inline-flex h-10 items-center justify-center whitespace-nowrap rounded-full bg-[var(--gold)] px-4 text-[0.65rem] font-bold uppercase tracking-[0.1em] text-[var(--navy)] transition hover:brightness-95"
      >
        Add Batch
      </button>

      {isOpen && typeof document !== "undefined"
        ? createPortal(
            <DialogBackdrop onClose={closeDialog}>
              <section
                role="dialog"
                aria-modal="true"
                aria-labelledby="confirm-delivery-title"
                className="w-full max-w-2xl rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] shadow-[var(--shadow-card)]"
                onMouseDown={(event) => event.stopPropagation()}
              >
                <DialogHeader
                  title="Add batch details."
                  eyebrow={batch.batch_id}
                  labelId="confirm-delivery-title"
                  onClose={closeDialog}
                  disabled={isSubmitting}
                />

                <form
                  onSubmit={handleSubmit(onSubmit)}
                  noValidate
                  className="grid gap-6 px-6 py-6"
                >
                  <div className="grid gap-5 sm:grid-cols-2">
                    <FormField
                      label="Delivery date"
                      error={errors.entry_date?.message}
                    >
                      <input
                        type="datetime-local"
                        {...register("entry_date")}
                        className="form-input"
                      />
                    </FormField>

                    <FormField
                      label="Confirmed chicks"
                      error={errors.quantity?.message}
                    >
                      <input
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
                      label="Expected maturity"
                      error={errors.expected_maturity_date?.message}
                    >
                      <input
                        type="datetime-local"
                        {...register("expected_maturity_date")}
                        className="form-input"
                      />
                    </FormField>
                  </div>

                  {serverError ? <ErrorMessage message={serverError} /> : null}

                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="inline-flex w-fit items-center justify-center gap-2 rounded-full bg-[var(--gold)] px-5 py-3 text-[0.7rem] font-bold uppercase tracking-[0.12em] text-[var(--navy)] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                    {isSubmitting ? "Saving..." : "Create batch"}
                  </button>
                </form>
              </section>
            </DialogBackdrop>,
            document.body
          )
        : null}
    </>
  );
}

type BatchRecordModalProps = {
  batch: PoultryBatch | null;
  onClose: () => void;
};

function BatchRecordModal({ batch, onClose }: BatchRecordModalProps) {
  if (!batch) {
    return null;
  }

  if (typeof document === "undefined") {
    return null;
  }

  const daysToMaturity = getDaysToMaturity(batch.expected_maturity_date);
  const isMature = daysToMaturity <= 0;
  const isBooked = batch.status === "booked";
  const isDelivered = batch.status === "delivered";
  const status = getStatusLabel(batch, isMature);
  const readout = isBooked
    ? `Expected delivery ${formatDate(batch.estimated_chick_arrival_date)}`
    : isDelivered
      ? "Ready for batch details"
      : isMature
        ? "Maturity reached"
        : `${Math.max(0, daysToMaturity)} days remaining`;

  return createPortal(
    <div
      className="fixed inset-0 z-[100] overflow-y-auto bg-[#e9ecf3]/80 px-4 py-8 backdrop-blur-[7px]"
      role="presentation"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="batch-row-detail-title"
        className="relative mx-auto mt-12 w-full max-w-4xl overflow-hidden rounded-[1.75rem] border border-white/90 bg-white shadow-[0_30px_90px_rgba(21,31,54,0.24)]"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="relative px-8 py-8 sm:px-12 sm:py-10">
          <div className="flex items-start justify-between gap-6">
            <div>
              <p className="text-xs font-extrabold uppercase tracking-[0.18em] text-[var(--navy-muted)]">
                Batch Detail
              </p>
              <h2
                id="batch-row-detail-title"
                className="mt-4 max-w-2xl text-3xl font-extrabold leading-tight text-[var(--navy)] sm:text-4xl"
              >
                {batch.batch_id}
              </h2>
              <p className="mt-3 text-base leading-7 text-[var(--navy-muted)]">
                Production cycle summary from booking through maturity.
              </p>
            </div>

            <button
              type="button"
              aria-label="Close batch detail"
              title="Close"
              onClick={onClose}
              className="grid h-11 w-11 shrink-0 place-items-center rounded-full text-[var(--navy-muted)] transition hover:bg-[var(--gold-soft)] hover:text-[var(--navy)]"
            >
              <X className="h-6 w-6" aria-hidden="true" />
            </button>
          </div>

          <div className="mt-9 border-t border-[var(--line)] pt-8">
            <div className="grid gap-x-16 gap-y-8 md:grid-cols-2">
              <BatchDetailField
                label="Bird Type"
                value={`${formatBirdType(batch.bird_type)} cycle`}
              />
              <BatchDetailField
                label={isBooked ? "Booked Chicks" : "Initial Birds"}
                value={batch.quantity.toLocaleString()}
              />
              <BatchDetailField
                label={isBooked ? "Booking" : "Placement"}
                value={formatDate(isBooked ? batch.booking_date : batch.entry_date)}
              />
              <BatchDetailField
                label={isBooked ? "Expected Delivery" : "Maturity"}
                value={formatDate(
                  isBooked
                    ? batch.estimated_chick_arrival_date
                    : batch.expected_maturity_date
                )}
              />
              <BatchDetailField label="Status" value={status} pill />
              <BatchDetailField label="Readout" value={readout} />
            </div>
          </div>

          <div className="mt-10 flex flex-col gap-3 sm:flex-row sm:items-center">
            {isBooked ? (
              <MarkDeliveredDialog batch={batch} />
            ) : isDelivered ? (
              <ConfirmDeliveryDialog batch={batch} />
            ) : (
              <Link
                href={`/poultry/batches/${batch.id}`}
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-[var(--gold)] px-6 py-3 text-sm font-extrabold uppercase tracking-[0.14em] text-[var(--navy)] shadow-sm transition hover:brightness-95"
              >
                <Eye className="h-4 w-4" aria-hidden="true" />
                Open Workspace
              </Link>
            )}
            <button
              type="button"
              onClick={onClose}
              className="inline-flex items-center justify-center rounded-xl border border-[var(--line)] bg-white px-6 py-3 text-sm font-extrabold uppercase tracking-[0.14em] text-[var(--navy-muted)] transition hover:bg-[var(--gold-soft)] hover:text-[var(--navy)]"
            >
              Close Detail
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

type DialogBackdropProps = {
  children: ReactNode;
  onClose: () => void;
};

function DialogBackdrop({ children, onClose }: DialogBackdropProps) {
  return (
    <div
      className="fixed inset-0 z-[110] grid place-items-center bg-[rgba(23,36,67,0.72)] px-4 py-6"
      role="presentation"
      onMouseDown={onClose}
    >
      {children}
    </div>
  );
}

type DialogHeaderProps = {
  title: string;
  eyebrow: string;
  labelId: string;
  onClose: () => void;
  disabled?: boolean;
};

function DialogHeader({
  title,
  eyebrow,
  labelId,
  onClose,
  disabled = false,
}: DialogHeaderProps) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-[var(--line)] px-6 py-5">
      <div>
        <p className="text-label text-[var(--navy-muted)]">{eyebrow}</p>
        <h2
          id={labelId}
          className="font-display mt-2 text-4xl leading-none text-[var(--navy)]"
        >
          {title}
        </h2>
      </div>

      <button
        type="button"
        onClick={onClose}
        disabled={disabled}
        aria-label="Close dialog"
        className="grid h-10 w-10 place-items-center rounded-full border border-[var(--line)] text-[var(--navy)] transition hover:bg-[var(--gold-soft)] disabled:cursor-not-allowed disabled:opacity-60"
      >
        <X className="h-5 w-5" aria-hidden="true" />
      </button>
    </div>
  );
}

function ErrorMessage({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800"
    >
      {message}
    </p>
  );
}

function BatchDetailField({
  label,
  value,
  pill = false,
}: {
  label: string;
  value: string;
  pill?: boolean;
}) {
  const displayValue = value || "-";

  return (
    <div>
      <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-[var(--navy-muted)]">
        {label}
      </p>
      {pill ? (
        <span className="mt-3 inline-flex rounded-full bg-[var(--gold-soft)] px-4 py-2 text-sm font-extrabold text-[var(--navy)]">
          {displayValue}
        </span>
      ) : (
        <p className="mt-3 whitespace-pre-wrap break-words text-base font-bold leading-7 text-[var(--navy-soft)]">
          {displayValue}
        </p>
      )}
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

type TableHeadProps = {
  label: string;
  align?: "left" | "right";
};

function TableHead({ label, align = "left" }: TableHeadProps) {
  const alignClass = align === "right" ? "text-right" : "text-left";

  return (
    <th
      className={`px-6 py-4 ${alignClass} text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]`}
    >
      {label}
    </th>
  );
}
