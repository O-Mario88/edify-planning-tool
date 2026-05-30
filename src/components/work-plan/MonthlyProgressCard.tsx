"use client";

import Link from "next/link";
import { ChevronRight, ArrowRight } from "lucide-react";
import { monthlyProgress } from "@/lib/work-plan-mock";

export function MonthlyProgressCard() {
  return (
    <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-4">
      <div className="flex items-start justify-between">
        <h3 className="text-[15px] font-extrabold tracking-tight">Monthly Progress Overview</h3>
        <Link href="/my-targets" className="text-[var(--color-edify-muted)]" aria-label="See details">
          <ChevronRight size={18} />
        </Link>
      </div>

      <div className="mt-3 flex items-center gap-4">
        <Ring pct={monthlyProgress.overallPercent} />
        <div className="grid grid-cols-4 gap-2 flex-1 text-center">
          <Stat value={monthlyProgress.total}      label="Tasks Total"  tone="text-[var(--color-edify-text)]" />
          <Stat value={monthlyProgress.completed}  label="Completed"    tone="text-emerald-600" />
          <Stat value={monthlyProgress.inProgress} label="In Progress" tone="text-blue-600" />
          <Stat value={monthlyProgress.overdue}    label="Overdue"      tone="text-rose-600" />
        </div>
      </div>

      <div className="mt-4 h-2 rounded-full bg-[#eef2f4] overflow-hidden">
        <div
          className="h-full rounded-full bg-emerald-500"
          style={{ width: `${monthlyProgress.overallPercent}%` }}
        />
      </div>

      <div className="mt-3 flex items-center justify-between">
        <div className="leading-tight">
          <div className="inline-flex items-center gap-1.5 text-body font-bold text-emerald-600">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
            {monthlyProgress.status}
          </div>
          <div className="text-[11.5px] muted mt-0.5">{monthlyProgress.message}</div>
        </div>
        <Link
          href="/my-targets"
          className="inline-flex items-center gap-1 text-body font-semibold text-emerald-600"
        >
          View Details
          <ArrowRight size={12} />
        </Link>
      </div>
    </section>
  );
}

function Stat({ value, label, tone }: { value: number; label: string; tone: string }) {
  return (
    <div className="leading-tight">
      <div className={`text-[20px] font-extrabold tabular leading-none ${tone}`}>{value}</div>
      <div className="text-caption muted font-semibold mt-1 leading-tight">{label}</div>
    </div>
  );
}

function Ring({ pct }: { pct: number }) {
  const size = 96;
  const stroke = 9;
  const r = size / 2 - stroke;
  const c = 2 * Math.PI * r;
  const off = c * (1 - pct / 100);
  return (
    <span className="relative inline-block shrink-0" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#eef2f4" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="#10b981"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={off}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center leading-tight">
        <span className="text-center">
          <span className="block text-[22px] font-extrabold tabular leading-none">{pct}%</span>
          <span className="block text-[10px] muted font-semibold mt-1">Overall</span>
        </span>
      </span>
    </span>
  );
}
