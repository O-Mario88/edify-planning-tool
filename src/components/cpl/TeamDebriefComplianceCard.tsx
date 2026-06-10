import Link from "next/link";
import { ArrowUpRight, Brain } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { dailyDebriefs } from "@/lib/field-intelligence-mock";
import { cceosSupervisedBy } from "@/lib/org/supervision";
import { cn } from "@/lib/utils";

// Team Debrief Compliance — who on the team filed their daily debrief,
// who is missing, and which blockers keep recurring. The PL reads the
// pattern here and opens individual debriefs only when needed.

export function TeamDebriefComplianceCard({ plStaffId }: { plStaffId: string }) {
  const roster = cceosSupervisedBy(plStaffId);
  const rosterIds = new Set(roster.map((s) => s.staffId));

  // Team debriefs: routed to this PL, or filed by their roster.
  const teamDebriefs = dailyDebriefs.filter(
    (d) => d.programLeadId === plStaffId || rosterIds.has(d.staffId),
  );

  // Latest debrief day on file = "today" for the demo dataset.
  const latestDate = teamDebriefs.reduce((max, d) => (d.date > max ? d.date : max), "");
  const todays = teamDebriefs.filter((d) => d.date === latestDate);
  const submittedIds = new Set(todays.map((d) => d.staffId));
  const missing = roster.filter((s) => !submittedIds.has(s.staffId));

  // Recurring blockers across the recent window (all on-file debriefs).
  const counts = new Map<string, number>();
  for (const d of teamDebriefs) {
    counts.set(d.systemClassification, (counts.get(d.systemClassification) ?? 0) + 1);
  }
  const recurring = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3);

  const metrics: MetricCell[] = [
    { key: "filed",   label: "Filed (latest day)", value: `${submittedIds.size}/${roster.length || submittedIds.size}`, tone: missing.length ? "alert" : "good" },
    { key: "missing", label: "Missing debriefs",   value: missing.length, tone: missing.length ? "alert" : "default" },
    { key: "window",  label: "Debriefs on file",   value: teamDebriefs.length },
    { key: "themes",  label: "Recurring blockers", value: recurring.length },
  ];

  return (
    <SectionCard
      icon={<Brain size={13} />}
      title="Team Debrief Summary"
      actions={
        <Link href="/debriefs" className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline">
          All debriefs <ArrowUpRight size={12} />
        </Link>
      }
    >
      <MetricStrip metrics={metrics} columns="grid-cols-2 xl:grid-cols-4" />

      {recurring.length > 0 && (
        <ul className="mt-2.5 space-y-1">
          {recurring.map(([cls, n]) => (
            <li key={cls} className="flex items-baseline gap-2 text-[12px]">
              <span
                className={cn(
                  "shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-extrabold",
                  cls.includes("Funding") || cls.includes("Support")
                    ? "bg-rose-50 text-rose-700 border-rose-200"
                    : "bg-amber-50 text-amber-700 border-amber-200",
                )}
              >
                {n}×
              </span>
              <span className="font-semibold">{cls}</span>
            </li>
          ))}
        </ul>
      )}

      {missing.length > 0 && (
        <p className="mt-2 text-[11.5px] muted leading-snug">
          Missing on the latest field day: {missing.map((s) => s.name).join(", ")}. A nudge
          today beats a gap in the weekly pattern.
        </p>
      )}
    </SectionCard>
  );
}
