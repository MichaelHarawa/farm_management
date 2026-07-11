"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useForm, useWatch, type SubmitHandler } from "react-hook-form";

import { getApiErrorMessage } from "@/lib/errors";
import { createBatchSale } from "../api/sales";
import type { CreateSalePayload } from "../types";
import { formatCurrency } from "../utils/formatters";
import { saleSchema, type SaleFormValues } from "../validation/sale";

const productOptions = [
  { value: "live_chicken", label: "Live Chicken" },
  { value: "dressed_chicken", label: "Dressed Chicken" },
  { value: "eggs", label: "Eggs" },
  { value: "manure", label: "Manure" },
] as const;

const buyerTypeOptions = [
  { value: "market_vendor", label: "Market Vendor" },
  { value: "retail", label: "Retail" },
  { value: "retail_supply", label: "Retail Supply" },
  { value: "bulk_order", label: "Bulk Order" },
] as const;

const paymentStatusOptions = [
  { value: "paid", label: "Paid" },
  { value: "partial", label: "Partial" },
  { value: "loan", label: "Loan" },
  { value: "unpaid", label: "Unpaid" },
  { value: "cancelled", label: "Cancelled" },
] as const;

const paymentMethodOptions = [
  { value: "cash", label: "Cash" },
  { value: "mobile_money", label: "Mobile Money" },
  { value: "bank_transfer", label: "Bank Transfer" },
  { value: "credit", label: "Credit" },
] as const;

type AddSaleFormProps = {
  batchId: number;
};

function getDefaultSaleDate(): string {
  const date = new Date();
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());

  return date.toISOString().slice(0, 16);
}

export function AddSaleForm({ batchId }: AddSaleFormProps) {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    control,
    formState: { errors, isSubmitting },
  } = useForm<SaleFormValues>({
    resolver: zodResolver(saleSchema),
    defaultValues: {
      sale_date: getDefaultSaleDate(),
      product_type: "live_chicken",
      quantity_sold: 1,
      unit_price: 0,
      buyer_name: "",
      buyer_type: "market_vendor",
      payment_status: "partial",
      payment_method: "cash",
      amount_paid: 0,
      sold_by_name: "",
      notes: "Recorded through Farmnotes.",
    },
    mode: "onBlur",
  });

  const quantitySold =
    useWatch({
      control,
      name: "quantity_sold",
    }) ?? 0;
  const unitPrice =
    useWatch({
      control,
      name: "unit_price",
    }) ?? 0;
  const amountPaid =
    useWatch({
      control,
      name: "amount_paid",
    }) ?? 0;

  const saleTotal = quantitySold * unitPrice;
  const balance = Math.max(saleTotal - amountPaid, 0);

  const onSubmit: SubmitHandler<SaleFormValues> = async (values) => {
    setServerError(null);
    setSuccessMessage(null);

    const payload: CreateSalePayload = {
      ...values,
      balance: Math.max(values.quantity_sold * values.unit_price - values.amount_paid, 0),
    };

    try {
      await createBatchSale(batchId, payload);

      reset({
        sale_date: getDefaultSaleDate(),
        product_type: "live_chicken",
        quantity_sold: 1,
        unit_price: 0,
        buyer_name: "",
        buyer_type: "market_vendor",
        payment_status: "partial",
        payment_method: "cash",
        amount_paid: 0,
        sold_by_name: "",
        notes: "Recorded through Farmnotes.",
      });

      setSuccessMessage("The sale was recorded successfully.");
      router.refresh();
    } catch (error) {
      setServerError(getApiErrorMessage(error));
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="grid gap-6">
      <div>
        <p className="text-label text-[var(--navy-muted)]">New Sale</p>

        <h3 className="font-display mt-2 text-3xl text-[var(--navy)]">
          Record revenue for this batch.
        </h3>
      </div>

      <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
        <FormField label="Sale date" error={errors.sale_date?.message}>
          <input
            id="sale-date"
            type="datetime-local"
            {...register("sale_date")}
            className="form-input"
          />
        </FormField>

        <FormField label="Product" error={errors.product_type?.message}>
          <select
            id="sale-product-type"
            {...register("product_type")}
            className="form-input"
          >
            {productOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FormField>

        <FormField label="Quantity sold" error={errors.quantity_sold?.message}>
          <input
            id="sale-quantity-sold"
            type="number"
            min="1"
            step="1"
            {...register("quantity_sold", {
              valueAsNumber: true,
            })}
            className="form-input"
          />
        </FormField>

        <FormField label="Unit price" error={errors.unit_price?.message}>
          <input
            id="sale-unit-price"
            type="number"
            min="1"
            step="1"
            {...register("unit_price", {
              valueAsNumber: true,
            })}
            className="form-input"
          />
        </FormField>

        <FormField label="Buyer name" error={errors.buyer_name?.message}>
          <input
            id="sale-buyer-name"
            type="text"
            placeholder="Example: Banda"
            {...register("buyer_name")}
            className="form-input"
          />
        </FormField>

        <FormField label="Buyer type" error={errors.buyer_type?.message}>
          <select
            id="sale-buyer-type"
            {...register("buyer_type")}
            className="form-input"
          >
            {buyerTypeOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FormField>

        <FormField
          label="Payment status"
          error={errors.payment_status?.message}
        >
          <select
            id="sale-payment-status"
            {...register("payment_status")}
            className="form-input"
          >
            {paymentStatusOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FormField>

        <FormField
          label="Payment method"
          error={errors.payment_method?.message}
        >
          <select
            id="sale-payment-method"
            {...register("payment_method")}
            className="form-input"
          >
            {paymentMethodOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </FormField>

        <FormField label="Amount paid" error={errors.amount_paid?.message}>
          <input
            id="sale-amount-paid"
            type="number"
            min="0"
            step="1"
            {...register("amount_paid", {
              valueAsNumber: true,
            })}
            className="form-input"
          />
        </FormField>

        <FormField label="Sold by" error={errors.sold_by_name?.message}>
          <input
            id="sale-sold-by"
            type="text"
            placeholder="Seller name"
            {...register("sold_by_name")}
            className="form-input"
          />
        </FormField>

        <div className="md:col-span-2">
          <FormField label="Notes" error={errors.notes?.message}>
            <textarea
              id="sale-notes"
              rows={3}
              {...register("notes")}
              className="form-input resize-y"
            />
          </FormField>
        </div>
      </div>

      <div className="grid gap-4 border-t border-[var(--line)] pt-5 sm:grid-cols-[1fr_auto] sm:items-center">
        <div className="grid gap-3 sm:grid-cols-2">
          <SummaryFigure label="Sale Total" value={formatCurrency(saleTotal)} />
          <SummaryFigure label="Balance Due" value={formatCurrency(balance)} />
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-full bg-[var(--gold)] px-6 py-3 text-[0.7rem] font-bold uppercase tracking-[0.18em] text-[var(--navy)] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmitting ? "Saving..." : "Record Sale"}
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
