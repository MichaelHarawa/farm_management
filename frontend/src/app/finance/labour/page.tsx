import {
  getAccountingPeriods,
  getAdHocLabour,
} from "@/features/finance/api/finance";
import { LabourPaymentForm } from "@/features/finance/components/FinanceForms";
import {
  EmptyState,
  FinanceNav,
  FinancePageShell,
  Panel,
} from "@/features/finance/components/FinanceUI";
import { formatCurrency, formatDate, formatLabel } from "@/features/finance/utils/formatters";

export default async function FinanceLabourPage() {
  const [periods, labour] = await Promise.all([
    getAccountingPeriods("/finance/labour"),
    getAdHocLabour("/finance/labour"),
  ]);

  return (
    <FinancePageShell
      eyebrow="Finance / Labour"
      title="Ad-hoc labour."
      detail="Record temporary and task-based labour by cost scope for direct or shared allocation."
      actions={<FinanceNav />}
    >
      <Panel title="Record Labour">
        {periods.length ? (
          <LabourPaymentForm periods={periods} />
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
