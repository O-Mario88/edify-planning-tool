// IA Cluster Quality Queue — read-only monitoring surface for Impact
// Assessment to watch cluster data quality across three lenses:
//   1. Unclustered schools (the assignment backlog)
//   2. Schools flagged for cluster review
//   3. Cluster integrity issues (structural health checks)
//
// Pure server render + next/link — no client interactivity. Consumes the
// stable cluster engine; never mutates it.

import Link from "next/link";
import { AlertTriangle, Building2, Network } from "lucide-react";
import {
  clusterById,
  clusterHealthChecks,
  needsReviewSchools,
  unclusteredSchools,
} from "@/lib/cluster/cluster-core";
import type { IntakeSchool } from "@/lib/intake/intake-mock";
import { cn } from "@/lib/utils";

// Integrity kinds surfaced as data-quality issues (the school-backlog kinds
// "school_without_cluster" / "core_without_cluster" already have their own
// sections above, so they are excluded here to avoid double-counting).
const INTEGRITY_KINDS = new Set<string>([
  "cross_district_school",
  "cluster_without_schools",
  "cluster_missing_district",
  "duplicate_cluster_name",
  "inactive_cluster_with_schools",
  "core_without_cluster",
]);

function locationLabel(s: IntakeSchool): string {
  return s.subCounty ? `${s.district} · ${s.subCounty}` : s.district;
}

function SchoolRow({
  s,
  clusterName,
}: {
  s: IntakeSchool;
  clusterName?: string;
}) {
  return (
    <Link
      href="/clusters/assign"
      className={cn(
        "flex items-center justify-between gap-3 rounded-xl px-3 py-2.5",
        "border border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]",
        "transition-colors",
      )}
    >
      <div className="min-w-0">
        <div className="truncate text-[12.5px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
          {s.schoolName}
        </div>
        <div className="muted truncate text-[12px]">
          {locationLabel(s)}
          {s.assignedCceo ? ` · ${s.assignedCceo}` : " · Unassigned"}
          {clusterName ? ` · ${clusterName}` : ""}
        </div>
      </div>
      <span
        className={cn(
          "shrink-0 rounded-full border border-[var(--color-edify-border)] px-2 py-0.5",
          "text-[11px] font-bold text-[var(--color-edify-text)]",
        )}
      >
        {s.schoolType}
      </span>
    </Link>
  );
}

function SectionHeader({
  icon,
  title,
  count,
}: {
  icon: React.ReactNode;
  title: string;
  count: number;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <span className="text-[var(--color-edify-primary)]">{icon}</span>
        <h2 className="text-[16px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
          {title}
        </h2>
      </div>
      <span className="tabular text-[12.5px] font-extrabold text-[var(--color-edify-text)]">
        {count}
      </span>
    </div>
  );
}

export default function IaClusterQualityQueue() {
  const unclustered = unclusteredSchools();
  const flagged = needsReviewSchools();
  const issues = clusterHealthChecks().filter((c) => INTEGRITY_KINDS.has(c.kind));

  return (
    <div className="space-y-4">
      {/* 1 — Unclustered schools */}
      <section className="card rounded-2xl p-4 space-y-3">
        <SectionHeader
          icon={<Building2 className="h-4 w-4" />}
          title="Unclustered schools"
          count={unclustered.length}
        />
        {unclustered.length === 0 ? (
          <p className="muted text-[12px]">Every school is in a cluster.</p>
        ) : (
          <div className="space-y-1.5">
            {unclustered.map((s) => (
              <SchoolRow key={s.schoolId} s={s} />
            ))}
          </div>
        )}
      </section>

      {/* 2 — Flagged for review */}
      <section className="card rounded-2xl p-4 space-y-3">
        <SectionHeader
          icon={<AlertTriangle className="h-4 w-4" />}
          title="Flagged for review"
          count={flagged.length}
        />
        {flagged.length === 0 ? (
          <p className="muted text-[12px]">No cluster assignments are flagged for review.</p>
        ) : (
          <div className="space-y-1.5">
            {flagged.map((s) => (
              <SchoolRow
                key={s.schoolId}
                s={s}
                clusterName={clusterById(s.clusterId)?.name}
              />
            ))}
          </div>
        )}
      </section>

      {/* 3 — Data-quality issues */}
      <section className="card rounded-2xl p-4 space-y-3">
        <SectionHeader
          icon={<Network className="h-4 w-4" />}
          title="Data-quality issues"
          count={issues.length}
        />
        {issues.length === 0 ? (
          <div
            className={cn(
              "flex items-center gap-2 rounded-xl px-3 py-2.5",
              "border border-emerald-500/30 bg-emerald-500/10",
              "text-[12px] font-bold text-emerald-600 dark:text-emerald-400",
            )}
          >
            No issues
          </div>
        ) : (
          <div className="space-y-1.5">
            {issues.map((c) => (
              <div
                key={c.kind}
                className={cn(
                  "flex items-center justify-between gap-3 rounded-xl px-3 py-2.5",
                  "border border-[var(--color-edify-border)]",
                )}
              >
                <span className="text-[12.5px] font-bold text-[var(--color-edify-text)]">
                  {c.label}
                </span>
                <span className="tabular shrink-0 rounded-full border border-[var(--color-edify-border)] px-2 py-0.5 text-[11px] font-extrabold text-[var(--color-edify-text)]">
                  {c.count}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
