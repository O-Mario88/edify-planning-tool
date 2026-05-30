"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  Building2,
  CheckCircle2,
  ShieldCheck,
  Sparkles,
  Star,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { ActionButton } from "@/components/ui/ActionButton";
import { type CoreSchoolRow } from "@/lib/core-schools-mock";
import { cn } from "@/lib/utils";

// Champion Recommendations is the *action surface* — every row carries
// a primary "Recommend for Review" button and a secondary "View School"
// link. Sits next to BestCoreSchoolsCard so the reading pattern is
// "celebrate the leaders" → "act on the candidates".
export function ChampionRecommendationsCard({ schools }: { schools: CoreSchoolRow[] }) {
  const candidates = schools.filter(
    (s) => s.championStatus === "Potential Champion" || s.championStatus === "Recommended as Champion",
  );

  // Editorial computations.
  const recommended = candidates.filter((s) => s.championStatus === "Recommended as Champion").length;
  const potential   = candidates.filter((s) => s.championStatus === "Potential Champion").length;
  const top         = [...candidates].sort(
    (a, b) => (b.latestVerifiedSsaAverage ?? 0) - (a.latestVerifiedSsaAverage ?? 0),
  )[0];

  const headline = top
    ? `${top.schoolName} leads candidates at SSA ${top.latestVerifiedSsaAverage?.toFixed(1) ?? "—"}. ${recommended} recommended · ${potential} potential — Program Lead approval required.`
    : `No recommendations yet for this cohort.`;

  return (
    <SectionCard
      icon={<Star size={13} className="text-violet-700" />}
      title="Champion School Recommendations"
      subtitle={headline}
      actions={
        <Link
          href="/ssa/core-candidates"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      {candidates.length === 0 ? (
        <div className="text-[12px] muted text-center py-6 flex items-center justify-center gap-1.5">
          <CheckCircle2 size={13} className="text-emerald-600" />
          No recommendations yet for this cohort.
        </div>
      ) : (
        <div className="space-y-2.5">
          {candidates.map((s) => {
            const isRecommended = s.championStatus === "Recommended as Champion";
            return (
              <div
                key={s.schoolId}
                className={cn(
                  "rounded-xl border border-l-[3px] p-3 transition-colors",
                  isRecommended
                    ? "border-emerald-200 border-l-emerald-500 bg-emerald-50/40"
                    : "border-violet-200 border-l-violet-500 bg-gradient-to-br from-violet-50/60 to-white",
                )}
              >
                <div className="flex items-start gap-3 flex-wrap">
                  <span className={cn(
                    "w-10 h-10 rounded-xl grid place-items-center shrink-0",
                    isRecommended
                      ? "bg-gradient-to-br from-emerald-500 to-emerald-700 text-white shadow-[0_4px_12px_-2px_rgba(16,185,129,0.45)]"
                      : "bg-gradient-to-br from-violet-500 to-violet-700 text-white shadow-[0_4px_12px_-2px_rgba(124,58,237,0.4)]",
                  )}>
                    <Star size={16} />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <div className="text-[13px] font-extrabold leading-tight text-slate-900">{s.schoolName}</div>
                      <span className={cn(
                        "inline-flex items-center px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold uppercase tracking-wide",
                        isRecommended
                          ? "bg-emerald-100 text-emerald-800"
                          : "bg-violet-100 text-violet-800",
                      )}>
                        {isRecommended ? "Recommended" : "Potential"}
                      </span>
                    </div>
                    <div className="text-caption muted leading-snug inline-flex items-center gap-1 mt-0.5">
                      <Building2 size={10} />
                      {s.district} · CCEO {s.assignedCceoName}
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-2 max-w-[320px]">
                      <MiniMetric label="SSA" value={s.latestVerifiedSsaAverage?.toFixed(1) ?? "—"} tone="emerald" />
                      <MiniMetric label="Visits" value={`${s.visitsCompleted}/4`} tone="slate" />
                      <MiniMetric label="Trainings" value={`${s.trainingsCompleted}/4`} tone="slate" />
                    </div>
                    <div className="text-[11px] muted mt-2 leading-snug">
                      {s.recommendedNextAction}
                    </div>
                  </div>
                  <div className="flex flex-col gap-1.5 shrink-0">
                    <ActionButton
                      Icon={ShieldCheck}
                      label={isRecommended ? "Push to Review" : "Recommend for Review"}
                      className="btn btn-sm btn-primary inline-flex items-center gap-1.5"
                      ariaLabel={`Recommend ${s.schoolName} for Champion review`}
                      oneShot
                      oneShotLabel="Submitted"
                      toast={{
                        tone: "success",
                        title: `Recommended ${s.schoolName}`,
                        body: "Submitted to Program Lead for Champion School review.",
                      }}
                    />
                    <Link
                      href={`/schools/${s.schoolId}`}
                      className="btn btn-sm inline-flex items-center justify-center gap-1"
                      aria-label={`Open ${s.schoolName} profile`}
                    >
                      View school
                    </Link>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Sparkles size={12} className="text-amber-500" />
          <span className="font-bold">Approval-only:</span>
          <span className="muted">Champion conversion never auto-fires — Program Lead must approve every promotion.</span>
        </span>
      </div>
    </SectionCard>
  );
}

// ───────────── MiniMetric ─────────────

function MiniMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "emerald" | "slate";
}) {
  return (
    <div className={cn(
      "rounded-md px-2 py-1.5 text-center border",
      tone === "emerald"
        ? "bg-emerald-50 border-emerald-200"
        : "bg-white border-[var(--color-edify-border)]",
    )}>
      <div className="text-[9.5px] uppercase tracking-wide font-bold text-slate-500">{label}</div>
      <div className={cn(
        "text-body-lg font-extrabold tabular leading-tight mt-0.5",
        tone === "emerald" ? "text-emerald-700" : "text-slate-900",
      )}>
        {value}
      </div>
    </div>
  );
}
