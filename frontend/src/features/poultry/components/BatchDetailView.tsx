"use client";

import Link from "next/link";
import { createPortal } from "react-dom";
import { useMemo, useState, type ReactNode } from "react";
import { X } from "lucide-react";

import type {
  InputCost,
  PoultryBatch,
  PoultryFeedUsage,
  PoultryMortality,
  PoultrySale,
  PoultryVaccination,
} from "../types";
import {
  formatCurrency,
  formatLabel,
  formatNumber,
} from "../utils/formatters";
import { AddInputCostForm } from "./AddInputCostForm";
import { AddSaleForm } from "./AddSaleForm";
import { AddMortalityForm } from "./AddMortalityForm";
import { AddFeedUsageForm } from "./AddFeedUsageForm";
import { AddVaccinationForm } from "./AddVaccinationForm";

type BatchDetailViewProps = {
  batch: PoultryBatch;
  inputCosts: InputCost[];
  feedInputCosts: InputCost[];
  sales: PoultrySale[];
  mortalities: PoultryMortality[];
  feedUsages: PoultryFeedUsage[];
  vaccinations: PoultryVaccination[];
};

type ActiveTab =
  | "overview"
  | "flock"
  | "costs"
  | "sales"
  | "mortality"
  | "feed"
  | "vaccination";
type ModalKind =
  | "input-cost-form"
  | "sale-form"
  | "mortality-form"
  | "feed-usage-form"
  | "vaccination-form"
  | null;

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
  value: string;
};

type VaccinationScheduleItem = {
  title: string;
  type: string;
  date: Date;
  status: string;
  record?: PoultryVaccination;
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
  { id: "mortality", label: "Mortality", sidebarLabel: "Mortality" },
  { id: "feed", label: "Feed", sidebarLabel: "Feed usage" },
  {
    id: "vaccination",
    label: "Vaccination & Drugs",
    sidebarLabel: "Vaccination & Drugs",
  },
];

const dayInMs = 24 * 60 * 60 * 1000;

function calculateInputCostTotal(cost: InputCost): number {
  const unitMultiplier = cost.unit ?? 1;

  return cost.quantity * unitMultiplier * cost.unit_cost;
}

function calculateSaleTotal(sale: PoultrySale): number {
  return sale.quantity_sold * sale.unit_price;
}

function calculateMortalityTotal(records: PoultryMortality[]): number {
  return records.reduce((total, record) => total + record.quantity_dead, 0);
}

function getFeedQuantityInKg(feedUsage: PoultryFeedUsage): number {
  if (feedUsage.unit_of_measurement === "g") {
    return feedUsage.quantity_given / 1000;
  }

  return feedUsage.quantity_given;
}

function formatFeedQuantity(feedUsage: PoultryFeedUsage): string {
  return `${formatNumber(feedUsage.quantity_given)} ${feedUsage.unit_of_measurement}`;
}

function formatFeedType(value: string): string {
  if (value === "pre_starter") {
    return "Pre-Starter";
  }

  return formatLabel(value);
}

function formatFeedSource(value: string): string {
  const labels: Record<string, string> = {
    cp_feed: "CP Feed",
    proto_feed: "Proto Feed",
    concentrates_feed: "Concentrates Feed",
    self_made: "Self Made",
  };

  return labels[value] ?? formatLabel(value);
}

function formatDrugVaccinationType(value: string): string {
  const labels: Record<string, string> = {
    gumbolo: "Gumbolo",
    hitchner: "Hitchner",
    lasota: "Lasota",
    other: "Other",
  };

  return labels[value] ?? formatLabel(value);
}

function getVaccinationName(vaccination: PoultryVaccination): string {
  if (vaccination.drug_vaccination_type === "other") {
    return vaccination.other_drug_vaccination || "Other";
  }

  return formatDrugVaccinationType(vaccination.drug_vaccination_type);
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

function getSignedDaysBetween(start: string | Date, end: string | Date): number {
  const startDate = new Date(start);
  const endDate = new Date(end);

  return Math.floor((endDate.getTime() - startDate.getTime()) / dayInMs);
}

function formatCostCategory(value: string): string {
  const normalized = value.trim().toLowerCase();

  if (normalized.includes("feed")) {
    return "Feed";
  }

  if (normalized.includes("transport")) {
    return "Transport";
  }

  if (normalized.includes("drug") || normalized.includes("medicine")) {
    return "Drug";
  }

  if (normalized.includes("water")) {
    return "Water";
  }

  if (
    normalized.includes("temperature") ||
    normalized.includes("heat") ||
    normalized.includes("charcoal")
  ) {
    return "Temperature Control";
  }

  if (normalized.includes("biosecurity") || normalized.includes("disinfect")) {
    return "Biosecurity";
  }

  if (normalized.includes("chick")) {
    return "Chick Care";
  }

  if (normalized.includes("vaccin") || normalized.includes("hitchner")) {
    return "Vaccination";
  }

  if (["ops", "operation", "operations"].includes(normalized)) {
    return "Operations";
  }

  return formatLabel(value);
}

function formatBatchSource(batch: PoultryBatch): string {
  if (batch.source === "other") {
    return batch.source_other?.trim() || "Other";
  }

  if (batch.source === "central_poultry") {
    return "Central Poultry";
  }

  if (batch.source === "proto") {
    return "Proto";
  }

  return formatLabel(batch.source);
}

function getCostQuantity(cost: InputCost): string {
  const unit = cost.unit ? ` x ${formatNumber(cost.unit)}` : "";

  return `${formatNumber(cost.quantity)}${unit} ${cost.unit_measurement}`;
}

function formatDrugCategory(value: string): string {
  return formatLabel(value);
}

function costDetail(cost: InputCost): TableRowDetail {
  return {
    title: cost.item,
    subtitle: `Recorded on ${formatDisplayDate(cost.purchase_date)}`,
    fields: [
      { label: "Category", value: formatCostCategory(cost.category) },
      { label: "Original Category", value: cost.category },
      { label: "Quantity", value: getCostQuantity(cost) },
      { label: "Unit Cost", value: formatCurrency(cost.unit_cost) },
      { label: "Total", value: formatCurrency(calculateInputCostTotal(cost)) },
      { label: "Notes", value: cost.notes },
    ],
  };
}

function saleDetail(sale: PoultrySale): TableRowDetail {
  return {
    title: sale.sale_id,
    subtitle: `Sale recorded on ${formatDisplayDate(sale.sale_date)}`,
    fields: [
      { label: "Product", value: formatLabel(sale.product_type) },
      { label: "Quantity", value: formatNumber(sale.quantity_sold) },
      { label: "Unit Price", value: formatCurrency(sale.unit_price) },
      { label: "Total", value: formatCurrency(calculateSaleTotal(sale)) },
      { label: "Amount Paid", value: formatCurrency(sale.amount_paid) },
      { label: "Balance", value: formatCurrency(sale.balance) },
      { label: "Buyer", value: sale.buyer_name },
      { label: "Buyer Type", value: formatLabel(sale.buyer_type) },
      { label: "Payment Status", value: formatLabel(sale.payment_status) },
      { label: "Payment Method", value: formatLabel(sale.payment_method) },
      { label: "Sold By", value: sale.sold_by_name },
      { label: "Notes", value: sale.notes },
    ],
  };
}

function mortalityDetail(mortality: PoultryMortality): TableRowDetail {
  return {
    title: mortality.suspected_cause,
    subtitle: `Mortality recorded on ${formatDisplayDate(mortality.mortality_date)}`,
    fields: [
      { label: "Quantity Dead", value: formatNumber(mortality.quantity_dead) },
      { label: "Age", value: `${formatNumber(mortality.age_in_days)} days` },
      { label: "Reported By", value: mortality.reported_by_name },
      { label: "Description", value: mortality.description },
      { label: "Action Taken", value: mortality.action_taken },
    ],
  };
}

function feedUsageDetail(feedUsage: PoultryFeedUsage): TableRowDetail {
  return {
    title: formatFeedType(feedUsage.feed_type),
    subtitle: `${formatDisplayDate(feedUsage.feeding_start_date)} to ${formatDisplayDate(feedUsage.feeding_end_date)}`,
    fields: [
      { label: "Feed Source", value: formatFeedSource(feedUsage.feed_source) },
      { label: "Quantity", value: formatFeedQuantity(feedUsage) },
      { label: "Initial Age", value: `${formatNumber(feedUsage.initial_age)} days` },
      { label: "Birds Fed", value: formatNumber(feedUsage.current_number_of_birds) },
      { label: "Reported By", value: feedUsage.reported_by_name },
      { label: "Notes", value: feedUsage.notes },
    ],
  };
}

function vaccinationDetail(vaccination: PoultryVaccination): TableRowDetail {
  return {
    title: getVaccinationName(vaccination),
    subtitle: `Administered on ${formatDisplayDate(vaccination.vaccination_date)}`,
    fields: [
      { label: "Category", value: formatDrugCategory(vaccination.drug_category) },
      { label: "Type", value: formatDrugVaccinationType(vaccination.drug_vaccination_type) },
      { label: "Quantity", value: formatNumber(vaccination.quantity) },
      { label: "Timely Status", value: vaccination.timely_status },
      { label: "Reported By", value: vaccination.reported_by_name },
      { label: "Description", value: vaccination.description },
    ],
  };
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
  feedInputCosts,
  sales,
  mortalities,
  feedUsages,
  vaccinations,
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
    const mortality = calculateMortalityTotal(mortalities);
    const currentBirds = Math.max(
      batch.quantity - totalBirdsSold - mortality,
      0
    );
    const totalFeedKg = feedUsages.reduce(
      (total, feedUsage) => total + getFeedQuantityInKg(feedUsage),
      0
    );
    const feedPerLiveBird =
      currentBirds > 0 ? totalFeedKg / currentBirds : 0;
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
      totalFeedKg,
      feedPerLiveBird,
      dayOfCycle,
      cycleLength,
    };
  }, [batch, inputCosts, sales, mortalities, feedUsages]);

  const costBreakdown = useMemo(
    () =>
      buildBreakdown(
        inputCosts,
        (cost) => formatCostCategory(cost.category),
        calculateInputCostTotal
      ),
    [inputCosts]
  );

  const feedTypeBreakdown = useMemo(
    () =>
      buildBreakdown(
        feedUsages,
        (feedUsage) => formatFeedType(feedUsage.feed_type),
        getFeedQuantityInKg
      ),
    [feedUsages]
  );

  const feedSourceBreakdown = useMemo(
    () =>
      buildBreakdown(
        feedUsages,
        (feedUsage) => formatFeedSource(feedUsage.feed_source),
        getFeedQuantityInKg
      ),
    [feedUsages]
  );

  const latestRecords = useMemo<LatestRecord[]>(() => {
    const saleRecords = sales.map((sale) => ({
      id: `sale-${sale.id}`,
      date: sale.sale_date,
      type: "Sale",
      description: `${sale.sale_id} - ${formatLabel(sale.payment_status)}`,
      value: formatCurrency(calculateSaleTotal(sale)),
    }));

    const costRecords = inputCosts.map((cost) => ({
      id: `cost-${cost.id}`,
      date: cost.purchase_date,
      type: "Cost",
      description: cost.item,
      value: formatCurrency(calculateInputCostTotal(cost)),
    }));

    const mortalityRecords = mortalities.map((mortality) => ({
      id: `mortality-${mortality.id}`,
      date: mortality.mortality_date,
      type: "Mortality",
      description: mortality.suspected_cause,
      value: `${formatNumber(mortality.quantity_dead)} dead`,
    }));

    const feedRecords = feedUsages.map((feedUsage) => ({
      id: `feed-${feedUsage.id}`,
      date: feedUsage.created_at,
      type: "Feed",
      description: formatFeedType(feedUsage.feed_type),
      value: formatFeedQuantity(feedUsage),
    }));

    const vaccinationRecords = vaccinations.map((vaccination) => ({
      id: `vaccination-${vaccination.id}`,
      date: vaccination.vaccination_date,
      type: "Vaccination",
      description: getVaccinationName(vaccination),
      value: vaccination.timely_status,
    }));

    return [
      ...saleRecords,
      ...costRecords,
      ...mortalityRecords,
      ...feedRecords,
      ...vaccinationRecords,
    ].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
  }, [inputCosts, sales, mortalities, feedUsages, vaccinations]);

  const vaccinationSchedule = useMemo(() => {
    const hichnerDate = addDays(batch.entry_date, 7);
    const gumboloDate = addDays(batch.entry_date, 14);
    const lasotaDate = addDays(batch.entry_date, 21);

    return [
      {
        title: "Hitchner",
        type: "hitchner",
        date: hichnerDate,
        record: vaccinations.find(
          (vaccination) => vaccination.drug_vaccination_type === "hitchner"
        ),
      },
      {
        title: "Gumbolo",
        type: "gumbolo",
        date: gumboloDate,
        record: vaccinations.find(
          (vaccination) => vaccination.drug_vaccination_type === "gumbolo"
        ),
      },
      {
        title: "Lasota",
        type: "lasota",
        date: lasotaDate,
        record: vaccinations.find(
          (vaccination) => vaccination.drug_vaccination_type === "lasota"
        ),
      },
    ].map((item) => {
      const daysUntilDue = getSignedDaysBetween(new Date(), item.date);

      return {
        ...item,
        status: item.record
          ? item.record.timely_status
          : daysUntilDue === 0
            ? "Due today"
            : daysUntilDue > 0
              ? "Upcoming"
              : "Due",
      };
    });
  }, [batch.entry_date, vaccinations]);

  const nextCare =
    vaccinationSchedule.find((item) => !item.record) ??
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
                return;
              }

              if (activeTab === "mortality") {
                setOpenModal("mortality-form");
                return;
              }

              if (activeTab === "feed") {
                setOpenModal("feed-usage-form");
                return;
              }

              if (activeTab === "vaccination") {
                setOpenModal("vaccination-form");
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
            />
          ) : null}

          {activeTab === "flock" ? (
            <FlockTab
              batch={batch}
              metrics={metrics}
              sales={sales}
              mortalities={mortalities}
              feedUsages={feedUsages}
              vaccinations={vaccinations}
              vaccinationSchedule={vaccinationSchedule}
            />
          ) : null}

          {activeTab === "costs" ? (
            <CostsTab
              batch={batch}
              inputCosts={inputCosts}
              feedInputCosts={feedInputCosts}
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

          {activeTab === "mortality" ? (
            <MortalityTab
              batch={batch}
              mortalities={mortalities}
              metrics={metrics}
              onAddMortality={() => setOpenModal("mortality-form")}
            />
          ) : null}

          {activeTab === "feed" ? (
            <FeedUsageTab
              feedUsages={feedUsages}
              metrics={metrics}
              feedTypeBreakdown={feedTypeBreakdown}
              feedSourceBreakdown={feedSourceBreakdown}
              onAddFeedUsage={() => setOpenModal("feed-usage-form")}
            />
          ) : null}

          {activeTab === "vaccination" ? (
            <VaccinationTab
              batch={batch}
              vaccinations={vaccinations}
              vaccinationSchedule={vaccinationSchedule}
              onAddVaccination={() => setOpenModal("vaccination-form")}
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

      <DetailModal
        isOpen={openModal === "mortality-form"}
        label="New mortality"
        title="Record mortality"
        onClose={() => setOpenModal(null)}
      >
        <AddMortalityForm
          batchId={batch.id}
          availableBirds={metrics.currentBirds}
          arrivalDate={batch.entry_date}
          defaultAgeInDays={metrics.dayOfCycle}
        />
      </DetailModal>

      <DetailModal
        isOpen={openModal === "feed-usage-form"}
        label="New feed usage"
        title="Record feed usage"
        onClose={() => setOpenModal(null)}
      >
        <AddFeedUsageForm
          batchId={batch.id}
          currentBirds={metrics.currentBirds}
          defaultAgeInDays={metrics.dayOfCycle}
        />
      </DetailModal>

      <DetailModal
        isOpen={openModal === "vaccination-form"}
        label="New vaccination / drug"
        title="Record drug or vaccination"
        onClose={() => setOpenModal(null)}
      >
        <AddVaccinationForm
          batchId={batch.id}
          arrivalDate={batch.entry_date}
          currentBirds={metrics.currentBirds}
        />
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

  if (activeTab === "mortality") {
    return {
      title: "Mortality register",
      description:
        "Track flock losses, causes, action taken, and mortality rate.",
      actionLabel: "Record mortality",
    };
  }

  if (activeTab === "feed") {
    return {
      title: "Feed usage",
      description:
        "Track feed issued, feed source, and consumption against live birds.",
      actionLabel: "Record feed usage",
    };
  }

  if (activeTab === "vaccination") {
    return {
      title: "Vaccination schedule",
      description:
        "Track vaccine administration against the day 7, 14, and 21 care plan.",
      actionLabel: "Record vaccination",
    };
  }

  return {
    title: `${formatLabel(batch.bird_type)} batch`,
    description: "A calm operational summary for the current production cycle.",
    actionLabel: undefined,
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
  totalFeedKg: number;
  feedPerLiveBird: number;
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
  actionLabel?: string;
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

        {actionLabel ? (
          <button
            type="button"
            onClick={onAction}
            className="h-14 rounded-xl bg-[#151f36] px-8 text-base font-bold text-white transition hover:bg-[#22345f]"
          >
            {actionLabel}
          </button>
        ) : null}
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
  nextCare: VaccinationScheduleItem;
};

function OverviewTab({
  batch,
  metrics,
  latestRecords,
  nextCare,
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

      <Card className="overflow-hidden">
        <div className="grid gap-0 lg:grid-cols-[1fr_0.42fr]">
          <div className="p-6 lg:p-8">
            <SectionLabel>Batch Information</SectionLabel>
            <div className="mt-5 flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <h2 className="text-4xl font-extrabold tracking-[-0.02em]">
                  Production cycle
                </h2>
                <p className="mt-3 max-w-2xl text-base leading-7 text-[#747b8d]">
                  {batch.batch_id} - {formatLabel(batch.bird_type)} from{" "}
                  {formatBatchSource(batch)}
                </p>
              </div>
              <div className="rounded-xl border border-[#ddd7c9] bg-[#f6f3eb] px-5 py-4">
                <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-[#747b8d]">
                  Cycle Window
                </p>
                <p className="mt-2 text-base font-extrabold">
                  {formatDisplayDate(batch.entry_date)} -{" "}
                  {formatDisplayDate(batch.expected_maturity_date)}
                </p>
              </div>
            </div>

            <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <ExecutiveMetric
                label="Live Birds"
                value={formatNumber(metrics.currentBirds)}
                detail={`${formatPercent(metrics.survivalPercent)} of initial flock`}
                progress={metrics.survivalPercent}
                tone="green"
              />
              <ExecutiveMetric
                label="Birds Sold"
                value={formatNumber(metrics.totalBirdsSold)}
                detail={`${formatPercent(metrics.soldPercent)} sold`}
                progress={metrics.soldPercent}
                tone="gold"
              />
              <ExecutiveMetric
                label="Mortality"
                value={formatNumber(metrics.mortality)}
                detail={`${formatDecimalPercent(metrics.mortalityPercent)} mortality rate`}
                progress={metrics.mortalityPercent}
                tone={metrics.mortality > 0 ? "red" : "muted"}
              />
              <ExecutiveMetric
                label="Input Cost"
                value={formatCurrency(metrics.totalInputCosts)}
                detail={`${formatCurrency(metrics.costPerBird)} per initial bird`}
                tone="navy"
              />
              <ExecutiveMetric
                label="Sales Value"
                value={formatCurrency(metrics.totalSales)}
                detail={`${formatPercent(metrics.collectionPercent)} collected`}
                progress={metrics.collectionPercent}
                tone="green"
              />
              <ExecutiveMetric
                label="Net Position"
                value={formatSignedCurrency(metrics.grossProfit)}
                detail="Sales less input costs"
                tone={metrics.grossProfit < 0 ? "red" : "navy"}
              />
            </div>
          </div>

          <aside className="border-t border-[#ddd7c9] bg-[#151f36] p-6 text-white lg:border-l lg:border-t-0 lg:p-8">
            <SectionLabel className="text-[#e1aa3f]">Executive Readout</SectionLabel>
            <div className="mt-7 grid gap-6">
              <TimelineStat
                label="Day Of Cycle"
                value={`${formatNumber(metrics.dayOfCycle)} / ${formatNumber(
                  metrics.cycleLength
                )}`}
              />
              <TimelineStat
                label="Initial Flock"
                value={formatNumber(batch.quantity)}
              />
              <TimelineStat
                label="Next Maturity"
                value={formatDisplayDate(batch.expected_maturity_date)}
              />
              <div className="rounded-xl bg-white/8 p-4">
                <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-white/60">
                  Flock Allocation
                </p>
                <StackedBar
                  segments={[
                    {
                      label: `${formatNumber(metrics.currentBirds)} live`,
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
                      color: "#b24a43",
                    },
                  ]}
                  total={batch.quantity}
                  compact
                  inverse
                />
              </div>
            </div>
          </aside>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1fr_0.5fr]">
        <Card>
          <div className="p-6">
            <SectionLabel>Activity</SectionLabel>
            <h2 className="mt-3 text-3xl font-extrabold">Latest records</h2>
          </div>
          <SimpleTable
            columns={["Date", "Type", "Description", "Readout"]}
            rows={latestRecords.slice(0, 4).map((record) => [
              formatDisplayDate(record.date),
              record.type,
              record.description,
              record.value,
            ])}
            rowDetails={latestRecords.slice(0, 4).map((record) => ({
              title: record.description,
              subtitle: `${record.type} - ${formatDisplayDate(record.date)}`,
              fields: [
                { label: "Type", value: record.type },
                { label: "Date", value: formatDisplayDate(record.date) },
                { label: "Readout", value: record.value },
              ],
            }))}
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
              {metrics.mortality > 0
                ? `${formatNumber(metrics.mortality)} mortality recorded; current live birds have been adjusted.`
                : "No mortality has been recorded for this batch."}
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
  mortalities: PoultryMortality[];
  feedUsages: PoultryFeedUsage[];
  vaccinations: PoultryVaccination[];
  vaccinationSchedule: VaccinationScheduleItem[];
};

function FlockTab({
  batch,
  metrics,
  sales,
  mortalities,
  feedUsages,
  vaccinations,
  vaccinationSchedule,
}: FlockTabProps) {
  const activityRows = [
    ...sales.map((sale) => [
      formatDisplayDate(sale.sale_date),
      "Birds sold",
      formatNumber(sale.quantity_sold),
      sale.sold_by_name || "Farmnotes",
    ]),
    ...mortalities.map((mortality) => [
      formatDisplayDate(mortality.mortality_date),
      "Mortality",
      formatNumber(mortality.quantity_dead),
      mortality.reported_by_name || "Farmnotes",
    ]),
    ...feedUsages.map((feedUsage) => [
      formatDisplayDate(feedUsage.created_at),
      `Feed issued - ${formatFeedType(feedUsage.feed_type)}`,
      formatFeedQuantity(feedUsage),
      feedUsage.reported_by_name || "Farmnotes",
    ]),
    ...vaccinations.map((vaccination) => [
      formatDisplayDate(vaccination.vaccination_date),
      `Vaccination - ${getVaccinationName(vaccination)}`,
      formatNumber(vaccination.quantity),
      vaccination.reported_by_name || "Farmnotes",
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
            rowDetails={activityRows.map((row) => ({
              title: row[1],
              subtitle: row[0],
              fields: [
                { label: "Activity", value: row[1] },
                { label: "Quantity", value: row[2] },
                { label: "Recorded By", value: row[3] },
              ],
            }))}
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
  feedInputCosts: InputCost[];
  metrics: Metrics;
  costBreakdown: BreakdownItem[];
  largestCategory?: BreakdownItem;
};

function CostsTab({
  batch,
  inputCosts,
  feedInputCosts,
  metrics,
  costBreakdown,
  largestCategory,
}: CostsTabProps) {
  const [showFeedDetails, setShowFeedDetails] = useState(false);
  const [breakdownPage, setBreakdownPage] = useState(1);
  const breakdownPageSize = 5;
  const breakdownTotalPages = Math.max(
    1,
    Math.ceil(costBreakdown.length / breakdownPageSize)
  );
  const safeBreakdownPage = Math.min(
    breakdownPage,
    breakdownTotalPages
  );
  const visibleCostBreakdown = costBreakdown.slice(
    (safeBreakdownPage - 1) * breakdownPageSize,
    safeBreakdownPage * breakdownPageSize
  );
  const feedInputTotal = feedInputCosts.reduce(
    (total, cost) => total + calculateInputCostTotal(cost),
    0
  );

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
              visibleCostBreakdown.map((item) => (
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
          {costBreakdown.length > breakdownPageSize ? (
            <div className="mt-7 flex flex-col gap-3 border-t border-[#ddd7c9] pt-5 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-[#747b8d]">
                Showing {formatNumber((safeBreakdownPage - 1) * breakdownPageSize + 1)}
                -
                {formatNumber(
                  Math.min(safeBreakdownPage * breakdownPageSize, costBreakdown.length)
                )}{" "}
                of {formatNumber(costBreakdown.length)} categories
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() =>
                    setBreakdownPage((page) => Math.max(1, page - 1))
                  }
                  disabled={safeBreakdownPage === 1}
                  className="rounded-lg border border-[#ddd7c9] bg-white px-4 py-2 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Previous
                </button>
                <span className="px-2 text-sm font-bold text-[#747b8d]">
                  {formatNumber(safeBreakdownPage)} / {formatNumber(breakdownTotalPages)}
                </span>
                <button
                  type="button"
                  onClick={() =>
                    setBreakdownPage((page) => Math.min(breakdownTotalPages, page + 1))
                  }
                  disabled={safeBreakdownPage === breakdownTotalPages}
                  className="rounded-lg border border-[#ddd7c9] bg-white px-4 py-2 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          ) : null}
        </Card>

        <section className="rounded-xl bg-[#151f36] p-7 text-white">
          <SectionLabel className="text-[#e1aa3f]">Cost Control</SectionLabel>
          <h2 className="mt-6 text-3xl font-extrabold leading-tight">
            {largestCategory
              ? `${largestCategory.label} drives most recorded cost.`
              : "No recorded input spend yet."}
          </h2>
          <p className="mt-5 text-base leading-7 text-white/70">
            {feedInputCosts.length > 0
              ? `${formatCurrency(feedInputTotal)} has been recorded in feed-related categories.`
              : "Feed-related input costs will appear once category names include feed."}
          </p>
          <button
            type="button"
            onClick={() => setShowFeedDetails((current) => !current)}
            className="mt-5 rounded-lg bg-[#e1aa3f] px-8 py-4 text-base font-bold text-[#151926]"
          >
            {showFeedDetails ? "Hide feed details" : "Review feed details"}
          </button>
        </section>
      </div>

      {showFeedDetails ? (
        <Card>
          <RegisterHeader title="Feed cost components" />
          <SimpleTable
            columns={["Date", "Item", "Category", "Quantity", "Notes", "Total"]}
            rows={feedInputCosts.map((cost) => [
              formatDisplayDate(cost.purchase_date),
              cost.item,
              cost.category,
              getCostQuantity(cost),
              cost.notes,
              formatCurrency(calculateInputCostTotal(cost)),
            ])}
            rowDetails={feedInputCosts.map(costDetail)}
            emptyMessage="No feed-related input costs were found."
          />
        </Card>
      ) : null}

      <Card>
        <RegisterHeader title="Input cost records" />
        <SimpleTable
          columns={[
            "Date",
            "Cost Item",
            "Category",
            "Quantity",
            "Notes",
            "Total",
          ]}
          rows={inputCosts.map((cost) => [
            formatDisplayDate(cost.purchase_date),
            cost.item,
            formatCostCategory(cost.category),
            getCostQuantity(cost),
            cost.notes,
            formatCurrency(calculateInputCostTotal(cost)),
          ])}
          rowDetails={inputCosts.map(costDetail)}
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
          rowDetails={sales.map(saleDetail)}
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

type MortalityTabProps = {
  batch: PoultryBatch;
  mortalities: PoultryMortality[];
  metrics: Metrics;
  onAddMortality: () => void;
};

function MortalityTab({
  batch,
  mortalities,
  metrics,
  onAddMortality,
}: MortalityTabProps) {
  const latestMortality = mortalities[0];

  return (
    <div className="mt-8 grid gap-8">
      <div className="grid gap-6 lg:grid-cols-4">
        <KpiCard
          label="Total Mortality"
          value={formatNumber(metrics.mortality)}
          detail={`${formatDecimalPercent(metrics.mortalityPercent)} mortality rate`}
          tone={metrics.mortality > 0 ? "danger" : "default"}
        />
        <KpiCard
          label="Available Live Birds"
          value={formatNumber(metrics.currentBirds)}
          detail="Initial birds less sold and mortality"
        />
        <KpiCard
          label="Birds Sold"
          value={formatNumber(metrics.totalBirdsSold)}
          detail={`${formatPercent(metrics.soldPercent)} of initial flock`}
        />
        <KpiCard
          label="Initial Flock"
          value={formatNumber(batch.quantity)}
          detail={`Placed on ${formatDisplayDate(batch.entry_date)}`}
        />
      </div>

      <Card className="p-6">
        <SectionLabel>Live Flock Logic</SectionLabel>
        <h2 className="mt-6 text-3xl font-extrabold">
          Available birds after mortality
        </h2>
        <p className="mt-5 text-base leading-7 text-[#747b8d]">
          Mortality records reduce live birds immediately, alongside sales.
        </p>
        <StackedBar
          segments={[
            {
              label: `${formatNumber(metrics.currentBirds)} live`,
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
              color: "#b24a43",
            },
          ]}
          total={batch.quantity}
        />
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1fr_0.42fr]">
        <Card>
          <RegisterHeader
            title="Mortality records"
            actionLabel="Record mortality"
            onAction={onAddMortality}
          />
          <SimpleTable
            columns={[
              "Date",
              "Dead",
              "Age",
              "Suspected Cause",
              "Reported By",
            ]}
            rows={mortalities.map((mortality) => [
              formatDisplayDate(mortality.mortality_date),
              formatNumber(mortality.quantity_dead),
              `${formatNumber(mortality.age_in_days)} days`,
              mortality.suspected_cause,
              mortality.reported_by_name,
            ])}
            rowDetails={mortalities.map(mortalityDetail)}
            emptyMessage="No mortality has been recorded."
          />
        </Card>

        <Card className="p-6">
          <SectionLabel>Latest Incident</SectionLabel>
          <h2 className="mt-6 text-3xl font-extrabold">
            {latestMortality
              ? latestMortality.suspected_cause
              : "No incidents yet"}
          </h2>
          <p className="mt-5 text-base leading-7 text-[#747b8d]">
            {latestMortality
              ? latestMortality.description
              : "When mortality is recorded, the latest cause and action taken will appear here."}
          </p>
          {latestMortality ? (
            <div className="mt-6 border-t border-[#ddd7c9] pt-5">
              <p className="text-sm font-bold text-[#747b8d]">Action taken</p>
              <p className="mt-3 text-base leading-7">
                {latestMortality.action_taken}
              </p>
            </div>
          ) : null}
        </Card>
      </div>
    </div>
  );
}

type FeedUsageTabProps = {
  feedUsages: PoultryFeedUsage[];
  metrics: Metrics;
  feedTypeBreakdown: BreakdownItem[];
  feedSourceBreakdown: BreakdownItem[];
  onAddFeedUsage: () => void;
};

function FeedUsageTab({
  feedUsages,
  metrics,
  feedTypeBreakdown,
  feedSourceBreakdown,
  onAddFeedUsage,
}: FeedUsageTabProps) {
  const latestFeedUsage = feedUsages[0];

  return (
    <div className="mt-8 grid gap-8">
      <div className="grid gap-6 lg:grid-cols-3">
        <KpiCard
          label="Total Feed Issued"
          value={`${formatNumber(metrics.totalFeedKg)} kg`}
          detail={formatRecordCount(feedUsages.length)}
        />
        <KpiCard
          label="Feed Per Live Bird"
          value={`${formatNumber(metrics.feedPerLiveBird)} kg`}
          detail={`Based on ${formatNumber(metrics.currentBirds)} current birds`}
        />
        <KpiCard
          label="Latest Feed"
          value={
            latestFeedUsage ? formatFeedType(latestFeedUsage.feed_type) : "None"
          }
          detail={
            latestFeedUsage
              ? `${formatFeedQuantity(latestFeedUsage)} issued`
              : "No feed issued yet"
          }
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_0.6fr]">
        <Card className="p-6">
          <SectionLabel>Feed Mix</SectionLabel>
          <h2 className="mt-6 text-3xl font-extrabold">Usage by feed type</h2>
          <div className="mt-6 grid gap-8">
            {feedTypeBreakdown.length > 0 ? (
              feedTypeBreakdown.map((item) => (
                <CategoryBar
                  key={item.label}
                  item={item}
                  total={metrics.totalFeedKg}
                  formatValue={(value) => `${formatNumber(value)} kg`}
                />
              ))
            ) : (
              <p className="text-base text-[#747b8d]">
                No feed usage has been recorded.
              </p>
            )}
          </div>
        </Card>

        <Card className="p-6">
          <SectionLabel>Source Control</SectionLabel>
          <h2 className="mt-6 text-3xl font-extrabold">Usage by source</h2>
          <div className="mt-6 grid gap-7">
            {feedSourceBreakdown.length > 0 ? (
              feedSourceBreakdown.map((item) => (
                <CategoryBar
                  key={item.label}
                  item={item}
                  total={metrics.totalFeedKg}
                  formatValue={(value) => `${formatNumber(value)} kg`}
                />
              ))
            ) : (
              <p className="text-base text-[#747b8d]">
                Feed source data will appear after the first record.
              </p>
            )}
          </div>
        </Card>
      </div>

      <Card>
        <RegisterHeader
          title="Feed usage records"
          actionLabel="Record feed usage"
          onAction={onAddFeedUsage}
        />
        <SimpleTable
          columns={["Date", "Feed", "Source", "Quantity", "Birds", "Reported By"]}
          rows={feedUsages.map((feedUsage) => [
            formatDisplayDate(feedUsage.created_at),
            formatFeedType(feedUsage.feed_type),
            formatFeedSource(feedUsage.feed_source),
            formatFeedQuantity(feedUsage),
            formatNumber(feedUsage.current_number_of_birds),
            feedUsage.reported_by_name,
          ])}
          rowDetails={feedUsages.map(feedUsageDetail)}
          emptyMessage="No feed usage has been recorded."
        />
      </Card>
    </div>
  );
}

type VaccinationTabProps = {
  batch: PoultryBatch;
  vaccinations: PoultryVaccination[];
  vaccinationSchedule: VaccinationScheduleItem[];
  onAddVaccination: () => void;
};

function VaccinationTab({
  batch,
  vaccinations,
  vaccinationSchedule,
  onAddVaccination,
}: VaccinationTabProps) {
  const completedScheduleCount = vaccinationSchedule.filter(
    (item) => item.record
  ).length;
  const delayedCount = vaccinations.filter((vaccination) =>
    vaccination.timely_status.toLowerCase().startsWith("delayed")
  ).length;
  const nextDue =
    vaccinationSchedule.find((item) => !item.record) ??
    vaccinationSchedule[vaccinationSchedule.length - 1];

  return (
    <div className="mt-8 grid gap-8">
      <div className="grid gap-6 lg:grid-cols-3">
        <KpiCard
          label="Schedule Completed"
          value={`${formatNumber(completedScheduleCount)} / ${formatNumber(
            vaccinationSchedule.length
          )}`}
          detail="Core vaccine milestones recorded"
        />
        <KpiCard
          label="Vaccination / Drug Records"
          value={formatNumber(vaccinations.length)}
          detail="Includes scheduled and other drugs"
        />
        <KpiCard
          label="Delayed Records"
          value={formatNumber(delayedCount)}
          detail="Calculated from administration date"
          tone={delayedCount > 0 ? "danger" : "default"}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_0.42fr]">
        <Card className="p-6">
          <SectionLabel>Care Plan</SectionLabel>
          <h2 className="mt-6 text-3xl font-extrabold">
            Scheduled vaccine milestones
          </h2>
          <p className="mt-5 text-base leading-7 text-[#747b8d]">
            Hitchner is expected 7 days after arrival, Gumbolo after 14 days,
            and Lasota after 21 days.
          </p>
          <div className="mt-8 grid gap-5 md:grid-cols-3">
            {vaccinationSchedule.map((item) => (
              <ScheduleItem key={item.title} item={item} />
            ))}
          </div>
        </Card>

        <Card className="p-6">
          <SectionLabel>Next Due</SectionLabel>
          <h2 className="mt-6 text-3xl font-extrabold">{nextDue.title}</h2>
          <p className="mt-5 text-base leading-7 text-[#747b8d]">
            Expected on {formatDisplayDate(nextDue.date)} from the batch arrival
            date of {formatDisplayDate(batch.entry_date)}.
          </p>
          <button
            type="button"
            onClick={onAddVaccination}
            className="mt-6 rounded-lg bg-[#151f36] px-8 py-4 text-base font-bold text-white"
          >
            Record drug / vaccination
          </button>
        </Card>
      </div>

      <Card>
        <RegisterHeader
          title="Vaccination & drug records"
          actionLabel="Record drug / vaccination"
          onAction={onAddVaccination}
        />
        <SimpleTable
          columns={[
            "Date",
            "Category",
            "Drug / Vaccination",
            "Quantity",
            "Timely Status",
            "Reported By",
          ]}
          rows={vaccinations.map((vaccination) => [
            formatDisplayDate(vaccination.vaccination_date),
            formatDrugCategory(vaccination.drug_category),
            getVaccinationName(vaccination),
            formatNumber(vaccination.quantity),
            vaccination.timely_status,
            vaccination.reported_by_name,
          ])}
          rowDetails={vaccinations.map(vaccinationDetail)}
          emptyMessage="No vaccination or drug administration has been recorded."
        />
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

type ExecutiveMetricProps = {
  label: string;
  value: string;
  detail: string;
  progress?: number;
  tone?: "green" | "gold" | "muted" | "navy" | "red";
};

function ExecutiveMetric({
  label,
  value,
  detail,
  progress,
  tone = "navy",
}: ExecutiveMetricProps) {
  const colorByTone = {
    green: "#4e8b61",
    gold: "#e1aa3f",
    muted: "#747b8d",
    navy: "#151f36",
    red: "#b24a43",
  } as const;
  const color = colorByTone[tone];

  return (
    <div className="rounded-xl border border-[#ddd7c9] bg-white px-5 py-4">
      <p className="text-xs font-extrabold uppercase tracking-[0.15em] text-[#747b8d]">
        {label}
      </p>
      <p className="mt-3 text-3xl font-extrabold tracking-[-0.02em] text-[#151926]">
        {value}
      </p>
      <p className="mt-2 text-sm leading-6 text-[#747b8d]">{detail}</p>
      {typeof progress === "number" ? (
        <div className="mt-4 h-2 overflow-hidden rounded-full bg-[#e7e4d9]">
          <div
            className="h-full rounded-full"
            style={{
              width: `${getPercent(progress, 100)}%`,
              backgroundColor: color,
            }}
          />
        </div>
      ) : null}
    </div>
  );
}

type TimelineStatProps = {
  label: string;
  value: string;
};

function TimelineStat({ label, value }: TimelineStatProps) {
  return (
    <div className="border-b border-white/15 pb-5">
      <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-white/55">
        {label}
      </p>
      <p className="mt-2 text-2xl font-extrabold text-white">{value}</p>
    </div>
  );
}

function KpiCard({
  label,
  value,
  detail,
  tone = "default",
}: KpiCardProps) {
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
  pageSize?: number;
  exportFileName?: string;
  rowDetails?: TableRowDetail[];
};

type TableRowDetail = {
  title: string;
  subtitle?: string;
  fields: Array<{
    label: string;
    value: string;
  }>;
};

function SimpleTable({
  columns,
  rows,
  emptyMessage,
  pageSize = 5,
  exportFileName = "farmnotes-register",
  rowDetails = [],
}: SimpleTableProps) {
  const [currentPage, setCurrentPage] = useState(1);
  const [filterValue, setFilterValue] = useState("");
  const [selectedDetail, setSelectedDetail] =
    useState<TableRowDetail | null>(null);
  const normalizedFilter = filterValue.trim().toLowerCase();
  const keyedRows = rows.map((row, index) => ({
    row,
    detail: rowDetails[index],
  }));
  const filteredRows = normalizedFilter
    ? keyedRows.filter(({ row, detail }) =>
        [
          ...row,
          ...(detail?.fields.map((field) => field.value) ?? []),
        ].some((cell) => cell.toLowerCase().includes(normalizedFilter))
      )
    : keyedRows;
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const startIndex = (safeCurrentPage - 1) * pageSize;
  const paginatedRows = filteredRows.slice(startIndex, startIndex + pageSize);

  function exportRows() {
    const csvRows = [columns, ...filteredRows.map(({ row }) => row)].map((row) =>
      row
        .map((cell) => `"${cell.replace(/"/g, '""')}"`)
        .join(",")
    );
    const blob = new Blob([csvRows.join("\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = url;
    link.download = `${exportFileName}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      <div className="flex flex-col gap-3 border-t border-[#ddd7c9] px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <label className="flex min-w-0 flex-1 items-center gap-3">
          <span className="text-xs font-extrabold uppercase tracking-[0.16em] text-[#747b8d]">
            Filter
          </span>
          <input
            type="search"
            value={filterValue}
            onChange={(event) => {
              setFilterValue(event.target.value);
              setCurrentPage(1);
            }}
            placeholder="Search table"
            className="min-w-0 flex-1 rounded-lg border border-[#ddd7c9] bg-white px-4 py-2 text-sm text-[#151926] outline-none transition focus:border-[#e1aa3f]"
          />
        </label>
        <button
          type="button"
          onClick={exportRows}
          disabled={filteredRows.length === 0}
          className="rounded-lg bg-[#151f36] px-5 py-2 text-sm font-bold text-white transition hover:bg-[#22345f] disabled:cursor-not-allowed disabled:opacity-50"
        >
          Export CSV
        </button>
      </div>

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
            {filteredRows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-5 py-8 text-base text-[#747b8d]"
                >
                  {rows.length === 0
                    ? emptyMessage
                    : "No records match the current filter."}
                </td>
              </tr>
            ) : (
              paginatedRows.map(({ row, detail }, rowIndex) => (
                <tr
                  key={`${row[0]}-${startIndex + rowIndex}`}
                  onClick={() => {
                    if (detail) {
                      setSelectedDetail(detail);
                    }
                  }}
                  tabIndex={detail ? 0 : undefined}
                  onKeyDown={(event) => {
                    if (
                      detail &&
                      (event.key === "Enter" || event.key === " ")
                    ) {
                      event.preventDefault();
                      setSelectedDetail(detail);
                    }
                  }}
                  className={`border-b border-[#ddd7c9] ${
                    detail
                      ? "cursor-pointer transition hover:bg-[#fff4c6]/60 focus:bg-[#fff4c6]/60 focus:outline-none"
                      : ""
                  }`}
                >
                  {row.map((cell, cellIndex) => (
                    <td
                      key={`${cell}-${cellIndex}`}
                      className={`px-5 py-5 text-base ${
                        cellIndex === 0
                          ? "font-extrabold text-[#151926]"
                          : "text-[#747b8d]"
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

      {filteredRows.length > pageSize ? (
        <div className="flex flex-col gap-3 border-t border-[#ddd7c9] px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-[#747b8d]">
            Showing {formatNumber(startIndex + 1)}-
            {formatNumber(Math.min(startIndex + pageSize, filteredRows.length))}{" "}
            of {formatNumber(filteredRows.length)}
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() =>
                setCurrentPage((page) => Math.max(1, page - 1))
              }
              disabled={safeCurrentPage === 1}
              className="rounded-lg border border-[#ddd7c9] bg-white px-4 py-2 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-50"
            >
              Previous
            </button>
            <span className="px-2 text-sm font-bold text-[#747b8d]">
              {formatNumber(safeCurrentPage)} / {formatNumber(totalPages)}
            </span>
            <button
              type="button"
              onClick={() =>
                setCurrentPage((page) => Math.min(totalPages, page + 1))
              }
              disabled={safeCurrentPage === totalPages}
              className="rounded-lg border border-[#ddd7c9] bg-white px-4 py-2 text-sm font-bold disabled:cursor-not-allowed disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      ) : null}

      <RecordDetailModal
        detail={selectedDetail}
        onClose={() => setSelectedDetail(null)}
      />
    </div>
  );
}

type RecordDetailModalProps = {
  detail: TableRowDetail | null;
  onClose: () => void;
};

function RecordDetailModal({
  detail,
  onClose,
}: RecordDetailModalProps) {
  if (!detail) {
    return null;
  }

  if (typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[100] overflow-y-auto bg-[#e9ecf3]/80 px-4 py-8 backdrop-blur-[7px]"
      role="presentation"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="record-detail-title"
        className="relative mx-auto mt-12 w-full max-w-4xl overflow-hidden rounded-[1.75rem] border border-white/90 bg-white shadow-[0_30px_90px_rgba(21,31,54,0.24)]"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-[var(--gold-soft)]/70 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-24 -right-24 h-72 w-72 rounded-full bg-[#f3f5fa] blur-3xl" />

        <div className="relative px-8 py-8 sm:px-12 sm:py-10">
          <div className="flex items-start justify-between gap-6">
            <div>
              <p className="text-xs font-extrabold uppercase tracking-[0.18em] text-[var(--navy-muted)]">
                Record Details
              </p>
              <h2
                id="record-detail-title"
                className="mt-4 max-w-2xl text-3xl font-extrabold leading-tight text-[var(--navy)] sm:text-4xl"
              >
                {detail.title}
              </h2>
              {detail.subtitle ? (
                <p className="mt-3 text-base leading-7 text-[var(--navy-muted)]">
                  {detail.subtitle}
                </p>
              ) : null}
            </div>

            <button
              type="button"
              aria-label="Close record detail"
              title="Close"
              onClick={onClose}
              className="grid h-11 w-11 shrink-0 place-items-center rounded-full text-[var(--navy-muted)] transition hover:bg-[var(--gold-soft)] hover:text-[var(--navy)]"
            >
              <X className="h-6 w-6" aria-hidden="true" />
            </button>
          </div>

          <div className="mt-9 border-t border-[var(--line)] pt-8">
            <div className="grid gap-x-16 gap-y-8 md:grid-cols-2">
              {detail.fields.map((field) => (
                <RecordDetailField
                  key={field.label}
                  label={field.label}
                  value={field.value}
                />
              ))}
            </div>
          </div>

          <div className="mt-10">
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl bg-[var(--gold)] px-6 py-3 text-sm font-extrabold uppercase tracking-[0.14em] text-[var(--navy)] shadow-sm transition hover:brightness-95"
            >
              Close Detail
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

function RecordDetailField({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  const displayValue = value || "-";
  const pillLabels = [
    "Status",
    "Payment Status",
    "Timely Status",
    "Category",
    "Type",
  ];
  const shouldUsePill =
    pillLabels.includes(label) ||
    displayValue.toLowerCase().includes("delayed") ||
    displayValue.toLowerCase().includes("early");

  return (
    <div>
      <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-[var(--navy-muted)]">
        {label}
      </p>
      {shouldUsePill ? (
        <span className="mt-3 inline-flex max-w-full rounded-full bg-[var(--gold-soft)] px-4 py-2 text-sm font-extrabold text-[var(--navy)]">
          {displayValue}
        </span>
      ) : (
        <p className="mt-3 whitespace-pre-wrap break-words text-base font-bold leading-7 text-[var(--navy-soft)]">
          {displayValue}
        </p>
      )}
    </div>
  );
}

type RegisterHeaderProps = {
  title: string;
  actionLabel?: string;
  onAction?: () => void;
};

function RegisterHeader({ title, actionLabel, onAction }: RegisterHeaderProps) {
  return (
    <div className="flex flex-col gap-4 p-6 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <SectionLabel>Register</SectionLabel>
        <h2 className="mt-3 text-3xl font-extrabold">{title}</h2>
      </div>
      <div className="flex gap-3">
        {actionLabel && onAction ? (
          <button
            type="button"
            onClick={onAction}
            className="rounded-lg bg-[#151f36] px-8 py-4 text-base font-bold text-white"
          >
            {actionLabel}
          </button>
        ) : null}
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
  compact?: boolean;
  inverse?: boolean;
};

function StackedBar({
  segments,
  total,
  compact = false,
  inverse = false,
}: StackedBarProps) {
  return (
    <div className={compact ? "mt-4" : "mt-6"}>
      <div
        className={`flex overflow-hidden rounded-full ${
          compact ? "h-3" : "h-7"
        } ${inverse ? "bg-white/15" : "bg-[#e7e4d9]"}`}
      >
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
            <span
              className={`text-sm font-extrabold ${
                inverse ? "text-white/80" : "text-[#151926]"
              }`}
            >
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
  formatValue?: (value: number) => string;
};

function CategoryBar({
  item,
  total,
  formatValue = formatCurrency,
}: CategoryBarProps) {
  return (
    <div>
      <div className="flex items-center justify-between gap-5">
        <p className="text-base font-extrabold">{item.label}</p>
        <p className="text-base font-extrabold">{formatValue(item.value)}</p>
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
  item: VaccinationScheduleItem;
};

function ScheduleItem({ item }: ScheduleItemProps) {
  const isAttention = item.status === "Upcoming" || item.status === "Due today";
  const isCompleted = Boolean(item.record);

  return (
    <div
      className={`grid grid-cols-[70px_1fr] gap-4 rounded-lg p-4 ${
        isAttention ? "bg-[#fff4c6]" : ""
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
            isCompleted ? "text-[#4e8b61]" : "text-[#747b8d]"
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
