"use client";

// Special Projects — the ENTIRE overview, driven by the live backend Project
// graph (no mock). Fetches the real project list once, then renders:
//   1. the KPI strip (count + summed school/partner/activity counts),
//   2. the live project board (per-project counts + impact FY),
//   3. per-project impact (before→after intervention SSA) + partner delivery
//      (completed/total %), pulled live from /impact and /partners.
//
// Each project links to /projects/[id] — the full live monitor (ProjectMonitorLive)
// with Schedule / Assign / partner add-remove. This card is read-only summary.

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Sparkles, School, Handshake, Activity, TrendingUp, TrendingDown, Minus, ArrowUpRight,
  Briefcase, Building2,
} from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import type { BeProject, BeProjectImpact, BeProjectPartner } from "@/lib/api/surfaces";

const CATEGORY_LABEL: Record<string, string> = {
  intervention_specific: "Intervention-specific",
  pilot: "Pilot",
  selective_limited: "Selective / limited",
};

function humanize(key?: string | null): string {
  if (!key) return "—";
  return key.split("_").map((w) => (w === "and" ? "&" : w.charAt(0).toUpperCase() + w.slice(1))).join(" ");
}

function DeltaPill({ value }: { value: number | null }) {
  if (value == null) return <span className="muted text-[11px]">—</span>;
  const tone = value > 0 ? "bg-emerald-50 text-emerald-700" : value < 0 ? "bg-rose-50 text-rose-700" : "bg-slate-100 text-slate-500";
  const Icon = value > 0 ? TrendingUp : value < 0 ? TrendingDown : Minus;
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[11px] font-extrabold tabular ${tone}`}>
      <Icon size={11} /> {value > 0 ? "+" : ""}{value.toFixed(1)}
    </span>
  );
}

type LiveDetail = { impact: BeProjectImpact | null; partners: BeProjectPartner[] | null };

export function SpecialProjectsLiveOverview() {
  const [projects, setProjects] = useState<BeProject[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [details, setDetails] = useState<Record<string, LiveDetail>>({});

  const load = () => {
    setLoading(true); setError(null); setDetails({});
    fetch("/api/special-projects", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setProjects(j.projects ?? []); else setError(j.error || "Could not load projects"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  // Per-project impact + partner delivery, fetched live once the list lands.
  useEffect(() => {
    if (!projects || projects.length === 0) return;
    let cancelled = false;
    Promise.all(
      projects.map(async (p) => {
        const [im, pr] = await Promise.all([
          fetch(`/api/special-projects/${encodeURIComponent(p.id)}/impact`, { credentials: "include" }).then((r) => r.json()).catch(() => ({ live: false })),
          fetch(`/api/special-projects/${encodeURIComponent(p.id)}/partners`, { credentials: "include" }).then((r) => r.json()).catch(() => ({ live: false })),
        ]);
        return [p.id, { impact: im.live ? (im as BeProjectImpact) : null, partners: pr.live ? (pr.partners ?? []) : null }] as const;
      }),
    ).then((entries) => {
      if (!cancelled) setDetails(Object.fromEntries(entries));
    });
    return () => { cancelled = true; };
  }, [projects]);

  // KPI strip — computed ENTIRELY from the live list. Only the four metrics the
  // backend Project graph actually emits; no hardcoded aggregates.
  const kpiCells: MetricCell[] = useMemo(() => {
    const list = projects ?? [];
    return [
      { key: "projects", label: "Active Projects", icon: Briefcase, value: list.length },
      { key: "schools", label: "Schools in Projects", icon: Building2, value: list.reduce((a, p) => a + (p.schoolCount ?? 0), 0).toLocaleString() },
      { key: "partners", label: "Partner Assignments", icon: Handshake, value: list.reduce((a, p) => a + (p.partnerCount ?? 0), 0).toLocaleString() },
      { key: "activities", label: "Project Activities", icon: Activity, value: list.reduce((a, p) => a + (p.activityCount ?? 0), 0).toLocaleString() },
    ];
  }, [projects]);

  const impactRows = useMemo(
    () => (projects ?? [])
      .map((p) => ({ p, d: details[p.id] }))
      .filter((r) => r.d?.impact && (r.d.impact.measuredCount ?? 0) > 0),
    [projects, details],
  );
  const partnerRows = useMemo(
    () => (projects ?? [])
      .flatMap((p) => (details[p.id]?.partners ?? []).map((pt) => ({ project: p, pt }))),
    [projects, details],
  );

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!projects || projects.length === 0) {
    return <EmptyState title="No projects yet" message="Special projects appear here once they're created in the system." />;
  }

  return (
    <div className="space-y-3 md:space-y-4">
      {/* KPI strip — live aggregates only */}
      <MetricStrip metrics={kpiCells} columns="grid-cols-2 sm:grid-cols-4" />

      {/* Live project board */}
      <section className="card p-3.5">
        <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
          <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Sparkles size={14} /> Special projects · {projects.length}</h2>
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">Live · backend</span>
        </header>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
          {projects.map((p) => (
            <Link
              key={p.id}
              href={`/projects/${encodeURIComponent(p.id)}`}
              className="group rounded-xl border border-[var(--color-edify-border)] p-3 hover:border-[var(--color-edify-primary)] hover:bg-[var(--color-edify-soft)]/40 transition-colors"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="text-[12.5px] font-extrabold tracking-tight truncate">{p.name}</div>
                <ArrowUpRight size={13} className="shrink-0 text-[var(--color-edify-muted)] group-hover:text-[var(--color-edify-primary)]" />
              </div>
              <div className="text-[10.5px] muted mb-2">{CATEGORY_LABEL[p.category] ?? p.category}{p.latestImpactFy ? ` · impact FY${p.latestImpactFy}` : ""}</div>
              <div className="flex items-center gap-3 text-[11px]">
                <span className="inline-flex items-center gap-1 font-semibold"><School size={12} className="text-sky-500" />{p.schoolCount} schools</span>
                <span className="inline-flex items-center gap-1 font-semibold"><Handshake size={12} className="text-violet-500" />{p.partnerCount}</span>
                <span className="inline-flex items-center gap-1 font-semibold"><Activity size={12} className="text-emerald-500" />{p.activityCount}</span>
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* Project impact — intervention SSA before → after (live) */}
      <SectionCard
        icon={<TrendingUp size={13} />}
        title="Project Impact vs. SSA Intervention"
        subtitle="Did the mapped intervention move for project schools? Baseline → latest SSA on the target area."
      >
        {impactRows.length === 0 ? (
          <p className="text-[12px] muted py-6 text-center">
            No project has measured SSA improvement yet. Assign schools and complete a follow-up SSA to measure impact.
          </p>
        ) : (
          <div className="overflow-x-auto scrollbar -mx-1 px-1">
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">Project</th>
                  <th scope="col" className="text-left">Mapped Intervention</th>
                  <th scope="col" className="text-right">Schools Measured</th>
                  <th scope="col" className="text-right">Avg Δ</th>
                  <th scope="col" className="text-right">Improved</th>
                </tr>
              </thead>
              <tbody>
                {impactRows.map(({ p, d }) => {
                  const im = d!.impact!;
                  return (
                    <tr key={p.id} className="hover:bg-[var(--color-edify-soft)]/40">
                      <td>
                        <Link href={`/projects/${encodeURIComponent(p.id)}`} className="text-body font-semibold whitespace-nowrap hover:text-[var(--color-edify-primary)] hover:underline">
                          {p.name}
                        </Link>
                      </td>
                      <td>
                        <span className="inline-flex items-center px-2 py-[2px] rounded-md text-[11px] font-semibold bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] whitespace-nowrap">
                          {humanize(im.intervention)}
                        </span>
                      </td>
                      <td className="text-right tabular text-body">{im.measuredCount}</td>
                      <td className="text-right"><DeltaPill value={im.avgDelta} /></td>
                      <td className="text-right tabular text-[12px]">
                        <span className="font-bold text-emerald-700">{im.improvedCount}</span>
                        <span className="muted">/{im.measuredCount}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {/* Partner delivery — completed / total per partner (live) */}
      <SectionCard
        icon={<Handshake size={13} />}
        title="Partner Assignment & Delivery"
        subtitle="Project activities delivered vs. assigned, per partner."
      >
        {partnerRows.length === 0 ? (
          <p className="text-[12px] muted py-6 text-center">
            No partners assigned to projects yet. Assign a partner from a project page to track delivery.
          </p>
        ) : (
          <table className="w-full dtable">
            <thead>
              <tr>
                <th scope="col" className="text-left">Partner</th>
                <th scope="col" className="text-left">Project</th>
                <th scope="col" className="text-right">Delivered</th>
                <th scope="col" className="text-left">Delivery Progress</th>
              </tr>
            </thead>
            <tbody>
              {partnerRows.map(({ project, pt }) => {
                const pct = pt.activityTotal ? Math.round((pt.activityCompleted / pt.activityTotal) * 100) : 0;
                return (
                  <tr key={`${project.id}:${pt.id}`}>
                    <td className="text-[12px] font-semibold whitespace-nowrap">
                      {pt.name}
                      {pt.isCertified && <span className="ml-1.5 inline-flex items-center px-1.5 py-[1px] rounded bg-emerald-50 text-emerald-700 text-[9.5px] font-bold">Certified</span>}
                    </td>
                    <td className="text-[12px] muted whitespace-nowrap">{project.name}</td>
                    <td className="text-right tabular text-[12px]">{pt.activityCompleted}/{pt.activityTotal}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                          <div className="h-full rounded-full bg-[var(--color-success)]" style={{ width: `${pct}%` }} />
                        </div>
                        <span className="text-[11.5px] font-bold tabular w-10 text-right">{pct}%</span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </SectionCard>
    </div>
  );
}
