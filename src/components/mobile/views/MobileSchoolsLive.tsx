"use client";

// Mobile School Directory — LIVE. Renders the SAME directory rows the desktop
// directory uses (live from edify-api when the backend is on, the in-memory
// directory otherwise), so a phone tester sees real schools with real status
// instead of the legacy fabricated SchoolsIntelligence mock set. Read-only +
// scannable: name, type, location, owner, and the workflow-status chips. Full
// assign/cluster actions stay on the desktop directory.

import { useMemo, useState } from "react";
import { School, MapPin, UserRound, Search } from "lucide-react";
import type { DirectorySchoolVM } from "@/components/cluster/DirectoryClusterDrawer";
import { EmptyState } from "@/components/ui/DataStates";

const STAGE_LABEL: Record<NonNullable<DirectorySchoolVM["stage"]>, { label: string; tone: string }> = {
  needs_owner:    { label: "Needs owner",    tone: "bg-rose-100 text-rose-700" },
  unclustered:    { label: "Unclustered",    tone: "bg-amber-100 text-amber-700" },
  ssa_required:   { label: "SSA required",   tone: "bg-sky-100 text-sky-700" },
  planning_ready: { label: "Planning ready", tone: "bg-emerald-100 text-emerald-700" },
};

export function MobileSchoolsLive({ schools, live = false }: { schools: DirectorySchoolVM[]; live?: boolean }) {
  const [q, setQ] = useState("");
  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return schools;
    return schools.filter(
      (s) => s.schoolName.toLowerCase().includes(t) || s.district.toLowerCase().includes(t) || (s.assignedCceo ?? "").toLowerCase().includes(t),
    );
  }, [q, schools]);

  return (
    <div className="px-3 pb-24 space-y-3">
      <div className="flex items-center justify-between gap-2 pt-1">
        <h1 className="text-[17px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><School size={17} /> Schools</h1>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">{live ? "Live" : "Demo"} · {schools.length}</span>
      </div>

      <label className="flex items-center gap-2 h-10 px-3 rounded-xl border border-[var(--color-edify-border)] bg-[var(--surface-1)]">
        <Search size={15} className="muted shrink-0" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search school, district, owner" className="flex-1 bg-transparent text-[13px] outline-none" />
      </label>

      {filtered.length === 0 ? (
        <EmptyState compact title="No schools" message={q ? "Nothing matches your search." : "No schools in your portfolio yet."} />
      ) : (
        <ul className="space-y-2">
          {filtered.map((s) => {
            const stage = s.stage ? STAGE_LABEL[s.stage] : null;
            return (
              <li key={s.schoolId} className="rounded-xl border border-[var(--color-edify-border)] bg-[var(--surface-1)] p-3">
                <div className="flex items-start justify-between gap-2">
                  <span className="min-w-0">
                    <span className="block text-[13.5px] font-bold truncate">{s.schoolName}</span>
                    <span className="block text-[11px] muted truncate inline-flex items-center gap-1"><MapPin size={11} /> {s.district}{s.region ? ` · ${s.region}` : ""}</span>
                  </span>
                  <span className="shrink-0 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] border border-[var(--color-edify-border)]">{s.schoolType}</span>
                </div>
                {s.assignedCceo && (
                  <p className="mt-1 text-[11px] muted inline-flex items-center gap-1"><UserRound size={11} /> {s.assignedCceo}</p>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span className={`px-1.5 py-0.5 rounded text-[9.5px] font-bold ${s.ssaStatus === "SSA Done" ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>{s.ssaStatus}</span>
                  <span className={`px-1.5 py-0.5 rounded text-[9.5px] font-bold ${s.clusterStatus === "clustered" ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>{s.clusterStatus === "clustered" ? "Clustered" : "Unclustered"}</span>
                  {stage && <span className={`px-1.5 py-0.5 rounded text-[9.5px] font-bold ${stage.tone}`}>{stage.label}</span>}
                  {s.duplicate && <span className="px-1.5 py-0.5 rounded text-[9.5px] font-bold bg-rose-100 text-rose-700">Possible duplicate</span>}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
