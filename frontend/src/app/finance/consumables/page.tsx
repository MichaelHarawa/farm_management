import {
  getAccountingPeriods,
  getConsumableLots,
  getConsumableUsages,
} from "@/features/finance/api/finance";
import {
  ConsumableLotForm,
  ConsumableUsageForm,
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
  formatLabel,
  formatNumber,
} from "@/features/finance/utils/formatters";

export default async function FinanceConsumablesPage() {
  const [periods, lots, usages] = await Promise.all([
    getAccountingPeriods("/finance/consumables"),
    getConsumableLots("/finance/consumables"),
    getConsumableUsages("/finance/consumables"),
  ]);

  return (
    <FinancePageShell
      eyebrow="Finance / Consumables"
      title="Consumable inventory."
      detail="Track shared purchases as stock, then recognize expense when the farm consumes them."
      actions={<FinanceNav />}
    >
      <Panel title="Record Consumable Purchase">
        <ConsumableLotForm />
      </Panel>

      <Panel title="Record Consumable Usage">
        {periods.length && lots.length ? (
          <ConsumableUsageForm periods={periods} lots={lots} />
        ) : (
          <EmptyState message="Create an accounting period and a consumable lot before recording usage." />
        )}
      </Panel>

      <Panel title="Consumable Lots">
        {lots.length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-[var(--line)] text-left text-[var(--navy-muted)]">
                  <th className="py-3 pr-4">Item</th>
                  <th className="py-3 pr-4">Purchased</th>
                  <th className="py-3 pr-4">Available</th>
                  <th className="py-3 pr-4">Unit cost</th>
                  <th className="py-3 pr-4">USD ref</th>
                  <th className="py-3 pr-4">Status</th>
                </tr>
              </thead>
              <tbody>
                {lots.map((lot) => (
                  <tr key={lot.id} className="border-b border-[var(--line)]">
                    <td className="py-4 pr-4">
                      <p className="font-extrabold text-[var(--navy)]">{lot.item}</p>
                      <p className="text-xs text-[var(--navy-muted)]">{lot.category}</p>
                    </td>
                    <td className="py-4 pr-4">{formatDate(lot.purchase_date)}</td>
                    <td className="py-4 pr-4">
                      {formatNumber(lot.quantity_available)} {lot.unit_of_measurement}
                    </td>
                    <td className="py-4 pr-4">{formatCurrency(lot.unit_cost)}</td>
                    <td className="py-4 pr-4">
                      {lot.usd_equivalent ? `$${lot.usd_equivalent}` : "-"}
                    </td>
                    <td className="py-4 pr-4">
                      {lot.is_expired ? "Expired" : formatLabel(lot.payment_status)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState message="No consumable lots have been recorded." />
        )}
      </Panel>

      <Panel title="Usage Recognition">
        {usages.length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-[var(--line)] text-left text-[var(--navy-muted)]">
                  <th className="py-3 pr-4">Date</th>
                  <th className="py-3 pr-4">Scope</th>
                  <th className="py-3 pr-4">Quantity</th>
                  <th className="py-3 pr-4">Recognized cost</th>
                  <th className="py-3 pr-4">Driver</th>
                </tr>
              </thead>
              <tbody>
                {usages.map((usage) => (
                  <tr key={usage.id} className="border-b border-[var(--line)]">
                    <td className="py-4 pr-4">{formatDate(usage.usage_date)}</td>
                    <td className="py-4 pr-4">{formatLabel(usage.usage_scope)}</td>
                    <td className="py-4 pr-4">{formatNumber(usage.quantity_used)}</td>
                    <td className="py-4 pr-4">{formatCurrency(usage.recognized_cost)}</td>
                    <td className="py-4 pr-4">{formatLabel(usage.allocation_driver)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState message="No consumable usage has been recognized." />
        )}
      </Panel>
    </FinancePageShell>
  );
}
