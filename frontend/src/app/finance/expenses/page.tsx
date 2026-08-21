import {
  getAccountingPeriods,
  getSharedExpenses,
} from "@/features/finance/api/finance";
import { ExpenseDialog } from "@/features/finance/components/FinanceForms";
import { getPoultryBatches } from "@/features/poultry/api/batches";
import {
  EmptyState,
  FinanceNav,
  FinancePageShell,
  Panel,
} from "@/features/finance/components/FinanceUI";
import { formatCurrency, formatDate, formatLabel } from "@/features/finance/utils/formatters";

export default async function FinanceExpensesPage() {
  const [periods, expenses, batches] = await Promise.all([
    getAccountingPeriods("/finance/expenses"),
    getSharedExpenses("/finance/expenses"),
    getPoultryBatches("/finance/expenses"),
  ]);
  const batchLabels = new Map(batches.map((batch) => [batch.id, batch.batch_id]));
  const selectableBatches = batches.filter(
    (batch) =>
      !["booked", "delivered"].includes(batch.status) &&
      !(batch.status === "closed" && batch.profitability_finalized_at)
  );

  return (
    <FinancePageShell
      eyebrow="Finance / Expenses"
      title="Shared expense ledger."
      detail="Separate production overhead, administration, selling, finance costs, tax, and capital expenditure."
      actions={<FinanceNav />}
    >
      <Panel title="Expense Actions">
        {periods.length ? (
          <ExpenseDialog periods={periods} batches={selectableBatches} />
        ) : (
          <EmptyState message="Create an accounting period before recording expenses." />
        )}
      </Panel>

      <Panel title="Expense Ledger">
        {expenses.length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-[var(--line)] text-left text-[var(--navy-muted)]">
                  <th className="py-3 pr-4">Description</th>
                  <th className="py-3 pr-4">Date</th>
                  <th className="py-3 pr-4">Scope</th>
                  <th className="py-3 pr-4">Batch</th>
                  <th className="py-3 pr-4">Amount</th>
                  <th className="py-3 pr-4">Status</th>
                </tr>
              </thead>
              <tbody>
                {expenses.map((expense) => (
                  <tr key={expense.id} className="border-b border-[var(--line)]">
                    <td className="py-4 pr-4 font-bold">{expense.description}</td>
                    <td className="py-4 pr-4">{formatDate(expense.expense_date)}</td>
                    <td className="py-4 pr-4">{formatLabel(expense.scope)}</td>
                    <td className="py-4 pr-4">
                      {expense.directly_assigned_batch
                        ? batchLabels.get(expense.directly_assigned_batch) ??
                          `Batch ${expense.directly_assigned_batch}`
                        : "Shared"}
                    </td>
                    <td className="py-4 pr-4">{formatCurrency(expense.amount)}</td>
                    <td className="py-4 pr-4">
                      {expense.is_capital_expenditure ? "Capitalized" : expense.payment_status}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState message="No shared expenses are recorded." />
        )}
      </Panel>
    </FinancePageShell>
  );
}
