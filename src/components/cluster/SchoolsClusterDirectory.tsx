"use client";

// The School Directory / Portfolio list — the SINGLE assignment surface (on the
// uploaded/intake schools, the source of truth). Every row shows its workflow
// stage; the "Manage" action opens one drawer for cluster, special-project, and
// partner assignment. Multi-select enables bulk cluster / project assignment —
// there is no separate workspace.

import { useMemo, useState, useTransition } from "react";
import Link from "next/link";
import {
  Building2, MapPin, User, Search, Network, CheckCircle2, AlertTriangle,
  Sparkles, Handshake, X, ChevronDown, ChevronRight, Phone, UserCircle2,
  Calendar, AlertCircle, Users, Briefcase,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DirectoryClusterDrawer, type DirectorySchoolVM } from "./DirectoryClusterDrawer";
import type { DirectoryProjectTag } from "./DirectoryClusterDrawer";
import { CreateClusterButton } from "./CreateClusterButton";
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
  canManageClusters = true,
  userRole = "",
  userName = "",
  clusterOptions = [],
  projectOptions = [],
  partnerOptions = [],
  interventionAreas = [],
}: {
  schools: DirectorySchoolVM[];
  canManage: boolean;
  /** Cluster assignment is a CCEO/PL responsibility; when false (e.g. Project
   *  Coordinator) cluster controls are hidden and the drawer shows it read-only. */
  canManageClusters?: boolean;
  /** Viewer's role — drives the CCEO/PL vs. other role button set. */
  userRole?: string;
  /** Viewer's name — used as defaultProposedBy in the scheduling drawer. */
  userName?: string;
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
  // Per-row expansion — tracks which school ids are expanded.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

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

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  }

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
        <div className="ml-auto shrink-0 flex items-center gap-2">
          {/* The full standalone "Create a new cluster" drawer (district →
              sub-counties → name → leader). Creates an empty cluster; schools are
              assigned from this directory afterwards. */}
          {canManageClusters && <CreateClusterButton />}
          <span className={cn("inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[12px] font-extrabold",
            unclusteredCount ? "bg-rose-50 text-rose-700" : "bg-emerald-50 text-emerald-700")}>
            {unclusteredCount ? <AlertTriangle size={13} /> : <CheckCircle2 size={13} />}
            {unclusteredCount} unclustered
          </span>
        </div>
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
          {canManageClusters && (
            <>
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
            </>
          )}
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

      {/* Rows — unclustered schools first (full opacity), clustered greyed out at end */}
      <ul className="divide-y divide-[var(--color-edify-divider)] max-h-[60vh] overflow-y-auto">
        {filtered.length === 0 ? (
          <li className="px-4 py-8 text-center text-[12px] muted">No schools match these filters.</li>
        ) : filtered.map((s) => {
          const stage = stageOf(s);
          const meta = STAGE_META[stage];
          const projects = s.projects ?? [];
          const delegations = s.delegations ?? [];
          const isClustered = s.clusterStatus === "clustered";
          const isExpanded = expanded.has(s.schoolId);

          return (
            <li
              key={s.schoolId}
              className={cn("flex flex-col transition-colors", isClustered && "opacity-50")}
            >
              {/* ── Main row ── */}
              <div className="px-3.5 py-3 flex items-start gap-3">
                {canManage && !isClustered && (
                  <input type="checkbox" checked={selected.has(s.schoolId)} onChange={() => toggleOne(s.schoolId)}
                    className="mt-1.5 h-3.5 w-3.5 accent-[var(--color-edify-primary)] shrink-0" />
                )}
                {/* Expand toggle */}
                <button
                  type="button"
                  aria-label={isExpanded ? "Collapse school details" : "Expand school details"}
                  onClick={() => toggleExpand(s.schoolId)}
                  className="grid place-items-center h-8 w-8 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0 hover:brightness-95 transition-all"
                >
                  {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                </button>
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
                    {s.recommendation?.hasSsa && s.recommendation.strugglingCount > 0 && (
                      <span className={cn(
                        "text-[10.5px] inline-flex items-center gap-1 px-1.5 py-[1px] rounded font-semibold",
                        s.recommendation.weakestSeverity === "Critical" ? "bg-rose-50 text-rose-700" : "bg-amber-50 text-amber-700",
                      )}
                        title={`Weakest: ${s.recommendation.weakestArea} (${s.recommendation.weakestScore?.toFixed(1)}/10)`}>
                        <AlertTriangle size={9} />
                        {s.recommendation.strugglingCount} gap{s.recommendation.strugglingCount === 1 ? "" : "s"}
                      </span>
                    )}
                  </div>
                </div>
                {/* ── Directory actions — the directory does exactly two things:
                    assign the school to a CLUSTER and to a PROJECT. Scheduling /
                    partner assignment happen on the Planning page (after the
                    school is clustered), not here. ── */}
                <div className="shrink-0 flex flex-col items-end gap-1.5">
                  {canManage && (
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => openDrawer(s, "cluster")}
                        className={cn(
                          "inline-flex items-center gap-1 h-8 px-2.5 rounded-lg text-[11.5px] font-extrabold transition-colors whitespace-nowrap",
                          isClustered
                            ? "border border-[var(--color-edify-border)] bg-white text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]"
                            : "bg-[var(--color-edify-primary)] text-white hover:bg-[var(--color-edify-dark)]",
                        )}
                      >
                        <Users size={11} /> {isClustered ? "Clustered" : "Add to Cluster"}
                      </button>
                      <button
                        type="button"
                        onClick={() => openDrawer(s, "project")}
                        className="inline-flex items-center gap-1 h-8 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold text-violet-700 hover:bg-violet-50 transition-colors whitespace-nowrap"
                      >
                        <Briefcase size={11} /> Assign to Project
                      </button>
                    </div>
                  )}
                  {isClustered && (
                    <Link
                      href="/planning"
                      className="inline-flex items-center gap-1 text-[11px] font-semibold muted hover:text-[var(--color-edify-text)] transition-colors"
                    >
                      <Calendar size={10} /> View in Planning
                    </Link>
                  )}
                </div>
              </div>

              {/* ── Expanded detail panel ── */}
              {isExpanded && (
                <div className="mx-3.5 mb-3 rounded-xl border border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/40 px-3 py-2.5 space-y-2">
                  {/* Location */}
                  <div className="flex items-start gap-2">
                    <MapPin size={11} className="mt-0.5 shrink-0 text-[var(--color-edify-primary)]" />
                    <div className="text-[11.5px]">
                      <span className="font-semibold">{s.district}</span>
                      {s.subCounty && <span className="muted"> · {s.subCounty}</span>}
                      {s.parish && <span className="muted"> · {s.parish}</span>}
                    </div>
                  </div>
                  {/* Phone */}
                  <div className="flex items-center gap-2">
                    <Phone size={11} className="shrink-0 text-[var(--color-edify-muted)]" />
                    <span className="text-[11.5px]">{s.phone ?? <span className="muted italic">Phone not on file</span>}</span>
                  </div>
                  {/* Primary contact */}
                  <div className="flex items-center gap-2">
                    <UserCircle2 size={11} className="shrink-0 text-[var(--color-edify-muted)]" />
                    <span className="text-[11.5px]">
                      {s.primaryContact
                        ? <><span className="font-semibold">{s.primaryContact}</span><span className="muted"> · Director / Primary contact</span></>
                        : <span className="muted italic">Primary contact not on file</span>}
                    </span>
                  </div>
                  {/* SSA weak areas */}
                  {s.weakAreas && s.weakAreas.length > 0 && (
                    <div>
                      <div className="text-[10px] font-bold uppercase tracking-wide text-rose-600 mb-1 flex items-center gap-1">
                        <AlertCircle size={9} /> Struggling intervention areas
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {s.weakAreas.map((w) => (
                          <span
                            key={w.area}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-[11px] font-extrabold"
                          >
                            {w.area}
                            <span className="ml-0.5 text-[10px] font-bold opacity-70">{w.score.toFixed(1)}/10</span>
                          </span>
                        ))}
                      </div>
                      <p className="text-[10px] muted mt-1">These areas should inform the cluster meeting agenda and training focus.</p>
                    </div>
                  )}
                  {s.ssaStatus === "SSA Not Done" && (
                    <div className="text-[11px] text-amber-700 inline-flex items-center gap-1">
                      <AlertTriangle size={10} /> No SSA on record — intervention priorities unknown.
                    </div>
                  )}
                </div>
              )}
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
        canManageClusters={canManageClusters}
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
