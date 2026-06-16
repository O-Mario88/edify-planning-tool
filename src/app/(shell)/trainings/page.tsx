"use client";

import { useState } from "react";
import Link from "next/link";
import { GraduationCap, Building2 } from "lucide-react";
import { EntityIndex } from "@/components/shell/EntityIndex";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { StatusBadge, type ChipTone } from "@/components/ui/primitives";
import { TRAININGS, type TrainingStatus } from "@/lib/training-mock";
import { shortStatusLabel, fullStatusLabel } from "@/lib/status-labels";
import { ConfirmCompletionButton } from "@/components/my-targets/ConfirmCompletionButton";
import { cn } from "@/lib/utils";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

// Training status → ChipTone. "In Progress" / "Scheduled" / "Cancelled"
// are not in the canonical STATUS_TONE_MAP so we pin them here.
const STATUS_TONE: Record<TrainingStatus, ChipTone> = {
  Scheduled:    "blue",
  "In Progress": "amber",
  Completed:    "green",
  Cancelled:    "grey",
};

const FILTERS: Array<"All" | TrainingStatus> = [
  "All",
  "Scheduled",
  "In Progress",
  "Completed",
  "Cancelled",
];

const STATS: { key: string; label: string; value: string }[] = [
  { key: "scheduled",   label: "Scheduled",   value: TRAININGS.filter((t) => t.status === "Scheduled").length.toString() },
  { key: "inProgress",  label: "In Progress", value: TRAININGS.filter((t) => t.status === "In Progress").length.toString() },
  { key: "completed",   label: "Completed",   value: TRAININGS.filter((t) => t.status === "Completed").length.toString() },
];

export default function TrainingsIndex() {
  const [statusFilter, setStatusFilter] = useState<(typeof FILTERS)[number]>("All");
  // Training rows/counts are mock; never render them as live production data.
  if (!isMockAllowed()) return <InsufficientData surface="the trainings log" />;

  const rows = statusFilter === "All"
    ? TRAININGS
    : TRAININGS.filter((t) => t.status === statusFilter);

  return (
    <EntityIndex
      title="Trainings"
      subtitle="Cluster-based training cohorts. Sign up your staff, track attendance, see SSA improvement after delivery."
      Icon={GraduationCap}
      count={TRAININGS.length}
      searchPlaceholder="Search by title, cluster, facilitator"
    >
      <MetricStrip
        columns="grid-cols-1 sm:grid-cols-3"
        metrics={STATS.map((s) => ({ key: s.key, label: s.label, value: s.value }))}
      />

      {/* Filter chips */}
      <div className="flex flex-wrap items-center gap-1.5">
        {FILTERS.map((f) => {
          const active = statusFilter === f;
          return (
            <button
              key={f}
              type="button"
              onClick={() => setStatusFilter(f)}
              className={cn(
                "h-8 px-3 rounded-full border text-[12px] font-semibold transition-colors",
                active
                  ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)]"
                  : "border-[var(--color-edify-border)] bg-white text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/40",
              )}
            >
              {f}
            </button>
          );
        })}
        <span className="ml-auto text-[11.5px] muted">
          {rows.length} of {TRAININGS.length} trainings
        </span>
      </div>

      <section className="card rounded-2xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full dtable">
            <thead>
              <tr>
                <th scope="col" className="text-left">Training</th>
                <th scope="col" className="text-left">Intervention</th>
                <th scope="col" className="text-left">Cluster</th>
                <th scope="col" className="text-left">Facilitator</th>
                <th scope="col" className="text-left">Date</th>
                <th scope="col" className="text-right">Participants</th>
                <th scope="col" className="text-left">Status</th>
                <th scope="col" className="text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center muted text-body py-8">
                    No trainings recorded
                  </td>
                </tr>
              ) : (
                rows.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <div className="flex items-center gap-2">
                        <span className="w-7 h-7 rounded-md grid place-items-center bg-violet-100 text-violet-700 shrink-0">
                          <GraduationCap size={13} />
                        </span>
                        <span className="text-body font-semibold whitespace-nowrap">{t.title}</span>
                      </div>
                    </td>
                    <td className="text-[12px] muted whitespace-nowrap">{t.intervention}</td>
                    <td>
                      <span className="inline-flex items-center gap-1.5 text-[12px] muted whitespace-nowrap">
                        <Building2 size={11} className="text-[var(--color-edify-muted)]" />
                        {t.cluster}
                      </span>
                    </td>
                    <td className="text-[12px] muted whitespace-nowrap">{t.facilitator}</td>
                    <td className="text-[12px] muted whitespace-nowrap tabular">{t.date}</td>
                    <td className="text-right text-body font-extrabold tabular">{t.participants}</td>
                    <td>
                      <StatusBadge tone={STATUS_TONE[t.status]}>
                        <span title={fullStatusLabel(t.status)}>{shortStatusLabel(t.status)}</span>
                      </StatusBadge>
                    </td>
                    <td className="text-right whitespace-nowrap">
                      <div className="inline-flex items-center gap-1.5">
                        {t.status !== "Completed" && t.status !== "Cancelled" && (
                          <ConfirmCompletionButton
                            activity={{
                              id: t.id,
                              schoolName: t.title,
                              activityType: "Training",
                              purpose: t.cluster,
                              intervention: t.intervention,
                            }}
                          />
                        )}
                        <Link
                          href={`/trainings/${t.id}`}
                          className="btn btn-sm"
                          aria-label={`View training ${t.title}`}
                        >
                          View
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </EntityIndex>
  );
}
