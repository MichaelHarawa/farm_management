import {
  getAccountingPeriods,
  getAssetCategories,
  getAssets,
} from "@/features/finance/api/finance";
import {
  AssetCategoryForm,
  AssetForm,
  PeriodDepreciationButtons,
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
} from "@/features/finance/utils/formatters";

export default async function FinanceAssetsPage() {
  const [periods, categories, assets] = await Promise.all([
    getAccountingPeriods("/finance/assets"),
    getAssetCategories("/finance/assets"),
    getAssets("/finance/assets"),
  ]);
  const latestPeriod = periods[0];

  return (
    <FinancePageShell
      eyebrow="Finance / Assets"
      title="Fixed asset register."
      detail="Capitalize durable assets, run depreciation, and keep replacement funding separate from profit."
      actions={<FinanceNav />}
    >
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Create Asset Category">
          <AssetCategoryForm />
        </Panel>
        <Panel title="Create Asset">
          {categories.length ? (
            <AssetForm categories={categories} />
          ) : (
            <EmptyState message="Create an asset category before recording assets." />
          )}
        </Panel>
      </div>

      {latestPeriod ? (
        <Panel title={`Depreciation: ${formatDate(latestPeriod.period_start)} to ${formatDate(latestPeriod.period_end)}`}>
          <PeriodDepreciationButtons period={latestPeriod} />
        </Panel>
      ) : (
        <Panel title="Depreciation">
          <EmptyState message="Create an accounting period before generating depreciation." />
        </Panel>
      )}

      <Panel title="Asset Register">
        {assets.length ? (
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-[var(--line)] text-left text-[var(--navy-muted)]">
                  <th className="py-3 pr-4">Asset</th>
                  <th className="py-3 pr-4">Status</th>
                  <th className="py-3 pr-4">Available</th>
                  <th className="py-3 pr-4">Capitalized cost</th>
                  <th className="py-3 pr-4">USD ref</th>
                  <th className="py-3 pr-4">Method</th>
                </tr>
              </thead>
              <tbody>
                {assets.map((asset) => (
                  <tr key={asset.id} className="border-b border-[var(--line)]">
                    <td className="py-4 pr-4">
                      <p className="font-extrabold text-[var(--navy)]">
                        {asset.asset_code || asset.name}
                      </p>
                      <p className="text-xs text-[var(--navy-muted)]">{asset.name}</p>
                    </td>
                    <td className="py-4 pr-4">{formatLabel(asset.status)}</td>
                    <td className="py-4 pr-4">
                      {asset.available_for_use_date
                        ? formatDate(asset.available_for_use_date)
                        : "-"}
                    </td>
                    <td className="py-4 pr-4">
                      {formatCurrency(asset.total_capitalized_cost)}
                    </td>
                    <td className="py-4 pr-4">
                      {asset.usd_equivalent ? `$${asset.usd_equivalent}` : "-"}
                    </td>
                    <td className="py-4 pr-4">{formatLabel(asset.depreciation_method)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState message="No fixed assets have been recorded." />
        )}
      </Panel>
    </FinancePageShell>
  );
}
