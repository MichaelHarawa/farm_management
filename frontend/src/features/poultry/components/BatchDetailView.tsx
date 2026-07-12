"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { X } from "lucide-react";

import type { InputCost, PoultryBatch, PoultrySale } from "../types";
import {
  formatCurrency,
  formatLabel,
  formatNumber,
} from "../utils/formatters";
import { AddInputCostForm } from "./AddInputCostForm";
import { AddSaleForm } from "./AddSaleForm";

type BatchDetailViewProps = {
  batch: PoultryBatch;
  inputCosts: InputCost[];
  sales: PoultrySale[];
};

type ActiveTab = "overview" | "flock" | "costs" | "sales";
type ModalKind = "input-cost-form" | "sale-form" | null;

type BreakdownItem = {
  label: string;
  value: number;
  count: number;
};

type LatestRecord = {
  id: string;
  date: string;
  type: string;
  description: string;
  amount: number;
};

const tabs: Array<{
  id: ActiveTab;
  label: string;
  sidebarLabel: string;
}> = [
  { id: "overview", label: "Overview", sidebarLabel: "Overview" },
  { id: "flock", label: "Flock", sidebarLabel: "Flock activity" },
  { id: "costs", label: "Costs", sidebarLabel: "Input costs" },
  { id: "sales", label: "Sales", sidebarLabel: "Sales" },
];

const dayInMs = 24 * 60 * 60 * 1000;

function calculateInputCostTotal(cost: InputCost): number {
  const unitMultiplier = cost.unit ?? 1;

  return cost.quantity * unitMultiplier * cost.unit_cost;
}

function calculateSaleTotal(sale: PoultrySale): number {
  return sale.quantity_sold * sale.unit_price;
}

function formatDisplayDate(value: string | Date): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

function formatShortDate(value: string | Date): string {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
  }).format(new Date(value));
}

function formatPercent(value: number): string {
  return `${Math.round(value)}%`;
}

function formatDecimalPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

function getPercent(value: number, total: number): number {
  if (total <= 0) {
    return 0;
  }

  return Math.min(100, Math.max(0, (value / total) * 100));
}

function formatRecordCount(count: number): string {
  return `${formatNumber(count)} ${count === 1 ? "record" : "records"}`;
}

function formatSignedCurrency(value: number): string {
  if (value < 0) {
    return `- ${formatCurrency(Math.abs(value))}`;
  }

  return formatCurrency(value);
}

function addDays(value: string | Date, days: number): Date {
  const date = new Date(value);
  date.setDate(date.getDate() + days);

  return date;
}

function getDaysBetween(start: string | Date, end: string | Date): number {
  const startDate = new Date(start);
  const endDate = new Date(end);

  return Math.max(
    0,
    Math.floor((endDate.getTime() - startDate.getTime()) / dayInMs)
  );
}

function formatCostCategory(value: string): string {
  const normalized = value.trim().toLowerCase();

  if (["ops", "operation", "operations"].includes(normalized)) {
    return "Operations";
  }

  return formatLabel(value);
}

function getCostQuantity(cost: InputCost): string {
  const unit = cost.unit ? ` x ${formatNumber(cost.unit)}` : "";

  return `${formatNumber(cost.quantity)}${unit} ${cost.unit_measurement}`;
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
  const [activeTab, setActiveTab] = useState<ActiveTab>("overview");
  const [openModal, setOpenModal] = useState<ModalKind>(null);

  const metrics = useMemo(() => {
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
    const mortality = 0;
    const currentBirds = Math.max(
      batch.quantity - totalBirdsSold - mortality,
      0
    );
    const cycleLength = getDaysBetween(
      batch.entry_date,
      batch.expected_maturity_date
    );
    const dayOfCycle = getDaysBetween(batch.entry_date, new Date());

    return {
      totalInputCosts,
      totalSales,
      totalPaid,
      totalBalance,
      totalBirdsSold,
      mortality,
      currentBirds,
      grossProfit: totalSales - totalInputCosts,
      survivalPercent: getPercent(currentBirds, batch.quantity),
      soldPercent: getPercent(totalBirdsSold, batch.quantity),
      mortalityPercent: getPercent(mortality, batch.quantity),
      collectionPercent: getPercent(totalPaid, totalSales),
      costPerBird: batch.quantity > 0 ? totalInputCosts / batch.quantity : 0,
      dayOfCycle,
      cycleLength,
    };
  }, [batch, inputCosts, sales]);

  const costBreakdown = useMemo(
    () =>
      buildBreakdown(
        inputCosts,
        (cost) => formatCostCategory(cost.category),
        calculateInputCostTotal
      ),
    [inputCosts]
  );

  const latestRecords = useMemo<LatestRecord[]>(() => {
    const saleRecords = sales.map((sale) => ({
      id: `sale-${sale.id}`,
      date: sale.sale_date,
      type: "Sale",
      description: `${sale.sale_id} - ${formatLabel(sale.payment_status)}`,
      amount: calculateSaleTotal(sale),
    }));

    const costRecords = inputCosts.map((cost) => ({
      id: `cost-${cost.id}`,
      date: cost.created_at,
      type: "Cost",
      description: cost.item,
      amount: calculateInputCostTotal(cost),
    }));

    return [...saleRecords, ...costRecords].sort(
      (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()
    );
  }, [inputCosts, sales]);

  const vaccinationSchedule = useMemo(() => {
    const hichnerDate = addDays(batch.entry_date, 7);
    const gumboroDate = addDays(batch.entry_date, 14);
    const lasotaDate = addDays(batch.entry_date, 21);

    return [
      {
        title: "Hitchner",
        date: hichnerDate,
        status: metrics.dayOfCycle >= 7 ? "Completed" : "Scheduled",
      },
      {
        title: "Gumboro",
        date: gumboroDate,
        status: metrics.dayOfCycle >= 14 ? "Completed" : "Upcoming",
      },
      {
        title: "Lasota",
        date: lasotaDate,
        status: metrics.dayOfCycle >= 21 ? "Completed" : "Scheduled",
      },
    ];
  }, [batch.entry_date, metrics.dayOfCycle]);

  const nextCare =
    vaccinationSchedule.find((item) => item.status !== "Completed") ??
    vaccinationSchedule[vaccinationSchedule.length - 1];
  const largestCategory = costBreakdown[0];
  const followUpSale = sales.find((sale) => sale.balance > 0);

  const pageHeader = getPageHeader(activeTab, batch);

  return (
    <main className="min-h-screen bg-[#f6f3eb] text-[#151926] lg:grid lg:grid-cols-[260px_1fr]">
      <DetailSidebar
        activeTab={activeTab}
        batch={batch}
        onTabChange={setActiveTab}
      />

      <section className="min-w-0 px-5 py-8 sm:px-8 lg:px-12">
        <div className="mx-auto max-w-[1320px]">
          <PageHeader
            title={pageHeader.title}
            description={pageHeader.description}
            activeTab={activeTab}
            actionLabel={pageHeader.actionLabel}
            onAction={() => {
              if (activeTab === "costs") {
                setOpenModal("input-cost-form");
                return;
              }

              if (activeTab === "sales") {
                setOpenModal("sale-form");
              }
            }}
            onTabChange={setActiveTab}
          />

          {activeTab === "overview" ? (
            <OverviewTab
              batch={batch}
              metrics={metrics}
              latestRecords={latestRecords}
              nextCare={nextCare}
              onAddCost={() => setOpenModal("input-cost-form")}
              onAddSale={() => setOpenModal("sale-form")}
            />
          ) : null}

          {activeTab === "flock" ? (
            <FlockTab
              batch={batch}
              metrics={metrics}
              sales={sales}
              vaccinationSchedule={vaccinationSchedule}
            />
          ) : null}

          {activeTab === "costs" ? (
            <CostsTab
              batch={batch}
              inputCosts={inputCosts}
              metrics={metrics}
              costBreakdown={costBreakdown}
              largestCategory={largestCategory}
            />
          ) : null}

          {activeTab === "sales" ? (
            <SalesTab
              sales={sales}
              metrics={metrics}
              followUpSale={followUpSale}
              onAddSale={() => setOpenModal("sale-form")}
            />
          ) : null}
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
        isOpen={openModal === "sale-form"}
        label="New sale"
        title="Record sale"
        onClose={() => setOpenModal(null)}
      >
        <AddSaleForm batchId={batch.id} />
      </DetailModal>
    </main>
  );
}

function getPageHeader(activeTab: ActiveTab, batch: PoultryBatch) {
  if (activeTab === "flock") {
    return {
      title: "Flock activity",
      description: "Track bird movement, mortality, and scheduled care.",
      actionLabel: "Record activity",
    };
  }

  if (activeTab === "costs") {
    return {
      title: "Input costs",
      description: "Review spending for this batch without sales or flock indicators.",
      actionLabel: "Add input cost",
    };
  }

  if (activeTab === "sales") {
    return {
      title: "Sales & collections",
      description: "Track revenue and outstanding balances for this batch.",
      actionLabel: "Record sale",
    };
  }

  return {
    title: `${formatLabel(batch.bird_type)} batch`,
    description: "A calm operational summary for the current production cycle.",
    actionLabel: "More actions",
  };
}

type Metrics = {
  totalInputCosts: number;
  totalSales: number;
  totalPaid: number;
  totalBalance: number;
  totalBirdsSold: number;
  mortality: number;
  currentBirds: number;
  grossProfit: number;
  survivalPercent: number;
  soldPercent: number;
  mortalityPercent: number;
  collectionPercent: number;
  costPerBird: number;
  dayOfCycle: number;
  cycleLength: number;
};

type DetailSidebarProps = {
  activeTab: ActiveTab;
  batch: PoultryBatch;
  onTabChange: (tab: ActiveTab) => void;
};

function DetailSidebar({ activeTab, batch, onTabChange }: DetailSidebarProps) {
  return (
    <aside className="bg-[#151f36] px-6 py-8 text-white lg:sticky lg:top-0 lg:flex lg:h-screen lg:flex-col">
      <Link href="/" className="flex items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-full bg-[#e1aa3f] text-base font-bold text-[#151f36]">
          F
        </span>
        <span className="text-base font-extrabold tracking-wide">FARMNOTES</span>
      </Link>

      <div className="mt-10">
        <p className="text-xs font-bold uppercase tracking-wide text-white/60">
          Poultry
        </p>

        <nav className="mt-3 grid gap-5 lg:gap-6">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id;

            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => onTabChange(tab.id)}
                className={`rounded-lg px-4 py-3 text-left text-base font-bold transition ${
                  isActive
                    ? "bg-[#fff4c6] text-[#151926]"
                    : "text-white hover:bg-white/10"
                }`}
              >
                {tab.sidebarLabel}
              </button>
            );
          })}
        </nav>
      </div>

      <div className="mt-10 border-t border-white/70 pt-5 lg:mt-auto">
        <p className="text-xs font-bold text-white/60">Batch</p>
        <p className="mt-3 text-sm font-bold text-white">{batch.batch_id}</p>
        <p className="mt-3 text-sm text-white/70">
          {formatLabel(batch.bird_type)} - Active
        </p>
      </div>
    </aside>
  );
}

type PageHeaderProps = {
  title: string;
  description: string;
  activeTab: ActiveTab;
  actionLabel: string;
  onAction: () => void;
  onTabChange: (tab: ActiveTab) => void;
};

function PageHeader({
  title,
  description,
  activeTab,
  actionLabel,
  onAction,
  onTabChange,
}: PageHeaderProps) {
  return (
    <header>
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <Link
            href="/poultry"
            className="text-sm font-bold uppercase tracking-wide text-[#747b8d] transition hover:text-[#151f36]"
          >
            &larr; Batch register
          </Link>

          <h1 className="mt-4 text-4xl font-extrabold tracking-[-0.02em] text-[#151926]">
            {title}
          </h1>
          <p className="mt-2 text-base leading-7 text-[#747b8d]">{description}</p>
        </div>

        <button
          type="button"
          onClick={onAction}
          className="h-14 rounded-xl bg-[#151f36] px-8 text-base font-bold text-white transition hover:bg-[#22345f]"
        >
          {actionLabel}
        </button>
      </div>

      <nav className="mt-7 flex flex-wrap gap-5">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;

          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabChange(tab.id)}
              className={`rounded-lg px-6 py-3 text-base font-bold transition ${
                isActive
                  ? "bg-[#151f36] text-white"
                  : "text-[#747b8d] hover:bg-white"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </nav>
    </header>
  );
}

type OverviewTabProps = {
  batch: PoultryBatch;
  metrics: Metrics;
  latestRecords: LatestRecord[];
  nextCare: {
    title: string;
    date: Date;
    status: string;
  };
  onAddCost: () => void;
  onAddSale: () => void;
};

function OverviewTab({
  batch,
  metrics,
  latestRecords,
  nextCare,
  onAddCost,
  onAddSale,
}: OverviewTabProps) {
  return (
    <div className="mt-8 grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-full bg-[#e6f5e9] px-4 py-2 text-sm font-bold uppercase text-[#4e8b61]">
          Active
        </span>
        <span className="text-sm font-bold text-[#747b8d]">
          Day {metrics.dayOfCycle} of {metrics.cycleLength} - Matures{" "}
          {formatDisplayDate(batch.expected_maturity_date)}
        </span>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_0.55fr]">
        <Card className="p-6">
          <SectionLabel>Batch Information</SectionLabel>
          <h2 className="mt-6 text-3xl font-extrabold">Production cycle</h2>

          <div className="mt-7 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
            <InfoItem label="Batch ID" value={batch.batch_id} />
            <InfoItem label="Bird Type" value={formatLabel(batch.bird_type)} />
            <InfoItem
              label="Entry Date"
              value={formatDisplayDate(batch.entry_date)}
            />
            <InfoItem label="Source" value={batch.source || "Central Poultry"} />
            <InfoItem
              label="Initial Birds"
              value={formatNumber(batch.quantity)}
            />
            <InfoItem
              label="Current Birds"
              value={formatNumber(metrics.currentBirds)}
            />
            <InfoItem label="Sold" value={formatNumber(metrics.totalBirdsSold)} />
            <InfoItem
              label="Maturity"
              value={formatDisplayDate(batch.expected_maturity_date)}
            />
          </div>
        </Card>

        <Card className="p-6">
          <SectionLabel>Quick Actions</SectionLabel>
          <h2 className="mt-6 text-3xl font-extrabold">Record new activity</h2>

          <div className="mt-6 grid gap-4">
            <button
              type="button"
              className="h-14 rounded-lg bg-[#151f36] px-5 text-base font-bold text-white"
            >
              Record flock activity
            </button>
            <div className="grid gap-4 sm:grid-cols-2">
              <button
                type="button"
                onClick={onAddCost}
                className="h-14 rounded-lg border border-[#ddd7c9] bg-white px-5 text-base font-bold"
              >
                Add cost
              </button>
              <button
                type="button"
                onClick={onAddSale}
                className="h-14 rounded-lg bg-[#e1aa3f] px-5 text-base font-bold"
              >
                Record sale
              </button>
            </div>
          </div>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <KpiCard
          label="Birds Remaining"
          value={formatNumber(metrics.currentBirds)}
          detail={`${formatPercent(metrics.survivalPercent)} of initial flock`}
        />
        <KpiCard
          label="Total Input Cost"
          value={formatCurrency(metrics.totalInputCosts)}
          detail={`${formatCurrency(metrics.costPerBird)} per initial bird`}
        />
        <KpiCard
          label="Net Position"
          value={formatSignedCurrency(metrics.grossProfit)}
          detail="Sales less recorded input costs"
          tone={metrics.grossProfit < 0 ? "danger" : "default"}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_0.5fr]">
        <Card>
          <div className="p-6">
            <SectionLabel>Activity</SectionLabel>
            <h2 className="mt-3 text-3xl font-extrabold">Latest records</h2>
          </div>
          <SimpleTable
            columns={["Date", "Type", "Description", "Amount"]}
            rows={latestRecords.slice(0, 4).map((record) => [
              formatDisplayDate(record.date),
              record.type,
              record.description,
              formatCurrency(record.amount),
            ])}
            emptyMessage="No activity has been recorded for this batch."
          />
        </Card>

        <Card className="p-6">
          <SectionLabel>Next Up</SectionLabel>
          <h2 className="mt-6 text-3xl font-extrabold">Upcoming care</h2>
          <span className="mt-6 inline-flex rounded-full bg-[#fff4c6] px-5 py-3 text-sm font-extrabold uppercase">
            Due in {getDaysBetween(new Date(), nextCare.date)} days
          </span>
          <h3 className="mt-6 text-xl font-extrabold">
            {nextCare.title} vaccination
          </h3>
          <p className="mt-3 text-sm leading-6 text-[#747b8d]">
            Scheduled for {formatDisplayDate(nextCare.date)}
          </p>
          <div className="mt-6 border-t border-[#ddd7c9] pt-5">
            <p className="text-sm font-bold text-[#747b8d]">Batch note</p>
            <p className="mt-4 text-base leading-7">
              No mortality has been recorded for this batch.
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}

type FlockTabProps = {
  batch: PoultryBatch;
  metrics: Metrics;
  sales: PoultrySale[];
  vaccinationSchedule: Array<{
    title: string;
    date: Date;
    status: string;
  }>;
};

function FlockTab({
  batch,
  metrics,
  sales,
  vaccinationSchedule,
}: FlockTabProps) {
  const activityRows = [
    ...sales.map((sale) => [
      formatDisplayDate(sale.sale_date),
      "Birds sold",
      formatNumber(sale.quantity_sold),
      sale.sold_by_name || "Farmnotes",
    ]),
    [
      formatDisplayDate(batch.entry_date),
      "Batch placement",
      formatNumber(batch.quantity),
      "Farmnotes",
    ],
  ];

  return (
    <div className="mt-8 grid gap-8">
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Initial Birds"
          value={formatNumber(batch.quantity)}
          detail={`Placed on ${formatDisplayDate(batch.entry_date)}`}
        />
        <KpiCard
          label="Current Birds"
          value={formatNumber(metrics.currentBirds)}
          detail={`${formatPercent(metrics.survivalPercent)} survival / availability`}
        />
        <KpiCard
          label="Birds Sold"
          value={formatNumber(metrics.totalBirdsSold)}
          detail={`${formatPercent(metrics.soldPercent)} of initial flock`}
        />
        <KpiCard
          label="Mortality"
          value={formatNumber(metrics.mortality)}
          detail={`${formatDecimalPercent(metrics.mortalityPercent)} mortality rate`}
        />
      </div>

      <Card className="p-6">
        <SectionLabel>Reconciliation</SectionLabel>
        <h2 className="mt-6 text-3xl font-extrabold">
          Where the {formatNumber(batch.quantity)} birds are now
        </h2>
        <p className="mt-5 text-base leading-7 text-[#747b8d]">
          Every bird should be accounted for across remaining, sold, and
          mortality.
        </p>
        <StackedBar
          segments={[
            {
              label: `${formatNumber(metrics.currentBirds)} remaining`,
              value: metrics.currentBirds,
              color: "#4e8b61",
            },
            {
              label: `${formatNumber(metrics.totalBirdsSold)} sold`,
              value: metrics.totalBirdsSold,
              color: "#e1aa3f",
            },
            {
              label: `${formatNumber(metrics.mortality)} mortality`,
              value: metrics.mortality,
              color: "#747b8d",
            },
          ]}
          total={batch.quantity}
        />
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1fr_0.47fr]">
        <Card>
          <div className="p-6">
            <SectionLabel>Register</SectionLabel>
            <h2 className="mt-3 text-3xl font-extrabold">Flock activity log</h2>
            <p className="mt-2 text-base text-[#747b8d]">
              Movement and health records only.
            </p>
          </div>
          <SimpleTable
            columns={["Date", "Activity", "Quantity", "Recorded By"]}
            rows={activityRows}
            emptyMessage="No flock activity has been recorded."
          />
        </Card>

        <Card className="p-6">
          <SectionLabel>Care Plan</SectionLabel>
          <h2 className="mt-6 text-3xl font-extrabold">Vaccination schedule</h2>
          <div className="mt-8 grid gap-5">
            {vaccinationSchedule.map((item) => (
              <ScheduleItem key={item.title} item={item} />
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

type CostsTabProps = {
  batch: PoultryBatch;
  inputCosts: InputCost[];
  metrics: Metrics;
  costBreakdown: BreakdownItem[];
  largestCategory?: BreakdownItem;
};

function CostsTab({
  batch,
  inputCosts,
  metrics,
  costBreakdown,
  largestCategory,
}: CostsTabProps) {
  return (
    <div className="mt-8 grid gap-8">
      <div className="grid gap-6 lg:grid-cols-3">
        <KpiCard
          label="Total Input Costs"
          value={formatCurrency(metrics.totalInputCosts)}
          detail={formatRecordCount(inputCosts.length)}
        />
        <KpiCard
          label="Cost Per Initial Bird"
          value={formatCurrency(metrics.costPerBird)}
          detail={`Based on ${formatNumber(batch.quantity)} birds`}
        />
        <KpiCard
          label="Largest Category"
          value={largestCategory?.label ?? "None"}
          detail={
            largestCategory
              ? `${formatDecimalPercent(
                  getPercent(largestCategory.value, metrics.totalInputCosts)
                )} of recorded spend`
              : "No recorded spend"
          }
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_0.6fr]">
        <Card className="p-6">
          <SectionLabel>Breakdown</SectionLabel>
          <h2 className="mt-6 text-3xl font-extrabold">Spend by category</h2>
          <div className="mt-6 grid gap-8">
            {costBreakdown.length > 0 ? (
              costBreakdown.map((item) => (
                <CategoryBar
                  key={item.label}
                  item={item}
                  total={metrics.totalInputCosts}
                />
              ))
            ) : (
              <p className="text-base text-[#747b8d]">
                No input costs have been recorded.
              </p>
            )}
          </div>
        </Card>

        <section className="rounded-xl bg-[#151f36] p-7 text-white">
          <SectionLabel className="text-[#e1aa3f]">Cost Control</SectionLabel>
          <h2 className="mt-6 text-3xl font-extrabold leading-tight">
            {largestCategory
              ? `${largestCategory.label} drives most recorded cost.`
              : "No recorded input spend yet."}
          </h2>
          <p className="mt-5 text-base leading-7 text-white/70">
            Review ingredient-level feed costs before adding more purchases.
          </p>
          <button
            type="button"
            className="mt-5 rounded-lg bg-[#e1aa3f] px-8 py-4 text-base font-bold text-[#151926]"
          >
            Review feed details
          </button>
        </section>
      </div>

      <Card>
        <RegisterHeader title="Input cost records" />
        <SimpleTable
          columns={["Date", "Cost Item", "Category", "Quantity", "Total"]}
          rows={inputCosts.map((cost) => [
            formatDisplayDate(cost.created_at),
            cost.item,
            formatCostCategory(cost.category),
            getCostQuantity(cost),
            formatCurrency(calculateInputCostTotal(cost)),
          ])}
          emptyMessage="No input costs have been recorded."
        />
      </Card>
    </div>
  );
}

type SalesTabProps = {
  sales: PoultrySale[];
  metrics: Metrics;
  followUpSale?: PoultrySale;
  onAddSale: () => void;
};

function SalesTab({ sales, metrics, followUpSale, onAddSale }: SalesTabProps) {
  return (
    <div className="mt-8 grid gap-8">
      <div className="grid gap-6 lg:grid-cols-3">
        <KpiCard
          label="Total Sales Value"
          value={formatCurrency(metrics.totalSales)}
          detail={`${formatNumber(metrics.totalBirdsSold)} birds sold`}
        />
        <KpiCard
          label="Cash Collected"
          value={formatCurrency(metrics.totalPaid)}
          detail={`${formatPercent(metrics.collectionPercent)} collection rate`}
        />
        <KpiCard
          label="Outstanding"
          value={formatCurrency(metrics.totalBalance)}
          detail={`${sales.filter((sale) => sale.balance > 0).length} partial-payment sale`}
          tone={metrics.totalBalance > 0 ? "danger" : "default"}
        />
      </div>

      <Card className="p-6">
        <SectionLabel>Collections</SectionLabel>
        <h2 className="mt-6 text-3xl font-extrabold">Payment status</h2>
        <p className="mt-5 text-base leading-7 text-[#747b8d]">
          A single view of paid and outstanding sales value.
        </p>
        <StackedBar
          segments={[
            {
              label: `Collected ${formatCurrency(metrics.totalPaid)}`,
              value: metrics.totalPaid,
              color: "#4e8b61",
            },
            {
              label: `Outstanding ${formatCurrency(metrics.totalBalance)}`,
              value: metrics.totalBalance,
              color: "#e1aa3f",
            },
          ]}
          total={metrics.totalSales}
        />
      </Card>

      <Card>
        <RegisterHeader title="Sales transactions" />
        <SimpleTable
          columns={["Sale ID", "Date", "Qty", "Status", "Amount"]}
          rows={sales.map((sale) => [
            sale.sale_id,
            formatDisplayDate(sale.sale_date),
            formatNumber(sale.quantity_sold),
            formatLabel(sale.payment_status),
            formatCurrency(calculateSaleTotal(sale)),
          ])}
          emptyMessage="No sales have been recorded."
        />

        {followUpSale ? (
          <div className="mx-0 mb-8 ml-0 mr-10 flex flex-col gap-4 rounded-lg bg-[#fff4c6] px-5 py-4 sm:mx-0 sm:flex-row sm:items-center sm:justify-between">
            <p className="font-bold">
              Follow up: {formatCurrency(followUpSale.balance)} remains due on{" "}
              {followUpSale.sale_id}.
            </p>
            <button
              type="button"
              onClick={onAddSale}
              className="rounded-lg bg-[#151f36] px-8 py-4 text-base font-bold text-white"
            >
              Record payment
            </button>
          </div>
        ) : null}
      </Card>
    </div>
  );
}

type KpiCardProps = {
  label: string;
  value: string;
  detail: string;
  tone?: "default" | "danger";
};

function KpiCard({ label, value, detail, tone = "default" }: KpiCardProps) {
  return (
    <Card className="p-6">
      <p className="text-sm font-extrabold uppercase text-[#747b8d]">{label}</p>
      <p
        className={`mt-3 text-4xl font-extrabold tracking-[-0.02em] ${
          tone === "danger" ? "text-[#b24a43]" : "text-[#151926]"
        }`}
      >
        {value}
      </p>
      <p className="mt-3 text-base leading-6 text-[#747b8d]">{detail}</p>
    </Card>
  );
}

type InfoItemProps = {
  label: string;
  value: string;
};

function InfoItem({ label, value }: InfoItemProps) {
  return (
    <div>
      <p className="text-xs font-extrabold uppercase text-[#747b8d]">{label}</p>
      <p className="mt-2 text-base font-extrabold text-[#151926]">{value}</p>
    </div>
  );
}

type CardProps = {
  children: ReactNode;
  className?: string;
};

function Card({ children, className = "" }: CardProps) {
  return (
    <section className={`rounded-xl border border-[#ddd7c9] bg-[#fffdf8] ${className}`}>
      {children}
    </section>
  );
}

type SectionLabelProps = {
  children: ReactNode;
  className?: string;
};

function SectionLabel({ children, className = "" }: SectionLabelProps) {
  return (
    <p className={`text-sm font-extrabold uppercase text-[#e1aa3f] ${className}`}>
      {children}
    </p>
  );
}

type SimpleTableProps = {
  columns: string[];
  rows: string[][];
  emptyMessage: string;
};

function SimpleTable({ columns, rows, emptyMessage }: SimpleTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse">
        <thead>
          <tr className="bg-[#ece9dd]">
            {columns.map((column) => (
              <th
                key={column}
                className="px-5 py-4 text-left text-xs font-extrabold uppercase text-[#747b8d]"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-5 py-8 text-base text-[#747b8d]"
              >
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row, rowIndex) => (
              <tr key={`${row[0]}-${rowIndex}`} className="border-b border-[#ddd7c9]">
                {row.map((cell, cellIndex) => (
                  <td
                    key={`${cell}-${cellIndex}`}
                    className={`px-5 py-5 text-base ${
                      cellIndex === 0 ? "font-extrabold text-[#151926]" : "text-[#747b8d]"
                    }`}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

type RegisterHeaderProps = {
  title: string;
};

function RegisterHeader({ title }: RegisterHeaderProps) {
  return (
    <div className="flex flex-col gap-4 p-6 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <SectionLabel>Register</SectionLabel>
        <h2 className="mt-3 text-3xl font-extrabold">{title}</h2>
      </div>
      <div className="flex gap-3">
        <button
          type="button"
          className="rounded-lg border border-[#ddd7c9] bg-white px-8 py-4 text-base font-bold"
        >
          Filter
        </button>
        <button
          type="button"
          className="rounded-lg border border-[#ddd7c9] bg-white px-8 py-4 text-base font-bold"
        >
          Export
        </button>
      </div>
    </div>
  );
}

type StackedBarProps = {
  segments: Array<{
    label: string;
    value: number;
    color: string;
  }>;
  total: number;
};

function StackedBar({ segments, total }: StackedBarProps) {
  return (
    <div className="mt-6">
      <div className="flex h-7 overflow-hidden rounded-full bg-[#e7e4d9]">
        {segments.map((segment) => (
          <div
            key={segment.label}
            className="h-full"
            style={{
              width: `${getPercent(segment.value, total)}%`,
              backgroundColor: segment.color,
            }}
          />
        ))}
      </div>
      <div className="mt-4 flex flex-wrap gap-x-8 gap-y-3">
        {segments.map((segment) => (
          <div key={segment.label} className="flex items-center gap-2">
            <span
              className="h-3 w-3 rounded-full"
              style={{ backgroundColor: segment.color }}
            />
            <span className="text-sm font-extrabold text-[#151926]">
              {segment.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

type CategoryBarProps = {
  item: BreakdownItem;
  total: number;
};

function CategoryBar({ item, total }: CategoryBarProps) {
  return (
    <div>
      <div className="flex items-center justify-between gap-5">
        <p className="text-base font-extrabold">{item.label}</p>
        <p className="text-base font-extrabold">{formatCurrency(item.value)}</p>
      </div>
      <div className="mt-3 h-3 overflow-hidden rounded-full bg-[#e7e4d9]">
        <div
          className="h-full rounded-full bg-[#e1aa3f]"
          style={{ width: `${getPercent(item.value, total)}%` }}
        />
      </div>
    </div>
  );
}

type ScheduleItemProps = {
  item: {
    title: string;
    date: Date;
    status: string;
  };
};

function ScheduleItem({ item }: ScheduleItemProps) {
  const isUpcoming = item.status === "Upcoming";

  return (
    <div
      className={`grid grid-cols-[70px_1fr] gap-4 rounded-lg p-4 ${
        isUpcoming ? "bg-[#fff4c6]" : ""
      }`}
    >
      <div>
        <p className="font-extrabold">{formatShortDate(item.date)}</p>
        <p className="text-sm text-[#747b8d]">{item.date.getFullYear()}</p>
      </div>
      <div>
        <p className="font-extrabold">{item.title}</p>
        <p
          className={`mt-1 text-sm font-bold ${
            item.status === "Completed" ? "text-[#4e8b61]" : "text-[#747b8d]"
          }`}
        >
          {item.status}
        </p>
      </div>
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
      className="fixed inset-0 z-50 overflow-y-auto bg-[rgba(21,31,54,0.72)] px-4 py-6 backdrop-blur-sm"
      role="presentation"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="batch-detail-modal-title"
        className="mx-auto w-full max-w-5xl rounded-xl border border-[#ddd7c9] bg-[#fffdf8] shadow-[0_24px_80px_rgba(0,0,0,0.32)]"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-[#ddd7c9] px-6 py-5">
          <div>
            <SectionLabel>{label}</SectionLabel>
            <h2
              id="batch-detail-modal-title"
              className="mt-2 text-3xl font-extrabold text-[#151926]"
            >
              {title}
            </h2>
          </div>

          <button
            type="button"
            aria-label="Close dialog"
            title="Close"
            onClick={onClose}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full border border-[#ddd7c9] text-[#151926] transition hover:bg-[#fff4c6]"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="px-6 py-6">{children}</div>
      </div>
    </div>
  );
}
