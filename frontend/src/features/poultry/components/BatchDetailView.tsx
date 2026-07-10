import Link from "next/link";
import type { InputCost, PoultryBatch, PoultrySale } from "../types";
import {
  formatCurrency,
  formatDate,
  formatLabel,
  formatNumber,
} from "../utils/formatters";

type BatchDetailViewProps = {
  batch: PoultryBatch;
  inputCosts: InputCost[];
  sales: PoultrySale[];
};

function calculateInputCostTotal(cost: InputCost): number {
  const unitMultiplier = cost.unit ?? 1;

  return cost.quantity * unitMultiplier * cost.unit_cost;
}

function calculateSaleTotal(sale: PoultrySale): number {
  return sale.quantity_sold * sale.unit_price;
}

export function BatchDetailView({
  batch,
  inputCosts,
  sales,
}: BatchDetailViewProps) {
  const totalInputCosts = inputCosts.reduce(
    (total, cost) => total + calculateInputCostTotal(cost),
    0
  );

  const totalSales = sales.reduce(
    (total, sale) => total + calculateSaleTotal(sale),
    0
  );

  const totalPaid = sales.reduce((total, sale) => total + sale.amount_paid, 0);

  const totalBalance = sales.reduce((total, sale) => total + sale.balance, 0);

  const grossProfit = totalSales - totalInputCosts;

  const totalBirdsSold = sales.reduce(
    (total, sale) => total + sale.quantity_sold,
    0
  );

  const remainingBirds = batch.quantity - totalBirdsSold;

  return (
    <main>
      <section className="border-b border-[var(--line)] bg-[var(--surface-cream)]">
        <div className="mx-auto max-w-7xl px-5 py-12 sm:px-8">
          <Link
            href="/poultry"
            className="text-label text-[var(--navy-muted)] transition hover:text-[var(--gold)]"
          >
            ← Back to batch register
          </Link>

          <div className="mt-8 grid gap-8 lg:grid-cols-[1.1fr_0.9fr]">
            <div>
              <p className="text-label text-[var(--navy-muted)]">
                Batch Detail / {batch.batch_id}
              </p>

              <h1 className="font-display mt-4 max-w-4xl text-6xl leading-[0.92] tracking-[-0.06em] text-[var(--navy)] sm:text-7xl">
                {formatLabel(batch.bird_type)} batch performance.
              </h1>

              <p className="mt-6 max-w-2xl text-lg leading-8 text-[var(--navy-soft)]">
                Review the batch quantity, input costs, sales records, balances,
                and early profit position for this poultry production cycle.
              </p>
            </div>

            <div className="grid content-end gap-4 sm:grid-cols-2">
              <MetricCard label="Initial Birds" value={formatNumber(batch.quantity)} />
              <MetricCard label="Sold Birds" value={formatNumber(totalBirdsSold)} />
              <MetricCard label="Remaining" value={formatNumber(remainingBirds)} />
              <MetricCard label="Gross Profit" value={formatCurrency(grossProfit)} />
            </div>
          </div>
        </div>
      </section>

      <section className="bg-[var(--navy)] px-5 py-12 sm:px-8">
        <div className="mx-auto grid max-w-7xl gap-8">
          <BatchSummaryCard
            batch={batch}
            totalInputCosts={totalInputCosts}
            totalSales={totalSales}
            totalPaid={totalPaid}
            totalBalance={totalBalance}
          />

          <InputCostsTable inputCosts={inputCosts} />

          <SalesTable sales={sales} />
        </div>
      </section>
    </main>
  );
}

type MetricCardProps = {
  label: string;
  value: string;
};

function MetricCard({ label, value }: MetricCardProps) {
  return (
    <div className="border-y border-[var(--line)] py-4">
      <p className="font-display text-4xl font-bold tracking-[-0.04em] text-[var(--navy)]">
        {value}
      </p>
      <p className="text-label mt-2 text-[var(--navy-muted)]">{label}</p>
    </div>
  );
}

type BatchSummaryCardProps = {
  batch: PoultryBatch;
  totalInputCosts: number;
  totalSales: number;
  totalPaid: number;
  totalBalance: number;
};

function BatchSummaryCard({
  batch,
  totalInputCosts,
  totalSales,
  totalPaid,
  totalBalance,
}: BatchSummaryCardProps) {
  return (
    <div className="rounded-[1.7rem] border border-[var(--line)] bg-[var(--surface-cream)] p-7 shadow-[var(--shadow-card)]">
      <p className="text-label text-[var(--navy-muted)]">Batch Summary</p>

      <div className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryItem label="Batch ID" value={batch.batch_id} />
        <SummaryItem label="Bird Type" value={formatLabel(batch.bird_type)} />
        <SummaryItem label="Entry Date" value={formatDate(batch.entry_date)} />
        <SummaryItem
          label="Maturity Date"
          value={formatDate(batch.expected_maturity_date)}
        />
        <SummaryItem label="Input Costs" value={formatCurrency(totalInputCosts)} />
        <SummaryItem label="Sales Value" value={formatCurrency(totalSales)} />
        <SummaryItem label="Cash Received" value={formatCurrency(totalPaid)} />
        <SummaryItem label="Balance Due" value={formatCurrency(totalBalance)} />
      </div>
    </div>
  );
}

type SummaryItemProps = {
  label: string;
  value: string;
};

function SummaryItem({ label, value }: SummaryItemProps) {
  return (
    <div>
      <p className="text-label text-[var(--navy-muted)]">{label}</p>
      <p className="mt-2 text-sm font-semibold text-[var(--navy)]">{value}</p>
    </div>
  );
}

type InputCostsTableProps = {
  inputCosts: InputCost[];
};

function InputCostsTable({ inputCosts }: InputCostsTableProps) {
  return (
    <div className="overflow-hidden rounded-[1.7rem] border border-[var(--line)] bg-[var(--surface-cream)] shadow-[var(--shadow-card)]">
      <TableHeader
        label="Cost Register / Inputs"
        title="Input costs attached to this batch."
      />

      {inputCosts.length === 0 ? (
        <EmptyTableMessage message="No input costs have been recorded for this batch yet." />
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse">
            <thead>
              <tr className="border-b border-[var(--line)]">
                <TableHead label="Item" />
                <TableHead label="Category" />
                <TableHead label="Quantity" align="right" />
                <TableHead label="Unit" />
                <TableHead label="Unit Cost" align="right" />
                <TableHead label="Total" align="right" />
              </tr>
            </thead>

            <tbody>
              {inputCosts.map((cost) => (
                <tr
                  key={cost.id}
                  className="border-b border-[var(--line)] transition hover:bg-[var(--surface-cream-soft)]"
                >
                  <TableCell>{cost.item}</TableCell>
                  <TableCell>{formatLabel(cost.category)}</TableCell>
                  <TableCell align="right">{formatNumber(cost.quantity)}</TableCell>
                  <TableCell>
                    {cost.unit ? `${formatNumber(cost.unit)} ` : ""}
                    {cost.unit_measurement}
                  </TableCell>
                  <TableCell align="right">{formatCurrency(cost.unit_cost)}</TableCell>
                  <TableCell align="right">
                    {formatCurrency(calculateInputCostTotal(cost))}
                  </TableCell>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

type SalesTableProps = {
  sales: PoultrySale[];
};

function SalesTable({ sales }: SalesTableProps) {
  return (
    <div className="overflow-hidden rounded-[1.7rem] border border-[var(--line)] bg-[var(--surface-cream)] shadow-[var(--shadow-card)]">
      <TableHeader
        label="Sales Register / Revenue"
        title="Sales activity recorded against this batch."
      />

      {sales.length === 0 ? (
        <EmptyTableMessage message="No sales have been recorded for this batch yet." />
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse">
            <thead>
              <tr className="border-b border-[var(--line)]">
                <TableHead label="Sale ID" />
                <TableHead label="Date" />
                <TableHead label="Product" />
                <TableHead label="Qty" align="right" />
                <TableHead label="Total" align="right" />
                <TableHead label="Paid" align="right" />
                <TableHead label="Balance" align="right" />
                <TableHead label="Status" />
                <TableHead label="Sold By" />
              </tr>
            </thead>

            <tbody>
              {sales.map((sale) => (
                <tr
                  key={sale.id}
                  className="border-b border-[var(--line)] transition hover:bg-[var(--surface-cream-soft)]"
                >
                  <TableCell>{sale.sale_id}</TableCell>
                  <TableCell>{formatDate(sale.sale_date)}</TableCell>
                  <TableCell>{formatLabel(sale.product_type)}</TableCell>
                  <TableCell align="right">
                    {formatNumber(sale.quantity_sold)}
                  </TableCell>
                  <TableCell align="right">
                    {formatCurrency(calculateSaleTotal(sale))}
                  </TableCell>
                  <TableCell align="right">
                    {formatCurrency(sale.amount_paid)}
                  </TableCell>
                  <TableCell align="right">
                    {formatCurrency(sale.balance)}
                  </TableCell>
                  <TableCell>
                    <span className="inline-flex rounded-full bg-[var(--gold-soft)] px-3 py-1 text-[0.68rem] font-bold uppercase tracking-[0.16em] text-[var(--navy)]">
                      {formatLabel(sale.payment_status)}
                    </span>
                  </TableCell>
                  <TableCell>{sale.sold_by_name}</TableCell>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

type TableHeaderProps = {
  label: string;
  title: string;
};

function TableHeader({ label, title }: TableHeaderProps) {
  return (
    <div className="border-b border-[var(--line)] px-7 py-6">
      <p className="text-label text-[var(--navy-muted)]">{label}</p>
      <h2 className="font-display mt-3 text-4xl leading-none tracking-[-0.05em] text-[var(--navy)]">
        {title}
      </h2>
    </div>
  );
}

type TableHeadProps = {
  label: string;
  align?: "left" | "right";
};

function TableHead({ label, align = "left" }: TableHeadProps) {
  return (
    <th
      className={`px-7 py-4 text-${align} text-[0.68rem] font-bold uppercase tracking-[0.2em] text-[var(--navy-muted)]`}
    >
      {label}
    </th>
  );
}

type TableCellProps = {
  children: React.ReactNode;
  align?: "left" | "right";
};

function TableCell({ children, align = "left" }: TableCellProps) {
  return (
    <td
      className={`whitespace-nowrap px-7 py-5 text-${align} text-sm text-[var(--navy-soft)]`}
    >
      {children}
    </td>
  );
}

type EmptyTableMessageProps = {
  message: string;
};

function EmptyTableMessage({ message }: EmptyTableMessageProps) {
  return (
    <div className="px-7 py-10">
      <p className="text-sm text-[var(--navy-muted)]">{message}</p>
    </div>
  );
}