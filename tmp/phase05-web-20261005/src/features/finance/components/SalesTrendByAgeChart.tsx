"use client";

import { useMemo, useState } from "react";

import type { FinanceDashboard } from "@/features/finance/types";
import { formatCurrency, formatDate, formatNumber, parseDecimal } from "@/features/finance/utils/formatters";

type SalesTrendPoint = FinanceDashboard["batch_analysis"]["sales_trend"][number];

const chartColors = ["#172443", "#d4a642", "#4e8b61", "#b4533a", "#6f5da8", "#3f7c91"];

function compactCurrency(value: number) {
  return `MWK ${new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value)}`;
}

function niceMaximum(value: number) {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const nice = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return nice * magnitude;
}

function dayTicks(minDay: number, maxDay: number) {
  const span = Math.max(maxDay - minDay, 1);
  const targetStep = span / 5;
  const steps = [1, 2, 5, 7, 10, 14, 21, 28];
  const step = steps.find((candidate) => candidate >= targetStep) ?? 28;
  const ticks: number[] = [];
  for (let day = minDay; day <= maxDay; day += step) ticks.push(day);
  if (ticks[ticks.length - 1] !== maxDay) {
    if (maxDay - ticks[ticks.length - 1] < step * 0.55) ticks[ticks.length - 1] = maxDay;
    else ticks.push(maxDay);
  }
  return [...new Set(ticks)];
}

function aggregatePoints(rows: SalesTrendPoint[]) {
  const values = new Map<string, SalesTrendPoint>();
  rows.forEach((row) => {
    const key = `${row.batch_id}-${row.age_day}`;
    const existing = values.get(key);
    values.set(key, existing ? {
      ...row,
      quantity: existing.quantity + row.quantity,
      revenue: String(parseDecimal(existing.revenue) + parseDecimal(row.revenue)),
    } : row);
  });
  return [...values.values()];
}

export function SalesTrendByAgeChart({ rows }: { rows: SalesTrendPoint[] }) {
  const [activePoint, setActivePoint] = useState<SalesTrendPoint | null>(null);
  const [mobileBatchId, setMobileBatchId] = useState("");
  const points = useMemo(() => aggregatePoints(rows), [rows]);

  if (!points.length) {
    return <p className="rounded-lg border border-dashed border-[var(--line)] p-5 text-sm text-[var(--navy-muted)]">No bird sales have been recorded from four weeks onward for the selected batches.</p>;
  }

  const width = 820;
  const height = 350;
  const left = 86;
  const right = 24;
  const top = 24;
  const bottom = 68;
  const minDay = 28;
  const maxDay = Math.max(minDay, ...points.map((row) => row.age_day));
  const maxRevenue = niceMaximum(Math.max(...points.map((row) => parseDecimal(row.revenue))));
  const x = (day: number) => left + ((day - minDay) / Math.max(maxDay - minDay, 1)) * (width - left - right);
  const y = (revenue: number) => top + (1 - revenue / maxRevenue) * (height - top - bottom);
  const xTicks = dayTicks(minDay, maxDay);
  const yTicks = Array.from({ length: 5 }, (_, index) => (maxRevenue / 4) * index);
  const batches = Array.from(new Map(points.map((row) => [row.batch_id, row.batch_code])).entries());
  const selectedMobileBatchId = mobileBatchId || String(batches[0][0]);
  const mobilePoints = points
    .filter((row) => String(row.batch_id) === selectedMobileBatchId)
    .sort((a, b) => a.age_day - b.age_day);
  const mobileWidth = 320;
  const mobileHeight = 210;
  const mobileLeft = 54;
  const mobileRight = 12;
  const mobileTop = 14;
  const mobileBottom = 42;
  const mobileMaxDay = Math.max(minDay, ...mobilePoints.map((row) => row.age_day));
  const mobileMaxRevenue = niceMaximum(Math.max(...mobilePoints.map((row) => parseDecimal(row.revenue))));
  const mobileX = (day: number) => mobileLeft + ((day - minDay) / Math.max(mobileMaxDay - minDay, 1)) * (mobileWidth - mobileLeft - mobileRight);
  const mobileY = (revenue: number) => mobileTop + (1 - revenue / mobileMaxRevenue) * (mobileHeight - mobileTop - mobileBottom);
  const mobileColor = chartColors[Math.max(0, batches.findIndex(([id]) => String(id) === selectedMobileBatchId)) % chartColors.length];
  const activeMobilePoint = activePoint && String(activePoint.batch_id) === selectedMobileBatchId ? activePoint : null;

  const tooltip = activePoint ? {
    x: x(activePoint.age_day),
    y: y(parseDecimal(activePoint.revenue)),
  } : null;
  const tooltipWidth = 230;
  const tooltipHeight = 86;
  const tooltipX = tooltip ? Math.max(left, Math.min(tooltip.x + 12, width - right - tooltipWidth)) : 0;
  const tooltipY = tooltip ? Math.max(top, Math.min(tooltip.y - tooltipHeight - 10, height - bottom - tooltipHeight)) : 0;

  return (
    <div>
      <div className="rounded-xl bg-white/35 p-2 sm:p-3 md:hidden">
        <label className="block text-xs font-extrabold uppercase tracking-[0.12em] text-[var(--navy-muted)]">
          Batch to display
          <select
            className="form-input mt-2 bg-white text-sm font-bold normal-case tracking-normal"
            value={selectedMobileBatchId}
            onChange={(event) => {
              setMobileBatchId(event.target.value);
              setActivePoint(null);
            }}
          >
            {batches.map(([id, code]) => <option key={id} value={String(id)}>{code}</option>)}
          </select>
        </label>
        <svg viewBox={`0 0 ${mobileWidth} ${mobileHeight}`} className="mt-3 h-auto w-full" role="img" aria-label="Selected batch sales revenue by flock age">
          {[0, mobileMaxRevenue / 2, mobileMaxRevenue].map((tick) => (
            <g key={tick}>
              <line x1={mobileLeft} x2={mobileWidth - mobileRight} y1={mobileY(tick)} y2={mobileY(tick)} stroke="#d9d3c6" strokeDasharray={tick === 0 ? undefined : "4 5"} />
              <text x={mobileLeft - 7} y={mobileY(tick) + 4} textAnchor="end" fontSize="10" fill="#6b7280">{compactCurrency(tick)}</text>
            </g>
          ))}
          <text x={mobileX(minDay)} y={mobileHeight - 14} textAnchor="start" fontSize="10" fontWeight="700" fill="#5f6674">Day {minDay}</text>
          <text x={mobileX(mobileMaxDay)} y={mobileHeight - 14} textAnchor="end" fontSize="10" fontWeight="700" fill="#5f6674">Day {mobileMaxDay}</text>
          <polyline
            fill="none"
            stroke={mobileColor}
            strokeWidth="3.5"
            strokeLinejoin="round"
            strokeLinecap="round"
            points={mobilePoints.map((point) => `${mobileX(point.age_day)},${mobileY(parseDecimal(point.revenue))}`).join(" ")}
          />
          {mobilePoints.map((point) => {
            const active = activeMobilePoint?.age_day === point.age_day;
            return (
              <circle
                key={`${point.batch_id}-${point.age_day}`}
                cx={mobileX(point.age_day)}
                cy={mobileY(parseDecimal(point.revenue))}
                r={active ? 7 : 6}
                fill="white"
                stroke={mobileColor}
                strokeWidth={active ? 4 : 3}
                role="button"
                tabIndex={0}
                aria-label={`Day ${point.age_day}, ${formatCurrency(point.revenue)}, ${formatNumber(point.quantity)} birds`}
                className="cursor-pointer outline-none"
                onClick={() => setActivePoint(active ? null : point)}
                onFocus={() => setActivePoint(point)}
                onBlur={() => setActivePoint(null)}
              />
            );
          })}
        </svg>
        <div className="mt-2 min-h-16 rounded-lg border border-[var(--line)] bg-white px-3 py-2 text-sm" aria-live="polite">
          {activeMobilePoint ? (
            <div className="grid grid-cols-2 gap-2">
              <span className="text-[var(--navy-muted)]">Day {activeMobilePoint.age_day} · {formatDate(activeMobilePoint.date)}</span>
              <strong className="text-right">{formatCurrency(activeMobilePoint.revenue)}</strong>
              <span className="col-span-2 text-xs text-[var(--navy-muted)]">{formatNumber(activeMobilePoint.quantity)} bird{activeMobilePoint.quantity === 1 ? "" : "s"} sold</span>
            </div>
          ) : <p className="text-xs leading-5 text-[var(--navy-muted)]">Tap a point to view its exact sale value and quantity.</p>}
        </div>
      </div>

      <div className="hidden overflow-hidden rounded-xl bg-white/35 p-3 md:block">
        <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label="Sales revenue by flock age from day 28 onward">
          {yTicks.map((tick) => (
            <g key={tick}>
              <line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} stroke="#d9d3c6" strokeDasharray={tick === 0 ? undefined : "4 5"} />
              <text x={left - 12} y={y(tick) + 4} textAnchor="end" fontSize="11" fill="#6b7280">{compactCurrency(tick)}</text>
            </g>
          ))}

          {xTicks.map((day) => (
            <g key={day}>
              <line x1={x(day)} x2={x(day)} y1={top} y2={height - bottom} stroke="#ede8de" />
              <text x={x(day)} y={height - bottom + 24} textAnchor="middle" fontSize="11" fontWeight="600" fill="#5f6674">Day {day}</text>
            </g>
          ))}
          <text x={(left + width - right) / 2} y={height - 14} textAnchor="middle" fontSize="11" fontWeight="700" fill="#747b8d">Flock age from four weeks onward</text>

          {batches.map(([batchId], index) => {
            const batchPoints = points.filter((row) => row.batch_id === batchId).sort((a, b) => a.age_day - b.age_day);
            const color = chartColors[index % chartColors.length];
            return (
              <g key={batchId}>
                <polyline
                  fill="none"
                  stroke={color}
                  strokeWidth="3.5"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  points={batchPoints.map((point) => `${x(point.age_day)},${y(parseDecimal(point.revenue))}`).join(" ")}
                />
                {batchPoints.map((point) => {
                  const active = activePoint?.batch_id === point.batch_id && activePoint.age_day === point.age_day;
                  return (
                    <circle
                      key={`${point.batch_id}-${point.age_day}`}
                      cx={x(point.age_day)}
                      cy={y(parseDecimal(point.revenue))}
                      r={active ? 7 : 5}
                      fill="white"
                      stroke={color}
                      strokeWidth={active ? 4 : 3}
                      tabIndex={0}
                      role="button"
                      aria-label={`${point.batch_code}, day ${point.age_day}, ${formatCurrency(point.revenue)}, ${formatNumber(point.quantity)} birds`}
                      className="cursor-pointer outline-none transition"
                      onMouseEnter={() => setActivePoint(point)}
                      onMouseLeave={() => setActivePoint(null)}
                      onFocus={() => setActivePoint(point)}
                      onBlur={() => setActivePoint(null)}
                      onClick={() => setActivePoint(active ? null : point)}
                    />
                  );
                })}
              </g>
            );
          })}

          {activePoint && tooltip ? (
            <g pointerEvents="none">
              <line x1={tooltip.x} x2={tooltip.x} y1={top} y2={height - bottom} stroke="#8b8272" strokeDasharray="3 4" />
              <rect x={tooltipX} y={tooltipY} width={tooltipWidth} height={tooltipHeight} rx="10" fill="#172443" opacity="0.97" />
              <text x={tooltipX + 14} y={tooltipY + 22} fontSize="12" fontWeight="800" fill="#ffffff">{activePoint.batch_code}</text>
              <text x={tooltipX + 14} y={tooltipY + 42} fontSize="11" fill="#e8e2d5">Day {activePoint.age_day} · {formatDate(activePoint.date)}</text>
              <text x={tooltipX + 14} y={tooltipY + 63} fontSize="12" fontWeight="800" fill="#ffffff">{formatCurrency(activePoint.revenue)}</text>
              <text x={tooltipX + 14} y={tooltipY + 78} fontSize="10" fill="#d4a642">{formatNumber(activePoint.quantity)} bird{activePoint.quantity === 1 ? "" : "s"} sold</text>
            </g>
          ) : null}
        </svg>
      </div>

      <div className="mt-3 hidden flex-wrap gap-x-5 gap-y-2 md:flex">
        {batches.map(([id, code], index) => (
          <span key={id} className="flex items-center gap-2 text-xs font-bold">
            <i className="h-2.5 w-6 rounded-full" style={{ backgroundColor: chartColors[index % chartColors.length] }} />
            {code}
          </span>
        ))}
      </div>
      <p className="mt-3 hidden text-xs text-[var(--navy-muted)] md:block">Hover, tap, or focus a point for the exact sale value and quantity.</p>
    </div>
  );
}
