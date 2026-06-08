"use client";

// Special Projects — live from the backend Project graph (no mock). Shows the
// real projects with their school/partner/activity counts + latest impact FY.
// The richer portfolio cards below still read mock until the backend emits their
// shape; this board is the source of truth for what projects actually exist.

import { useEffect, useState } from "react";
import { Sparkles, School, Handshake, Activity } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BeProject } from "@/lib/api/surfaces";

const CATEGORY_LABEL: Record<string, string> = {
  intervention_specific: "Intervention-specific",
  pilot: "Pilot",
  selective_limited: "Selective / limited",
};

export function SpecialProjectsLiveBoard() {
  const [projects, setProjects] = useState<BeProject[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true); setError(null);
    fetch("/api/special-projects", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setProjects(j.projects ?? []); else setError(j.error || "Could not load projects"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Sparkles size={14} /> Special projects{projects ? ` · ${projects.length}` : ""}</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">Live · backend</span>
      </header>

      {loading ? (
        <LoadingState compact />
      ) : error ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : !projects || projects.length === 0 ? (
        <EmptyState compact title="No projects yet" message="Special projects appear here once they're created in the system." />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
          {projects.map((p) => (
            <div key={p.id} className="rounded-xl border border-[var(--color-edify-border)] p-3">
              <div className="text-[12.5px] font-extrabold tracking-tight truncate">{p.name}</div>
              <div className="text-[10.5px] muted mb-2">{CATEGORY_LABEL[p.category] ?? p.category}{p.latestImpactFy ? ` · impact FY${p.latestImpactFy}` : ""}</div>
              <div className="flex items-center gap-3 text-[11px]">
                <span className="inline-flex items-center gap-1 font-semibold"><School size={12} className="text-sky-500" />{p.schoolCount} schools</span>
                <span className="inline-flex items-center gap-1 font-semibold"><Handshake size={12} className="text-violet-500" />{p.partnerCount}</span>
                <span className="inline-flex items-center gap-1 font-semibold"><Activity size={12} className="text-emerald-500" />{p.activityCount}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
