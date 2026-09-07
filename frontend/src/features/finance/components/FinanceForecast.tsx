"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { clientApiFetch } from "@/lib/client-api";
import { getApiErrorMessage } from "@/lib/errors";
import type { BatchProfitabilityReport, FinanceDashboard } from "../types";
import { formatCurrency, formatNumber, formatPercent, parseDecimal } from "../utils/formatters";

type Props = { forecast: FinanceDashboard["forecast"] };

const INPUT_LABELS: Record<string, string> = {
  selling_price: "selling price",
  mortality_assumption: "mortality assumption",
  remaining_feed_cost: "remaining feed cost",
  remaining_other_cost: "remaining other/shared costs",
};

export function FinanceForecast({ forecast }: Props) {
  const total = forecast.expected_final_profit === null ? null : parseDecimal(forecast.expected_final_profit);
  return (
    <section className="rounded-xl border border-[var(--line)] bg-[var(--surface-cream)] p-5 shadow-[var(--shadow-card)]">
      <div className="grid gap-4 md:grid-cols-[1fr_auto] md:items-start">
        <div>
          <p className="text-label text-[var(--navy-muted)]">Completion estimate</p>
          <h2 className="mt-2 text-2xl font-extrabold">Expected profit when batches finish</h2>
          <p className="mt-3 max-w-4xl text-sm leading-6 text-[var(--navy-muted)]">{forecast.basis}</p>
        </div>
        <div className="rounded-lg bg-white/70 p-4 md:text-right">
          <p className="text-xs font-bold uppercase tracking-wide text-[var(--navy-muted)]">Forecast coverage</p>
          <p className="mt-2 font-extrabold">{forecast.available_batch_count} of {forecast.selected_batch_count} active batches</p>
          <p className="mt-1 text-xs text-[var(--navy-muted)]">Estimated {forecast.estimated_at}</p>
        </div>
      </div>

      <div className="mt-5 rounded-xl border border-[var(--line)] bg-white/70 p-5">
        {total === null ? (
          <>
            <p className="text-xl font-extrabold">Forecast unavailable — add selling price and remaining cost estimates</p>
            <p className="mt-2 text-sm text-[var(--navy-muted)]">No active batch has a complete set of assumptions. Missing batches are never included as zero.</p>
          </>
        ) : (
          <>
            <p className={"font-display whitespace-nowrap text-3xl font-bold " + (total < 0 ? "text-[var(--danger)]" : "text-[#315f3e]")}>
              {total < 0 ? "Expected loss: " : "Expected profit: "}{formatCurrency(Math.abs(total))}
            </p>
            <p className="mt-2 text-sm text-[var(--navy-muted)]">
              Complete batches only. {forecast.unavailable_batch_count} incomplete batch{forecast.unavailable_batch_count === 1 ? "" : "es"} excluded from this total.
            </p>
          </>
        )}
      </div>

      <div className="mt-5 grid gap-3">
        {forecast.rows.map((row) => <ForecastRow key={row.batch} row={row} />)}
        {!forecast.rows.length ? <p className="rounded-lg border border-dashed border-[var(--line)] p-5 text-sm text-[var(--navy-muted)]">There are no active production batches to forecast.</p> : null}
      </div>
    </section>
  );
}

function ForecastRow({ row }: { row: BatchProfitabilityReport }) {
  const [editing, setEditing] = useState(false);
  const result = row.forecast_final_profit === null ? null : parseDecimal(row.forecast_final_profit);
  return (
    <article className="rounded-xl border border-[var(--line)] bg-white/70 p-4">
      <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-start">
        <div>
          <p className="font-extrabold">{row.batch_id}</p>
          <p className="mt-1 text-sm text-[var(--navy-muted)]">{formatNumber(row.remaining_live_birds)} birds currently remaining · {formatCurrency(row.revenue)} sales recorded</p>
        </div>
        {result === null ? (
          <span className="rounded-full bg-[var(--gold-soft)] px-3 py-1 text-xs font-bold">Forecast unavailable</span>
        ) : (
          <p className={"whitespace-nowrap font-extrabold " + (result < 0 ? "text-[var(--danger)]" : "text-[#315f3e]")}>
            {result < 0 ? "Expected loss " : "Expected profit "}{formatCurrency(Math.abs(result))}
          </p>
        )}
      </div>

      {row.forecast_available ? (
        <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <SmallMetric label="Actual sales" value={formatCurrency(row.forecast_actual_revenue)} />
          <SmallMetric label="Estimated future sales" value={formatCurrency(row.forecast_estimated_future_revenue)} />
          <SmallMetric label="Costs incurred" value={formatCurrency(row.forecast_costs_incurred)} />
          <SmallMetric label="Estimated remaining costs" value={formatCurrency(row.forecast_estimated_remaining_cost)} />
        </div>
      ) : (
        <p className="mt-3 text-sm text-[var(--navy-muted)]">
          Missing: {row.forecast_missing_inputs.map((item) => INPUT_LABELS[item] || item).join(", ")}.
        </p>
      )}

      <details className="mt-4">
        <summary className="cursor-pointer text-sm font-bold underline">Assumptions and calculation details</summary>
        <div className="mt-3 rounded-lg bg-[var(--surface-cream-soft)] p-4 text-sm">
          <p>{row.forecast_basis}</p>
          {row.forecast_available ? <p className="mt-2">Expected bird sales: {formatNumber(row.forecast_expected_birds_sold)} at {formatCurrency(row.forecast_assumptions.selling_price)} each after {formatPercent(row.forecast_assumptions.remaining_bird_mortality_percent)} expected mortality among currently live birds.</p> : null}
        </div>
      </details>

      <button type="button" onClick={() => setEditing((value) => !value)} className="mt-4 rounded-lg border border-[var(--line)] px-4 py-2 text-sm font-bold">
        {editing ? "Close assumptions" : "Edit forecast assumptions"}
      </button>
      {editing ? <AssumptionForm row={row} /> : null}
    </article>
  );
}

function AssumptionForm({ row }: { row: BatchProfitabilityReport }) {
  const router = useRouter();
  const assumptions = row.forecast_assumptions || {
    selling_price: null,
    remaining_bird_mortality_percent: null,
    remaining_feed_cost: null,
    remaining_other_and_shared_cost: null,
  };
  const [values, setValues] = useState({
    target_selling_price: assumptions.selling_price || "",
    forecast_mortality_rate_percent: assumptions.remaining_bird_mortality_percent || "",
    estimated_remaining_feed_cost: assumptions.remaining_feed_cost || "",
    estimated_remaining_other_cost: assumptions.remaining_other_and_shared_cost || "",
  });
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setStatus("");
    try {
      const payload = Object.fromEntries(
        Object.entries(values).map(([key, value]) => [key, value === "" ? null : value])
      );
      await clientApiFetch("/api/poultry/batches/" + row.batch + "/forecast-assumptions", {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setStatus("Saved. Refreshing forecast…");
      router.refresh();
    } catch (error) {
      setStatus(getApiErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return <form onSubmit={save} className="mt-4 grid gap-3 rounded-lg border border-[var(--line)] p-4 sm:grid-cols-2">
    <NumberInput label="Expected selling price per bird (MWK)" value={values.target_selling_price} onChange={(value) => setValues({ ...values, target_selling_price: value })} />
    <NumberInput label="Expected mortality among remaining birds (%)" value={values.forecast_mortality_rate_percent} onChange={(value) => setValues({ ...values, forecast_mortality_rate_percent: value })} max="100" />
    <NumberInput label="Remaining feed cost (MWK)" value={values.estimated_remaining_feed_cost} onChange={(value) => setValues({ ...values, estimated_remaining_feed_cost: value })} />
    <NumberInput label="Remaining other/shared costs (MWK)" value={values.estimated_remaining_other_cost} onChange={(value) => setValues({ ...values, estimated_remaining_other_cost: value })} />
    <div className="sm:col-span-2 flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-[var(--navy-muted)]" role="status">{status}</p>
      <button disabled={busy} className="finance-button px-5 py-2">{busy ? "Saving…" : "Save assumptions"}</button>
    </div>
  </form>;
}

function NumberInput({ label, value, onChange, max }: { label: string; value: string | number; onChange: (value: string) => void; max?: string }) {
  return <label className="text-sm font-bold">{label}<input className="form-input mt-2 w-full bg-white" type="number" min="0" max={max} step="0.01" value={value} onChange={(event) => onChange(event.target.value)} /></label>;
}

function SmallMetric({ label, value }: { label: string; value: string }) {
  return <div><p className="text-xs font-bold uppercase tracking-wide text-[var(--navy-muted)]">{label}</p><p className="mt-1 whitespace-nowrap font-extrabold">{value}</p></div>;
}

