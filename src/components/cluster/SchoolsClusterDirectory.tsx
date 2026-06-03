"use client";

// Cluster-aware Schools Directory (on the uploaded/intake schools — the cluster
// workflow universe). Every unclustered school shows "Add to Cluster"; clustered
// schools show their cluster + a link. Cluster-status + geography filters make
// the directory an action surface, not a passive list.

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  Building2, MapPin, User, Search, Network, ArrowRight, CheckCircle2, AlertTriangle, Eye,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DirectoryClusterDrawer, type DirectorySchoolVM } from "./DirectoryClusterDrawer";

type StatusFilter = "all" | "unclustered" | "clustered" | "needs_review";

const STATUS_META: Record<DirectorySchoolVM["clusterStatus"], { label: string; cls: string }> = {
  clustered:    { label: "Clustered",     cls: "bg-emerald-50 text-emerald-700" },
  unclustered:  { label: "Unclustered",   cls: "bg-rose-50 text-rose-700" },
  needs_review: { label: "Needs review",  cls: "bg-amber-50 text-amber-700" },
};

export function SchoolsClusterDirectory({
  schools,
  canManage,
}: {
  schools: DirectorySchoolVM[];
  canManage: boolean;
}) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [district, setDistrict] = useState("");
  const [subCounty, setSubCounty] = useState("");
  const [owner, setOwner] = useState("");
  const [type, setType] = useState("");
  const [ssa, setSsa] = useState("");
  const [cluster, setCluster] = useState("");
  const [drawerSchool, setDrawerSchool] = useState<DirectorySchoolVM | null>(null);
  const [toast, setToast] = useState<string | null>(null);

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
      if (status !== "all" && s.clusterStatus !== status) return false;
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

  function onDrawerClose(assigned?: boolean) {
    if (assigned && drawerSchool) {
      setToast(`${drawerSchool.schoolName} added to a cluster. It's now in cluster planning.`);
      setTimeout(() => setToast(null), 4500);
    }
    setDrawerSchool(null);
  }

  return (
    <section className="card rounded-2xl overflow-hidden">
      <header className="px-4 pt-3.5 pb-2 flex items-start gap-3 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <Network size={15} className="text-[var(--color-edify-primary)]" /> Cluster setup
          </h2>
          <p className="text-[12px] muted mt-0.5">
            Every school belongs to a cluster. Assign unclustered schools here — clustering unlocks SSA / SIT and planning.
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
          <FilterSelect value={status} onChange={(v) => setStatus(v as StatusFilter)} label="Cluster status"
            options={[["all", "All statuses"], ["unclustered", "Unclustered"], ["clustered", "Clustered"], ["needs_review", "Needs review"]]} />
          <FilterSelect value={district} onChange={setDistrict} label="District" options={districts} />
          <FilterSelect value={subCounty} onChange={setSubCounty} label="Sub-county" options={subCounties} />
          <FilterSelect value={owner} onChange={setOwner} label="Account owner" options={owners} />
          <FilterSelect value={type} onChange={setType} label="Type" options={["Client", "Core", "Potential Core", "Other"]} />
          <FilterSelect value={ssa} onChange={setSsa} label="SSA" options={[["pending", "SSA pending"], ["done", "SSA done"]]} />
          {clusterNames.length > 0 && <FilterSelect value={cluster} onChange={setCluster} label="Cluster" options={clusterNames} />}
        </div>
      </div>

      {/* Rows */}
      <ul className="divide-y divide-[var(--color-edify-divider)] max-h-[60vh] overflow-y-auto">
        {filtered.length === 0 ? (
          <li className="px-4 py-8 text-center text-[12px] muted">No schools match these filters.</li>
        ) : filtered.map((s) => {
          const meta = STATUS_META[s.clusterStatus];
          const showAdd = canManage && s.clusterStatus !== "clustered";
          return (
            <li key={s.schoolId} className="px-3.5 py-3 flex items-start gap-3">
              <span className="grid place-items-center h-8 w-8 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                <Building2 size={13} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[12.5px] font-extrabold tracking-tight truncate">{s.schoolName}</span>
                  <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold", s.schoolType === "Core" ? "bg-violet-50 text-violet-700" : "bg-blue-50 text-blue-700")}>{s.schoolType}</span>
                  <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold", meta.cls)}>{meta.label}</span>
                  {s.duplicate && <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-amber-50 text-amber-700 inline-flex items-center gap-1"><AlertTriangle size={9} />Dup</span>}
                  <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold", s.ssaStatus === "SSA Done" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500")}>{s.ssaStatus === "SSA Done" ? "SSA done" : "SSA pending"}</span>
                </div>
                <p className="text-[11px] muted leading-tight inline-flex items-center gap-1 mt-0.5">
                  <MapPin size={9} className="text-[var(--color-edify-primary)]" />{s.district}{s.subCounty ? ` · ${s.subCounty}` : ""}
                  <span className="opacity-50">·</span><User size={9} />{s.assignedCceo ?? "Unassigned"}
                </p>
                {s.clusterStatus === "clustered" && s.clusterName && (
                  <p className="text-[11px] mt-0.5 inline-flex items-center gap-1 text-[var(--color-edify-primary)] font-semibold">
                    <Network size={9} /> {s.clusterName}
                    <Link href="/clusters" className="ml-1 muted hover:underline inline-flex items-center gap-0.5"><Eye size={9} /> View</Link>
                  </p>
                )}
              </div>
              {showAdd ? (
                <button
                  type="button"
                  onClick={() => setDrawerSchool(s)}
                  className="shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[11.5px] font-extrabold hover:bg-[var(--color-edify-dark)] transition-colors"
                >
                  Add to Cluster <ArrowRight size={12} />
                </button>
              ) : s.clusterStatus === "clustered" ? (
                <span className="shrink-0 inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700"><CheckCircle2 size={12} /> Clustered</span>
              ) : null}
            </li>
          );
        })}
      </ul>

      <DirectoryClusterDrawer open={!!drawerSchool} school={drawerSchool} onClose={onDrawerClose} />

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
