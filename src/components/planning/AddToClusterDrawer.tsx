"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Users, Plus, MapPin, AlertTriangle, CheckCircle2 } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { clustersForLocation } from "@/lib/cluster/cluster-core";
import { subCountiesOf } from "@/lib/geography";
import { cn } from "@/lib/utils";

// "Add to Cluster" drawer — sub-county aware, wired to the real cluster workflow.
//
//   • If the school's sub-county ALREADY has a cluster → lead with
//     "Add to Existing Cluster" (pick from that sub-county's clusters).
//   • If NOT → lead with "Create Cluster", prefilled with the school's
//     district + sub-county, and show "This sub-county does not have a
//     cluster yet." Creating the cluster also attaches the school.
//
// Cluster uniqueness is one active cluster per sub-county (enforced by the
// cluster engine on create).

export type AddToClusterOutcome =
  | { mode: "existing"; clusterId: string; clusterName: string; schoolId: string; schoolName: string }
  | { mode: "create";   clusterName: string; district: string; subCounty: string; schoolId: string; schoolName: string };

export type AddToClusterContext = {
  schoolId:   string;
  schoolName: string;
  district:   string;
  subCounty?: string;
  cceoName?:  string;
};

export function AddToClusterDrawer({
  open, context, onClose, onSubmit,
}: {
  open: boolean;
  context: AddToClusterContext | null;
  onClose: () => void;
  onSubmit: (outcome: AddToClusterOutcome) => void;
}) {
  // Clusters that actually COVER this school's sub-county (the spec's "cluster
  // for that area"). District clusters that don't cover the sub-county don't
  // count — and a school with no sub-county set must create/pick one. Read from
  // the live cluster store.
  const subCountyClusters = useMemo(() => {
    if (!context?.subCounty) return [];
    const sc = context.subCounty.trim().toLowerCase();
    return clustersForLocation(context.district, context.subCounty)
      .filter((c) => (c.subCounties ?? []).some((s) => s.toLowerCase() === sc));
  }, [context]);
  const hasExisting = subCountyClusters.length > 0;

  const [mode, setMode] = useState<"existing" | "create">("existing");
  const [clusterId, setClusterId] = useState<string>("");
  const [subCounty, setSubCounty] = useState<string>("");
  const [clusterName, setClusterName] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open && context) {
      // Default to whichever mode is correct for this sub-county.
      setMode(hasExisting ? "existing" : "create");
      setClusterId(subCountyClusters[0]?.id ?? "");
      setSubCounty(context.subCounty ?? "");
      setClusterName(context.subCounty ? `${context.subCounty} Cluster` : "");
      setError(null);
    }
  }, [open, context, hasExisting, subCountyClusters]);

  if (!context) return null;

  const subCountyLocked = !!context.subCounty;
  const subCountyOptions = subCountiesOf(context.district).map((s) => ({ value: s.name, label: s.name }));

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!context) return;

    if (mode === "existing") {
      const cluster = subCountyClusters.find((c) => c.id === clusterId);
      if (!cluster) { setError("Pick a cluster, or switch to Create Cluster."); return; }
      onSubmit({ mode: "existing", clusterId: cluster.id, clusterName: cluster.name, schoolId: context.schoolId, schoolName: context.schoolName });
      return;
    }

    // Create
    const name = clusterName.trim();
    const sc = (context.subCounty ?? subCounty).trim();
    if (name.length < 3) { setError("Give the cluster a name (≥ 3 characters)."); return; }
    if (!sc) { setError("Pick the sub-county the cluster covers."); return; }
    onSubmit({ mode: "create", clusterName: name, district: context.district, subCounty: sc, schoolId: context.schoolId, schoolName: context.schoolName });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Add ${context.schoolName} to a cluster`}
      description="Every school must belong to a cluster before full planning. Attach it to an existing cluster, or create one for its sub-county."
      size="md"
      variant="sheet"
      footer={
        <div className="flex items-center justify-end gap-2 w-full">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button
            size="sm"
            Icon={mode === "existing" ? Users : Plus}
            onClick={() => (document.getElementById("add-to-cluster-form") as HTMLFormElement | null)?.requestSubmit()}
          >
            {mode === "existing" ? "Add to Existing Cluster" : "Create Cluster"}
          </Button>
        </div>
      }
    >
      <form id="add-to-cluster-form" onSubmit={handleSubmit} className="space-y-4">
        {/* Mode toggle — only meaningful when the sub-county already has a cluster. */}
        {hasExisting && (
          <div role="tablist" aria-label="Cluster mode" className="grid grid-cols-2 gap-1.5 rounded-lg border border-[var(--color-edify-border)] p-1 bg-[var(--color-edify-soft)]/40">
            <ModeTab label="Existing cluster" sub={`${subCountyClusters.length} in ${context.subCounty ?? context.district}`} Icon={Users} active={mode === "existing"} onClick={() => setMode("existing")} />
            <ModeTab label="Create new" sub="District → sub-county → name" Icon={Plus} active={mode === "create"} onClick={() => setMode("create")} />
          </div>
        )}

        {mode === "existing" && hasExisting && (
          <section className="space-y-3">
            <Select
              label="Cluster"
              required
              value={clusterId}
              onChange={(e) => setClusterId(e.target.value)}
              options={subCountyClusters.map((c) => ({ value: c.id, label: `${c.name} · ${c.district}${c.subCounty ? ` · ${c.subCounty}` : ""}` }))}
              helper={`School joins this cluster's roster; existing meetings + SIT carry over to ${context.schoolName}.`}
            />
            {(() => {
              const c = subCountyClusters.find((x) => x.id === clusterId);
              if (!c) return null;
              return (
                <div className="rounded-lg border border-[var(--color-edify-border)] bg-white p-3 text-[12px]">
                  <div className="text-[10px] uppercase tracking-wider font-bold muted">You're adding to</div>
                  <div className="font-extrabold text-[13px] tracking-tight mt-0.5">{c.name}</div>
                  <div className="muted text-[11px] inline-flex items-center gap-1 mt-0.5">
                    <MapPin size={10} /> {c.district}{c.subCounty ? ` · ${c.subCounty}` : ""}
                  </div>
                  {c.managedByPartnerName && <div className="text-[11px] muted mt-1">Partner: <span className="font-semibold text-[var(--color-edify-text)]">{c.managedByPartnerName}</span></div>}
                </div>
              );
            })()}
          </section>
        )}

        {mode === "create" && (
          <section className="space-y-3">
            {!hasExisting && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-[12px] text-amber-800 flex items-start gap-2">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                <span><span className="font-extrabold">{context.subCounty ?? context.district}</span> does not have a cluster yet. Create one now — {context.schoolName} is attached as its first school.</span>
              </div>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Input label="District" value={context.district} disabled readOnly />
              {subCountyLocked ? (
                <Input label="Sub-county" value={context.subCounty} disabled readOnly />
              ) : (
                <Select label="Sub-county" required value={subCounty} onChange={(e) => setSubCounty(e.target.value)} options={subCountyOptions} placeholder="Pick a sub-county" disabled={subCountyOptions.length === 0} />
              )}
            </div>
            <Input label="Cluster name" required value={clusterName} onChange={(e) => setClusterName(e.target.value)} placeholder="e.g. Nakifuma Hill Cluster" helper="Geography-anchored name — one active cluster per sub-county." />
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5 flex items-start gap-2">
              <CheckCircle2 size={13} className="text-emerald-600 shrink-0 mt-0.5" />
              <p className="text-[11.5px] text-emerald-800 leading-snug">Creates the cluster and attaches <span className="font-extrabold">{context.schoolName}</span>, moving it out of the No Cluster list and unlocking SSA / planning.</p>
            </div>
          </section>
        )}

        {error && (
          <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700 inline-flex items-start gap-1.5">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {error}
          </div>
        )}
      </form>
    </Modal>
  );
}

function ModeTab({ label, sub, Icon, active, onClick }: { label: string; sub: string; Icon: typeof Users; active: boolean; onClick: () => void }) {
  return (
    <button type="button" role="tab" aria-selected={active} onClick={onClick}
      className={cn("rounded-md px-3 py-2 text-left transition-colors flex items-start gap-2",
        active ? "bg-white border border-[var(--color-edify-primary)] ring-1 ring-[var(--color-edify-primary)]/30 text-[var(--color-edify-text)]" : "border border-transparent text-[var(--color-edify-muted)] hover:bg-white/60")}>
      <Icon size={14} className={cn("mt-0.5 shrink-0", active ? "text-[var(--color-edify-primary)]" : "")} />
      <div className="min-w-0">
        <div className="text-[12px] font-extrabold tracking-tight leading-tight">{label}</div>
        <div className="text-caption opacity-80 leading-snug">{sub}</div>
      </div>
    </button>
  );
}
