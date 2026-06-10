import Link from "next/link";
import { ArrowUpRight, Handshake } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import {
  partnerTargetPerformance,
  type PartnerTargetRow,
} from "@/lib/team-targets-mock";
import { cn } from "@/lib/utils";

// Partner Performance Summary — the CD owns partner onboarding and
// certification, so this card answers "are partners delivering quality
// work?" at a glance: coverage, certification, delivery, and who is at
// risk. Onboarding/activation lives on /partners (CD has edit rights).

const RISK_TONE: Record<PartnerTargetRow["risk"], string> = {
  Low:      "bg-emerald-50 text-emerald-700 border-emerald-200",
  Medium:   "bg-amber-50 text-amber-700 border-amber-200",
  High:     "bg-rose-50 text-rose-700 border-rose-200",
  Critical: "bg-rose-100 text-rose-800 border-rose-300",
};

const CERT_TONE: Record<PartnerTargetRow["certificationStatus"], string> = {
  Certified:       "bg-emerald-50 text-emerald-700 border-emerald-200",
  Pending:         "bg-amber-50 text-amber-700 border-amber-200",
  "Not Certified": "bg-slate-100 text-slate-600 border-slate-200",
};

export function PartnerPerformanceSummary() {
  const rows = partnerTargetPerformance;
  const certified = rows.filter((p) => p.certificationStatus === "Certified").length;
  const atRisk = rows.filter((p) => p.risk === "High" || p.risk === "Critical").length;
  const assigned = rows.reduce((a, p) => a + p.assignedActivities, 0);
  const completed = rows.reduce((a, p) => a + p.completedActivities, 0);
  const avgAchievement = rows.length
    ? Math.round(rows.reduce((a, p) => a + p.achievementPercent, 0) / rows.length)
    : 0;

  const metrics: MetricCell[] = [
    { key: "active",    label: "Active partners",   value: rows.length },
    { key: "certified", label: "Certified",         value: certified, caption: `of ${rows.length}` },
    { key: "assigned",  label: "Assigned activities", value: assigned.toLocaleString() },
    { key: "completed", label: "Completed",         value: completed.toLocaleString() },
    { key: "avg",       label: "Avg achievement",   value: `${avgAchievement}%` },
    { key: "risk",      label: "At delivery risk",  value: atRisk, tone: atRisk ? "alert" : "default" },
  ];

  return (
    <SectionCard
      icon={<Handshake size={13} />}
      title="Partner Performance Summary"
      actions={
        <Link href="/partners" className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline">
          Manage partners <ArrowUpRight size={12} />
        </Link>
      }
    >
      <MetricStrip metrics={metrics} columns="grid-cols-2 sm:grid-cols-3 xl:grid-cols-6" />
      <ul className="mt-2.5 divide-y divide-[var(--color-edify-divider)]">
        {rows.map((p) => (
          <li key={p.partnerId} className="flex items-center gap-3 py-2">
            <div className="min-w-0 flex-1">
              <div className="text-[12.5px] font-bold tracking-tight truncate">{p.partner}</div>
              <div className="text-[11px] muted truncate">
                {p.region} · {p.completedActivities.toLocaleString()}/{p.assignedActivities.toLocaleString()} activities · {p.validVisits.toLocaleString()} valid visits
              </div>
            </div>
            <span className={cn("hidden sm:inline-flex shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-extrabold", CERT_TONE[p.certificationStatus])}>
              {p.certificationStatus}
            </span>
            <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-extrabold", RISK_TONE[p.risk])}>
              {p.risk}
            </span>
            <span className="shrink-0 w-10 text-right text-[12px] font-extrabold tabular">{p.achievementPercent}%</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] muted leading-snug">
        Partners are available for assignment only after activation — onboarding, coverage, and certification are managed on the Partners page.
      </p>
    </SectionCard>
  );
}
