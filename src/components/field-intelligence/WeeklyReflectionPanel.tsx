"use client";

import {
  CalendarRange,
  Target,
  ShieldCheck,
  Trophy,
  AlertTriangle,
  Building2,
  CheckCircle2,
  Sparkles,
  Compass,
  type LucideIcon,
} from "lucide-react";
import { type WeeklyStaffSummary, type SupportRequest } from "@/lib/field-intelligence-mock";
import { cn } from "@/lib/utils";

const SUPPORT_ICON: Partial<Record<SupportRequest, LucideIcon>> = {
  "School Contact Update": Building2,
  "Salesforce Support":    ShieldCheck,
  "Rescheduling Help":     CalendarRange,
};

export function WeeklyReflectionPanel({
  summary,
  staffName,
}: {
  summary: WeeklyStaffSummary;
  staffName: string;
}) {
  return (
    <article className="card rounded-2xl flex flex-col">
      {/* Header */}
      <header className="px-4 pt-4 pb-3 flex items-start gap-2">
        <span className="h-7 w-7 rounded-md bg-sky-100 text-sky-700 grid place-items-center shrink-0">
          <CalendarRange size={14} />
        </span>
        <div className="min-w-0">
          <h2 className="text-[15px] font-extrabold tracking-tight">My Weekly Reflection</h2>
          <div className="text-[11px] muted leading-tight mt-0.5">
            <span className="font-semibold text-[var(--color-edify-text)]">{staffName}</span>
            {" · "}Week of {summary.weekStart} → {summary.weekEnd}
          </div>
        </div>
      </header>

      {/* Achievement cards */}
      <section className="mx-4 grid grid-cols-2 gap-2 mt-1">
        <ReflectStat
          Icon={Target}
          label="Raw Achievement"
          value={`${summary.rawAchievementPercent}%`}
          caption={`${summary.verifiedActivities}/${summary.plannedActivities} verified`}
          tone="violet"
        />
        <ReflectStat
          Icon={ShieldCheck}
          label="Context-Adjusted"
          value={`${summary.contextAdjustedAchievementPercent}%`}
          caption="Protected field constraints applied"
          tone="green"
        />
      </section>

      {/* Top success */}
      <section className="mx-4 mt-3 flex items-start gap-2.5">
        <span className="h-7 w-7 rounded-md bg-emerald-100 text-emerald-700 grid place-items-center shrink-0 mt-0.5">
          <Trophy size={13} />
        </span>
        <div className="min-w-0">
          <div className="text-[10px] muted font-bold tracking-wide uppercase">Top Success</div>
          <div className="text-[12px] leading-snug mt-0.5">{summary.topSuccess}</div>
        </div>
      </section>

      {/* Top barrier */}
      <section className="mx-4 mt-3 flex items-start gap-2.5">
        <span className="h-7 w-7 rounded-md bg-rose-100 text-rose-700 grid place-items-center shrink-0 mt-0.5">
          <AlertTriangle size={13} />
        </span>
        <div className="min-w-0">
          <div className="text-[10px] muted font-bold tracking-wide uppercase">Top Barrier</div>
          <div className="text-[12px] leading-snug mt-0.5">{summary.topBarrier}</div>
        </div>
      </section>

      {/* Support requested */}
      {summary.supportRequested.length > 0 && (
        <section className="mx-4 mt-3 flex items-start gap-2.5">
          <span className="h-7 w-7 rounded-md bg-slate-100 text-slate-700 grid place-items-center shrink-0 mt-0.5">
            <Compass size={13} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[10px] muted font-bold tracking-wide uppercase">Support Requested</div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {summary.supportRequested.map((s) => {
                const Icon = SUPPORT_ICON[s] ?? Compass;
                return (
                  <span
                    key={s}
                    className="inline-flex items-center gap-1.5 rounded-full bg-sky-50 border border-sky-200 text-sky-700 px-2 py-0.5 text-caption font-semibold"
                  >
                    <Icon size={10} />
                    {s}
                  </span>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {/* Recommended next-week actions */}
      {summary.recommendedActions.length > 0 && (
        <section className="mx-4 mt-3 rounded-xl border border-[var(--color-edify-border)] p-3">
          <div className="text-[12px] font-extrabold tracking-tight mb-1.5">
            Recommended Next-Week Actions
          </div>
          <ul className="space-y-1.5">
            {summary.recommendedActions.map((a) => (
              <li key={a} className="flex items-start gap-2 text-[11.5px]">
                <CheckCircle2 size={12} className="text-emerald-600 mt-0.5 shrink-0" />
                <span className="leading-snug">{a}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Leadership signal */}
      <section className="mx-4 mt-3 mb-4 rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/50 p-3">
        <div className="flex items-center gap-1.5 mb-1">
          <Sparkles size={12} className="text-[var(--color-edify-primary)]" />
          <h3 className="text-[12px] font-extrabold tracking-tight">Leadership Signal</h3>
        </div>
        <p className="text-[11px] leading-snug muted">
          Strong execution in verified visits this week. Raw-to-context gap suggests data quality
          and external constraints are main risks. Protect verification momentum while addressing
          early closures.
        </p>
        <div className="mt-2 inline-flex items-center gap-1.5 text-[10px] muted">
          <Sparkles size={10} />
          AI-generated insight
        </div>
      </section>
    </article>
  );
}

function ReflectStat({
  Icon,
  label,
  value,
  caption,
  tone,
}: {
  Icon: LucideIcon;
  label: string;
  value: string;
  caption: string;
  tone: "violet" | "green";
}) {
  const styles =
    tone === "violet"
      ? "bg-violet-50 border-violet-200 text-violet-700"
      : "bg-emerald-50 border-emerald-200 text-emerald-700";
  return (
    <div className={cn("rounded-xl border p-2.5 relative overflow-hidden", styles)}>
      <div className="text-caption font-semibold leading-tight">{label}</div>
      <div className="text-[24px] font-extrabold tabular leading-none mt-1 text-[var(--color-edify-text)]">
        {value}
      </div>
      <div className="text-[9.5px] muted mt-1 line-clamp-1">{caption}</div>
      <span className="absolute right-2 top-2 h-7 w-7 rounded-md bg-white grid place-items-center">
        <Icon size={13} />
      </span>
    </div>
  );
}
