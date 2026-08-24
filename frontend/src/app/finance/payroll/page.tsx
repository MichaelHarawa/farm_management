import {
  getAccountingPeriods,
  getPayrollEntries,
} from "@/features/finance/api/finance";
import {
  AccountingPeriodCreateDialog,
  PeriodActionButtons,
} from "@/features/finance/components/FinanceForms";
import {
  EmptyState,
  FinanceNav,
  FinancePageShell,
  Panel,
} from "@/features/finance/components/FinanceUI";
import {
  formatCurrency,
  formatDate,
} from "@/features/finance/utils/formatters";

export default async function FinancePayrollPage() {
  const [periods, entries] = await Promise.all([
    getAccountingPeriods("/finance/payroll"),
    getPayrollEntries("/finance/payroll"),
  ]);
  return (
    <FinancePageShell
      eyebrow="Finance / Payroll"
      title="Payroll allocation."
      detail="Generate monthly salary snapshots and allocate production portions by bird-days."
      actions={<FinanceNav />}
    >
      <Panel title="Payroll Actions">
        <AccountingPeriodCreateDialog />
      </Panel>

      {periods.length ? (
        <Panel id="period-actions" title="Accounting Periods">
          <div className="grid gap-4">
            {periods.map((period) => (
              <div
                key={period.id}
                className="flex flex-col gap-4 rounded-lg border border-[var(--line)] bg-white/55 p-4 lg:flex-row lg:items-center lg:justify-between"
              >
                <div>
                  <p className="font-extrabold text-[var(--navy)]">
                    {formatDate(period.period_start)} to {formatDate(period.period_end)}
                  </p>
                  <p className="mt-1 text-sm capitalize text-[var(--navy-muted)]">
                    {period.status} period
                  </p>
                </div>
                <PeriodActionButtons period={period} />
              </div>
            ))}
          </div>
        </Panel>
      ) : (
        <Panel id="period-actions" title="Accounting Periods">
          <EmptyState message="No accounting period has been created yet." />
        </Panel>
      )}

      <Panel title="Payroll Entries">
        {entries.length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-[var(--line)] text-left text-[var(--navy-muted)]">
                  <th className="py-3 pr-4">Employee</th>
                  <th className="py-3 pr-4">Gross</th>
                  <th className="py-3 pr-4">Production</th>
                  <th className="py-3 pr-4">Admin</th>
                  <th className="py-3 pr-4">Selling</th>
                  <th className="py-3 pr-4">Status</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.id} className="border-b border-[var(--line)]">
                    <td className="py-4 pr-4 font-bold">{entry.employee_name}</td>
                    <td className="py-4 pr-4">{formatCurrency(entry.gross_salary)}</td>
                    <td className="py-4 pr-4">{formatCurrency(entry.production_amount)}</td>
                    <td className="py-4 pr-4">{formatCurrency(entry.administration_amount)}</td>
                    <td className="py-4 pr-4">{formatCurrency(entry.selling_amount)}</td>
                    <td className="py-4 pr-4">{entry.payment_status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState message="No payroll entries have been generated." />
        )}
      </Panel>
    </FinancePageShell>
  );
}
