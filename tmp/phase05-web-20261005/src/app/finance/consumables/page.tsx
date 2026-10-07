import {
  getAccountingPeriods,
  getConsumableLots,
  getConsumableUsages,
  getStockMovements,
} from "@/features/finance/api/finance";
import {
  ConsumableLotDialog,
  ConsumableUsageDialog,
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
import { getPoultryBatches } from "@/features/poultry/api/batches";
import { MobileRecordList } from "@/components/ui/MobileRecordList";
import { PaginatedTableBody } from "@/components/ui/PaginatedTableBody";

export default async function FinanceConsumablesPage() {
  const [periods, lots, usages, movements, batches] = await Promise.all([
    getAccountingPeriods("/finance/consumables"),
    getConsumableLots("/finance/consumables"),
    getConsumableUsages("/finance/consumables"),
    getStockMovements("/finance/consumables"),
    getPoultryBatches("/finance/consumables"),
  ]);
  const batchLabels = new Map(batches.map((batch) => [batch.id, batch.batch_id]));
  const selectableBatches = batches.filter(
    (batch) =>
      !["booked", "delivered"].includes(batch.status) &&
      !(batch.status === "closed" && batch.profitability_finalized_at)
  );

  return (
    <FinancePageShell
      eyebrow="Finance / Consumables"
      title="Consumable inventory."
      detail="Track shared purchases as stock, then recognize expense when the farm consumes them."
      actions={<FinanceNav />}
    >
      <Panel title="Consumable Actions">
        <div className="flex flex-wrap items-center gap-3">
          <ConsumableLotDialog />
          {periods.length && lots.length ? (
            <ConsumableUsageDialog
              periods={periods}
              lots={lots}
              batches={selectableBatches}
            />
          ) : (
            <p className="text-sm text-[var(--navy-muted)]">
              Create an accounting period and a consumable lot to record usage.
            </p>
          )}
        </div>
      </Panel>

      <Panel id="consumable-lots" title="Consumable Lots">
        {lots.length ? (
          <>
          <MobileRecordList records={lots.map((lot) => ({
            key: lot.id,
            title: lot.item,
            subtitle: lot.category,
            badge: <span className="rounded-full bg-[var(--gold-soft)] px-2 py-1 text-xs font-bold">{lot.is_expired ? "Expired" : formatLabel(lot.payment_status)}</span>,
            fields: [
              { label: "Purchased", value: formatDate(lot.purchase_date) },
              { label: "Available", value: `${formatNumber(lot.quantity_available)} ${lot.unit_of_measurement}` },
              { label: "Unit cost", value: formatCurrency(lot.unit_cost) },
              { label: "USD reference", value: lot.usd_equivalent ? `$${lot.usd_equivalent}` : "-" },
            ],
          }))} emptyMessage="No consumable lots have been recorded." />
          <div className="hidden overflow-x-auto md:block">
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
              <PaginatedTableBody columnCount={6} itemLabel="consumable lots">
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
              </PaginatedTableBody>
            </table>
          </div>
          </>
        ) : (
          <EmptyState message="No consumable lots have been recorded." />
        )}
      </Panel>

      <Panel id="usage-recognition" title="Usage Recognition">
        {usages.length ? (
          <>
          <MobileRecordList records={usages.map((usage) => ({
            key: usage.id,
            title: formatCurrency(usage.recognized_cost),
            subtitle: `${formatLabel(usage.usage_scope)} · ${formatDate(usage.usage_date)}`,
            fields: [
              { label: "Batch", value: usage.batch ? batchLabels.get(usage.batch) ?? `Batch ${usage.batch}` : "Shared" },
              { label: "Quantity", value: formatNumber(usage.quantity_used) },
              { label: "Allocation driver", value: formatLabel(usage.allocation_driver) },
            ],
          }))} emptyMessage="No consumable usage has been recognized." />
          <div className="hidden overflow-x-auto md:block">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-[var(--line)] text-left text-[var(--navy-muted)]">
                  <th className="py-3 pr-4">Date</th>
                  <th className="py-3 pr-4">Scope</th>
                  <th className="py-3 pr-4">Batch</th>
                  <th className="py-3 pr-4">Quantity</th>
                  <th className="py-3 pr-4">Recognized cost</th>
                  <th className="py-3 pr-4">Driver</th>
                </tr>
              </thead>
              <PaginatedTableBody columnCount={6} itemLabel="usage records">
                {usages.map((usage) => (
                  <tr key={usage.id} className="border-b border-[var(--line)]">
                    <td className="py-4 pr-4">{formatDate(usage.usage_date)}</td>
                    <td className="py-4 pr-4">{formatLabel(usage.usage_scope)}</td>
                    <td className="py-4 pr-4">
                      {usage.batch
                        ? batchLabels.get(usage.batch) ?? `Batch ${usage.batch}`
                        : "Shared"}
                    </td>
                    <td className="py-4 pr-4">{formatNumber(usage.quantity_used)}</td>
                    <td className="py-4 pr-4">{formatCurrency(usage.recognized_cost)}</td>
                    <td className="py-4 pr-4">{formatLabel(usage.allocation_driver)}</td>
                  </tr>
                ))}
              </PaginatedTableBody>
            </table>
          </div>
          </>
        ) : (
          <EmptyState message="No consumable usage has been recognized." />
        )}
      </Panel>

      <Panel id="stock-movements" title="Immutable Stock Movement Ledger">
        {movements.length ? <><MobileRecordList records={movements.map((movement) => ({ key: movement.id, title: movement.item_name, subtitle: `${formatLabel(movement.movement_type)} · ${formatDate(movement.movement_date)}`, fields: [{ label: "Batch", value: movement.batch_code || "Farm stock" }, { label: "Quantity", value: formatNumber(movement.quantity) }, { label: "Cost", value: formatCurrency(movement.total_cost) }] }))} emptyMessage="No stock movements have been posted." /><div className="hidden overflow-x-auto md:block"><table className="min-w-full text-sm"><thead><tr className="border-b text-left"><th className="py-3 pr-4">Date</th><th className="py-3 pr-4">Movement</th><th className="py-3 pr-4">Item</th><th className="py-3 pr-4">Batch</th><th className="py-3 pr-4 text-right">Quantity</th><th className="py-3 pr-4 text-right">Cost</th></tr></thead><PaginatedTableBody columnCount={6} itemLabel="stock movements">{movements.map((movement) => <tr key={movement.id} className="border-b"><td className="py-3 pr-4">{formatDate(movement.movement_date)}</td><td className="py-3 pr-4">{formatLabel(movement.movement_type)}</td><td className="py-3 pr-4 font-bold">{movement.item_name}</td><td className="py-3 pr-4">{movement.batch_code || "Farm stock"}</td><td className="py-3 pr-4 text-right">{formatNumber(movement.quantity)}</td><td className="py-3 pr-4 text-right">{formatCurrency(movement.total_cost)}</td></tr>)}</PaginatedTableBody></table></div></> : <EmptyState message="No stock movements have been posted." />}
      </Panel>
    </FinancePageShell>
  );
}
