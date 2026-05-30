"use client";

import { PieChart } from "lucide-react";
import { weeklyOverview } from "@/lib/planning-mock";

export function WeeklyPlanOverviewCard() {
  const total = weeklyOverview.reduce((acc, s) => acc + s.value, 0);
  // build donut as svg
  const r = 38;
  const stroke = 14;
  const c = 2 * Math.PI * r;
  // Precompute cumulative offsets so the render path is pure (no `let`
  // reassigned inside .map — the React compiler rejects that pattern).
  const lens = weeklyOverview.map((s) => (s.pct / 100) * c);
  const offsets = lens.reduce<number[]>((acc, _len, i) => {
    acc.push(i === 0 ? 0 : acc[i - 1] + lens[i - 1]);
    return acc;
  }, []);

  return (
    <div className="card col-span-12 md:col-span-3 p-4">
      <div className="flex items-center gap-2 mb-3">
        <span
          className="w-6 h-6 rounded-md flex items-center justify-center"
          style={{ background: "var(--color-edify-soft)", color: "var(--color-edify-primary)" }}
        >
          <PieChart size={13} />
        </span>
        <h3 className="text-body-lg font-bold">This Week&apos;s Plan Overview</h3>
      </div>
      <div className="flex items-center gap-4">
        <div className="relative w-[110px] h-[110px] shrink-0">
          <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
            {weeklyOverview.map((s, i) => {
              const len = lens[i];
              const dasharray = `${len} ${c - len}`;
              return (
                <circle
                  key={s.label}
                  cx="50"
                  cy="50"
                  r={r}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={stroke}
                  strokeDasharray={dasharray}
                  strokeDashoffset={-offsets[i]}
                />
              );
            })}
            <circle
              cx="50"
              cy="50"
              r={r - stroke / 2 - 4}
              fill="white"
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center leading-tight">
            <div className="text-[18px] font-extrabold tabular">{total}</div>
            <div className="text-[10px] muted">Total</div>
          </div>
        </div>
        <div className="flex-1 min-w-0 space-y-1.5">
          {weeklyOverview.map((s) => (
            <div key={s.label} className="flex items-center gap-2 text-[12px]">
              <span
                className="w-2.5 h-2.5 rounded-sm shrink-0"
                style={{ background: s.color }}
              />
              <span className="font-medium">{s.label}</span>
              <span className="ml-auto tabular font-semibold">
                {s.value}{" "}
                <span className="muted font-normal">({s.pct}%)</span>
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
