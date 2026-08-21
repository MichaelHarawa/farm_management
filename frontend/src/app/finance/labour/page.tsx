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

      <Panel title="Labour Ledger">
        {labour.length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-[var(--line)] text-left text-[var(--navy-muted)]">
                  <th className="py-3 pr-4">Worker</th>
                  <th className="py-3 pr-4">Task</th>
                  <th className="py-3 pr-4">Date</th>
                  <th className="py-3 pr-4">Scope</th>
                  <th className="py-3 pr-4">Batch</th>
                  <th className="py-3 pr-4">Amount</th>
                </tr>
              </thead>
              <tbody>
                {labour.map((item) => (
                  <tr key={item.id} className="border-b border-[var(--line)]">
                    <td className="py-4 pr-4 font-bold">{item.worker_name}</td>
                    <td className="py-4 pr-4">{item.task_description}</td>
                    <td className="py-4 pr-4">{formatDate(item.work_date)}</td>
                    <td className="py-4 pr-4">{formatLabel(item.cost_scope)}</td>
                    <td className="py-4 pr-4">
                      {item.batch ? batchLabels.get(item.batch) ?? `Batch ${item.batch}` : "Shared"}
                    </td>
                    <td className="py-4 pr-4">{formatCurrency(item.payment_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState message="No ad-hoc labour payments are recorded." />
        )}
      </Panel>
    </FinancePageShell>
  );
}
