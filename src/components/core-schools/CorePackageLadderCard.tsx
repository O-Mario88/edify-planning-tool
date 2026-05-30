"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  CalendarCheck,
  GraduationCap,
  Layers,
  ShieldCheck,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  type CorePackageSummary,
  remainingCorePackageTasks,
  type CoreSchoolRow,
} from "@/lib/core-schools-mock";
import { cn } from "@/lib/utils";

export function CorePackageLadderCard({
  s,
  schools,
}: {
  s: CorePackageSummary;
  schools: CoreSchoolRow[];
}) {
  const total = Math.max(s.totalCoreSchools, 1);
  const remaining = remainingCorePackageTasks(schools);

  // Editorial computations — pure progress story now. The four rungs
  // climb from 1V+1T → 4V+4T; the zero-floor counts live in the KPI
  // Strip's Risk Triage above this card, so showing them again here
  // would be data duplication.
  const ladder = [
    { label: "1 Visit + 1 Training",        value: s.coreSchoolsWithOneVisitOneTraining,          tone: "watch" as const, dot: "bg-amber-400"  },
    { label: "2 Visits + 2 Trainings",      value: s.coreSchoolsWithTwoVisitsTwoTrainings,        tone: "watch" as const, dot: "bg-amber-500"  },
    { label: "3 Visits + 3 Trainings",      value: s.coreSchoolsWithThreeVisitsThreeTrainings,    tone: "good"  as const, dot: "bg-emerald-400" },
    { label: "4 Visits + 4 Trainings",      value: s.coreSchoolsWithFourVisitsFourTrainings,      tone: "good"  as const, dot: "bg-emerald-600" },
  ];

  // Editorial headline — surface progress, not the zero-floor (that
  // lives in the Risk Triage above).
  const complete    = s.coreSchoolsWithFourVisitsFourTrainings;
  const nearly      = s.coreSchoolsWithThreeVisitsThreeTrainings;
  const completePct = Math.round((complete / total) * 100);
  const progressed  = ladder.reduce((a, r) => a + r.value, 0);
  const progressedPct = Math.round((progressed / total) * 100);

  const headline = `${complete} of ${total} schools (${completePct}%) have the full 4-visits + 4-trainings package · ${nearly} are one step away (3V+3T) · ${progressedPct}% of schools are progressing on the ladder.`;

  return (
    <SectionCard
      icon={<Layers size={13} />}
      title="Core Package Completion"
      subtitle={headline}
      actions={
        <Link
          href="/schools"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      <div className="space-y-2">
        {ladder.map((row) => (
          <div key={row.label} className="grid grid-cols-[180px_1fr_72px] items-center gap-2">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className={cn("w-2 h-2 rounded-full shrink-0", row.dot)} />
              <span className="text-[12px] font-semibold truncate">{row.label}</span>
            </div>
            <div className="h-3 rounded-full bg-[#eef2f4] overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-[width] duration-500",
                  row.tone === "watch" ? "bg-amber-300" : "bg-emerald-300",
                )}
                style={{ width: `${(row.value / total) * 100}%` }}
              />
            </div>
            <div className="text-right tabular text-body font-bold">
              {row.value}
              <span className="muted font-medium">/{total}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 pt-3 border-t border-[#eef2f4]">
        <div className="text-caption uppercase tracking-[0.12em] muted font-bold mb-2">
          Remaining Core Package Tasks
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
          <RemainingStat
            icon={CalendarCheck}
            label="Need more visits"
            value={remaining.needMoreVisits}
            tone="watch"
          />
          <RemainingStat
            icon={GraduationCap}
            label="Need more trainings"
            value={remaining.needMoreTrainings}
            tone="watch"
          />
          <RemainingStat
            icon={ShieldCheck}
            label="Need final verification"
            value={remaining.needFinalVerification}
            tone="good"
          />
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Sparkles size={12} className="text-emerald-600" />
          <span className="font-bold">Push the leaders:</span>
          <span className="muted">{nearly} schools at 3V+3T are one visit + one training away from full package.</span>
        </span>
      </div>
    </SectionCard>
  );
}

// ───────────── RemainingStat ─────────────

type RemainingTone = "good" | "watch";

const REM_TONE: Record<RemainingTone, { bg: string; iconBg: string; iconColor: string }> = {
  good:  { bg: "bg-gradient-to-br from-emerald-50 to-white border-emerald-200", iconBg: "bg-emerald-100", iconColor: "text-emerald-700" },
  watch: { bg: "bg-gradient-to-br from-amber-50 to-white border-amber-200",     iconBg: "bg-amber-100",   iconColor: "text-amber-700"   },
};

function RemainingStat({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: LucideIcon;
  label: string;
  value: number;
  tone: RemainingTone;
}) {
  const p = REM_TONE[tone];
  return (
    <div className={cn("rounded-lg border p-2.5 flex items-start gap-2", p.bg)}>
      <span className={cn("w-8 h-8 rounded-lg grid place-items-center shrink-0", p.iconBg)}>
        <Icon size={13} className={p.iconColor} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-caption muted font-bold uppercase tracking-wide leading-tight">
          {label}
        </div>
        <div className="text-[18px] font-extrabold tabular leading-none mt-1">{value}</div>
      </div>
    </div>
  );
}
