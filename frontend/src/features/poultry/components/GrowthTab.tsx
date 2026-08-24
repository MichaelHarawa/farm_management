"use client";

import { formatNumber } from "../utils/formatters";
import type { PoultryBatch, WeightSamplesResponse } from "../types";

type GrowthTabProps = {
  batch: PoultryBatch;
  weightSamplesResp: WeightSamplesResponse | null;
  onWeighIn: () => void;
  refreshSamples?: () => Promise<void>;
};

export function GrowthTab({
  batch,
  weightSamplesResp,
  onWeighIn,
}: GrowthTabProps) {
  const strain = weightSamplesResp?.strain ?? (batch.bird_type === "broilers" ? (batch.broiler_strain || "ross308") : "n/a");
  const status = weightSamplesResp?.latest_status ?? null;
  const series = weightSamplesResp?.series ?? [];

  const hasData = series.length > 0;

  return (
    <div className="mt-6 grid gap-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-[#747b8d]">
            Growth tracking • {formatLabelStrain(strain)}
          </p>
          <h3 className="mt-1 text-2xl font-extrabold tracking-tight">Live weight vs target curve</h3>
        </div>
        <button
          type="button"
          onClick={onWeighIn}
          className="rounded-full bg-[#151f36] px-4 py-2 text-xs font-extrabold uppercase tracking-[0.12em] text-white transition hover:bg-[#22345f]"
        >
          Record weigh-in
        </button>
      </div>

      {!hasData ? (
        <div className="rounded-lg border border-dashed border-[#ddd7c9] bg-white/60 p-6 text-sm text-[#747b8d]">
          No weight samples yet. Click “Record weigh-in” to start comparing against the
          {batch.bird_type === "broilers" ? " selected broiler strain target curve" : " expected growth for this species"}.
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-5">
          <div className="lg:col-span-3">
            <div className="overflow-auto rounded-xl border border-[#ddd7c9] bg-white p-4">
              <table className="min-w-[620px] w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-[#747b8d]">
                    <th className="py-2 pr-3">Age (d)</th>
                    <th className="py-2 pr-3 text-right">Actual (g)</th>
                    <th className="py-2 pr-3 text-right">Target (g)</th>
                    <th className="py-2 pr-3 text-right">Deviation</th>
                    <th className="py-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {series.map((p, idx) => (
                    <tr key={idx} className="border-b last:border-0">
                      <td className="py-2 pr-3 font-semibold">{formatNumber(p.age_in_days)}</td>
                      <td className="py-2 pr-3 text-right font-extrabold">{formatNumber(p.actual_g)}</td>
                      <td className="py-2 pr-3 text-right text-[#747b8d]">{p.target_g ? formatNumber(p.target_g) : "—"}</td>
                      <td className={`py-2 pr-3 text-right font-extrabold ${p.deviation_pct != null && p.deviation_pct < 0 ? "text-[#b24a43]" : "text-[#151926]"}`}>
                        {p.deviation_pct != null ? `${p.deviation_pct.toFixed(1)}%` : "—"}
                      </td>
                      <td className="py-2">
                        <span className={`inline-block rounded px-2 py-0.5 text-[10px] font-extrabold uppercase tracking-[0.1em] ${
                          p.severity === "urgent" ? "bg-red-100 text-red-700" :
                          p.severity === "action" ? "bg-amber-100 text-amber-800" :
                          p.severity === "watch" ? "bg-yellow-100 text-yellow-800" :
                          "bg-emerald-100 text-emerald-700"
                        }`}>
                          {p.severity}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="lg:col-span-2">
            <div className="rounded-xl border border-[#ddd7c9] bg-white p-5">
              <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-[#747b8d]">Latest status</p>
              {!status ? (
                <p className="mt-3 text-sm text-[#747b8d]">No status available yet.</p>
              ) : (
                <div className="mt-3 space-y-3">
                  <div>
                    <div className="text-3xl font-extrabold tracking-tighter">
                      {formatNumber(status.average_weight_g)} <span className="text-base font-semibold text-[#747b8d]">g</span>
                    </div>
                    <div className="mt-1 text-sm">
                      Day {formatNumber(status.age_in_days)} • {status.sample_size} birds weighed
                    </div>
                  </div>

                  <div>
                    <div className={`inline-flex rounded px-3 py-1 text-xs font-extrabold uppercase tracking-[0.12em] ${
                      status.severity === "urgent" ? "bg-[#b24a43] text-white" :
                      status.severity === "action" ? "bg-[#a66b00] text-white" :
                      status.severity === "watch" ? "bg-[#e1aa3f] text-[#151926]" :
                      "bg-[#4e8b61] text-white"
                    }`}>
                      {status.severity.toUpperCase()}
                    </div>
                    <p className="mt-2 text-sm leading-6 text-[#151926]">{status.message}</p>
                  </div>

                  <ul className="mt-3 list-disc pl-5 text-sm text-[#747b8d]">
                    {status.recommended_actions.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <p className="text-[11px] text-[#747b8d]">
        Target curves: Ross 308 / Cobb 500 (day 0–42). For non-broilers the system records samples but does not compare against a standard curve.
      </p>
    </div>
  );
}

function formatLabelStrain(s: string) {
  if (!s || s === "n/a") return "N/A";
  if (s === "ross308") return "Ross 308";
  if (s === "cobb500") return "Cobb 500";
  return s;
}
