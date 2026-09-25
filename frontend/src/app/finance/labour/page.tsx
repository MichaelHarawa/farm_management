import {
  getAccountingPeriods,
  getAdHocLabour,
} from "@/features/finance/api/finance";
import { LabourPaymentDialog } from "@/features/finance/components/FinanceForms";
import { getPoultryBatches } from "@/features/poultry/api/batches";
import {
  EmptyState,
  FinanceNav,
  FinancePageShell,
  Panel,
} from "@/features/finance/components/FinanceUI";
import { formatCurrency, formatDate, formatLabel } from "@/features/finance/utils/formatters";
import { LabourWorkflowActions } from "@/features/finance/components/LabourWorkflowActions";
import { MobileRecordList } from "@/components/ui/MobileRecordList";
import { PaginatedTableBody } from "@/components/ui/PaginatedTableBody";

export default async function FinanceLabourPage() {
  const [periods, labour, batches] = await Promise.all([
    getAccountingPeriods("/finance/labour"),
    getAdHocLabour("/finance/labour"),
    getPoultryBatches("/finance/labour"),
  ]);
  const batchLabels = new Map(batches.map((batch) => [batch.id, batch.batch_id]));
  const selectableBatches = batches.filter(
    (batch) =>
      !["booked", "delivered"].includes(batch.status) &&
      !(batch.status === "closed" && batch.profitability_finalized_at)
  );

  return (
    <FinancePageShell
      eyebrow="Finance / Labour"
      title="Ad-hoc labour."
      detail="Record temporary and task-based labour by cost scope for direct or shared allocation."
      actions={<FinanceNav />}
    >
      <Panel title="Labour Actions">
        {periods.length ? (
          <LabourPaymentDialog periods={periods} batches={selectableBatches} />
        ) : (
          <EmptyState message="Create an accounting period before recording labour." />
        )}
      </Panel>

      <Panel id="labour-ledger" title="Labour Ledger">
        {labour.length ? (
          <>
          <MobileRecordList
            pageSize={10}
            records={labour.map((item) => ({
              key: item.id,
              title: item.worker_name,
              subtitle: item.task_description,
              badge: <span className="rounded-full bg-[var(--gold-soft)] px-2 py-1 text-xs font-bold">{formatLabel(item.workflow_status)}</span>,
              fields: [
                { label: "Work date", value: formatDate(item.work_date) },
                { label: "Amount", value: formatCurrency(item.payment_amount) },
                { label: "Cost scope", value: formatLabel(item.cost_scope) },
                { label: "Batch", value: item.batch ? batchLabels.get(item.batch) ?? `Batch ${item.batch}` : "Shared" },
              ],
              actions: <LabourWorkflowActions labour={item} />,
            }))}
            emptyMessage="No ad-hoc labour payments are recorded."
          />
          <div className="hidden overflow-x-auto md:block">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-[var(--line)] text-left text-[var(--navy-muted)]">
                  <th className="py-3 pr-4">Worker</th>
                  <th className="py-3 pr-4">Task</th>
                  <th className="py-3 pr-4">Date</th>
                  <th className="py-3 pr-4">Scope</th>
                  <th className="py-3 pr-4">Batch</th>
                  <th className="py-3 pr-4">Amount / status</th>
                  <th className="py-3 pr-4">Workflow</th>
                </tr>
              </thead>
              <PaginatedTableBody columnCount={7} itemLabel="labour records">
                {labour.map((item) => (
                  <tr key={item.id} className="border-b border-[var(--line)]">
                    <td className="py-4 pr-4 font-bold">{item.worker_name}</td>
                    <td className="py-4 pr-4">{item.task_description}</td>
                    <td className="py-4 pr-4">{formatDate(item.work_date)}</td>
                    <td className="py-4 pr-4">{formatLabel(item.cost_scope)}</td>
                    <td className="py-4 pr-4">
                      {item.batch ? batchLabels.get(item.batch) ?? `Batch ${item.batch}` : "Shared"}
                    </td>
                    <td className="py-4 pr-4">{formatCurrency(item.payment_amount)}<div className="text-xs">{formatLabel(item.workflow_status)}</div></td>
                    <td className="py-4 pr-4"><LabourWorkflowActions labour={item} /></td>
                  </tr>
                ))}
              </PaginatedTableBody>
            </table>
          </div>
          </>
        ) : (
          <EmptyState message="No ad-hoc labour payments are recorded." />
        )}
      </Panel>
    </FinancePageShell>
  );
}
