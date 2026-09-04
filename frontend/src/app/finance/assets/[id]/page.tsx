import Link from "next/link";
import { getAsset, getAssetDepreciationSchedule, getAssetHistory } from "@/features/finance/api/finance";
import { AssetLifecycleActions } from "@/features/finance/components/AssetLifecycleActions";
import { FinancePageShell, Panel } from "@/features/finance/components/FinanceUI";
import { formatCurrency, formatDate, formatLabel } from "@/features/finance/utils/formatters";

export default async function AssetDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const returnTo = `/finance/assets/${id}`;
  const [asset, history, depreciation] = await Promise.all([getAsset(id, returnTo), getAssetHistory(id, returnTo), getAssetDepreciationSchedule(id, returnTo)]);
  return <FinancePageShell eyebrow="Finance / Asset lifecycle" title={asset.name} detail={`${asset.asset_code} · ${formatLabel(asset.status)}`} actions={<Link href="/finance/assets" className="font-bold underline">← Asset register</Link>}>
    <div className="grid gap-4 md:grid-cols-4"><Info label="Capitalized cost" value={formatCurrency(asset.total_capitalized_cost)} /><Info label="Impairment" value={formatCurrency(asset.recognized_impairment_amount)} /><Info label="Location" value={asset.location || "Unassigned"} /><Info label="Custodian" value={asset.custodian || "Unassigned"} /></div>
    <Panel title="Controlled lifecycle actions"><AssetLifecycleActions assetId={asset.id} disposed={asset.status === "disposed"} /></Panel>
    <div className="grid gap-6 lg:grid-cols-2"><Panel title="Event history">{history.length ? <ul className="grid gap-3">{history.map(event => <li key={event.id} className="rounded border p-3"><b>{formatLabel(event.event_type)}</b><span className="ml-2 text-sm">{formatDate(event.event_date)}</span><p className="mt-1 text-sm text-[var(--navy-muted)]">{event.reason || "System-generated event"}</p></li>)}</ul> : <p>No lifecycle events yet.</p>}</Panel><Panel title="Depreciation history">{depreciation.length ? <ul className="grid gap-3">{depreciation.map(row => <li key={row.id} className="flex justify-between rounded border p-3"><span>Period #{row.accounting_period}</span><b>{formatCurrency(row.period_depreciation)}</b></li>)}</ul> : <p>No depreciation posted.</p>}</Panel></div>
  </FinancePageShell>;
}

function Info({ label, value }: { label: string; value: string }) { return <div className="rounded border border-[var(--line)] bg-white p-4"><p className="text-label text-[var(--navy-muted)]">{label}</p><p className="mt-2 font-bold text-[var(--navy)]">{value}</p></div>; }
