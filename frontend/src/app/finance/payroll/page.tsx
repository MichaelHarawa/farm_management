import {
  getAccountingPeriods,
  getPayrollEntries,
} from "@/features/finance/api/finance";
import { getPoultryBatches } from "@/features/poultry/api/batches";
import { PayrollLedgerManager } from "@/features/finance/components/PayrollLedgerManager";
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
  formatDate,
} from "@/features/finance/utils/formatters";

export default async function FinancePayrollPage() {
  const [periods, entries, batches] = await Promise.all([
    getAccountingPeriods("/finance/payroll"),
    getPayrollEntries("/finance/payroll"),
    getPoultryBatches("/finance/payroll"),
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
          <PayrollLedgerManager entries={entries} batches={batches} />
        ) : (
          <EmptyState message="No payroll entries have been generated." />
        )}
      </Panel>
    </FinancePageShell>
  );
}
