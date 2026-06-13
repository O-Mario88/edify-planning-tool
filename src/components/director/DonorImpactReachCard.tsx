"use client";

// DonorImpactReachCard — the donor-reporting snapshot for leadership.
// Six headline reach/training/impact figures pulled straight from the
// shared getDonorMetricSnapshot() builder, so the numbers match the full
// /donor-reporting report exactly (deduplicated, role-scoped, and only
// verified/confirmed records folded into the headline). Every tile drills
// into the full report.

import Link from "next/link";
import { ArrowUpRight, BadgeCheck } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import type { DonorMetricSnapshot, DonorMetricStatus } from "@/lib/donor-metrics-types";

// The six donor headline metrics, in spec order.
const WANTED: string[] = [
  "teachersTrained",
  "schoolLeadersTrained",
  "studentsImpacted",
  "schoolsReached",
  "districtsCovered",
  "schoolsImproved",
];

// Status → caption text + tone. Verified/confirmed read as donor-ready (good);
// anything pending reads as default; excluded reads default.
function statusMeta(status: DonorMetricStatus): { label: string; tone: MetricCell["tone"] } {
  switch (status) {
    case "verified":  return { label: "Verified",  tone: "good" };
    case "confirmed": return { label: "Confirmed", tone: "good" };
    case "excluded":  return { label: "Excluded",  tone: "default" };
    default:          return { label: "Pending",   tone: "default" };
  }
}

export function DonorImpactReachCard({ snapshot }: { snapshot: DonorMetricSnapshot }) {
  const byKey = new Map(snapshot.metrics.map((m) => [m.key, m]));

  const metrics: MetricCell[] = WANTED.flatMap((key) => {
    const m = byKey.get(key);
    if (!m) return [];
    const st = statusMeta(m.status);
    return [{
      key,
      label: m.label,
      value: m.value != null ? m.value.toLocaleString() : "—",
      caption: st.label,
      tone: st.tone,
      href: "/donor-reporting/print",
    }];
  });

  return (
    <SectionCard
      title="Impact Reach This Period"
      subtitle="Donor-ready figures — deduplicated, role-scoped, verified or confirmed only"
      icon={<BadgeCheck size={13} />}
      actions={
        <Link
          href="/donor-reporting/print"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline"
        >
          Full report
          <ArrowUpRight size={12} />
        </Link>
      }
    >
      <MetricStrip bare columns="grid-cols-2 md:grid-cols-3" metrics={metrics} />
    </SectionCard>
  );
}

export default DonorImpactReachCard;
