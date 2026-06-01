"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Users, Plus, MapPin, AlertTriangle, CheckCircle2 } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { clusterGaps, type ClusterGap } from "@/lib/planning/planning-gaps-mock";
import { subCountiesOf, SUBCOUNTIES } from "@/lib/geography";
import { cn } from "@/lib/utils";

// Dedicated drawer for the "Add to Cluster" action.
//
// Two modes, one drawer, one submit:
//   • Existing — pick from a dropdown of clusters this CCEO already
//     owns. The school is attached on save and removed from the
//     "No Cluster" gap bucket.
//   • Create new — define a brand-new peer cluster (District →
//     Sub-county → Cluster name). The cluster is saved AND the school
//     is auto-attached, so the CCEO doesn't have to do it twice.
//
// Same Modal chrome as the reschedule / assign drawers. Focus trap,
// ESC, scroll lock, portal — inherited from the primitive.

export type AddToClusterOutcome =
  | { mode: "existing"; clusterId: string; clusterName: string; schoolId: string; schoolName: string }
  | { mode: "create";   clusterName: string; district: string; subCounty: string; schoolId: string; schoolName: string };

export type AddToClusterContext = {
  schoolId:    string;
  schoolName:  string;
  /** Optional CCEO scope filter — when set, only clusters this CCEO owns
   *  show up in the Existing dropdown. */
  cceoName?:   string;
};

// District + sub-county options come from the single geography source of
// truth (@/lib/geography) — no hard-coded district lists here. The district
// dropdown lists the districts that have a sub-county catalogue; the
// sub-county dropdown filters by the selected district.
const DISTRICT_OPTIONS = Array.from(new Set(SUBCOUNTIES.map((s) => s.districtName)))
  .sort()
  .map((d) => ({ value: d, label: d }));

export function AddToClusterDrawer({
  open, context, onClose, onSubmit,
}: {
  open: boolean;
  context: AddToClusterContext | null;
  onClose: () => void;
  onSubmit: (outcome: AddToClusterOutcome) => void;
}) {
  const [mode, setMode] = useState<"existing" | "create">("existing");

  // Existing-cluster path.
  const [clusterId, setClusterId] = useState<string>("");

  // Create-new path.
  const [district, setDistrict]       = useState<string>(DISTRICT_OPTIONS[0]?.value ?? "");
  const [subCounty, setSubCounty]     = useState<string>("");
  const [clusterName, setClusterName] = useState<string>("");

  const [error, setError] = useState<string | null>(null);

  // Only show clusters this CCEO already runs. Default scope = the
  // demo CCEO. Production filters by current user.
  const eligibleClusters = useMemo<ClusterGap[]>(() => {
    if (!context?.cceoName) return clusterGaps;
    return clusterGaps.filter((c) => c.assignedCceo === context.cceoName);
  }, [context?.cceoName]);

  // Re-seed state on open.
  useEffect(() => {
    if (open) {
      setMode("existing");
      setClusterId(eligibleClusters[0]?.id ?? "");
      setDistrict(DISTRICT_OPTIONS[0]?.value ?? "");
      setSubCounty("");
      setClusterName("");
      setError(null);
    }
  }, [open, eligibleClusters]);

  // Sub-counties depend on district — sourced from the geography service.
  const subCountyOptions = subCountiesOf(district).map((s) => ({ value: s.name, label: s.name }));

  if (!context) return null;

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!context) return;

    if (mode === "existing") {
      const cluster = eligibleClusters.find((c) => c.id === clusterId);
      if (!cluster) {
        setError("Pick a cluster from the list, or switch to Create new.");
        return;
      }
      onSubmit({
        mode:        "existing",
        clusterId:   cluster.id,
        clusterName: cluster.clusterName,
        schoolId:    context.schoolId,
        schoolName:  context.schoolName,
      });
      return;
    }

    // Create-new
    const trimmedName = clusterName.trim();
    if (!trimmedName) {
      setError("Give the new cluster a name (e.g. ‘Kayunga North Cluster’).");
      return;
    }
    if (trimmedName.length < 3) {
      setError("Cluster name must be at least 3 characters.");
      return;
    }
    if (!district)  { setError("Pick the district the cluster sits in.");   return; }
    if (!subCounty) { setError("Pick the sub-county where the cluster meets."); return; }

    // Uniqueness — no two clusters may share the same name within the
    // same district/sub-county. Case-insensitive whitespace-normalised
    // compare so "Bukoto Hub" / "bukoto hub " / "BUKOTO HUB" collide.
    // Cross-district duplicates are allowed (the same name in a
    // different geography is a different cluster operationally).
    const normalise = (s: string) => s.toLowerCase().replace(/\s+/g, " ").trim();
    const target = normalise(trimmedName);
    const duplicate = clusterGaps.find(
      (c) => c.district === district && normalise(c.clusterName) === target,
    );
    if (duplicate) {
      setError(
        `A cluster called "${duplicate.clusterName}" already exists in ${district}. Pick a different name, or switch to Add to Existing Cluster to attach the school there.`,
      );
      return;
    }

    onSubmit({
      mode:        "create",
      clusterName: trimmedName,
      district,
      subCounty,
      schoolId:    context.schoolId,
      schoolName:  context.schoolName,
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Add ${context.schoolName} to a cluster`}
      description="Pick an existing cluster or create a new one. The school is attached to the chosen cluster on save."
      size="md"
      variant="sheet"
      footer={
        <div className="flex items-center justify-end gap-2 w-full">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button
            size="sm"
            Icon={mode === "existing" ? Users : Plus}
            onClick={() => {
              const form = document.getElementById("add-to-cluster-form") as HTMLFormElement | null;
              form?.requestSubmit();
            }}
          >
            {mode === "existing" ? "Add to Cluster" : "Create Cluster + Add School"}
          </Button>
        </div>
      }
    >
      <form id="add-to-cluster-form" onSubmit={handleSubmit} className="space-y-4">

        {/* Mode toggle */}
        <div role="tablist" aria-label="Cluster mode" className="grid grid-cols-2 gap-1.5 rounded-lg border border-[var(--color-edify-border)] p-1 bg-[var(--color-edify-soft)]/40">
          <ModeTab
            label="Existing cluster"
            sub={`${eligibleClusters.length} on your books`}
            Icon={Users}
            active={mode === "existing"}
            onClick={() => setMode("existing")}
          />
          <ModeTab
            label="Create new"
            sub="District → sub-county → name"
            Icon={Plus}
            active={mode === "create"}
            onClick={() => setMode("create")}
          />
        </div>

        {/* Existing path */}
        {mode === "existing" && (
          <section className="space-y-3">
            {eligibleClusters.length === 0 ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-[12px] text-amber-800 flex items-start gap-2">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                <span>No clusters yet on your books. Switch to <span className="font-extrabold">Create new</span> to define one.</span>
              </div>
            ) : (
              <Select
                label="Cluster"
                required
                value={clusterId}
                onChange={(e) => setClusterId(e.target.value)}
                options={eligibleClusters.map((c) => ({
                  value: c.id,
                  label: `${c.clusterName} · ${c.district} · ${c.schoolsCount} schools`,
                }))}
                helper={`School joins the cluster's roster. Existing meetings + SIT carry over to ${context.schoolName}.`}
              />
            )}

            {/* Quick context for the chosen cluster — keeps the user oriented */}
            {(() => {
              const c = eligibleClusters.find((x) => x.id === clusterId);
              if (!c) return null;
              return (
                <div className="rounded-lg border border-[var(--color-edify-border)] bg-white p-3 text-[12px]">
                  <div className="text-[10px] uppercase tracking-wider font-bold muted">You're adding to</div>
                  <div className="font-extrabold text-[13px] tracking-tight mt-0.5">{c.clusterName}</div>
                  <div className="muted text-[11px] inline-flex items-center gap-1 mt-0.5">
                    <MapPin size={10} /> {c.district}
                    <span className="opacity-50">·</span>
                    {c.schoolsCount} schools · {c.schoolsWithSsa} with SSA
                  </div>
                  {c.partnerFacilitator && (
                    <div className="text-[11px] muted mt-1">Partner facilitator: <span className="font-semibold text-[var(--color-edify-text)]">{c.partnerFacilitator}</span></div>
                  )}
                </div>
              );
            })()}
          </section>
        )}

        {/* Create-new path */}
        {mode === "create" && (
          <section className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Select
                label="District"
                required
                value={district}
                onChange={(e) => { setDistrict(e.target.value); setSubCounty(""); }}
                options={DISTRICT_OPTIONS}
              />
              <Select
                label="Sub-county"
                required
                value={subCounty}
                onChange={(e) => setSubCounty(e.target.value)}
                options={subCountyOptions}
                placeholder="Pick a sub-county"
                helper={subCountyOptions.length === 0 ? "Pick a district first." : undefined}
                disabled={subCountyOptions.length === 0}
              />
            </div>
            <Input
              label="Cluster name"
              required
              value={clusterName}
              onChange={(e) => setClusterName(e.target.value)}
              placeholder="e.g. Kayunga North Cluster"
              helper="Use a short, geography-anchored name. CCEOs and partners will see this on every cluster surface."
            />

            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5 flex items-start gap-2">
              <CheckCircle2 size={13} className="text-emerald-600 shrink-0 mt-0.5" />
              <p className="text-[11.5px] text-emerald-800 leading-snug">
                Saves the new cluster and attaches <span className="font-extrabold">{context.schoolName}</span> as the first school. You can add more schools later from the Cluster gaps card.
              </p>
            </div>
          </section>
        )}

        {error && (
          <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700 inline-flex items-start gap-1.5">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            {error}
          </div>
        )}
      </form>
    </Modal>
  );
}

function ModeTab({
  label, sub, Icon, active, onClick,
}: {
  label: string;
  sub:   string;
  Icon:  typeof Users;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "rounded-md px-3 py-2 text-left transition-colors flex items-start gap-2",
        active
          ? "bg-white border border-[var(--color-edify-primary)] ring-1 ring-[var(--color-edify-primary)]/30 text-[var(--color-edify-text)]"
          : "border border-transparent text-[var(--color-edify-muted)] hover:bg-white/60",
      )}
    >
      <Icon size={14} className={cn("mt-0.5 shrink-0", active ? "text-[var(--color-edify-primary)]" : "")} />
      <div className="min-w-0">
        <div className="text-[12px] font-extrabold tracking-tight leading-tight">{label}</div>
        <div className="text-caption opacity-80 leading-snug">{sub}</div>
      </div>
    </button>
  );
}
