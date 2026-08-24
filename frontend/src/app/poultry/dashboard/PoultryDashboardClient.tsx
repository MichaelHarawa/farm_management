"use client";

import { useMemo, useState } from "react";
import type { PoultryBatch, PoultrySale, PoultryMortality, PoultryFeedUsage } from "@/features/poultry/types";

type Props = {
  batches: PoultryBatch[];
  productionBatches: PoultryBatch[];
  allSales: PoultrySale[];
  allMortalities: PoultryMortality[];
  allFeedUsages: PoultryFeedUsage[];
};

export default function PoultryDashboardClient({ batches, productionBatches, allSales, allMortalities, allFeedUsages }: Props) {
  const [birdTypeFilter, setBirdTypeFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const filteredBatches = useMemo(() => {
    return batches.filter((b) => {
      const typeMatch = birdTypeFilter === "all" || b.bird_type === birdTypeFilter;
      const statusMatch = statusFilter === "all" || b.status === statusFilter;
      return typeMatch && statusMatch;
    });
  }, [batches, birdTypeFilter, statusFilter]);

  const filteredProduction = filteredBatches.filter(
    (b) => b.status !== "booked" && b.status !== "delivered"
  );

  const filteredBatchIds = new Set(filteredBatches.map((b) => b.id));

  const totalBirds = filteredProduction.reduce((sum, b) => sum + b.quantity, 0);
  const activeCount = filteredProduction.length;

  // Status breakdown (live)
  const statusCounts = filteredBatches.reduce((acc: Record<string, number>, b) => {
    acc[b.status] = (acc[b.status] || 0) + 1;
    return acc;
  }, {});

  // Bird type breakdown (by birds, live)
  const typeBirdCounts = filteredBatches.reduce((acc: Record<string, number>, b) => {
    acc[b.bird_type] = (acc[b.bird_type] || 0) + b.quantity;
    return acc;
  }, {});

  // Real sales aggregation from DB
  const filteredSales = allSales.filter((s) => filteredBatchIds.has(s.batch));
  const salesByProduct: Record<string, number> = {};
  filteredSales.forEach((s) => {
    salesByProduct[s.product_type] = (salesByProduct[s.product_type] || 0) + s.quantity_sold;
  });
  const salesData = Object.entries(salesByProduct)
    .sort((a, b) => b[1] - a[1])
    .map(([label, value]) => ({ label, value }));

  // Real mortality from DB
  const filteredMorts = allMortalities.filter((m) => filteredBatchIds.has(m.batch));
  const mortByCause: Record<string, number> = {};
  filteredMorts.forEach((m) => {
    mortByCause[m.suspected_cause] = (mortByCause[m.suspected_cause] || 0) + m.quantity_dead;
  });
  const mortData = Object.entries(mortByCause)
    .sort((a, b) => b[1] - a[1])
    .map(([label, value]) => ({ label, value }));

  // Real feed from DB (normalize g to kg)
  const filteredFeeds = allFeedUsages.filter((f) => filteredBatchIds.has(f.batch));
  const feedByType: Record<string, number> = {};
  filteredFeeds.forEach((f) => {
    let qty = f.quantity_given;
    if (f.unit_of_measurement === "g") qty = qty / 1000;
    feedByType[f.feed_type] = (feedByType[f.feed_type] || 0) + qty;
  });
  const feedData = Object.entries(feedByType)
    .sort((a, b) => b[1] - a[1])
    .map(([label, value]) => ({ label, value: Math.round(value) }));

  const birdTypes = Array.from(new Set(batches.map((b) => b.bird_type)));
  const statuses = Array.from(new Set(batches.map((b) => b.status)));

  // Simple pie using conic gradient (status)
  const pieSegments = Object.entries(statusCounts);
  let pieGradient = "";
  let currentDeg = 0;
  const totalStatus = Object.values(statusCounts).reduce((a, b) => a + b, 0) || 1;
  pieSegments.forEach(([status, count], i) => {
    const deg = (count / totalStatus) * 360;
    const color = i % 2 === 0 ? "#e1aa3f" : "#4e8b61";
    pieGradient += `${color} ${currentDeg}deg ${currentDeg + deg}deg, `;
    currentDeg += deg;
  });
  pieGradient = pieGradient.slice(0, -2);

  return (
    <div>
      {/* Filters */}
      <div className="mb-6 flex flex-wrap gap-3 rounded-xl border border-[#ddd7c9] bg-white p-4">
        <div>
          <label className="block text-xs font-bold uppercase tracking-widest text-[#747b8d]">Bird Type</label>
          <select
            value={birdTypeFilter}
            onChange={(e) => setBirdTypeFilter(e.target.value)}
            className="mt-1 rounded border border-[#ddd7c9] bg-white px-3 py-1 text-sm"
          >
            <option value="all">All</option>
            {birdTypes.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-bold uppercase tracking-widest text-[#747b8d]">Status</label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="mt-1 rounded border border-[#ddd7c9] bg-white px-3 py-1 text-sm"
          >
            <option value="all">All</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="ml-auto self-end text-xs text-[#747b8d]">
          Showing {filteredBatches.length} batches • {totalBirds.toLocaleString()} birds
        </div>
      </div>

      {/* KPIs */}
      <div className="mb-8 grid grid-cols-2 gap-4 md:grid-cols-4">
        {[
          { label: "Active Batches", value: activeCount },
          { label: "Total Birds", value: totalBirds.toLocaleString() },
          { label: "Avg Birds/Batch", value: activeCount ? Math.round(totalBirds / activeCount) : 0 },
          { label: "Bird Types", value: Object.keys(typeBirdCounts).length },
        ].map((kpi, i) => (
          <div key={i} className="rounded-xl border border-[#ddd7c9] bg-white p-4">
            <div className="text-xs font-bold uppercase tracking-widest text-[#747b8d]">{kpi.label}</div>
            <div className="mt-1 text-3xl font-extrabold">{kpi.value}</div>
          </div>
        ))}
      </div>

      {/* Visuals Grid */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Status Pie */}
        <div className="rounded-2xl border border-[#ddd7c9] bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <div className="font-bold">Batch Status Distribution</div>
            <div className="text-xs text-[#747b8d]">Pie</div>
          </div>
          <div className="flex items-center gap-8">
            <div
              className="h-40 w-40 flex-shrink-0 rounded-full"
              style={{
                background: `conic-gradient(${pieGradient})`,
              }}
            />
            <div className="space-y-1 text-sm">
              {pieSegments.map(([status, count], i) => (
                <div key={i} className="flex items-center gap-2">
                  <div className={`h-2.5 w-2.5 rounded ${i % 2 === 0 ? "bg-[#e1aa3f]" : "bg-[#4e8b61]"}`} />
                  <span className="capitalize">{status}</span>
                  <span className="text-[#747b8d]">({count})</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Birds by Type - Bars */}
        <div className="rounded-2xl border border-[#ddd7c9] bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <div className="font-bold">Birds by Type</div>
            <div className="text-xs text-[#747b8d]">Bar</div>
          </div>
          {Object.entries(typeBirdCounts)
            .sort((a, b) => b[1] - a[1])
            .map(([type, qty], idx) => {
              const max = Math.max(...Object.values(typeBirdCounts));
              const pct = max > 0 ? Math.round((qty / max) * 100) : 0;
              return (
                <div key={idx} className="mb-4">
                  <div className="mb-1 flex justify-between text-sm">
                    <span className="capitalize font-medium">{type}</span>
                    <span>{qty.toLocaleString()}</span>
                  </div>
                  <div className="h-3 rounded bg-[#e6e0d0]">
                    <div className="h-3 rounded bg-[#4e8b61]" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
        </div>

        {/* Sales Overview - live from DB */}
        <div className="rounded-2xl border border-[#ddd7c9] bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <div className="font-bold">Sales by Product Type</div>
              <div className="text-xs text-[#747b8d]">Live data from database</div>
            </div>
            <div className="text-xs text-[#747b8d]">Bar</div>
          </div>
          {salesData.length === 0 ? (
            <p className="text-sm text-[#747b8d]">No sales recorded yet.</p>
          ) : (
            salesData.map((s, i) => {
              const max = Math.max(...salesData.map(d => d.value));
              const pct = max > 0 ? Math.round((s.value / max) * 100) : 0;
              return (
                <div key={i} className="mb-4">
                  <div className="mb-1 flex justify-between text-sm">
                    <span>{s.label}</span>
                    <span>{s.value} units ({pct}%)</span>
                  </div>
                  <div className="h-3 rounded bg-[#e6e0d0]">
                    <div className="h-3 rounded bg-[#e1aa3f]" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Mortality Breakdown - live */}
        <div className="rounded-2xl border border-[#ddd7c9] bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <div className="font-bold">Mortality by Suspected Cause</div>
              <div className="text-xs text-[#747b8d]">Live data from database</div>
            </div>
          </div>
          {mortData.length === 0 ? (
            <p className="text-sm text-[#747b8d]">No mortality records yet.</p>
          ) : (
            mortData.map((m, i) => {
              const max = Math.max(...mortData.map(d => d.value));
              const pct = max > 0 ? Math.round((m.value / max) * 100) : 0;
              return (
                <div key={i} className="mb-4">
                  <div className="mb-1 flex justify-between text-sm">
                    <span>{m.label}</span>
                    <span>{m.value} birds ({pct}%)</span>
                  </div>
                  <div className="h-3 rounded bg-[#e6e0d0]">
                    <div className="h-3 rounded bg-[#b24a43]" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })
          )}
          <div className="text-[10px] text-[#747b8d]">Log causes in batch mortality tab for accurate trends.</div>
        </div>

        {/* Feed Usage - live */}
        <div className="rounded-2xl border border-[#ddd7c9] bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <div className="font-bold">Feed by Type (kg)</div>
              <div className="text-xs text-[#747b8d]">Live data from database</div>
            </div>
          </div>
          {feedData.length === 0 ? (
            <p className="text-sm text-[#747b8d]">No feed records yet.</p>
          ) : (
            feedData.map((f, i) => {
              const max = Math.max(...feedData.map(d => d.value));
              const pct = max > 0 ? Math.round((f.value / max) * 100) : 0;
              return (
                <div key={i} className="mb-4">
                  <div className="mb-1 flex justify-between text-sm">
                    <span>{f.label}</span>
                    <span>{f.value} kg ({pct}%)</span>
                  </div>
                  <div className="h-3 rounded bg-[#e6e0d0]">
                    <div className="h-3 rounded bg-[#151f36]" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })
          )}
          <div className="text-[10px] text-[#747b8d]">Track in Feed tab. Efficiency = total feed / live birds.</div>
        </div>

        {/* Growth note (real data per batch) */}
        <div className="rounded-2xl border border-[#ddd7c9] bg-white p-6">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <div className="font-bold">Growth Performance</div>
              <div className="text-xs text-[#747b8d]">Live per-batch data</div>
            </div>
          </div>
          <div className="text-sm text-[#747b8d]">
            Weight samples and target comparisons (Ross 308 / Cobb 500) are tracked per batch in the Growth tab.
            Open a batch to see real series, deviation, and alerts.
          </div>
          <div className="mt-3 text-xs text-[#747b8d]">Use the filter above to focus on active broiler batches for best results.</div>
        </div>
      </div>

      <div className="mt-8 text-xs text-[#747b8d]">
        Data is filtered live. Open individual batches for detailed logs and to record new sales / mortality / feed / growth samples.
      </div>
    </div>
  );
}
