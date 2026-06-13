"use client";

// ProjectMonitorLive — the backend-driven Project Coordinator monitoring panel.
// Self-fetches a project's assigned schools, intervention-improvement impact,
// and partner delivery from edify-api. Satisfies:
//  (1) assigned schools show here for planning/assigning (Schedule / Assign),
//  (2) intervention improvement is monitored (baseline → latest on the target),
//  (3) partners on the project are monitored (delivery progress) + assign/remove.

import { useEffect, useState } from "react";
import { Building2, TrendingUp, TrendingDown, Minus, Handshake, Calendar, Plus, X, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { ScheduleActivityLive } from "@/components/planning/ScheduleActivityLive";
import type { BeProjectImpact, BeProjectPartner } from "@/lib/api/surfaces";

type SchoolRow = { schoolId: string; name: string; schoolType: string; district: string | null; ssaStatus: string };
function humanizeIntervention(key?: string | null): string {
  if (!key) return "—";
  return key.split("_").map((w) => (w === "and" ? "&" : w.charAt(0).toUpperCase() + w.slice(1))).join(" ");
}

export function ProjectMonitorLive({ projectId, role }: { projectId: string; role?: string }) {
  const [schools, setSchools] = useState<SchoolRow[] | null>(null);
  const [impact, setImpact] = useState<BeProjectImpact | null>(null);
  const [partners, setPartners] = useState<BeProjectPartner[] | null>(null);
  const [allPartners, setAllPartners] = useState<{ id: string; name: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [scheduling, setScheduling] = useState<{ school: SchoolRow; mode: "schedule" | "assign" } | null>(null);
  const [addingPartner, setAddingPartner] = useState(false);
  const [partnerPick, setPartnerPick] = useState("");

  const load = () => {
    setLoading(true); setError(null);
    Promise.all([
      fetch(`/api/special-projects/${encodeURIComponent(projectId)}`, { credentials: "include" }).then((r) => r.json()),
      fetch(`/api/special-projects/${encodeURIComponent(projectId)}/impact`, { credentials: "include" }).then((r) => r.json()),
      fetch(`/api/special-projects/${encodeURIComponent(projectId)}/partners`, { credentials: "include" }).then((r) => r.json()),
    ])
      .then(([d, im, pr]) => {
        if (d.live) setSchools(d.schools ?? []); else setError(d.error || "Could not load the project");
        if (im.live) setImpact(im);
        if (pr.live) setPartners(pr.partners ?? []);
      })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, [projectId]);
  useEffect(() => {
    fetch("/api/partners", { credentials: "include" }).then((r) => r.json())
      .then((j) => { if (j.live) setAllPartners(j.partners.map((p: { id: string; name: string }) => ({ id: p.id, name: p.name }))); })
      .catch(() => undefined);
  }, []);

  async function addPartner() {
    if (!partnerPick) return;
    await fetch(`/api/special-projects/${encodeURIComponent(projectId)}/partners`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ partnerId: partnerPick }),
    }).catch(() => undefined);
    setAddingPartner(false); setPartnerPick(""); load();
  }
  async function removePartner(partnerId: string) {
    await fetch(`/api/special-projects/${encodeURIComponent(projectId)}/partners/${encodeURIComponent(partnerId)}`, { method: "DELETE", credentials: "include" }).catch(() => undefined);
    load();
  }

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} onRetry={load} />;

  const assignedIds = new Set((partners ?? []).map((p) => p.id));
  const addable = allPartners.filter((p) => !assignedIds.has(p.id));

  return (
    <div className="space-y-4">
      {/* ── Impact: intervention improvement ── */}
      <section className="card p-3.5">
        <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
          <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><TrendingUp size={14} /> Intervention impact</h3>
          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
        </header>
        {impact && (
          <>
            <div className="flex flex-wrap items-center gap-2 mb-2 text-[11.5px]">
              <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md bg-[var(--color-edify-soft)]/60 font-bold"><Sparkles size={11} className="text-[var(--color-edify-primary)]" /> Target: {humanizeIntervention(impact.intervention)}</span>
              <span className="muted">{impact.improvedCount}/{impact.measuredCount} schools improved</span>
              {impact.avgDelta != null && (
                <span className={cn("font-extrabold inline-flex items-center gap-0.5", impact.avgDelta > 0 ? "text-emerald-600" : impact.avgDelta < 0 ? "text-rose-600" : "muted")}>
                  {impact.avgDelta > 0 ? <TrendingUp size={12} /> : impact.avgDelta < 0 ? <TrendingDown size={12} /> : <Minus size={12} />}
                  avg {impact.avgDelta > 0 ? "+" : ""}{impact.avgDelta}/10
                </span>
              )}
            </div>
            <div className="overflow-x-auto rounded-lg border border-[var(--color-edify-divider)]">
              <table className="w-full text-[11.5px]">
                <thead><tr className="text-left text-[10px] uppercase tracking-wider font-bold muted border-b border-[var(--color-edify-divider)]">
                  <th className="px-2.5 py-1.5">School</th><th className="px-2.5 py-1.5">Baseline</th><th className="px-2.5 py-1.5">Latest</th><th className="px-2.5 py-1.5">Change</th>
                </tr></thead>
                <tbody className="divide-y divide-[var(--color-edify-divider)]">
                  {impact.schools.map((s) => (
                    <tr key={s.schoolId}>
                      <td className="px-2.5 py-1.5 font-semibold">{s.name}</td>
                      <td className="px-2.5 py-1.5 tabular">{s.baseline ?? "—"}</td>
                      <td className="px-2.5 py-1.5 tabular">{s.latest ?? "—"}</td>
                      <td className={cn("px-2.5 py-1.5 tabular font-extrabold", s.delta == null ? "muted" : s.delta > 0 ? "text-emerald-600" : s.delta < 0 ? "text-rose-600" : "muted")}>
                        {s.delta == null ? "—" : `${s.delta > 0 ? "+" : ""}${s.delta}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      {/* ── Assigned schools: plan / assign ── */}
      <section className="card p-3.5">
        <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5 mb-2.5"><Building2 size={14} /> Project schools <span className="muted font-semibold">· {schools?.length ?? 0}</span></h3>
        {!schools || schools.length === 0 ? (
          <EmptyState compact title="No schools yet" message="Assign schools to this project from the School Directory." />
        ) : (
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {schools.map((s) => (
              <li key={s.schoolId} className="flex items-center justify-between gap-2 py-2 text-[12px]">
                <span className="min-w-0 truncate"><span className="font-extrabold">{s.name}</span><span className="muted"> · {s.district ?? s.schoolId}</span></span>
                <span className="flex items-center gap-1.5 shrink-0">
                  <button onClick={() => setScheduling({ school: s, mode: "schedule" })} className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[10.5px] font-bold"><Calendar size={11} /> Schedule</button>
                  <button onClick={() => setScheduling({ school: s, mode: "assign" })} className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-sky-700 hover:bg-sky-50 text-[10.5px] font-bold"><Handshake size={11} /> Assign</button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── Partner monitoring ── */}
      <section className="card p-3.5">
        <header className="flex items-center justify-between gap-2 mb-2.5">
          <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Handshake size={14} /> Partner monitoring <span className="muted font-semibold">· {partners?.length ?? 0}</span></h3>
          {addable.length > 0 && !addingPartner && (
            <button onClick={() => setAddingPartner(true)} className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[10.5px] font-bold hover:bg-[var(--color-edify-soft)]/60"><Plus size={11} /> Assign partner</button>
          )}
        </header>
        {addingPartner && (
          <div className="flex items-center gap-1.5 mb-2.5">
            <select value={partnerPick} onChange={(e) => setPartnerPick(e.target.value)} className="h-8 px-2 rounded-lg border border-[var(--color-edify-border)] text-[12px] flex-1">
              <option value="">Choose a partner…</option>
              {addable.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <button onClick={addPartner} disabled={!partnerPick} className="h-8 px-2.5 rounded-lg bg-[var(--color-edify-primary)] text-white text-[11px] font-bold disabled:opacity-50">Add</button>
            <button onClick={() => { setAddingPartner(false); setPartnerPick(""); }} className="h-8 w-8 grid place-items-center rounded-lg hover:bg-[var(--color-edify-soft)]/60"><X size={14} /></button>
          </div>
        )}
        {!partners || partners.length === 0 ? (
          <EmptyState compact title="No partners assigned" message="Assign a partner to deliver and monitor their progress." />
        ) : (
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {partners.map((p) => {
              const pct = p.activityTotal ? Math.round((p.activityCompleted / p.activityTotal) * 100) : 0;
              return (
                <li key={p.id} className="flex items-center justify-between gap-2 py-2 text-[12px]">
                  <span className="min-w-0">
                    <span className="font-extrabold">{p.name}</span>
                    {p.isCertified && <span className="ml-1.5 inline-flex items-center px-1.5 py-[1px] rounded bg-emerald-50 text-emerald-700 text-[9.5px] font-bold">Certified</span>}
                    <span className="block text-[10.5px] muted">{p.activityCompleted}/{p.activityTotal} project activities delivered{p.activityTotal ? ` · ${pct}%` : ""}</span>
                  </span>
                  <button onClick={() => removePartner(p.id)} aria-label={`Remove ${p.name}`} className="h-7 w-7 grid place-items-center rounded-lg text-[var(--color-edify-muted)] hover:text-rose-600 hover:bg-rose-50"><X size={13} /></button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {scheduling && (
        <ScheduleActivityLive
          schoolId={scheduling.school.schoolId}
          schoolName={scheduling.school.name}
          schoolType="client"
          mode={scheduling.mode}
          assigningRole={role}
          onClose={() => setScheduling(null)}
          onScheduled={() => { setScheduling(null); load(); }}
        />
      )}
    </div>
  );
}
