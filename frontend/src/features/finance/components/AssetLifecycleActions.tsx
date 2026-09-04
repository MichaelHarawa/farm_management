"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { clientApiFetch } from "@/lib/client-api";

export function AssetLifecycleActions({ assetId, disposed }: { assetId: string; disposed: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  async function post(action: string, payload: Record<string, string>) {
    setBusy(true);
    try {
      await clientApiFetch(`/api/finance/assets/${assetId}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      router.refresh();
    } finally { setBusy(false); }
  }
  if (disposed) return <p className="text-sm font-bold text-[var(--navy-muted)]">Disposed assets are read-only.</p>;
  return <div className="flex flex-wrap gap-3">
    <button disabled={busy} className="rounded border px-4 py-2 font-bold" onClick={() => { const location=prompt("New location")?.trim(); const custodian=prompt("New custodian")?.trim() || ""; const reason=prompt("Transfer reason")?.trim(); if(location && reason) void post("transfer", { event_date: new Date().toISOString().slice(0,10), location, custodian, reason }); }}>Transfer / custodian</button>
    <button disabled={busy} className="rounded border px-4 py-2 font-bold" onClick={() => { const amount=prompt("Impairment amount")?.trim(); const reason=prompt("Impairment reason")?.trim(); if(amount && reason) void post("impair", { amount, event_date: new Date().toISOString().slice(0,10), reason }); }}>Record impairment</button>
    <button disabled={busy} className="rounded border border-red-300 px-4 py-2 font-bold text-red-700" onClick={() => { const proceeds=prompt("Disposal proceeds")?.trim() || "0"; const reason=prompt("Disposal reason")?.trim(); if(reason) void post("dispose", { proceeds, disposal_date: new Date().toISOString().slice(0,10), reason }); }}>Dispose</button>
  </div>;
}
