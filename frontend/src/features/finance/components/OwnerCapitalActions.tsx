"use client";

import { useMemo, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { Dialog } from "@/components/ui/Dialog";
import { clientApiFetch, ClientApiError } from "@/lib/client-api";
import type {
  OwnerContributionReceipt,
  OwnerContributionReport,
  OwnerContributor,
} from "@/features/finance/types";
import type { PoultryBatch } from "@/features/poultry/types";

type DesignationDraft = { batch: string; amount: string };

function today() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function errorMessage(error: unknown): string {
  if (error instanceof ClientApiError && error.details && typeof error.details === "object") {
    const details = error.details as Record<string, unknown>;
    const first = Object.values(details)[0];
    if (Array.isArray(first)) return String(first[0]);
    if (typeof first === "string") return first;
  }
  return error instanceof Error ? error.message : "The request could not be completed.";
}

export function OwnerCapitalActions({
  owners,
  batches,
  receipts,
  reportQuery,
}: {
  owners: OwnerContributor[];
  batches: PoultryBatch[];
  receipts: OwnerContributionReceipt[];
  reportQuery: string;
}) {
  const router = useRouter();
  const [dialog, setDialog] = useState<"owner" | "contribution" | "designation" | null>(null);
  const [selectedReceipt, setSelectedReceipt] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [ownerNotes, setOwnerNotes] = useState("");
  const [contribution, setContribution] = useState({
    owner: owners.find((owner) => owner.is_active)?.id.toString() ?? "",
    amount: "",
    receipt_date: today(),
    reference: "",
    notes: "",
  });
  const [designations, setDesignations] = useState<DesignationDraft[]>([
    { batch: "", amount: "" },
  ]);
  const [batchQuery, setBatchQuery] = useState("");
  const [designationDate, setDesignationDate] = useState(today());

  const receipt = useMemo(
    () => receipts.find((item) => item.id === selectedReceipt) ?? null,
    [receipts, selectedReceipt]
  );
  const designatedTotal = designations.reduce(
    (sum, item) => sum + (Number(item.amount) || 0),
    0
  );
  const normalizedBatchQuery = batchQuery.trim().toLowerCase();
  const designationBatchMatches = batches.filter(
    (batch) =>
      designations.some((item) => item.batch === String(batch.id)) ||
      !normalizedBatchQuery ||
      [batch.batch_id, batch.bird_type, batch.status]
        .join(" ")
        .toLowerCase()
        .includes(normalizedBatchQuery)
  );
  const selectedDesignationBatchIds = new Set(
    designations.map((item) => item.batch).filter(Boolean)
  );
  const designationBatches = [
    ...designationBatchMatches.filter((batch) =>
      selectedDesignationBatchIds.has(String(batch.id))
    ),
    ...designationBatchMatches.filter((batch) =>
      !selectedDesignationBatchIds.has(String(batch.id))
    ),
  ].slice(0, Math.max(100, selectedDesignationBatchIds.size));

  function close() {
    if (busy) return;
    setDialog(null);
    setError("");
  }

  async function createOwner(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await clientApiFetch("/api/finance/owners", {
        method: "POST",
        body: JSON.stringify({ display_name: ownerName, notes: ownerNotes, is_active: true }),
      });
      setOwnerName("");
      setOwnerNotes("");
      setDialog(null);
      router.refresh();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function recordContribution(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await clientApiFetch("/api/finance/owner-contributions", {
        method: "POST",
        body: JSON.stringify({
          ...contribution,
          idempotency_key: crypto.randomUUID(),
          designation_date: contribution.receipt_date,
          designations: designations
            .filter((item) => item.batch && Number(item.amount) > 0)
            .map((item) => ({ batch: Number(item.batch), amount: item.amount })),
        }),
      });
      setContribution({
        owner: contribution.owner,
        amount: "",
        receipt_date: today(),
        reference: "",
        notes: "",
      });
      setDesignations([{ batch: "", amount: "" }]);
      setDialog(null);
      router.refresh();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function addDesignations(event: FormEvent) {
    event.preventDefault();
    if (!receipt) return;
    setBusy(true);
    setError("");
    try {
      await clientApiFetch(`/api/finance/owner-designations/for-receipt/${receipt.id}`, {
        method: "POST",
        body: JSON.stringify({
          designation_date: designationDate,
          designations: designations
            .filter((item) => item.batch && Number(item.amount) > 0)
            .map((item) => ({ batch: Number(item.batch), amount: item.amount })),
        }),
      });
      setDesignations([{ batch: "", amount: "" }]);
      setDialog(null);
      router.refresh();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function reverse(path: string, promptText: string) {
    const reason = window.prompt(promptText);
    if (!reason?.trim()) return;
    setBusy(true);
    setError("");
    try {
      await clientApiFetch(path, {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim() }),
      });
      setDialog(null);
      router.refresh();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function exportCsv() {
    setBusy(true);
    setError("");
    try {
      const separator = reportQuery ? "&" : "?";
      const report = await clientApiFetch<OwnerContributionReport>(
        `/api/finance/reports/owner-contributions${reportQuery}${separator}export=1`
      );
      const safe = (value: unknown) => {
        let text = value === null || value === undefined ? "" : String(value);
        if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
        return `"${text.replace(/"/g, '""')}"`;
      };
      const header = [
        "section", "date", "owner", "batch", "reference", "event", "inflow",
        "outflow", "designated", "actual_spent", "running_cash",
        "running_net_capital", "status",
      ];
      const rows: unknown[][] = [];
      report.receipts.forEach((item) => rows.push([
        "receipt", item.receipt_date, item.owner_name, "", item.reference,
        "owner contribution", item.amount, "", item.designated_as_of, "", "", "",
        item.current_status,
      ]));
      report.batches.forEach((item) => rows.push([
        "batch", report.date_to, "", item.batch_code, "", "batch attribution", "", "",
        item.designated_as_of, item.owner_cash_spent_to_date, "", "", "",
      ]));
      report.timeline.forEach((item) => rows.push([
        "movement", item.date, item.owner_name, "", item.reference, item.event_type,
        item.inflow, item.outflow, "", "", item.running_cash_balance,
        item.running_net_contributed_capital, "",
      ]));
      const csv = [header, ...rows].map((row) => row.map(safe).join(",")).join("\r\n");
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `owner-capital-${report.date_to}.csv`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  const designationFields = (
    <div className="grid gap-3">
      <label className="text-sm font-bold text-[var(--navy)]">
        Find a batch
        <input
          className="form-input mt-2 w-full"
          type="search"
          value={batchQuery}
          onChange={(event) => setBatchQuery(event.target.value)}
          placeholder="Search batch ID, bird type, or status"
        />
        {designationBatchMatches.length > designationBatches.length ? (
          <span className="mt-1 block text-xs font-normal text-[var(--navy-muted)]">
            Showing the first 100 matches. Refine the search to find another batch.
          </span>
        ) : null}
      </label>
      {designations.map((item, index) => (
        <div className="grid gap-3 sm:grid-cols-[1fr_11rem_auto]" key={index}>
          <label className="text-sm font-bold text-[var(--navy)]">
            Batch
            <select
              className="form-input mt-2 w-full"
              value={item.batch}
              onChange={(event) =>
                setDesignations((rows) =>
                  rows.map((row, rowIndex) =>
                    rowIndex === index ? { ...row, batch: event.target.value } : row
                  )
                )
              }
            >
              <option value="">Unassigned for now</option>
              {designationBatches.map((batch) => (
                <option value={batch.id} key={batch.id}>{batch.batch_id}</option>
              ))}
            </select>
          </label>
          <label className="text-sm font-bold text-[var(--navy)]">
            Amount
            <input
              className="form-input mt-2 w-full"
              type="number"
              min="0.01"
              step="0.01"
              value={item.amount}
              onChange={(event) =>
                setDesignations((rows) =>
                  rows.map((row, rowIndex) =>
                    rowIndex === index ? { ...row, amount: event.target.value } : row
                  )
                )
              }
            />
          </label>
          <button
            type="button"
            className="self-end rounded-lg border px-3 py-3 font-bold text-[var(--danger)]"
            onClick={() => setDesignations((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}
            disabled={designations.length === 1}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        type="button"
        className="w-fit font-bold underline"
        onClick={() => setDesignations((rows) => [...rows, { batch: "", amount: "" }])}
      >
        + Split across another batch
      </button>
    </div>
  );

  return (
    <>
      <div className="grid gap-3 sm:flex sm:flex-wrap">
        <button className="finance-button w-full sm:w-auto" type="button" onClick={() => setDialog("contribution")}>
          Record owner contribution
        </button>
        <button className="min-h-11 w-full rounded-lg border border-[var(--navy)] px-4 py-3 font-bold text-[var(--navy)] sm:w-auto" type="button" onClick={() => setDialog("owner")}>
          Add owner or contributor
        </button>
        <button className="min-h-11 w-full rounded-lg border border-[var(--navy)] px-4 py-3 font-bold text-[var(--navy)] sm:w-auto" type="button" disabled={busy} onClick={exportCsv}>
          Export filtered CSV
        </button>
      </div>

      <Dialog open={dialog === "owner"} onClose={close} title="Add owner or contributor" eyebrow="Owner capital" size="md">
        <form className="grid gap-4" onSubmit={createOwner}>
          <label className="text-sm font-bold">Display name<input required className="form-input mt-2 w-full" value={ownerName} onChange={(event) => setOwnerName(event.target.value)} /></label>
          <label className="text-sm font-bold">Notes<textarea className="form-input mt-2 min-h-24 w-full" value={ownerNotes} onChange={(event) => setOwnerNotes(event.target.value)} /></label>
          {error ? <p role="alert" className="text-sm font-bold text-[var(--danger)]">{error}</p> : null}
          <button disabled={busy} className="finance-button w-full sm:w-auto sm:justify-self-end">{busy ? "Saving…" : "Save contributor"}</button>
        </form>
      </Dialog>

      <Dialog open={dialog === "contribution"} onClose={close} title="Record owner contribution" eyebrow="Cash introduced" size="lg">
        <form className="grid gap-5" onSubmit={recordContribution}>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="text-sm font-bold">Owner or contributor<select required className="form-input mt-2 w-full" value={contribution.owner} onChange={(event) => setContribution({ ...contribution, owner: event.target.value })}><option value="">Choose owner</option>{owners.filter((owner) => owner.is_active).map((owner) => <option key={owner.id} value={owner.id}>{owner.display_name}</option>)}</select></label>
            <label className="text-sm font-bold">Amount received<input required type="number" min="0.01" step="0.01" className="form-input mt-2 w-full" value={contribution.amount} onChange={(event) => setContribution({ ...contribution, amount: event.target.value })} /></label>
            <label className="text-sm font-bold">Receipt date<input required type="date" className="form-input mt-2 w-full" value={contribution.receipt_date} onChange={(event) => setContribution({ ...contribution, receipt_date: event.target.value })} /></label>
            <label className="text-sm font-bold">Reference<input className="form-input mt-2 w-full" value={contribution.reference} onChange={(event) => setContribution({ ...contribution, reference: event.target.value })} /></label>
          </div>
          <label className="text-sm font-bold">Notes<textarea className="form-input mt-2 min-h-20 w-full" value={contribution.notes} onChange={(event) => setContribution({ ...contribution, notes: event.target.value })} /></label>
          <div><h3 className="font-extrabold">Optional batch designation</h3><p className="mb-3 text-sm text-[var(--navy-muted)]">A designation explains intended use. It does not create spending or duplicate cash.</p>{designationFields}<p className="mt-3 text-sm font-bold">Designated now: MWK {designatedTotal.toLocaleString()}</p></div>
          {Number(contribution.amount) > 0 && designatedTotal > Number(contribution.amount) ? <p role="alert" className="text-sm font-bold text-[var(--danger)]">Designations cannot exceed the receipt.</p> : null}
          {error ? <p role="alert" className="text-sm font-bold text-[var(--danger)]">{error}</p> : null}
          <button disabled={busy || designatedTotal > Number(contribution.amount)} className="finance-button w-full sm:w-auto sm:justify-self-end">{busy ? "Recording…" : "Record contribution"}</button>
        </form>
      </Dialog>

      <Dialog open={dialog === "designation"} onClose={close} title={`Manage receipt ${receipt?.reference || receipt?.id || ""}`} eyebrow="Batch designation" size="lg">
        {receipt ? (
          <div className="grid gap-6">
            <form className="grid gap-4" onSubmit={addDesignations}>
              <p className="text-sm text-[var(--navy-muted)]">Unassigned amount: <strong>MWK {Number(receipt.unassigned_as_of).toLocaleString()}</strong></p>
              <label className="text-sm font-bold">Designation date<input required type="date" className="form-input mt-2 w-full" value={designationDate} onChange={(event) => setDesignationDate(event.target.value)} /></label>
              {designationFields}
              <button disabled={busy || designatedTotal > Number(receipt.unassigned_as_of)} className="finance-button w-full sm:w-auto sm:justify-self-end">Add designations</button>
            </form>
            {receipt.designations.length ? <div><h3 className="font-extrabold">Designation history</h3><div className="mt-3 grid gap-2">{receipt.designations.map((item) => <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3" key={item.id}><span>{item.batch_code} · MWK {Number(item.amount).toLocaleString()} · {item.current_status}</span>{item.current_status === "posted" ? <button disabled={busy} className="font-bold text-[var(--danger)] underline" onClick={() => reverse(`/api/finance/owner-designations/${item.id}/reverse`, "Why is this designation being reversed?")}>Reverse designation</button> : null}</div>)}</div></div> : null}
            {error ? <p role="alert" className="text-sm font-bold text-[var(--danger)]">{error}</p> : null}
            {receipt.current_status === "posted" ? <button disabled={busy} type="button" className="w-fit font-bold text-[var(--danger)] underline" onClick={() => reverse(`/api/finance/funding-receipts/${receipt.id}/reverse`, "Why is this owner contribution being reversed?")}>Reverse unused contribution</button> : null}
          </div>
        ) : null}
      </Dialog>

      <div className="sr-only" aria-live="polite">{busy ? "Saving finance record" : ""}</div>

      <div className="hidden">
        {receipts.map((item) => (
          <button key={item.id} data-owner-receipt-action={item.id} onClick={() => { setSelectedReceipt(item.id); setDesignations([{ batch: "", amount: "" }]); setDialog("designation"); }} />
        ))}
      </div>
    </>
  );
}

export function OwnerReceiptAction({ receiptId }: { receiptId: number }) {
  return (
    <button
      type="button"
      className="inline-flex min-h-11 items-center justify-center rounded-lg border border-[var(--navy)] bg-white px-4 py-2 font-bold text-[var(--navy)] transition hover:bg-[var(--gold-soft)]"
      onClick={() => {
        const trigger = document.querySelector<HTMLButtonElement>(`[data-owner-receipt-action="${receiptId}"]`);
        trigger?.click();
      }}
    >
      Manage
    </button>
  );
}
