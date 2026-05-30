"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  Building2,
  GraduationCap,
  Handshake,
  School,
  ShieldCheck,
  Sparkles,
  Trophy,
  Users,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  teamCategoryProgress,
  type TeamCategoryProgressRow,
  type TeamCategoryRowStatus,
} from "@/lib/team-targets-billion-mock";
import { cn } from "@/lib/utils";

const ICON_FOR: Record<TeamCategoryProgressRow["icon"], LucideIcon> = {
  staffVisit:   School,
  partnerVisit: Handshake,
  training:     GraduationCap,
  cluster:      Users,
  msc:          Sparkles,
  exam:         Trophy,
  ssa:          ShieldCheck,
};

const STATUS_TONE: Record<TeamCategoryRowStatus, string> = {
  "Critical":        "bg-rose-50    text-rose-700",
  "On Track":        "bg-emerald-50 text-emerald-700",
  "Slightly Behind": "bg-amber-50   text-amber-700",
};

function barColor(pct: number): string {
  if (pct >= 80) return "#10b981";
  if (pct >= 50) return "#f59e0b";
  return "#ef4444";
}

// Team-aggregated category matrix — 7 rows × 5 progress columns
// (Category · FY · Q4 · May · This Week · Target/Achieved · Status).
// Identical visual grammar to the my-targets matrix so a Program Lead
// who switches between My Targets and Team Targets reads the same
// pattern.
export function TeamKeyTargetsProgressCard() {
  return (
    <SectionCard
      icon={<Building2 size={13} />}
      title="Key Team Targets Progress"
      subtitle="Each row is one activity category tracked across the FY, quarter, month, and current week — aggregated across all supervised staff."
      actions={
        <Link
          href="/team-targets"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View full breakdown
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      {/* Desktop matrix */}
      <div className="hidden lg:block rounded-xl border border-[var(--color-edify-border)] bg-white overflow-hidden">
        <div className="max-h-[420px] overflow-y-auto overflow-x-auto scrollbar">
          <div className="min-w-[760px]">
            <div className="grid grid-cols-[1.5fr_1fr_1fr_1fr_72px_120px_96px] gap-2 px-3 py-2 bg-gradient-to-r from-[var(--color-edify-soft)] to-[var(--color-edify-soft)]/40 text-[9.5px] uppercase tracking-wide text-slate-600 font-bold sticky top-0 z-[1]">
              <div>Category</div>
              <div>FY Progress</div>
              <div>Q4 Progress</div>
              <div>May Progress</div>
              <div className="text-right">Week</div>
              <div className="text-right">Target / Achieved</div>
              <div>Status</div>
            </div>
            <div className="divide-y divide-[var(--color-edify-divider)]">
              {teamCategoryProgress.map((r) => {
                const Icon = ICON_FOR[r.icon];
                return (
                  <div
                    key={r.key}
                    className="grid grid-cols-[1.5fr_1fr_1fr_1fr_72px_120px_96px] gap-2 px-3 py-2.5 items-center text-[11.5px] hover:bg-[var(--color-edify-soft)]/40 transition-colors"
                  >
                    <div className="inline-flex items-center gap-1.5 min-w-0">
                      <Icon size={13} className="text-[var(--color-edify-muted)] shrink-0" />
                      <span className="font-bold text-slate-900 leading-tight truncate">{r.category}</span>
                    </div>
                    <PctCell pct={r.fyPct}  />
                    <PctCell pct={r.q4Pct}  />
                    <PctCell pct={r.mayPct} />
                    <WeekCell pct={r.weekPct} />
                    <div className="text-right tabular font-bold text-slate-700 whitespace-nowrap">
                      {r.targetAchieved}
                    </div>
                    <div>
                      <span className={cn("inline-flex items-center px-2 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", STATUS_TONE[r.status])}>
                        {r.status}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Mobile + tablet — stacked cards (1 per category) */}
      <div className="lg:hidden space-y-2">
        {teamCategoryProgress.map((r) => {
          const Icon = ICON_FOR[r.icon];
          return (
            <div
              key={r.key}
              className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3 space-y-2.5"
            >
              <div className="flex items-center gap-2.5">
                <span className="w-8 h-8 rounded-lg bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                  <Icon size={14} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-extrabold leading-tight text-slate-900 truncate">
                    {r.category}
                  </div>
                  <div className="text-caption muted font-semibold leading-tight mt-0.5">
                    Target / Achieved: <span className="font-bold text-slate-700">{r.targetAchieved}</span>
                  </div>
                </div>
                <span className={cn("inline-flex items-center px-2 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap shrink-0", STATUS_TONE[r.status])}>
                  {r.status}
                </span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <MobilePctRow label="FY"    pct={r.fyPct} />
                <MobilePctRow label="Q4"    pct={r.q4Pct} />
                <MobilePctRow label="May"   pct={r.mayPct} />
                <MobilePctRow label="Week"  pct={r.weekPct} />
              </div>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}

// ───────────── PctCell ─────────────

function PctCell({ pct }: { pct: number }) {
  const color = barColor(pct);
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="text-caption font-extrabold tabular w-[28px] text-right whitespace-nowrap text-slate-700">
        {pct}%
      </span>
    </div>
  );
}

function WeekCell({ pct }: { pct: number | null }) {
  if (pct === null) {
    return <div className="text-right tabular text-[11px] muted font-semibold">—</div>;
  }
  const color = barColor(pct);
  return (
    <div className="text-right tabular text-[11px] font-extrabold whitespace-nowrap" style={{ color }}>
      {pct}%
    </div>
  );
}

function MobilePctRow({ label, pct }: { label: string; pct: number | null }) {
  if (pct === null) {
    return (
      <div className="flex items-center gap-2 text-[11px]">
        <span className="text-[9.5px] uppercase tracking-wide muted font-bold w-[42px] shrink-0">{label}</span>
        <span className="muted">—</span>
      </div>
    );
  }
  const color = barColor(pct);
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="text-[9.5px] uppercase tracking-wide muted font-bold w-[42px] shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-[11px] font-extrabold tabular w-[32px] text-right whitespace-nowrap" style={{ color }}>
        {pct}%
      </span>
    </div>
  );
}
