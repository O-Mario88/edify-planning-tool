"use client";

// Cluster Assignment Workspace — the operational page that turns uploaded,
// unclustered schools into clustered, planning-ready ones.
//
// Left:  the Unclustered Schools queue with filters + checkboxes.
// Right: a selected-schools panel with two actions — Assign to an existing
//        cluster, or Create a new cluster and assign the selection to it.
//
// Cluster-first rule: a school stays planning-limited until it lands here and
// gets a cluster. Clustering never changes ownership — the account owner is
// shown but untouched.

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  Network, Building2, MapPin, User, Search, Plus, ArrowRight,
  CheckCircle2, AlertTriangle, X, Layers, Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  assignToExistingClusterAction,
  createClusterAndAssignAction,
} from "@/lib/actions/cluster-actions";

export type WorkspaceSchool = {
  schoolId: string;
  schoolName: string;
  region: string;
  district: string;
  subCounty?: string;
  schoolType: string;
  assignedCceo?: string;
  ssaStatus: "SSA Not Done" | "SSA Done";
  duplicate?: boolean;
  recommendation?: string;
};

export type WorkspaceCluster = {
  id: string;
  name: string;
  district: string;
  subCounty?: string;
  clusterType: string;
  schoolCount: number;
};

export function ClusterAssignmentWorkspace({
  schools,
  clusters,
}: {
  schools: WorkspaceSchool[];
  clusters: WorkspaceCluster[];
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  // Filters
  const [q, setQ] = useState("");
  const [district, setDistrict] = useState("");
  const [schoolType, setSchoolType] = useState("");
  const [owner, setOwner] = useState("");
  const [ssa, setSsa] = useState("");

  // Selection
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Right-panel mode + form
  const [mode, setMode] = useState<"existing" | "create">("existing");
  const [existingClusterId, setExistingClusterId] = useState("");
  const [newName, setNewName] = useState("");
  const [newSubCounty, setNewSubCounty] = useState("");
  const [newType, setNewType] = useState("Client");
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const districts = useMemo(
    () => [...new Set(schools.map((s) => s.district))].sort(),
    [schools],
  );
  const owners = useMemo(
    () => [...new Set(schools.map((s) => s.assignedCceo).filter(Boolean) as string[])].sort(),
    [schools],
  );

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return schools.filter((s) => {
      if (needle && !`${s.schoolName} ${s.schoolId} ${s.district} ${s.subCounty ?? ""}`.toLowerCase().includes(needle)) return false;
      if (district && s.district !== district) return false;
      if (schoolType && s.schoolType !== schoolType) return false;
      if (owner && s.assignedCceo !== owner) return false;
      if (ssa === "done" && s.ssaStatus !== "SSA Done") return false;
      if (ssa === "pending" && s.ssaStatus === "SSA Done") return false;
      return true;
    });
  }, [schools, q, district, schoolType, owner, ssa]);

  const selectedSchools = useMemo(
    () => schools.filter((s) => selected.has(s.schoolId)),
    [schools, selected],
  );

  // District uniformity of the selection — drives create-new eligibility and
  // which existing clusters are offered.
  const selectionDistricts = useMemo(
    () => [...new Set(selectedSchools.map((s) => s.district))],
    [selectedSchools],
  );
  const oneDistrict = selectionDistricts.length === 1 ? selectionDistricts[0] : null;
  const selectionSubCounties = useMemo(
    () => [...new Set(selectedSchools.map((s) => s.subCounty).filter(Boolean) as string[])],
    [selectedSchools],
  );

  // Existing clusters offered: same district as the (uniform) selection first.
  const offeredClusters = useMemo(() => {
    if (!oneDistrict) return clusters;
    return [...clusters].sort((a, b) => {
      const ad = a.district === oneDistrict ? 0 : 1;
      const bd = b.district === oneDistrict ? 0 : 1;
      return ad - bd;
    });
  }, [clusters, oneDistrict]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function selectAllVisible() {
    setSelected((prev) => {
      const next = new Set(prev);
      const allSelected = filtered.every((s) => next.has(s.schoolId));
      if (allSelected) filtered.forEach((s) => next.delete(s.schoolId));
      else filtered.forEach((s) => next.add(s.schoolId));
      return next;
    });
  }

  function flash(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(null), 4500);
  }

  function onAssignExisting() {
    setError(null);
    if (!existingClusterId) { setError("Pick a cluster to assign to."); return; }
    const ids = [...selected];
    startTransition(async () => {
      const res = await assignToExistingClusterAction(ids, existingClusterId);
      if (!res.ok) {
        setError(res.reason === "FORBIDDEN" ? "You don't have permission to assign clusters." : "Assignment failed.");
        return;
      }
      const cl = clusters.find((c) => c.id === existingClusterId);
      const failedNote = res.failed.length ? ` ${res.failed.length} skipped (different district).` : "";
      flash(`${res.assigned} school${res.assigned === 1 ? "" : "s"} assigned to ${cl?.name ?? "cluster"}.${failedNote}`);
      setSelected(new Set());
      setExistingClusterId("");
      router.refresh();
    });
  }

  function onCreateAndAssign() {
    setError(null);
    if (!newName.trim()) { setError("Cluster name is required."); return; }
    if (!oneDistrict) { setError("Selected schools belong to different districts. Create separate clusters."); return; }
    const ids = [...selected];
    const region = selectedSchools[0]?.region;
    const subCounty = newSubCounty || (selectionSubCounties.length === 1 ? selectionSubCounties[0] : "");
    if (!subCounty) { setError("Pick a sub-county (selection spans more than one)."); return; }
    startTransition(async () => {
      const res = await createClusterAndAssignAction(ids, {
        name: newName.trim(),
        region,
        district: oneDistrict,
        subCounty,
        clusterType: newType as "Client" | "Core" | "Mixed",
      });
      if (!res.ok) {
        if (res.reason === "INVALID_INPUT") setError(Object.values(res.errors)[0] ?? "Invalid cluster.");
        else if (res.reason === "FAILED") setError(res.message);
        else setError("You don't have permission to create clusters.");
        return;
      }
      flash(`Cluster ${res.clusterName} created in ${oneDistrict}. ${res.assigned} school${res.assigned === 1 ? "" : "s"} attached.`);
      setSelected(new Set());
      setNewName("");
      setNewSubCounty("");
      router.refresh();
    });
  }

  const allClustered = schools.length === 0;

  return (
    <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 space-y-4">
      {/* Header */}
      <header className="card rounded-2xl p-4 md:p-5">
        <div className="flex items-start gap-3">
          <span className="grid place-items-center h-10 w-10 rounded-xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
            <Network size={18} />
          </span>
          <div className="min-w-0">
            <h1 className="text-[18px] font-extrabold tracking-tight">Cluster Assignment Workspace</h1>
            <p className="text-[12.5px] muted mt-0.5 max-w-2xl">
              Every school must belong to a cluster. Clustering is the required setup step after upload — it unlocks
              SSA / SIT, cluster meetings, partner assignment, and reporting. Ownership stays with the account owner.
            </p>
          </div>
          <span className={cn(
            "ml-auto shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[12px] font-extrabold",
            allClustered ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700",
          )}>
            {allClustered ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
            {schools.length} unclustered
          </span>
        </div>
      </header>

      {allClustered ? (
        <div className="card rounded-2xl p-10 text-center">
          <CheckCircle2 size={28} className="mx-auto text-emerald-600" />
          <h2 className="text-[15px] font-extrabold mt-3">Every school is clustered</h2>
          <p className="text-[12.5px] muted mt-1">No unclustered schools in your scope. New uploads will appear here for assignment.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-4 items-start">
          {/* ── Left: unclustered queue ── */}
          <section className="card rounded-2xl overflow-hidden">
            {/* Filters */}
            <div className="p-3 border-b border-[var(--color-edify-divider)] space-y-2.5">
              <div className="relative">
                <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)]" />
                <input
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="Search school, id, district…"
                  className="w-full h-9 pl-8 pr-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12.5px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <FilterSelect value={district} onChange={setDistrict} label="District" options={districts} />
                <FilterSelect value={schoolType} onChange={setSchoolType} label="Type" options={["Client", "Core", "Potential Core", "Other"]} />
                <FilterSelect value={owner} onChange={setOwner} label="Account owner" options={owners} />
                <FilterSelect value={ssa} onChange={setSsa} label="SSA" options={[["pending", "SSA pending"], ["done", "SSA done"]]} />
              </div>
            </div>

            {/* Select-all bar */}
            <div className="flex items-center justify-between px-3.5 py-2 border-b border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/30">
              <label className="inline-flex items-center gap-2 text-[11.5px] font-semibold cursor-pointer">
                <input
                  type="checkbox"
                  checked={filtered.length > 0 && filtered.every((s) => selected.has(s.schoolId))}
                  onChange={selectAllVisible}
                  className="h-3.5 w-3.5 accent-[var(--color-edify-primary)]"
                />
                Select all ({filtered.length})
              </label>
              <span className="text-[11px] muted">{selected.size} selected</span>
            </div>

            {/* Rows */}
            <ul className="divide-y divide-[var(--color-edify-divider)] max-h-[60vh] overflow-y-auto">
              {filtered.length === 0 ? (
                <li className="px-4 py-8 text-center text-[12px] muted">No schools match these filters.</li>
              ) : (
                filtered.map((s) => {
                  const isSel = selected.has(s.schoolId);
                  return (
                    <li key={s.schoolId}>
                      <label className={cn(
                        "flex items-start gap-3 px-3.5 py-3 cursor-pointer transition-colors",
                        isSel ? "bg-[var(--color-edify-primary)]/5" : "hover:bg-[var(--color-edify-soft)]/40",
                      )}>
                        <input
                          type="checkbox"
                          checked={isSel}
                          onChange={() => toggle(s.schoolId)}
                          className="mt-0.5 h-3.5 w-3.5 accent-[var(--color-edify-primary)] shrink-0"
                        />
                        <span className="grid place-items-center h-8 w-8 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                          <Building2 size={13} />
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[12.5px] font-extrabold tracking-tight truncate">{s.schoolName}</span>
                            <TypeChip type={s.schoolType} />
                            {s.duplicate && (
                              <span className="inline-flex items-center gap-1 px-1.5 py-[1px] rounded text-[10px] font-bold bg-amber-50 text-amber-700">
                                <AlertTriangle size={9} /> Duplicate review
                              </span>
                            )}
                            <span className={cn(
                              "inline-flex items-center px-1.5 py-[1px] rounded text-[10px] font-bold",
                              s.ssaStatus === "SSA Done" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500",
                            )}>
                              {s.ssaStatus === "SSA Done" ? "SSA done" : "SSA pending"}
                            </span>
                          </div>
                          <p className="text-[11px] muted leading-tight inline-flex items-center gap-1 mt-0.5">
                            <MapPin size={9} className="text-[var(--color-edify-primary)]" />
                            {s.district}{s.subCounty ? ` · ${s.subCounty}` : ""}
                            <span className="opacity-50">·</span>
                            <User size={9} /> {s.assignedCceo ?? "Unassigned"}
                          </p>
                          {s.recommendation && (
                            <p className="text-[10.5px] text-[var(--color-edify-primary)] font-semibold leading-tight inline-flex items-center gap-1 mt-1">
                              <Sparkles size={9} /> {s.recommendation}
                            </p>
                          )}
                        </div>
                      </label>
                    </li>
                  );
                })
              )}
            </ul>
          </section>

          {/* ── Right: selected + actions ── */}
          <aside className="card rounded-2xl p-3.5 lg:sticky lg:top-4 space-y-3">
            <div className="flex items-center gap-2">
              <Layers size={15} className="text-[var(--color-edify-primary)]" />
              <h2 className="text-[13px] font-extrabold tracking-tight">Selected schools</h2>
              <span className="ml-auto text-[12px] font-extrabold tabular">{selected.size}</span>
            </div>

            {selected.size === 0 ? (
              <p className="text-[11.5px] muted py-3">
                Tick schools on the left to assign them to a cluster — singly or in bulk.
              </p>
            ) : (
              <>
                {/* Selection summary */}
                <div className="rounded-lg border border-[var(--color-edify-divider)] p-2.5 text-[11px] space-y-1">
                  <SummaryRow label="Schools" value={String(selected.size)} />
                  <SummaryRow label="District" value={oneDistrict ?? `${selectionDistricts.length} districts ⚠`} warn={!oneDistrict} />
                  {oneDistrict && (
                    <SummaryRow label="Sub-county" value={selectionSubCounties.length === 1 ? selectionSubCounties[0] : `${selectionSubCounties.length || 0} sub-counties`} />
                  )}
                  <SummaryRow label="SSA pending" value={String(selectedSchools.filter((s) => s.ssaStatus !== "SSA Done").length)} />
                </div>

                {/* Mode toggle */}
                <div className="grid grid-cols-2 gap-1 p-1 rounded-lg bg-[var(--color-edify-soft)]/50">
                  <ModeTab active={mode === "existing"} onClick={() => { setMode("existing"); setError(null); }}>Existing</ModeTab>
                  <ModeTab active={mode === "create"} onClick={() => { setMode("create"); setError(null); }}>Create new</ModeTab>
                </div>

                {mode === "existing" ? (
                  <div className="space-y-2">
                    <label className="block text-[10.5px] uppercase tracking-wide font-bold muted">Assign to cluster</label>
                    <select
                      value={existingClusterId}
                      onChange={(e) => setExistingClusterId(e.target.value)}
                      className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px]"
                    >
                      <option value="">Select a cluster…</option>
                      {offeredClusters.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name} · {c.district}{c.subCounty ? ` / ${c.subCounty}` : ""} · {c.schoolCount} schools
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={onAssignExisting}
                      disabled={pending || !existingClusterId}
                      className={primaryBtn(pending || !existingClusterId)}
                    >
                      Assign {selected.size} to cluster <ArrowRight size={13} />
                    </button>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {!oneDistrict ? (
                      <div className="rounded-lg bg-amber-50 text-amber-800 text-[11px] p-2.5 flex items-start gap-1.5">
                        <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                        Selected schools belong to different districts. A cluster is single-district — create separate clusters.
                      </div>
                    ) : (
                      <>
                        <Field label="Cluster name">
                          <input
                            value={newName}
                            onChange={(e) => setNewName(e.target.value)}
                            placeholder={`e.g. ${oneDistrict} Central Cluster`}
                            className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px]"
                          />
                        </Field>
                        <Field label="District (from selection)">
                          <input value={oneDistrict} readOnly className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 text-[12px] text-[var(--color-edify-muted)]" />
                        </Field>
                        <Field label="Sub-county">
                          {selectionSubCounties.length === 1 ? (
                            <input value={selectionSubCounties[0]} readOnly className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 text-[12px] text-[var(--color-edify-muted)]" />
                          ) : (
                            <select value={newSubCounty} onChange={(e) => setNewSubCounty(e.target.value)} className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px]">
                              <option value="">Select sub-county…</option>
                              {selectionSubCounties.map((sc) => <option key={sc} value={sc}>{sc}</option>)}
                            </select>
                          )}
                        </Field>
                        <Field label="Cluster type">
                          <select value={newType} onChange={(e) => setNewType(e.target.value)} className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px]">
                            <option>Client</option>
                            <option>Core</option>
                            <option>Mixed</option>
                          </select>
                        </Field>
                        <button
                          type="button"
                          onClick={onCreateAndAssign}
                          disabled={pending}
                          className={primaryBtn(pending)}
                        >
                          <Plus size={13} /> Create &amp; assign {selected.size}
                        </button>
                      </>
                    )}
                  </div>
                )}

                {error && (
                  <div className="rounded-lg bg-rose-50 text-rose-700 text-[11px] p-2.5 flex items-start gap-1.5">
                    <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {error}
                  </div>
                )}
              </>
            )}
          </aside>
        </div>
      )}

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-[12px] font-semibold px-4 py-3 max-w-[420px] flex items-start gap-2">
          <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
          <span>{toast}</span>
          <button onClick={() => setToast(null)} className="ml-1 opacity-80 hover:opacity-100"><X size={13} /></button>
        </div>
      )}
    </div>
  );
}

// ── small primitives ──

function primaryBtn(disabled?: boolean) {
  return cn(
    "w-full inline-flex items-center justify-center gap-1.5 h-10 px-3 rounded-lg text-[12px] font-extrabold transition-colors",
    disabled
      ? "bg-slate-100 text-slate-400 cursor-not-allowed"
      : "bg-[var(--color-edify-primary)] text-white hover:bg-[var(--color-edify-dark)]",
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
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        "h-8 px-2 rounded-lg border text-[11.5px] bg-white",
        value ? "border-[var(--color-edify-primary)] text-[var(--color-edify-primary)] font-semibold" : "border-[var(--color-edify-border)] text-[var(--color-edify-text)]",
      )}
    >
      <option value="">{label}</option>
      {options.map((o) => {
        const [val, lbl] = Array.isArray(o) ? o : [o, o];
        return <option key={val} value={val}>{lbl}</option>;
      })}
    </select>
  );
}

function TypeChip({ type }: { type: string }) {
  const core = type === "Core";
  return (
    <span className={cn(
      "inline-flex items-center px-1.5 py-[1px] rounded text-[10px] font-bold",
      core ? "bg-violet-50 text-violet-700" : "bg-blue-50 text-blue-700",
    )}>
      {type}
    </span>
  );
}

function SummaryRow({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="muted">{label}</span>
      <span className={cn("font-extrabold tabular", warn && "text-amber-600")}>{value}</span>
    </div>
  );
}

function ModeTab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "h-8 rounded-md text-[11.5px] font-bold transition-colors",
        active ? "bg-white shadow-sm text-[var(--color-edify-text)]" : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]",
      )}
    >
      {children}
    </button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="block text-[10.5px] uppercase tracking-wide font-bold muted">{label}</label>
      {children}
    </div>
  );
}
