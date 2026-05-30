import Link from "next/link";
import { GraduationCap, ShieldCheck, ShieldAlert, Clock, ChevronRight } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { trainingDataQualityStats } from "@/lib/training-stats";

// Training data-quality card for the IA dashboard.
//
// Mirrors how IA already tracks visit evidence: completed trainings
// either have full evidence (roster + materials + post-assessment),
// are pending IA verification, or have been flagged. This is the
// training-specific cut of the verification funnel — without it,
// trainings sit in the system uncounted in the IA quality picture.

export function TrainingDataQualityCard() {
  const stats = trainingDataQualityStats();

  return (
    <SectionCard
      icon={<GraduationCap size={13} />}
      title="Training Data Quality"
      subtitle="Verification funnel for completed cohorts. Roster + materials + post-assessment must land before a training counts in official reporting."
      actions={
        <Link
          href="/data-verification?type=training"
          className="text-[11.5px] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-1"
        >
          Open Queue
          <ChevronRight size={12} />
        </Link>
      }
    >
      <div className="space-y-3">
        <Row
          icon={<ShieldCheck size={14} />}
          label="Full Evidence"
          value={stats.withFullEvidence}
          denom={stats.totalCompleted}
          tone="green"
          caption="Roster + materials + post-assessment all on file"
        />
        <Row
          icon={<Clock size={14} />}
          label="Awaiting Verification"
          value={stats.pendingVerification}
          denom={stats.totalCompleted}
          tone="amber"
          caption="Evidence uploaded, IA spot-check pending"
        />
        <Row
          icon={<ShieldAlert size={14} />}
          label="Flagged / failed QC"
          value={stats.failedQc}
          denom={stats.totalCompleted}
          tone="rose"
          caption="Missing roster or contested attendance"
        />

        <div className="mt-3 pt-3 border-t border-[var(--color-edify-divider)] flex items-baseline justify-between">
          <span className="text-[11.5px] muted">
            Evidence rate · {stats.totalCompleted} completed cohort{stats.totalCompleted === 1 ? "" : "s"}
          </span>
          <span
            className={
              stats.evidencePct >= 80 ? "text-body-lg font-extrabold tabular text-emerald-700"
              : stats.evidencePct >= 60 ? "text-body-lg font-extrabold tabular text-amber-700"
              : "text-body-lg font-extrabold tabular text-rose-700"
            }
          >
            {stats.evidencePct}%
          </span>
        </div>
      </div>
    </SectionCard>
  );
}

function Row({
  icon, label, value, denom, tone, caption,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  denom: number;
  tone: "green" | "amber" | "rose";
  caption: string;
}) {
  const pct = denom === 0 ? 0 : Math.round((value / denom) * 100);
  const bar =
    tone === "green" ? "bg-emerald-500"
    : tone === "amber" ? "bg-amber-500"
    : "bg-rose-500";
  const iconBg =
    tone === "green" ? "bg-emerald-100 text-emerald-700"
    : tone === "amber" ? "bg-amber-100 text-amber-700"
    : "bg-rose-100 text-rose-700";
  return (
    <div className="flex items-start gap-3">
      <span className={`h-7 w-7 rounded-md grid place-items-center shrink-0 ${iconBg}`}>{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-body font-semibold">{label}</span>
          <span className="text-body font-extrabold tabular">{value}<span className="text-caption muted font-normal"> / {denom}</span></span>
        </div>
        <div className="pill-row mt-1">
          <span className={bar} style={{ width: `${pct}%` }} />
        </div>
        <div className="text-caption muted mt-1">{caption}</div>
      </div>
    </div>
  );
}
