"use client";

// Client-side Core School Directory. Self-fetches /api/core-schools (which
// proxies the edify-api backend via the shared surfaces fetchers) and renders
// the canonical DataStates — Loading while in flight, Error (with retry) on a
// backend failure, Empty when the database returns no core schools. No mock
// fallback: "No backend data = empty state. Backend failure = error."

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, BarChart3, Database, Wallet } from "lucide-react";
import { CoreExportButton, type ExportRow } from "@/components/core/CoreExportButton";
import { LoadingState, EmptyState, ErrorState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";

type BeSchool = {
  id: string;
  schoolId: string;
  name: string;
  district?: { name: string } | null;
  cluster?: { name: string } | null;
  accountOwnerNameRaw?: string | null;
  currentFySsaStatus: string;
  planningReadiness: string;
  schoolType: string;
};
type BeHeader = {
  fy: string;
  corePlansCount: number;
  championsCount: number;
  awaitingSSACount: number;
  totalCoreSchools: number;
  planningReadyCount: number;
};
type ApiResponse =
  | { live: true; header: BeHeader; schools: BeSchool[]; total: number }
  | { live: false; error: string | null };

type Loaded = { header: BeHeader; schools: BeSchool[]; total: number };

const SSA_LABEL: Record<string, string> = { done: "SSA Complete", not_done: "No SSA", scheduled: "SIT Scheduled", partner_assigned: "Partner SSA" };
const READY_LABEL: Record<string, string> = { ready: "Planning Ready", limited: "SSA Required", locked: "Unclustered" };

export function CoreDirectoryClient({ role }: { role: string }) {
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [failedAt, setFailedAt] = useState<Date | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/core-schools", { cache: "no-store" });
      const json = (await res.json()) as ApiResponse;
      if (!res.ok || !json.live) {
        setError(json.live === false && json.error ? json.error : "Could not load core schools.");
        setFailedAt(new Date());
        setData(null);
      } else {
        setData({ header: json.header, schools: json.schools, total: json.total });
      }
    } catch {
      setError("Could not reach the server.");
      setFailedAt(new Date());
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <LoadingState message="Loading core schools…" />;
  if (error) return <ErrorState message={error} at={failedAt ?? undefined} onRetry={() => void load()} />;
  if (!data) return <EmptyState title="No core schools" message="No core schools are in your scope yet." />;

  const { header, schools, total } = data;
  const exportRows: ExportRow[] = schools.map((s) => ({
    schoolId: s.schoolId, school: s.name, district: s.district?.name ?? "", cluster: s.cluster?.name ?? "",
    owner: s.accountOwnerNameRaw ?? "", ssaStatus: s.currentFySsaStatus, planningReadiness: s.planningReadiness,
  }));
  const canSeePayments = ["ProgramAccountant", "CountryDirector", "CountryProgramLead", "Admin"].includes(role);

  return (
    <>
      <div className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 text-emerald-700 px-2.5 py-1 text-[11px] font-bold border border-emerald-200">
        <Database size={12} /> Live · backend API · FY{header.fy}
      </div>
      <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
        <Kpi label="Core schools" value={header.totalCoreSchools} />
        <Kpi label="Core plans" value={header.corePlansCount} />
        <Kpi label="Awaiting SSA" value={header.awaitingSSACount} />
        <Kpi label="Planning ready" value={header.planningReadyCount} />
        <Kpi label="Champions" value={header.championsCount} tone="text-amber-700" />
        <Kpi label="Shown" value={schools.length} />
      </section>

      <section className="card p-3.5">
        <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
          <h2 className="text-[13px] font-extrabold tracking-tight">Core School Directory <span className="muted font-semibold">({total})</span></h2>
          <div className="flex items-center gap-3">
            <CoreExportButton rows={exportRows} filename="core-schools" />
            {canSeePayments && (
              <Link href="/core-schools/payments" className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-[var(--color-edify-primary)] hover:text-[var(--color-edify-dark)]"><Wallet size={12} /> Payments</Link>
            )}
            <Link href="/core-schools/analytics" className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-[var(--color-edify-primary)] hover:text-[var(--color-edify-dark)]"><BarChart3 size={12} /> Analytics</Link>
            <Link href="/planning/core-schools" className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-[var(--color-edify-primary)] hover:text-[var(--color-edify-dark)]">Planning Console <ArrowRight size={12} /></Link>
          </div>
        </div>
        {schools.length === 0 ? (
          <EmptyState compact title="No core schools" message="No core schools are in your scope." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                  <th className="py-2 pr-2">School</th><th className="py-2 px-2">District · Cluster</th><th className="py-2 px-2">Owner</th>
                  <th className="py-2 px-2">SSA</th><th className="py-2 px-2">Planning</th><th className="py-2 pl-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-edify-divider)]">
                {schools.map((s) => (
                  <tr key={s.id} className="hover:bg-[var(--color-edify-soft)]/30 align-top">
                    <td className="py-2.5 pr-2">
                      <Link href={`/core-schools/${s.schoolId}`} className="font-extrabold hover:underline">{s.name}</Link>
                      <div className="text-[10px] muted tabular">ID {s.schoolId}</div>
                    </td>
                    <td className="py-2.5 px-2 muted">{s.district?.name ?? "—"}{s.cluster?.name ? ` · ${s.cluster.name}` : ""}</td>
                    <td className="py-2.5 px-2 muted">{s.accountOwnerNameRaw ?? "—"}</td>
                    <td className="py-2.5 px-2"><Pill label={SSA_LABEL[s.currentFySsaStatus] ?? s.currentFySsaStatus} ok={s.currentFySsaStatus === "done"} /></td>
                    <td className="py-2.5 px-2"><Pill label={READY_LABEL[s.planningReadiness] ?? s.planningReadiness} ok={s.planningReadiness === "ready"} warn={s.planningReadiness === "limited"} /></td>
                    <td className="py-2.5 pl-2 text-right"><Link href={`/core-schools/${s.schoolId}`} className="text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline">Detail →</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

function Pill({ label, ok, warn }: { label: string; ok?: boolean; warn?: boolean }) {
  return <span className={cn("inline-flex px-1.5 py-[2px] rounded text-[10px] font-bold", ok ? "bg-emerald-100 text-emerald-700" : warn ? "bg-amber-100 text-amber-700" : "bg-rose-100 text-rose-700")}>{label}</span>;
}

function Kpi({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="card px-3 py-2.5">
      <div className="text-[10px] font-semibold muted leading-tight">{label}</div>
      <div className={cn("text-[18px] font-extrabold tabular leading-none mt-1", tone)}>{value}</div>
    </div>
  );
}
