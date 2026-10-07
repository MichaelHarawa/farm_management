"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { clientApiFetch } from "@/lib/client-api";
import type { AdHocLabourPayment } from "../types";

export function LabourWorkflowActions({ labour }: { labour: AdHocLabourPayment }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(action: "approve" | "post" | "reverse") {
    const reason = action === "reverse" ? window.prompt("Reason for reversal")?.trim() : "";
    if (action === "reverse" && !reason) return;
    setBusy(true);
    setError("");
    try {
      await clientApiFetch(`/api/finance/ad-hoc-labour/${labour.id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      });
      router.refresh();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="flex flex-wrap items-center gap-2">
    {labour.workflow_status === "draft" ? <button disabled={busy} onClick={() => void run("approve")} className="rounded border px-3 py-2 font-bold">Approve</button> : null}
    {labour.workflow_status === "approved" ? <button disabled={busy} onClick={() => void run("post")} className="finance-button px-3 py-2">Post payable</button> : null}
    {labour.expenditure && ["posted", "partially_paid"].includes(labour.workflow_status) ? <Link href={`/finance/expenditures/${labour.expenditure}`} className="font-bold underline">Pay payable</Link> : null}
    {labour.expenditure && ["posted", "partially_paid", "paid"].includes(labour.workflow_status) ? <button disabled={busy} onClick={() => void run("reverse")} className="text-sm font-bold text-red-700 underline">Reverse</button> : null}
    {error ? <span role="alert" className="text-xs text-red-700">{error}</span> : null}
  </div>;
}
