"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Building2, ChevronRight, School, Calendar } from "lucide-react";
import { DetailKpi } from "@/components/shell/EntityDetail";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";

// Live member-school list + SSA KPIs for a cluster detail page. Self-fetches
// the backend-backed /api/clusters/[id]/schools route — no mock fallback.
// "No backend data = empty state. Backend failure = error. Never fake data."

type BeClusterSchool = {
  schoolId: string;
  name: string;
  schoolType: string;
  subCounty?: string | null;
  accountOwner?: string | null;
  ssaStatus: string;
  planningReadiness: string;
  latestSsa: number | null;
  stage: string;
};

type Payload = {
  live: boolean;
  error?: string | null;
  count?: number;
  schools?: BeClusterSchool[];
};

type Status = "loading" | "ready" | "empty" | "error";

export function ClusterMemberSchoolsLive({ clusterId }: { clusterId: string }) {
  const [status, setStatus] = useState<Status>("loading");
  const [schools, setSchools] = useState<BeClusterSchool[]>([]);
  const [failedAt, setFailedAt] = useState<Date | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const res = await fetch(`/api/clusters/${encodeURIComponent(clusterId)}/schools`, { cache: "no-store" });
      const json: Payload = await res.json();
      if (!res.ok || !json.live) {
        setFailedAt(new Date());
        setStatus("error");
        return;
      }
      const rows = json.schools ?? [];
      setSchools(rows);
      setStatus(rows.length ? "ready" : "empty");
    } catch {
      setFailedAt(new Date());
      setStatus("error");
    }
  }, [clusterId]);

  useEffect(() => {
    void load();
  }, [load]);

  const completed = schools.filter((s) => s.ssaStatus === "Completed").length;
  const scored = schools.filter((s) => s.latestSsa != null);
  const avgSsa = scored.length
    ? Math.round((scored.reduce((a, s) => a + (s.latestSsa ?? 0), 0) / scored.length) * 10) / 10
    : 0;

  return (
    <>
      <section className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <DetailKpi
          label="Member Schools"
          value={status === "ready" || status === "empty" ? String(schools.length) : "—"}
          caption="In this cluster"
          Icon={School}
          tone="edify"
        />
        <DetailKpi
          label="Avg SSA"
          value={status === "ready" ? `${avgSsa}%` : "—"}
          caption="Across members"
          Icon={Calendar}
          tone={avgSsa >= 70 ? "green" : avgSsa >= 50 ? "amber" : "rose"}
        />
        <DetailKpi
          label="SSA Completed"
          value={status === "ready" || status === "empty" ? `${completed}/${schools.length}` : "—"}
          caption="Verified"
          Icon={Building2}
          tone="violet"
        />
      </section>

      <div className="card rounded-2xl overflow-hidden">
        <header className="px-4 pt-3.5 pb-2 flex items-baseline justify-between">
          <h3 className="text-[13px] font-extrabold tracking-tight">Member Schools</h3>
          <Link href="/schools" className="text-[11px] font-semibold text-[var(--color-edify-primary)]">
            View All schools →
          </Link>
        </header>

        {status === "loading" && <LoadingState message="Loading member schools…" />}
        {status === "error" && (
          <ErrorState message="Could not load member schools." onRetry={() => void load()} at={failedAt ?? undefined} />
        )}
        {status === "empty" && (
          <EmptyState
            icon={Building2}
            title="No schools in this cluster"
            message="Assign schools to this cluster from the cluster workspace."
            compact
          />
        )}
        {status === "ready" && (
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {schools.map((s) => (
              <li key={s.schoolId}>
                <Link
                  href={`/schools/${s.schoolId}`}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--color-edify-soft)]/40"
                >
                  <span className="h-8 w-8 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                    <Building2 size={14} />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-body font-extrabold tracking-tight truncate">{s.name}</div>
                    <div className="text-caption muted truncate">
                      {s.schoolType}
                      {s.subCounty ? ` · ${s.subCounty}` : ""}
                      {s.latestSsa != null ? ` · SSA ${s.latestSsa}%` : ""}
                    </div>
                  </div>
                  <span
                    className={`px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap ${
                      s.ssaStatus === "Completed"
                        ? "bg-emerald-100 text-emerald-700"
                        : s.ssaStatus === "Overdue"
                          ? "bg-rose-100 text-rose-700"
                          : "bg-amber-100 text-amber-700"
                    }`}
                  >
                    {s.ssaStatus}
                  </span>
                  <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
