"use client";

import Link from "next/link";
import {
  AlertTriangle,
  Info,
  AlertCircle,
} from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import {
  type SchoolRow,
  type Priority,
} from "@/lib/schools-mock";
import { cn } from "@/lib/utils";

const rankBg: Record<Priority, string> = {
  Critical: "bg-[var(--color-danger)] text-white",
  High:     "bg-[#f59e0b] text-white",
  Medium:   "bg-[#fde68a] text-amber-800",
  Low:      "bg-blue-100 text-[#1e40af]",
};

const riskTone: Record<Priority, "red" | "amber" | "blue" | "grey"> = {
  Critical: "red",
  High:     "red",
  Medium:   "amber",
  Low:      "grey",
};

function reasonText(s: SchoolRow): string {
  if (s.noVisit && s.noTraining) return "No visit & no training conducted";
  if (s.noVisit) return "No visit conducted";
  if (s.noTraining) return "No training conducted";
  if (s.schoolStatus === "Inactive") return "Marked inactive — re-engage";
  if (s.ssaScore < 50) return "SSA performance below threshold";
  return "Monitoring required";
}

function issueChips(s: SchoolRow) {
  const chips: { label: string; tone: "red" | "amber" }[] = [];
  if (s.noVisit) chips.push({ label: "No Visit", tone: "red" });
  if (s.noTraining) chips.push({ label: "No Training", tone: "amber" });
  if (chips.length === 0 && s.schoolStatus === "Inactive") {
    chips.push({ label: "Inactive", tone: "red" });
  }
  return chips;
}

// Top-N priority schools — SSA-first ordering already applied upstream.
export function UrgentSchoolsPanel({ schools }: { schools: SchoolRow[] }) {
  const ranked = schools.slice(0, 5);
  return (
    <SectionCard
      icon={<AlertTriangle size={13} className="text-[var(--color-danger)]" />}
      title="Schools Needing Urgent Attention"
      actions={
        <div className="flex items-center gap-3">
          <Info size={13} className="text-[var(--color-edify-muted)]" />
          <Link href="#urgent" className="text-[12px] font-semibold text-[var(--color-edify-primary)]">
            View All
          </Link>
        </div>
      }
    >
      <div className="space-y-2.5">
        {ranked.map((s, i) => {
          const priority: Priority = s.priority;
          const chips = issueChips(s);
          return (
            <div
              key={s.schoolId}
              className="rounded-xl border border-[var(--color-edify-border)] p-2.5 hover:bg-[var(--color-edify-soft)]/40"
            >
              <div className="flex items-start gap-2.5">
                <div
                  className={cn(
                    "w-7 h-7 rounded-md grid place-items-center text-[12px] font-extrabold tabular shrink-0",
                    rankBg[priority],
                  )}
                >
                  {i + 1}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-2">
                    <Link
                      href={`/schools/${s.schoolId}`}
                      className="text-body font-bold leading-tight hover:text-[var(--color-edify-primary)]"
                    >
                      {s.schoolName}
                    </Link>
                    <StatusBadge tone={riskTone[priority]} className="!py-0.5 shrink-0">
                      <AlertCircle size={10} className="mr-0.5" />
                      {priority}
                    </StatusBadge>
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-caption muted font-semibold">
                      SSA Score: <span className="text-[var(--color-edify-text)]">{s.ssaScore}%</span>
                    </span>
                    <span className="w-1 h-1 rounded-full bg-[var(--color-edify-muted)]" />
                    {chips.map((c) => (
                      <span
                        key={c.label}
                        className={cn(
                          "inline-flex items-center px-1.5 py-[1px] rounded text-[10px] font-semibold",
                          c.tone === "red"
                            ? "bg-red-100 text-red-700"
                            : "bg-amber-100 text-amber-800",
                        )}
                      >
                        {c.label}
                      </span>
                    ))}
                  </div>
                  <div className="text-[11px] muted mt-1 leading-snug">
                    <span className="font-semibold">Reason:</span> {reasonText(s)}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-caption muted leading-snug">
        Priorities are based on SSA score and service gaps.
      </div>
    </SectionCard>
  );
}
