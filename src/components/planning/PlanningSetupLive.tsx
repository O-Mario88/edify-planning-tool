"use client";

// Planning setup — LIVE. The caller's scoped schools grouped by planning stage
// from the backend (/api/planning/setup): not-yet-clustered, missing SSA, ready
// to plan, core-school planning. Each bucket links to the right next action so
// planning always starts from the correct place. No mock.

import { useEffect, useState } from "react";
import Link from "next/link";
import { ListChecks, ArrowRight, CalendarPlus, ChevronDown, ChevronRight } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { ScheduleActivityLive } from "./ScheduleActivityLive";
import type { BePlanningBucket } from "@/lib/api/surfaces";

// Buckets where the right next action is to SCHEDULE work for a specific school.
const PLANNABLE = new Set(["readyToPlan", "coreSchoolPlanning"]);

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
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [scheduling, setScheduling] = useState<{ schoolId: string; name: string; type: string } | null>(null);

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
          {buckets.map((b) => {
            const plannable = PLANNABLE.has(b.key) && b.items.length > 0;
            const open = openKey === b.key;
            return (
              <li key={b.key} className="rounded-lg border border-[var(--color-edify-border)] overflow-hidden">
                <div className="flex items-center justify-between gap-2 px-3 py-2">
                  <button
                    onClick={() => plannable && setOpenKey(open ? null : b.key)}
                    className={cnInline("min-w-0 text-left inline-flex items-center gap-1", plannable && "cursor-pointer")}
                  >
                    {plannable && (open ? <ChevronDown size={13} className="shrink-0" /> : <ChevronRight size={13} className="shrink-0" />)}
                    <span className="min-w-0">
                      <span className="text-[15px] font-extrabold tabular mr-2">{b.count}</span>
                      <span className="text-[12px] font-semibold">{b.label}</span>
                      {!plannable && b.items.length > 0 && <span className="block text-[10.5px] muted truncate">{b.items.slice(0, 3).map((s) => s.name).join(" · ")}{b.count > 3 ? " …" : ""}</span>}
                    </span>
                  </button>
                  {b.count > 0 && !plannable && NEXT[b.key] && (
                    <Link href={NEXT[b.key].href} className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11px] font-bold whitespace-nowrap shrink-0">
                      {NEXT[b.key].label} <ArrowRight size={11} />
                    </Link>
                  )}
                </div>
                {plannable && open && (
                  <ul className="border-t border-[var(--color-edify-divider)] divide-y divide-[var(--color-edify-divider)]">
                    {b.items.map((s) => (
                      <li key={s.schoolId} className="flex items-center justify-between gap-2 px-3 py-1.5 text-[11.5px]">
                        <span className="truncate">{s.name}<span className="muted"> · {s.subCounty ?? s.schoolId}</span></span>
                        <button
                          onClick={() => setScheduling({ schoolId: s.schoolId, name: s.name, type: s.schoolType })}
                          className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-[10.5px] font-bold whitespace-nowrap shrink-0"
                        >
                          <CalendarPlus size={11} /> Schedule
                        </button>
                      </li>
                    ))}
                    {b.count > b.items.length && <li className="px-3 py-1.5 text-[10.5px] muted">+{b.count - b.items.length} more — open the Directory to plan them.</li>}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {scheduling && (
        <ScheduleActivityLive
          schoolId={scheduling.schoolId}
          schoolName={scheduling.name}
          schoolType={scheduling.type}
          onClose={() => setScheduling(null)}
          onScheduled={load}
        />
      )}
    </section>
  );
}

// Tiny inline class helper (avoids importing cn just for one conditional).
function cnInline(...c: (string | false | undefined)[]) { return c.filter(Boolean).join(" "); }
