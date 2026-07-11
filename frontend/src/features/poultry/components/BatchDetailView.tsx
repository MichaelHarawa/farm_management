"use client";

import {
  BarChart3,
  Banknote,
  Package,
  Plus,
  ReceiptText,
  ShoppingCart,
  Table2,
  TrendingUp,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";

import type { InputCost, PoultryBatch, PoultrySale } from "../types";
import {
  formatCurrency,
  formatDate,
  formatLabel,
  formatNumber,
} from "../utils/formatters";
import { AddInputCostForm } from "./AddInputCostForm";

type BatchDetailViewProps = {
  batch: PoultryBatch;
  inputCosts: InputCost[];
  sales: PoultrySale[];
};

type ModalKind = "input-cost-form" | "input-costs" | "sales" | null;

type BreakdownItem = {
  label: string;
  value: number;
  count: number;
};

const REGISTER_PAGE_SIZE = 10;

function calculateInputCostTotal(cost: InputCost): number {
  const unitMultiplier = cost.unit ?? 1;

  return cost.quantity * unitMultiplier * cost.unit_cost;
}

function calculateSaleTotal(sale: PoultrySale): number {
  return sale.quantity_sold * sale.unit_price;
}

function getPercent(value: number, total: number): number {
  if (total <= 0) {
    return 0;
  }

  return Math.min(100, Math.max(0, (value / total) * 100));
}

function formatPercent(value: number): string {
  return `${Math.round(value)}%`;
}

function formatRecordCount(count: number): string {
  return `${formatNumber(count)} ${count === 1 ? "record" : "records"}`;
}

function buildBreakdown<T>(
  items: T[],
  getKey: (item: T) => string,
  getValue: (item: T) => number
): BreakdownItem[] {
  const grouped = new Map<string, BreakdownItem>();

  items.forEach((item) => {
    const key = getKey(item);
    const value = getValue(item);
    const current = grouped.get(key) ?? {
      label: key,
      value: 0,
      count: 0,
    };

    current.value += value;
    current.count += 1;
    grouped.set(key, current);
  });

  return Array.from(grouped.values()).sort((a, b) => b.value - a.value);
}

export function BatchDetailView({
  batch,
  inputCosts,
  sales,
}: BatchDetailViewProps) {
  const [openModal, setOpenModal] = useState<ModalKind>(null);

  const totals = useMemo(() => {
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
    const totalBirdsSold = sales.reduce(
      (total, sale) => total + sale.quantity_sold,
      0
    );

    return {
      totalInputCosts,
      totalSales,
      totalPaid,
      totalBalance,
      totalBirdsSold,
      remainingBirds: batch.quantity - totalBirdsSold,
      grossProfit: totalSales - totalInputCosts,
    };
  }, [batch.quantity, inputCosts, sales]);

  const costBreakdown = useMemo(
    () =>
      buildBreakdown(
        inputCosts,
        (cost) => formatLabel(cost.category),
        calculateInputCostTotal
      ),
    [inputCosts]
  );

  const paymentBreakdown = useMemo(
    () =>
      buildBreakdown(
        sales,
        (sale) => formatLabel(sale.payment_status),
        calculateSaleTotal
      ),
    [sales]
  );

  const recentInputCosts = inputCosts.slice(0, 4);
  const recentSales = sales.slice(0, 4);

  return (
    <main>
      <section className="border-b border-[var(--line)] bg-[var(--surface-cream)]">
        <div className="mx-auto max-w-7xl px-5 py-7 sm:px-8">
          <Link
            href="/poultry"
            className="text-label text-[var(--navy-muted)] transition hover:text-[var(--gold)]"
          >
            &larr; Back to batch register
          </Link>

          <div className="mt-6 grid gap-8 lg:grid-cols-[1.1fr_0.9fr]">
            <div>
              <p className="text-label text-[var(--navy-muted)]">
                Batch Detail / {batch.batch_id}
              </p>

              <h1 className="font-display mt-3 max-w-4xl text-5xl leading-none text-[var(--navy)] sm:text-6xl">
                {formatLabel(batch.bird_type)} batch performance.
              </h1>

              <p className="mt-5 max-w-2xl text-base leading-7 text-[var(--navy-soft)]">
                Review the batch quantity, costs, sales, balances, and profit
                position for this poultry production cycle.
              </p>
            </div>

            <div className="grid content-end gap-4 sm:grid-cols-2">
              <MetricCard
                label="Initial Birds"
                value={formatNumber(batch.quantity)}
              />
              <MetricCard
                label="Sold Birds"
                value={formatNumber(totals.totalBirdsSold)}
              />
              <MetricCard
                label="Remaining"
                value={formatNumber(totals.remainingBirds)}
              />
              <MetricCard
                label="Gross Profit"
                value={formatCurrency(totals.grossProfit)}
              />
            </div>
          </div>
        </div>
      </section>

      <section className="bg-[var(--navy)] px-5 py-12 sm:px-8">
        <div className="mx-auto grid max-w-7xl gap-6">
          <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
            <BatchSummaryPanel
              batch={batch}
              totalInputCosts={totals.totalInputCosts}
              totalSales={totals.totalSales}
              totalPaid={totals.totalPaid}
              totalBalance={totals.totalBalance}
            />

            <ActionPanel
              inputCostCount={inputCosts.length}
              salesCount={sales.length}
              onOpen={setOpenModal}
            />
          </div>

          <PerformanceDashboard
            batch={batch}
            totalInputCosts={totals.totalInputCosts}
            totalSales={totals.totalSales}
            totalPaid={totals.totalPaid}
            totalBalance={totals.totalBalance}
            totalBirdsSold={totals.totalBirdsSold}
            remainingBirds={totals.remainingBirds}
            grossProfit={totals.grossProfit}
          />

          <div className="grid gap-6 lg:grid-cols-2">
            <BreakdownPanel
              icon={Package}
              label="Cost Mix"
              title="Input spend by category"
              items={costBreakdown}
              total={totals.totalInputCosts}
              emptyMessage="No input costs have been recorded."
            />

            <BreakdownPanel
              icon={Banknote}
              label="Collections"
              title="Sales value by payment status"
              items={paymentBreakdown}
              total={totals.totalSales}
              emptyMessage="No sales have been recorded."
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <RecentInputCostsPanel
              inputCosts={recentInputCosts}
              totalCount={inputCosts.length}
              onOpen={() => setOpenModal("input-costs")}
            />

            <RecentSalesPanel
              sales={recentSales}
              totalCount={sales.length}
              onOpen={() => setOpenModal("sales")}
            />
          </div>
        </div>
      </section>

      <DetailModal
        isOpen={openModal === "input-cost-form"}
        label="New input cost"
        title="Record input cost"
        onClose={() => setOpenModal(null)}
      >
        <AddInputCostForm batchId={batch.id} />
      </DetailModal>

      <DetailModal
        isOpen={openModal === "input-costs"}
        label="Input register"
        title="Input cost records"
        onClose={() => setOpenModal(null)}
      >
        <InputCostsRegister inputCosts={inputCosts} />
      </DetailModal>

      <DetailModal
        isOpen={openModal === "sales"}
        label="Sales register"
        title="Sales records"
        onClose={() => setOpenModal(null)}
      >
        <SalesRegister sales={sales} />
      </DetailModal>
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
      <p className="font-display text-4xl font-bold text-[var(--navy)]">
        {value}
      </p>
      <p className="text-label mt-2 text-[var(--navy-muted)]">{label}</p>
    </div>
  );
}

type BatchSummaryPanelProps = {
  batch: PoultryBatch;
  totalInputCosts: number;
  totalSales: number;
  totalPaid: number;
  totalBalance: number;
};

function BatchSummaryPanel({
  batch,
  totalInputCosts,
  totalSales,
  totalPaid,
  totalBalance,
}: BatchSummaryPanelProps) {
  return (
    <section className="rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-6 shadow-[var(--shadow-card)]">
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
    </section>
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

type ActionPanelProps = {
  inputCostCount: number;
  salesCount: number;
  onOpen: (modal: ModalKind) => void;
};

function ActionPanel({ inputCostCount, salesCount, onOpen }: ActionPanelProps) {
  return (
    <section className="rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-6 shadow-[var(--shadow-card)]">
      <p className="text-label text-[var(--navy-muted)]">Batch Actions</p>

      <h2 className="font-display mt-3 text-3xl leading-tight text-[var(--navy)]">
        Cost and sales records.
      </h2>

      <div className="mt-6 grid gap-3">
        <ActionButton
          icon={Plus}
          title="Add input cost"
          detail="New expense"
          onClick={() => onOpen("input-cost-form")}
        />
        <ActionButton
          icon={Table2}
          title="Input register"
          detail={formatRecordCount(inputCostCount)}
          onClick={() => onOpen("input-costs")}
        />
        <ActionButton
          icon={ReceiptText}
          title="Sales register"
          detail={formatRecordCount(salesCount)}
          onClick={() => onOpen("sales")}
        />
      </div>
    </section>
  );
}

type ActionButtonProps = {
  icon: LucideIcon;
  title: string;
  detail: string;
  onClick: () => void;
};

function ActionButton({ icon: Icon, title, detail, onClick }: ActionButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-4 rounded-lg border border-[var(--line)] bg-[var(--surface-cream-soft)] px-4 py-3 text-left transition hover:border-[var(--gold)] hover:bg-[var(--gold-soft)]"
    >
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[var(--navy)] text-[var(--surface-cream)]">
        <Icon className="h-4 w-4" aria-hidden="true" />
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-bold text-[var(--navy)]">
          {title}
        </span>
        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-[var(--navy-muted)]">
          {detail}
        </span>
      </span>
    </button>
  );
}

type PerformanceDashboardProps = {
  batch: PoultryBatch;
  totalInputCosts: number;
  totalSales: number;
  totalPaid: number;
  totalBalance: number;
  totalBirdsSold: number;
  remainingBirds: number;
  grossProfit: number;
};

function PerformanceDashboard({
  batch,
  totalInputCosts,
  totalSales,
  totalPaid,
  totalBalance,
  totalBirdsSold,
  remainingBirds,
  grossProfit,
}: PerformanceDashboardProps) {
  const soldPercent = getPercent(totalBirdsSold, batch.quantity);
  const paidPercent = getPercent(totalPaid, totalSales);
  const costPerBird = batch.quantity > 0 ? totalInputCosts / batch.quantity : 0;
  const marginPercent = getPercent(grossProfit, totalSales);

  return (
    <section className="grid gap-6 lg:grid-cols-3">
      <IndicatorPanel
        icon={BarChart3}
        label="Bird Position"
        value={`${formatPercent(soldPercent)} sold`}
        detail={`${formatNumber(remainingBirds)} birds remaining`}
        percent={soldPercent}
      >
        <PairStat label="Initial" value={formatNumber(batch.quantity)} />
        <PairStat label="Sold" value={formatNumber(totalBirdsSold)} />
      </IndicatorPanel>

      <IndicatorPanel
        icon={Banknote}
        label="Cash Collection"
        value={formatCurrency(totalPaid)}
        detail={`${formatCurrency(totalBalance)} still outstanding`}
        percent={paidPercent}
      >
        <PairStat label="Sales value" value={formatCurrency(totalSales)} />
        <PairStat label="Collected" value={formatPercent(paidPercent)} />
      </IndicatorPanel>

      <IndicatorPanel
        icon={TrendingUp}
        label="Margin Signal"
        value={formatCurrency(grossProfit)}
        detail={`${formatCurrency(costPerBird)} cost per initial bird`}
        percent={marginPercent}
      >
        <PairStat label="Input costs" value={formatCurrency(totalInputCosts)} />
        <PairStat label="Margin" value={formatPercent(marginPercent)} />
      </IndicatorPanel>
    </section>
  );
}

type IndicatorPanelProps = {
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
  percent: number;
  children: ReactNode;
};

function IndicatorPanel({
  icon: Icon,
  label,
  value,
  detail,
  percent,
  children,
}: IndicatorPanelProps) {
  return (
    <article className="rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-6 shadow-[var(--shadow-card)]">
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-full bg-[var(--gold-soft)] text-[var(--navy)]">
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
        <p className="text-label text-[var(--navy-muted)]">{label}</p>
      </div>

      <p className="font-display mt-5 text-4xl font-bold leading-none text-[var(--navy)]">
        {value}
      </p>
      <p className="mt-2 text-sm leading-6 text-[var(--navy-muted)]">
        {detail}
      </p>

      <ProgressBar percent={percent} className="mt-5" />

      <div className="mt-5 grid grid-cols-2 gap-4 border-t border-[var(--line)] pt-4">
        {children}
      </div>
    </article>
  );
}

type PairStatProps = {
  label: string;
  value: string;
};

function PairStat({ label, value }: PairStatProps) {
  return (
    <div>
      <p className="text-[0.68rem] font-bold uppercase tracking-[0.16em] text-[var(--navy-muted)]">
        {label}
      </p>
      <p className="mt-1 text-sm font-bold text-[var(--navy)]">{value}</p>
    </div>
  );
}

type ProgressBarProps = {
  percent: number;
  className?: string;
};

function ProgressBar({ percent, className = "" }: ProgressBarProps) {
  return (
    <div
      className={`h-2 overflow-hidden rounded-full bg-[var(--surface-cream-soft)] ${className}`}
    >
      <div
        className="h-full rounded-full bg-[var(--gold)]"
        style={{ width: `${getPercent(percent, 100)}%` }}
      />
    </div>
  );
}

type BreakdownPanelProps = {
  icon: LucideIcon;
  label: string;
  title: string;
  items: BreakdownItem[];
  total: number;
  emptyMessage: string;
};

function BreakdownPanel({
  icon: Icon,
  label,
  title,
  items,
  total,
  emptyMessage,
}: BreakdownPanelProps) {
  const visibleItems = items.slice(0, 5);

  return (
    <section className="rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-6 shadow-[var(--shadow-card)]">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-label text-[var(--navy-muted)]">{label}</p>
          <h2 className="font-display mt-3 text-3xl leading-tight text-[var(--navy)]">
            {title}
          </h2>
        </div>
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[var(--navy)] text-[var(--surface-cream)]">
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
      </div>

      {visibleItems.length === 0 ? (
        <p className="mt-6 text-sm text-[var(--navy-muted)]">{emptyMessage}</p>
      ) : (
        <div className="mt-6 grid gap-4">
          {visibleItems.map((item) => {
            const percent = getPercent(item.value, total);

            return (
              <div key={item.label}>
                <div className="flex items-center justify-between gap-4">
                  <p className="truncate text-sm font-bold text-[var(--navy)]">
                    {item.label}
                  </p>
                  <p className="text-sm font-bold text-[var(--navy)]">
                    {formatCurrency(item.value)}
                  </p>
                </div>
                <ProgressBar percent={percent} className="mt-2" />
                <p className="mt-2 text-xs font-semibold uppercase tracking-[0.14em] text-[var(--navy-muted)]">
                  {formatPercent(percent)} / {formatRecordCount(item.count)}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

type RecentInputCostsPanelProps = {
  inputCosts: InputCost[];
  totalCount: number;
  onOpen: () => void;
};

function RecentInputCostsPanel({
  inputCosts,
  totalCount,
  onOpen,
}: RecentInputCostsPanelProps) {
  return (
    <RecentPanel
      icon={Package}
      label="Cost Register"
      title="Latest input costs"
      totalCount={totalCount}
      emptyMessage="No input costs have been recorded for this batch."
      actionLabel="Open register"
      onOpen={onOpen}
    >
      {inputCosts.map((cost) => (
        <ActivityRow
          key={cost.id}
          title={cost.item}
          meta={`${formatLabel(cost.category)} / ${formatNumber(cost.quantity)} x ${
            cost.unit ? `${formatNumber(cost.unit)} ` : ""
          }${cost.unit_measurement}`}
          value={formatCurrency(calculateInputCostTotal(cost))}
        />
      ))}
    </RecentPanel>
  );
}

type RecentSalesPanelProps = {
  sales: PoultrySale[];
  totalCount: number;
  onOpen: () => void;
};

function RecentSalesPanel({ sales, totalCount, onOpen }: RecentSalesPanelProps) {
  return (
    <RecentPanel
      icon={ShoppingCart}
      label="Sales Register"
      title="Latest sales activity"
      totalCount={totalCount}
      emptyMessage="No sales have been recorded for this batch."
      actionLabel="Open register"
      onOpen={onOpen}
    >
      {sales.map((sale) => (
        <ActivityRow
          key={sale.id}
          title={sale.sale_id}
          meta={`${formatDate(sale.sale_date)} / ${formatLabel(
            sale.payment_status
          )}`}
          value={formatCurrency(calculateSaleTotal(sale))}
        />
      ))}
    </RecentPanel>
  );
}

type RecentPanelProps = {
  icon: LucideIcon;
  label: string;
  title: string;
  totalCount: number;
  emptyMessage: string;
  actionLabel: string;
  onOpen: () => void;
  children: ReactNode;
};

function RecentPanel({
  icon: Icon,
  label,
  title,
  totalCount,
  emptyMessage,
  actionLabel,
  onOpen,
  children,
}: RecentPanelProps) {
  return (
    <section className="rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] p-6 shadow-[var(--shadow-card)]">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[var(--gold-soft)] text-[var(--navy)]">
            <Icon className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-label text-[var(--navy-muted)]">{label}</p>
            <h2 className="font-display mt-3 text-3xl leading-tight text-[var(--navy)]">
              {title}
            </h2>
          </div>
        </div>

        <button
          type="button"
          onClick={onOpen}
          className="inline-flex items-center justify-center gap-2 rounded-full bg-[var(--gold)] px-4 py-2 text-[0.68rem] font-bold uppercase tracking-[0.16em] text-[var(--navy)] transition hover:brightness-95"
        >
          <Table2 className="h-4 w-4" aria-hidden="true" />
          {actionLabel}
        </button>
      </div>

      {totalCount === 0 ? (
        <p className="mt-6 text-sm text-[var(--navy-muted)]">{emptyMessage}</p>
      ) : (
        <div className="mt-6 divide-y divide-[var(--line)]">{children}</div>
      )}
    </section>
  );
}

type ActivityRowProps = {
  title: string;
  meta: string;
  value: string;
};

function ActivityRow({ title, meta, value }: ActivityRowProps) {
  return (
    <div className="grid gap-2 py-4 sm:grid-cols-[1fr_auto] sm:items-center">
      <div className="min-w-0">
        <p className="truncate text-sm font-bold text-[var(--navy)]">{title}</p>
        <p className="mt-1 text-xs font-semibold uppercase tracking-[0.12em] text-[var(--navy-muted)]">
          {meta}
        </p>
      </div>
      <p className="text-sm font-bold text-[var(--navy)]">{value}</p>
    </div>
  );
}

type DetailModalProps = {
  isOpen: boolean;
  label: string;
  title: string;
  onClose: () => void;
  children: ReactNode;
};

function DetailModal({
  isOpen,
  label,
  title,
  onClose,
  children,
}: DetailModalProps) {
  if (!isOpen) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 overflow-y-auto bg-[rgba(23,36,67,0.72)] px-4 py-6 backdrop-blur-sm"
      role="presentation"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="batch-detail-modal-title"
        className="mx-auto w-full max-w-5xl rounded-lg border border-[var(--line)] bg-[var(--surface-cream)] shadow-[0_24px_80px_rgba(0,0,0,0.32)]"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-[var(--line)] px-6 py-5">
          <div>
            <p className="text-label text-[var(--navy-muted)]">{label}</p>
            <h2
              id="batch-detail-modal-title"
              className="font-display mt-2 text-4xl leading-tight text-[var(--navy)]"
            >
              {title}
            </h2>
          </div>

          <button
            type="button"
            aria-label="Close dialog"
            title="Close"
            onClick={onClose}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-[var(--line)] text-[var(--navy)] transition hover:border-[var(--gold)] hover:bg-[var(--gold-soft)]"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="px-6 py-6">{children}</div>
      </div>
    </div>
  );
}

type InputCostsRegisterProps = {
  inputCosts: InputCost[];
};

function InputCostsRegister({ inputCosts }: InputCostsRegisterProps) {
  const [page, setPage] = useState(0);
  const pageCount = Math.max(
    1,
    Math.ceil(inputCosts.length / REGISTER_PAGE_SIZE)
  );
  const currentPage = Math.min(page, pageCount - 1);
  const rows = inputCosts.slice(
    currentPage * REGISTER_PAGE_SIZE,
    currentPage * REGISTER_PAGE_SIZE + REGISTER_PAGE_SIZE
  );

  if (inputCosts.length === 0) {
    return <EmptyMessage message="No input costs have been recorded yet." />;
  }

  return (
    <div className="grid gap-4">
      <RegisterTable>
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
          {rows.map((cost) => (
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
      </RegisterTable>

      <PaginationControls
        page={currentPage}
        pageCount={pageCount}
        totalCount={inputCosts.length}
        onPageChange={setPage}
      />
    </div>
  );
}

type SalesRegisterProps = {
  sales: PoultrySale[];
};

function SalesRegister({ sales }: SalesRegisterProps) {
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(sales.length / REGISTER_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const rows = sales.slice(
    currentPage * REGISTER_PAGE_SIZE,
    currentPage * REGISTER_PAGE_SIZE + REGISTER_PAGE_SIZE
  );

  if (sales.length === 0) {
    return <EmptyMessage message="No sales have been recorded yet." />;
  }

  return (
    <div className="grid gap-4">
      <RegisterTable>
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
          {rows.map((sale) => (
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
              <TableCell align="right">{formatCurrency(sale.balance)}</TableCell>
              <TableCell>
                <span className="inline-flex rounded-full bg-[var(--gold-soft)] px-3 py-1 text-[0.68rem] font-bold uppercase tracking-[0.16em] text-[var(--navy)]">
                  {formatLabel(sale.payment_status)}
                </span>
              </TableCell>
              <TableCell>{sale.sold_by_name}</TableCell>
            </tr>
          ))}
        </tbody>
      </RegisterTable>

      <PaginationControls
        page={currentPage}
        pageCount={pageCount}
        totalCount={sales.length}
        onPageChange={setPage}
      />
    </div>
  );
}

type RegisterTableProps = {
  children: ReactNode;
};

function RegisterTable({ children }: RegisterTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--line)]">
      <table className="min-w-full border-collapse">{children}</table>
    </div>
  );
}

type PaginationControlsProps = {
  page: number;
  pageCount: number;
  totalCount: number;
  onPageChange: (page: number) => void;
};

function PaginationControls({
  page,
  pageCount,
  totalCount,
  onPageChange,
}: PaginationControlsProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--navy-muted)]">
        Page {page + 1} of {pageCount} / {formatRecordCount(totalCount)}
      </p>

      <div className="flex gap-2">
        <button
          type="button"
          disabled={page === 0}
          onClick={() => onPageChange(Math.max(0, page - 1))}
          className="rounded-full border border-[var(--line)] px-4 py-2 text-xs font-bold uppercase tracking-[0.14em] text-[var(--navy)] transition hover:border-[var(--gold)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={page >= pageCount - 1}
          onClick={() => onPageChange(Math.min(pageCount - 1, page + 1))}
          className="rounded-full border border-[var(--line)] px-4 py-2 text-xs font-bold uppercase tracking-[0.14em] text-[var(--navy)] transition hover:border-[var(--gold)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          Next
        </button>
      </div>
    </div>
  );
}

type TableHeadProps = {
  label: string;
  align?: "left" | "right";
};

function TableHead({ label, align = "left" }: TableHeadProps) {
  const alignClass = align === "right" ? "text-right" : "text-left";

  return (
    <th
      className={`whitespace-nowrap px-5 py-4 ${alignClass} text-[0.68rem] font-bold uppercase tracking-[0.18em] text-[var(--navy-muted)]`}
    >
      {label}
    </th>
  );
}

type TableCellProps = {
  children: ReactNode;
  align?: "left" | "right";
};

function TableCell({ children, align = "left" }: TableCellProps) {
  const alignClass = align === "right" ? "text-right" : "text-left";

  return (
    <td
      className={`whitespace-nowrap px-5 py-4 ${alignClass} text-sm text-[var(--navy-soft)]`}
    >
      {children}
    </td>
  );
}

type EmptyMessageProps = {
  message: string;
};

function EmptyMessage({ message }: EmptyMessageProps) {
  return <p className="text-sm text-[var(--navy-muted)]">{message}</p>;
}
