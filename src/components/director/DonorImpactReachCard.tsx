"use client";

// DonorImpactReachCard — the donor-reporting snapshot for leadership.
// Six headline reach/training/impact figures pulled straight from the
// shared getDonorMetricSnapshot() builder, so the numbers match the full
// /donor-reporting report exactly (deduplicated, role-scoped, and only
// verified/confirmed records folded into the headline). Every tile drills
// into the full report.

import Link from "next/link";
import {
  ArrowUpRight, BadgeCheck, GraduationCap, UserCheck, Users, School,
  MapPin, TrendingUp, type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import type { DonorMetricSnapshot, DonorMetricStatus } from "@/lib/donor-metrics-types";
import { cn } from "@/lib/utils";

// The six donor headline metrics, in spec order, with an icon each.
const WANTED: { key: string; icon: LucideIcon }[] = [
  { key: "teachersTrained",     icon: GraduationCap },
  { key: "schoolLeadersTrained", icon: UserCheck },
  { key: "studentsImpacted",    icon: Users },
  { key: "schoolsReached",      icon: School },
  { key: "districtsCovered",    icon: MapPin },
  { key: "schoolsImproved",     icon: TrendingUp },
];

// Status → small pill. Verified/confirmed read as donor-ready (green);
// anything pending reads amber; excluded reads grey.
function statusMeta(status: DonorMetricStatus): { label: string; cls: string } {
  switch (status) {
    case "verified":  return { label: "Verified",  cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" };
    case "confirmed": return { label: "Confirmed", cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300" };
    case "excluded":  return { label: "Excluded",  cls: "bg-slate-100 text-slate-600 dark:bg-slate-500/20 dark:text-slate-300" };
    default:          return { label: "Pending",   cls: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300" };
  }
}

export function DonorImpactReachCard({ snapshot }: { snapshot: DonorMetricSnapshot }) {
  const byKey = new Map(snapshot.metrics.map((m) => [m.key, m]));

  return (
    <SectionCard
      title="Impact Reach This Period"
      subtitle="Donor-ready figures — deduplicated, role-scoped, verified or confirmed only"
      icon={<BadgeCheck size={13} />}
      actions={
        <Link
          href="/donor-reporting"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline"
        >
          Full report
          <ArrowUpRight size={12} />
        </Link>
      }
    >
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5">
        {WANTED.map(({ key, icon: Icon }) => {
          const m = byKey.get(key);
          if (!m) return null;
          const st = statusMeta(m.status);
          return (
            <Link
              key={key}
              href="/donor-reporting"
              className="group rounded-xl border border-[var(--border-card)] bg-[var(--surface-1)] p-3 hover:border-[var(--color-edify-primary)]/40 transition-colors"
              title={`Open the full donor report for ${m.label}`}
            >
              <div className="flex items-center gap-2 mb-1.5">
                <span className="grid place-items-center h-6 w-6 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                  <Icon size={12} />
                </span>
                <span className="text-[11px] muted leading-tight line-clamp-2">{m.label}</span>
              </div>
              <div className="text-[22px] font-semibold tabular leading-none text-[var(--text-primary)]">
                {m.value != null ? m.value.toLocaleString() : "—"}
              </div>
              <span className={cn("mt-1.5 inline-flex items-center px-1.5 py-[1px] rounded text-[9.5px] font-semibold uppercase tracking-wide", st.cls)}>
                {st.label}
              </span>
            </Link>
          );
        })}
      </div>
    </SectionCard>
  );
}

export default DonorImpactReachCard;
