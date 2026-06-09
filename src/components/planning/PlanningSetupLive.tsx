"use client";

// Planning setup — LIVE. The caller's scoped schools grouped by planning stage
// from the backend (/api/planning/setup): not-yet-clustered, missing SSA, ready
// to plan, core-school planning. Each bucket links to the right next action so
// planning always starts from the correct place. No mock.

import { useEffect, useState } from "react";
import Link from "next/link";
import { ListChecks, ArrowRight } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BePlanningBucket } from "@/lib/api/surfaces";

const NEXT: Record<string, { label: string; href: string }> = {
  notYetClustered: { label: "Assign cluster (Directory)", href: "/schools" },
  clusteredSsaRequired: { label: "Schedule SSA", href: "/schools" },
  sitScheduledSsaMissing: { label: "Complete SSA", href: "/schools" },
  readyToPlan: { label: "Plan support", href: "/schools" },
  coreSchoolPlanning: { label: "Plan core package", href: "/schools" },
};

export function PlanningSetupLive() {
  const [buckets, setBuckets] = useState<BePlanningBucket[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true); setError(null);
    fetch("/api/planning/setup", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setBuckets(j.buckets as BePlanningBucket[]); else setError(j.error || "Could not load planning"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><ListChecks size={14} /> Planning — schools by stage</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">Live · scoped</span>
      </header>

      {loading ? (
        <LoadingState compact />
      ) : error ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : !buckets || buckets.every((b) => b.count === 0) ? (
        <EmptyState compact title="Nothing to plan" message="All your assigned schools are clustered, assessed, and planned for this period." />
      ) : (
        <ul className="space-y-1.5">
          {buckets.map((b) => (
            <li key={b.key} className="flex items-center justify-between gap-2 rounded-lg border border-[var(--color-edify-border)] px-3 py-2">
              <span className="min-w-0">
                <span className="text-[15px] font-extrabold tabular mr-2">{b.count}</span>
                <span className="text-[12px] font-semibold">{b.label}</span>
                {b.items.length > 0 && <span className="block text-[10.5px] muted truncate">{b.items.slice(0, 3).map((s) => s.name).join(" · ")}{b.count > 3 ? " …" : ""}</span>}
              </span>
              {b.count > 0 && NEXT[b.key] && (
                <Link href={NEXT[b.key].href} className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11px] font-bold whitespace-nowrap shrink-0">
                  {NEXT[b.key].label} <ArrowRight size={11} />
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
