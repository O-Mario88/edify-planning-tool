"use client";

// The School Directory / Portfolio list — the SINGLE assignment surface (on the
// uploaded/intake schools, the source of truth). Every row shows its workflow
// stage; the "Manage" action opens one drawer for cluster, special-project, and
// partner assignment. Multi-select enables bulk cluster / project assignment —
// there is no separate workspace.

import { useMemo, useState, useTransition } from "react";
import Link from "next/link";
import {
  Building2, MapPin, User, Search, Network, ArrowRight, CheckCircle2, AlertTriangle,
  Sparkles, Handshake, Settings2, X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DirectoryClusterDrawer, type DirectorySchoolVM } from "./DirectoryClusterDrawer";
import type { DirectoryProjectTag } from "./DirectoryClusterDrawer";
import { assignToExistingClusterAction } from "@/lib/actions/cluster-actions";
import { assignSchoolsToProjectAction } from "@/lib/actions/special-project-actions";

type Stage = NonNullable<DirectorySchoolVM["stage"]>;
type StageFilter = "all" | Stage;

export type DirectoryClusterOption = { id: string; name: string; district: string };

const STAGE_META: Record<Stage, { label: string; cls: string }> = {
  needs_owner:    { label: "Needs owner",    cls: "bg-rose-50 text-rose-700" },
  unclustered:    { label: "Unclustered",    cls: "bg-rose-50 text-rose-700" },
  ssa_required:   { label: "SSA required",   cls: "bg-amber-50 text-amber-700" },
  planning_ready: { label: "Planning ready", cls: "bg-emerald-50 text-emerald-700" },
};

function stageOf(s: DirectorySchoolVM): Stage {
  if (s.stage) return s.stage;
  return s.clusterStatus === "clustered" ? "ssa_required" : "unclustered";
}

export function SchoolsClusterDirectory({
  schools,
  canManage,
  clusterOptions = [],
  projectOptions = [],
  partnerOptions = [],
  interventionAreas = [],
}: {
  schools: DirectorySchoolVM[];
  canManage: boolean;
  clusterOptions?: DirectoryClusterOption[];
  projectOptions?: DirectoryProjectTag[];
  partnerOptions?: string[];
  interventionAreas?: string[];
}) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<StageFilter>("all");
  const [district, setDistrict] = useState("");
  const [subCounty, setSubCounty] = useState("");
  const [owner, setOwner] = useState("");
  const [type, setType] = useState("");
  const [ssa, setSsa] = useState("");
  const [cluster, setCluster] = useState("");
  const [drawerSchool, setDrawerSchool] = useState<DirectorySchoolVM | null>(null);
  const [drawerTab, setDrawerTab] = useState<"cluster" | "project" | "partner">("cluster");
  const [toast, setToast] = useState<string | null>(null);

  // Bulk selection
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkCluster, setBulkCluster] = useState("");
  const [bulkProject, setBulkProject] = useState("");
  const [pending, startTransition] = useTransition();

  const districts = useMemo(() => [...new Set(schools.map((s) => s.district))].sort(), [schools]);
  const subCounties = useMemo(
    () => [...new Set(schools.map((s) => s.subCounty).filter(Boolean) as string[])].sort(),
    [schools],
  );
  const owners = useMemo(() => [...new Set(schools.map((s) => s.assignedCceo).filter(Boolean) as string[])].sort(), [schools]);
  const clusterNames = useMemo(() => [...new Set(schools.map((s) => s.clusterName).filter(Boolean) as string[])].sort(), [schools]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return schools.filter((s) => {
      if (needle && !`${s.schoolName} ${s.schoolId} ${s.district} ${s.subCounty ?? ""}`.toLowerCase().includes(needle)) return false;
      if (status !== "all" && stageOf(s) !== status) return false;
      if (district && s.district !== district) return false;
      if (subCounty && s.subCounty !== subCounty) return false;
      if (owner && s.assignedCceo !== owner) return false;
      if (type && s.schoolType !== type) return false;
      if (ssa === "done" && s.ssaStatus !== "SSA Done") return false;
      if (ssa === "pending" && s.ssaStatus === "SSA Done") return false;
      if (cluster && s.clusterName !== cluster) return false;
      return true;
    });
  }, [schools, q, status, district, subCounty, owner, type, ssa, cluster]);

  const unclusteredCount = schools.filter((s) => s.clusterStatus === "unclustered").length;

  function showToast(msg: string) { setToast(msg); setTimeout(() => setToast(null), 4500); }

  function onDrawerClose(changed?: boolean) {
    if (changed && drawerSchool) showToast(`${drawerSchool.schoolName} updated.`);
    setDrawerSchool(null);
  }
  function openDrawer(s: DirectorySchoolVM, tab: "cluster" | "project" | "partner") {
    setDrawerTab(tab);
    setDrawerSchool(s);
  }

  // ── Selection ──
  function toggleOne(id: string) {
    setSelected((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }
  const allFilteredSelected = filtered.length > 0 && filtered.every((s) => selected.has(s.schoolId));
  function toggleAllFiltered() {
    setSelected((prev) => {
      const n = new Set(prev);
      if (allFilteredSelected) filtered.forEach((s) => n.delete(s.schoolId));
      else filtered.forEach((s) => n.add(s.schoolId));
      return n;
    });
  }
  function clearSelection() { setSelected(new Set()); setBulkCluster(""); setBulkProject(""); }

  function bulkAssignCluster() {
    if (!bulkCluster || selected.size === 0) return;
    const ids = [...selected];
    startTransition(async () => {
      const res = await assignToExistingClusterAction(ids, bulkCluster);
      if (res.ok) {
        const failed = res.failed?.length ?? 0;
        showToast(`${res.assigned} school${res.assigned === 1 ? "" : "s"} assigned to cluster${failed ? ` · ${failed} skipped (cross-district / already clustered)` : ""}.`);
        clearSelection();
      } else {
        showToast(res.reason === "FORBIDDEN" ? "You don't have permission." : res.reason === "FAILED" ? res.message : "Failed.");
      }
    });
  }
  function bulkAssignProject() {
    if (!bulkProject || selected.size === 0) return;
    const ids = [...selected];
    startTransition(async () => {
      const res = await assignSchoolsToProjectAction(ids, bulkProject);
      if (res.ok) {
        showToast(`${res.assigned} school${res.assigned === 1 ? "" : "s"} added to project${res.skipped ? ` · ${res.skipped} already in it` : ""}.`);
        clearSelection();
      } else {
        showToast(res.reason === "FORBIDDEN" ? "You don't have permission." : res.message);
      }
    });
  }

  return (
    <section className="card rounded-2xl overflow-hidden">
      <header className="px-4 pt-3.5 pb-2 flex items-start gap-3 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <Network size={15} className="text-[var(--color-edify-primary)]" /> School directory
          </h2>
          <p className="text-[12px] muted mt-0.5">
            Every assignment starts here — cluster, special project, and partner. Clustering unlocks SSA / SIT and planning.
          </p>
        </div>
        <span className={cn("ml-auto shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[12px] font-extrabold",
          unclusteredCount ? "bg-rose-50 text-rose-700" : "bg-emerald-50 text-emerald-700")}>
          {unclusteredCount ? <AlertTriangle size={13} /> : <CheckCircle2 size={13} />}
          {unclusteredCount} unclustered
        </span>
      </header>

      {/* Filters */}
      <div className="px-3 pb-3 border-b border-[var(--color-edify-divider)] space-y-2.5">
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)]" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search school, id, district…"
            className="w-full h-9 pl-8 pr-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12.5px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30" />
        </div>
        <div className="flex flex-wrap gap-2">
          <FilterSelect value={status} onChange={(v) => setStatus(v as StageFilter)} label="Stage"
            options={[["all", "All stages"], ["needs_owner", "Needs owner"], ["unclustered", "Unclustered"], ["ssa_required", "SSA required"], ["planning_ready", "Planning ready"]]} />
          <FilterSelect value={district} onChange={setDistrict} label="District" options={districts} />
          <FilterSelect value={subCounty} onChange={setSubCounty} label="Sub-county" options={subCounties} />
          <FilterSelect value={owner} onChange={setOwner} label="Account owner" options={owners} />
          <FilterSelect value={type} onChange={setType} label="Type" options={["Client", "Core", "Potential Core", "Other"]} />
          <FilterSelect value={ssa} onChange={setSsa} label="SSA" options={[["pending", "SSA pending"], ["done", "SSA done"]]} />
          {clusterNames.length > 0 && <FilterSelect value={cluster} onChange={setCluster} label="Cluster" options={clusterNames} />}
        </div>
      </div>

      {/* Bulk action bar */}
      {canManage && selected.size > 0 && (
        <div className="px-3 py-2.5 border-b border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/40 flex flex-wrap items-center gap-2">
          <span className="text-[12px] font-extrabold inline-flex items-center gap-1.5">
            <CheckCircle2 size={13} className="text-[var(--color-edify-primary)]" /> {selected.size} selected
          </span>
          <span className="mx-1 h-4 w-px bg-[var(--color-edify-border)]" />
          {/* Cluster */}
          <select value={bulkCluster} onChange={(e) => setBulkCluster(e.target.value)}
            className="h-8 px-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px]">
            <option value="">Assign to cluster…</option>
            {clusterOptions.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.district}</option>)}
          </select>
          <button type="button" disabled={pending || !bulkCluster} onClick={bulkAssignCluster}
            className="h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[11.5px] font-extrabold disabled:opacity-40 inline-flex items-center gap-1.5">
            <Network size={12} /> Assign
          </button>
          <span className="mx-1 h-4 w-px bg-[var(--color-edify-border)]" />
          {/* Project */}
          <select value={bulkProject} onChange={(e) => setBulkProject(e.target.value)}
            className="h-8 px-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px]">
            <option value="">Add to special project…</option>
            {projectOptions.map((p) => <option key={p.projectId} value={p.projectId}>{p.projectShortName}</option>)}
          </select>
          <button type="button" disabled={pending || !bulkProject} onClick={bulkAssignProject}
            className="h-8 px-3 rounded-lg bg-violet-600 text-white text-[11.5px] font-extrabold disabled:opacity-40 inline-flex items-center gap-1.5">
            <Sparkles size={12} /> Add
          </button>
          <button type="button" onClick={clearSelection} className="ml-auto text-[11.5px] font-semibold muted hover:text-[var(--color-edify-text)] inline-flex items-center gap-1">
            <X size={12} /> Clear
          </button>
        </div>
      )}

      {/* Select-all row */}
      {canManage && filtered.length > 0 && (
        <div className="px-3.5 py-1.5 border-b border-[var(--color-edify-divider)] flex items-center gap-2">
          <input type="checkbox" checked={allFilteredSelected} onChange={toggleAllFiltered} className="h-3.5 w-3.5 accent-[var(--color-edify-primary)]" />
          <span className="text-[11px] muted">Select all {filtered.length} shown</span>
        </div>
      )}

      {/* Rows */}
      <ul className="divide-y divide-[var(--color-edify-divider)] max-h-[60vh] overflow-y-auto">
        {filtered.length === 0 ? (
          <li className="px-4 py-8 text-center text-[12px] muted">No schools match these filters.</li>
        ) : filtered.map((s) => {
          const stage = stageOf(s);
          const meta = STAGE_META[stage];
          const projects = s.projects ?? [];
          const delegations = s.delegations ?? [];
          return (
            <li key={s.schoolId} className="px-3.5 py-3 flex items-start gap-3">
              {canManage && (
                <input type="checkbox" checked={selected.has(s.schoolId)} onChange={() => toggleOne(s.schoolId)}
                  className="mt-1.5 h-3.5 w-3.5 accent-[var(--color-edify-primary)] shrink-0" />
              )}
              <span className="grid place-items-center h-8 w-8 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                <Building2 size={13} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <Link href={`/schools/${s.schoolId}`} className="text-[12.5px] font-extrabold tracking-tight truncate hover:underline">{s.schoolName}</Link>
                  <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold", s.schoolType === "Core" ? "bg-violet-50 text-violet-700" : "bg-blue-50 text-blue-700")}>{s.schoolType}</span>
                  <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold", meta.cls)}>{meta.label}</span>
                  {s.duplicate && <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-amber-50 text-amber-700 inline-flex items-center gap-1"><AlertTriangle size={9} />Dup</span>}
                </div>
                <p className="text-[11px] muted leading-tight inline-flex items-center gap-1 mt-0.5">
                  <MapPin size={9} className="text-[var(--color-edify-primary)]" />{s.district}{s.subCounty ? ` · ${s.subCounty}` : ""}
                  <span className="opacity-50">·</span><User size={9} />{s.assignedCceo ?? "Unassigned"}
                </p>
                {/* Membership chips */}
                <div className="flex flex-wrap items-center gap-1.5 mt-1">
                  {s.clusterName && (
                    <span className="text-[10.5px] inline-flex items-center gap-1 px-1.5 py-[1px] rounded text-[var(--color-edify-primary)] font-semibold bg-[var(--color-edify-soft)]">
                      <Network size={9} /> {s.clusterName}
                    </span>
                  )}
                  {projects.map((p) => (
                    <span key={p.projectId} className="text-[10.5px] inline-flex items-center gap-1 px-1.5 py-[1px] rounded bg-violet-50 text-violet-700 font-semibold">
                      <Sparkles size={9} /> {p.projectShortName}
                    </span>
                  ))}
                  {delegations.map((d) => (
                    <span key={d.id} className="text-[10.5px] inline-flex items-center gap-1 px-1.5 py-[1px] rounded bg-sky-50 text-sky-700 font-semibold">
                      <Handshake size={9} /> {d.partnerName}
                    </span>
                  ))}
                </div>
              </div>
              {/* Actions */}
              <div className="shrink-0 flex flex-col items-end gap-1.5">
                {stage === "unclustered" && canManage ? (
                  <button type="button" onClick={() => openDrawer(s, "cluster")}
                    className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[11.5px] font-extrabold hover:bg-[var(--color-edify-dark)] transition-colors">
                    Add to Cluster <ArrowRight size={12} />
                  </button>
                ) : stage === "needs_owner" ? (
                  <Link href="/data-intake/queue" className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] font-extrabold text-rose-700 hover:bg-rose-50 transition-colors">
                    Map owner <ArrowRight size={12} />
                  </Link>
                ) : stage === "ssa_required" ? (
                  <Link href={`/schools/${s.schoolId}`} className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] font-extrabold text-amber-700 hover:bg-amber-50 transition-colors">
                    Activate SSA <ArrowRight size={12} />
                  </Link>
                ) : stage === "planning_ready" ? (
                  <Link href="/planning" className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] font-extrabold text-emerald-700 hover:bg-emerald-50 transition-colors">
                    Plan support <ArrowRight size={12} />
                  </Link>
                ) : null}
                {canManage && (
                  <button type="button" onClick={() => openDrawer(s, s.clusterStatus === "unclustered" ? "project" : "cluster")}
                    className="inline-flex items-center gap-1 text-[11px] font-semibold muted hover:text-[var(--color-edify-text)]">
                    <Settings2 size={11} /> Manage
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <DirectoryClusterDrawer
        key={`${drawerSchool?.schoolId ?? "none"}-${drawerTab}`}
        open={!!drawerSchool}
        school={drawerSchool}
        onClose={onDrawerClose}
        initialTab={drawerTab}
        projectOptions={projectOptions}
        partnerOptions={partnerOptions}
        interventionAreas={interventionAreas}
      />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-[12px] font-semibold px-4 py-3 max-w-[420px] inline-flex items-start gap-2">
          <CheckCircle2 size={15} className="mt-0.5 shrink-0" /> {toast}
        </div>
      )}
    </section>
  );
}

function FilterSelect({
  value, onChange, label, options,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  options: (string | [string, string])[];
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}
      className={cn("h-8 px-2 rounded-lg border text-[11.5px] bg-white",
        value && value !== "all" ? "border-[var(--color-edify-primary)] text-[var(--color-edify-primary)] font-semibold" : "border-[var(--color-edify-border)] text-[var(--color-edify-text)]")}>
      <option value={Array.isArray(options[0]) ? "all" : ""}>{label}</option>
      {options.map((o) => {
        const [val, lbl] = Array.isArray(o) ? o : [o, o];
        if (val === "all") return null;
        return <option key={val} value={val}>{lbl}</option>;
      })}
    </select>
  );
}
