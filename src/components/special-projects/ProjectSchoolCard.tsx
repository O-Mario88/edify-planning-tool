"use client";

// One project = one card = a mini school-directory for that project. The
// always-visible header carries summary + impact + actions; the collapsible
// body holds ONLY this project's assigned schools (the detail-heavy list).
// Clicking a metric filters the in-card school list to the schools behind it.

import { useState, useMemo } from "react";
import Link from "next/link";
import {
  Sparkles, ChevronDown, ChevronRight, MapPin, User, TrendingUp, TrendingDown, Minus,
  Handshake, Building2, ArrowRight, Plus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { StatusBadge } from "@/components/ui/primitives";
import { canManageProjectCategory } from "@/lib/special-projects-mock";
import type { ProjectCardVM, ProjectSchoolRowVM } from "@/lib/projects/project-school-directory";

type MetricKey = "assigned" | "trained" | "followedUp" | "evidencePending" | "iaVerified" | "improved";

const METRICS: { key: MetricKey; label: string; predicate: (r: ProjectSchoolRowVM) => boolean }[] = [
  { key: "assigned",        label: "Assigned",       predicate: () => true },
  { key: "trained",         label: "Trained",        predicate: (r) => r.trainingStatus === "Completed" },
  { key: "followedUp",      label: "Followed up",    predicate: (r) => r.followUpStatus === "Completed" },
  { key: "evidencePending", label: "Evidence pending", predicate: (r) => r.evidenceStatus === "Pending" },
  { key: "iaVerified",      label: "IA verified",    predicate: (r) => r.iaStatus === "Verified" },
  { key: "improved",        label: "SSA improved",   predicate: (r) => r.impactStatus === "Improved" },
];

function ChangeTrend({ value }: { value?: number }) {
  if (value === undefined) return <span className="muted text-[11px]">—</span>;
  const Icon = value > 0 ? TrendingUp : value < 0 ? TrendingDown : Minus;
  const tone = value > 0 ? "text-emerald-600" : value < 0 ? "text-rose-600" : "text-slate-400";
  return (
    <span className={cn("inline-flex items-center gap-0.5 font-bold tabular", tone)}>
      <Icon size={12} /> {value > 0 ? "+" : ""}{value.toFixed(1)}
    </span>
  );
}

function impactTone(s: ProjectSchoolRowVM["impactStatus"]): "green" | "red" | "amber" | "grey" {
  return s === "Improved" ? "green" : s === "Declined" ? "red" : s === "No Change" ? "amber" : "grey";
}

export function ProjectSchoolCard({
  card, userRole, query, defaultExpanded = false,
}: {
  card: ProjectCardVM;
  userRole: string;
  query: string;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [activeMetric, setActiveMetric] = useState<MetricKey | null>(null);
  const { project, impact, metrics, categoryLabel } = card;
  const canManage = canManageProjectCategory(userRole, project.projectCategory);

  const q = query.trim().toLowerCase();
  const rows = useMemo(() => {
    let r = card.schools;
    if (activeMetric) {
      const m = METRICS.find((x) => x.key === activeMetric)!;
      r = r.filter(m.predicate);
    }
    if (q) {
      r = r.filter((s) =>
        s.schoolName.toLowerCase().includes(q) ||
        s.schoolId.toLowerCase().includes(q) ||
        s.district.toLowerCase().includes(q) ||
        (s.cluster?.toLowerCase().includes(q) ?? false) ||
        (s.accountOwner?.toLowerCase().includes(q) ?? false),
      );
    }
    return r;
  }, [card.schools, activeMetric, q]);

  const metricValue = (k: MetricKey) => metrics[k];

  return (
    <section className="card rounded-2xl overflow-hidden">
      {/* Header — always visible */}
      <div className="p-3.5">
        <div className="flex items-start gap-3">
          <span className="w-8 h-8 rounded-lg grid place-items-center bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
            <Sparkles size={15} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <Link href={`/projects/${project.projectId}`} className="text-[14px] font-extrabold tracking-tight hover:text-[var(--color-edify-primary)] hover:underline">
                {project.projectName}
              </Link>
              <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-violet-50 text-violet-700">{categoryLabel}</span>
              <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">{project.primaryInterventionId}</span>
              <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-slate-100 text-slate-600">{project.status}</span>
            </div>
            <div className="mt-1 text-[11.5px] muted flex items-center gap-x-3 gap-y-0.5 flex-wrap">
              {project.coordinatorName && <span className="inline-flex items-center gap-1"><User size={10} />{project.coordinatorName}</span>}
              <span>{project.startDate} – {project.endDate}</span>
              {project.assignedPartnerName && <span className="inline-flex items-center gap-1"><Handshake size={10} />{project.assignedPartnerName} (execution)</span>}
            </div>
          </div>
          {/* Impact at a glance */}
          <div className="text-right shrink-0">
            <div className="text-[10.5px] muted font-semibold">{impact.intervention}</div>
            <div className="text-[12px] font-bold tabular">
              {impact.baselineAvg.toFixed(1)} → {impact.latestAvg.toFixed(1)} <ChangeTrend value={impact.change} />
            </div>
            <div className="text-[10.5px] muted">{impact.schoolsImproved}/{impact.schoolsWithComparison || metrics.assigned} improved</div>
          </div>
        </div>

        {/* Clickable metric row */}
        <div className="mt-3 flex flex-wrap gap-1.5">
          {METRICS.map((m) => {
            const active = activeMetric === m.key;
            return (
              <button
                key={m.key}
                type="button"
                onClick={() => setActiveMetric(active ? null : m.key === "assigned" ? null : m.key)}
                className={cn(
                  "px-2 py-[3px] rounded-md text-[11px] font-bold border transition-colors inline-flex items-center gap-1",
                  active
                    ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)]"
                    : "bg-white border-[var(--color-edify-border)] text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/50",
                )}
                title={`Filter to ${m.label.toLowerCase()}`}
              >
                <span className="tabular">{metricValue(m.key)}</span>
                <span className="font-semibold opacity-80">{m.label}</span>
              </button>
            );
          })}
        </div>

        {/* Actions */}
        <div className="mt-3 flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="inline-flex items-center gap-1 h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-bold hover:bg-[var(--color-edify-dark)]"
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            {expanded ? "Hide schools" : `View schools (${metrics.assigned})`}
          </button>
          <Link href={`/projects/${project.projectId}`} className="inline-flex items-center gap-1 h-8 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60">
            View project <ArrowRight size={12} />
          </Link>
          {canManage && (
            <Link href="/schools" className="inline-flex items-center gap-1 h-8 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60">
              <Plus size={12} /> Assign more schools
            </Link>
          )}
          {activeMetric && (
            <button type="button" onClick={() => setActiveMetric(null)} className="text-[11.5px] muted hover:text-[var(--color-edify-text)] underline">
              Clear filter
            </button>
          )}
        </div>
      </div>

      {/* Collapsible school list — only this project's assigned schools */}
      {expanded && (
        <div className="border-t border-[var(--color-edify-divider)] overflow-x-auto scrollbar">
          {rows.length === 0 ? (
            <p className="px-4 py-5 text-center text-[12px] muted">No schools match this filter.</p>
          ) : (
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">School</th>
                  <th scope="col" className="text-left">District / Cluster</th>
                  <th scope="col" className="text-left">Owner</th>
                  <th scope="col" className="text-left">Type</th>
                  <th scope="col" className="text-right">{project.primaryInterventionId}</th>
                  <th scope="col" className="text-left">Project status</th>
                  <th scope="col" className="text-left">Partner</th>
                  <th scope="col" className="text-left">Next action</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.schoolId} className="hover:bg-[var(--color-edify-soft)]/40">
                    <td>
                      <Link href={`/schools/${s.schoolId}`} className="font-semibold hover:text-[var(--color-edify-primary)] hover:underline">{s.schoolName}</Link>
                      <span className="muted text-[11px] ml-1">#{s.schoolId}</span>
                    </td>
                    <td className="text-[12px] muted">
                      <span className="inline-flex items-center gap-1"><MapPin size={9} />{s.district}</span>
                      {s.cluster && <span className="block inline-flex items-center gap-1 mt-0.5"><Building2 size={9} />{s.cluster}</span>}
                    </td>
                    <td className="text-[12px] muted">{s.accountOwner ?? "—"}</td>
                    <td className="text-[12px]">
                      <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold", s.schoolType === "Core" ? "bg-violet-50 text-violet-700" : "bg-blue-50 text-blue-700")}>{s.schoolType}</span>
                    </td>
                    <td className="text-right text-[12px] tabular whitespace-nowrap">
                      {s.baselineScore ?? "—"} → <span className="font-bold">{s.latestScore ?? "—"}</span> <ChangeTrend value={s.change} />
                    </td>
                    <td><StatusBadge tone={impactTone(s.impactStatus)}>{s.projectStatus}</StatusBadge></td>
                    <td className="text-[12px] muted">{s.partnerSupport ?? "—"}</td>
                    <td className="text-[12px] font-semibold">{s.nextAction}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}
