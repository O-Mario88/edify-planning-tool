"use client";

// "Add to Cluster" drawer launched from the Schools Directory. Shows the
// school's details + geography-matched clusters (same sub-county first, then
// district), lets the user attach to one or create a new cluster and attach in
// one step. Region-fallback clusters (different district) are shown but not
// selectable without an override (the engine blocks cross-district by design).

import { useMemo, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Network, MapPin, User, AlertTriangle, Plus, Users, Building2, CheckCircle2 } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { assignSchoolAction, createClusterAndAssignAction } from "@/lib/actions/cluster-actions";

export type DirectoryClusterMatch = {
  id: string;
  name: string;
  district: string;
  subCounties: string[];
  schoolCount: number;
  ssaRate: number;
  tier: "strong" | "district" | "region";
  leaderName?: string;
};

export type DirectorySchoolVM = {
  schoolId: string;
  schoolName: string;
  schoolType: string;
  region: string;
  district: string;
  subCounty?: string;
  parish?: string;
  assignedCceo?: string;
  ssaStatus: "SSA Not Done" | "SSA Done";
  duplicate?: boolean;
  clusterStatus: "unclustered" | "clustered" | "needs_review";
  clusterId?: string;
  clusterName?: string;
  matches: { strong: DirectoryClusterMatch[]; district: DirectoryClusterMatch[]; region: DirectoryClusterMatch[] };
};

export function DirectoryClusterDrawer({
  open, school, onClose,
}: {
  open: boolean;
  school: DirectorySchoolVM | null;
  onClose: (assigned?: boolean) => void;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<"existing" | "create">("existing");
  const [selected, setSelected] = useState<string>("");
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectable = useMemo(
    () => (school ? [...school.matches.strong, ...school.matches.district] : []),
    [school],
  );

  if (!school) return null;

  function flashError(msg: string) { setError(msg); }

  async function assignExisting() {
    setError(null);
    if (!selected) { flashError("Pick a cluster."); return; }
    setBusy(true);
    const res = await assignSchoolAction(school!.schoolId, selected);
    setBusy(false);
    if (!res.ok) {
      flashError(res.reason === "FORBIDDEN" ? "You don't have permission." : res.reason === "FAILED" ? res.message : "Failed.");
      return;
    }
    router.refresh();
    onClose(true);
  }

  async function createAndAssign(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!newName.trim()) { flashError("Give the cluster a name."); return; }
    setBusy(true);
    const res = await createClusterAndAssignAction([school!.schoolId], {
      name: newName.trim(),
      region: school!.region,
      district: school!.district,
      subCounties: school!.subCounty ? [school!.subCounty] : [],
    });
    setBusy(false);
    if (!res.ok) {
      flashError(res.reason === "INVALID_INPUT" ? (Object.values(res.errors)[0] ?? "Invalid.") : res.reason === "FAILED" ? res.message : "Failed.");
      return;
    }
    router.refresh();
    onClose(true);
  }

  const hasSelectable = selectable.length > 0;

  return (
    <Modal
      open={open}
      onClose={() => onClose(false)}
      title={`Add ${school.schoolName} to a cluster`}
      description="Attach this school to a cluster in its district / sub-county, or create a new one. Ownership stays with the account owner."
      size="md"
      variant="sheet"
    >
      <div className="space-y-4">
        {/* School summary */}
        <div className="rounded-lg border border-[var(--color-edify-border)] p-3 text-[11.5px] space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-extrabold text-[12.5px]">{school.schoolName}</span>
            <span className="muted">#{school.schoolId}</span>
            <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold", school.schoolType === "Core" ? "bg-violet-50 text-violet-700" : "bg-blue-50 text-blue-700")}>{school.schoolType}</span>
            {school.duplicate && <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-amber-50 text-amber-700 inline-flex items-center gap-1"><AlertTriangle size={9} />Duplicate review</span>}
            <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold", school.ssaStatus === "SSA Done" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500")}>{school.ssaStatus === "SSA Done" ? "SSA done" : "SSA pending"}</span>
          </div>
          <div className="muted inline-flex items-center gap-1"><MapPin size={10} className="text-[var(--color-edify-primary)]" />{school.district}{school.subCounty ? ` · ${school.subCounty}` : ""}{school.parish ? ` · ${school.parish}` : ""}</div>
          <div className="muted inline-flex items-center gap-1"><User size={10} />{school.assignedCceo ?? "Unassigned"}</div>
        </div>

        {/* Mode toggle */}
        <div className="grid grid-cols-2 gap-1 p-1 rounded-lg bg-[var(--color-edify-soft)]/50">
          <ModeTab active={mode === "existing"} onClick={() => { setMode("existing"); setError(null); }}>Existing cluster</ModeTab>
          <ModeTab active={mode === "create"} onClick={() => { setMode("create"); setError(null); if (!newName) setNewName(`${school.subCounty ?? school.district} Cluster`); }}>Create new</ModeTab>
        </div>

        {mode === "existing" ? (
          <div className="space-y-2">
            {!hasSelectable ? (
              <div className="rounded-lg bg-amber-50 text-amber-800 text-[11.5px] p-2.5 flex items-start gap-1.5">
                <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                No clusters found in {school.district}{school.subCounty ? ` / ${school.subCounty}` : ""}. Switch to <b>Create new</b> to start one.
              </div>
            ) : (
              <ul className="space-y-1.5 max-h-[40vh] overflow-y-auto">
                {selectable.map((m) => (
                  <li key={m.id}>
                    <label className={cn("flex items-start gap-2.5 rounded-lg border p-2.5 cursor-pointer transition-colors",
                      selected === m.id ? "border-[var(--color-edify-primary)] bg-[var(--color-edify-primary)]/5" : "border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40")}>
                      <input type="radio" name="cluster" checked={selected === m.id} onChange={() => setSelected(m.id)} className="mt-0.5 accent-[var(--color-edify-primary)]" />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2 flex-wrap">
                          <span className="text-[12px] font-extrabold tracking-tight">{m.name}</span>
                          {m.tier === "strong" && <span className="px-1.5 py-[1px] rounded text-[9.5px] font-bold bg-emerald-50 text-emerald-700">Same sub-county</span>}
                        </span>
                        <span className="text-[11px] muted inline-flex items-center gap-1 mt-0.5">
                          <Building2 size={9} />{m.district}{m.subCounties?.length ? ` · ${m.subCounties.join(", ")}` : ""}
                          <span className="opacity-50">·</span>
                          <Users size={9} />{m.schoolCount} schools
                          {m.schoolCount > 0 ? <><span className="opacity-50">·</span>SSA {m.ssaRate}%</> : null}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}

            {/* Region fallback — informational, blocked without override */}
            {school.matches.region.length > 0 && (
              <p className="text-[10.5px] muted">
                {school.matches.region.length} cluster(s) elsewhere in {school.region} — not shown (different district; would need an override).
              </p>
            )}

            {hasSelectable && (
              <Button size="sm" Icon={Network} disabled={busy || !selected} onClick={assignExisting}>
                {busy ? "Adding…" : "Add to selected cluster"}
              </Button>
            )}
          </div>
        ) : (
          <form onSubmit={createAndAssign} className="space-y-3">
            <Input label="Cluster name" required value={newName} onChange={(e) => setNewName(e.target.value)} placeholder={`e.g. ${school.subCounty ?? school.district} Cluster`} />
            <div className="grid grid-cols-2 gap-3">
              <Input label="District" value={school.district} readOnly />
              <Input label="Sub-county" value={school.subCounty ?? "—"} readOnly />
            </div>
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11.5px] text-emerald-800 inline-flex items-start gap-1.5">
              <CheckCircle2 size={12} className="mt-0.5 shrink-0" />
              Creates the cluster in {school.district} and adds {school.schoolName} as its first school.
            </div>
            <Button size="sm" Icon={Plus} disabled={busy} onClick={() => { const f = document.activeElement as HTMLElement; f?.blur(); }} type="submit">
              {busy ? "Creating…" : "Create cluster & add school"}
            </Button>
          </form>
        )}

        {error && (
          <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700 inline-flex items-start gap-1.5">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />{error}
          </div>
        )}
      </div>
    </Modal>
  );
}

function ModeTab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick}
      className={cn("h-8 rounded-md text-[11.5px] font-bold transition-colors", active ? "bg-white shadow-sm text-[var(--color-edify-text)]" : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]")}>
      {children}
    </button>
  );
}
