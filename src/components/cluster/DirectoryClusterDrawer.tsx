"use client";

// Unified school-actions drawer launched from the School Directory / Portfolio.
// One place to run every assignment a school needs, with ownership unchanged:
//   • Cluster        — attach to a geography-matched cluster or create a new one
//   • Special project — tag the school into one or more special projects
//   • Partner         — delegate delivery to a partner (execution only)
//
// The drawer is the single assignment surface — there is no separate workspace.

import { useMemo, useState, useTransition, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  Network, MapPin, User, AlertTriangle, Plus, Users, Building2, CheckCircle2,
  Sparkles, Handshake, X, UserCheck,
} from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { cn } from "@/lib/utils";
import { SUBCOUNTIES, subCountiesOf } from "@/lib/geography";
import { candidateClusterLeaders } from "@/lib/cluster/cluster-core";
import { assignSchoolAction, createEmptyClusterAction, markJoinedThroughClusterAction } from "@/lib/actions/cluster-actions";
import { notifyClustersUpdated } from "@/lib/cluster/cluster-events";

// Same source as the standalone "New cluster" form so the directory's create-new
// experience offers the identical district picker.
const DISTRICT_OPTIONS = Array.from(new Set(SUBCOUNTIES.map((s) => s.districtName)))
  .sort()
  .map((d) => ({ value: d, label: d }));
import { assignSchoolToProjectAction, removeSchoolFromProjectAction } from "@/lib/actions/special-project-actions";
import { assignPartnerToSchool, cancelPartnerAssignment } from "@/lib/actions/portfolio-actions";

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

export type DirectoryProjectTag = { projectId: string; projectShortName: string; projectType: string; primaryInterventionId?: string };
export type DirectoryDelegation = { id: string; partnerName: string; interventionArea?: string };

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
  /** Canonical workflow stage (set by the directory; the drawer ignores it). */
  stage?: "needs_owner" | "unclustered" | "ssa_required" | "planning_ready";
  matches: { strong: DirectoryClusterMatch[]; district: DirectoryClusterMatch[]; region: DirectoryClusterMatch[] };
  /** Active special-project memberships. */
  projects?: DirectoryProjectTag[];
  /** Project ids recommended for this school (SSA weakness matches the
   *  project's mapped intervention). Drives the "Recommended" badge. */
  recommendedProjectIds?: string[];
  /** Active partner delegations (execution only). */
  delegations?: DirectoryDelegation[];
  /** SSA-derived recommendation summary — severity + delivery for the weakest gap. */
  recommendation?: {
    hasSsa: boolean;
    strugglingCount: number;
    weakestArea?: string;
    weakestScore?: number;
    weakestSeverity?: "Critical" | "Needs Support" | "Good" | "Strong";
    weakestDelivery?: "staff" | "partner";
  };
  /** School contact details shown in the expanded card row. */
  phone?: string;
  primaryContact?: string;
  /** Top-2 weakest SSA intervention areas (score 0–10), shown in red. */
  weakAreas?: Array<{ area: string; score: number }>;
};

type Tab = "cluster" | "project" | "partner";

export function DirectoryClusterDrawer({
  open, school, onClose, projectOptions = [], partnerOptions = [], interventionAreas = [], initialTab = "cluster",
  canManageClusters = true, geoByDistrict = {},
}: {
  open: boolean;
  school: DirectorySchoolVM | null;
  onClose: (changed?: boolean) => void;
  projectOptions?: DirectoryProjectTag[];
  partnerOptions?: string[];
  interventionAreas?: string[];
  initialTab?: Tab;
  /** When false, the Cluster tab is read-only — cluster assignment is a
   *  CCEO/PL responsibility (e.g. the Project Coordinator only views it). */
  canManageClusters?: boolean;
  /** Backend-accurate district → sub-counties map (from the directory's schools)
   *  so the Create-new form offers only real, in-scope geography that resolves. */
  geoByDistrict?: Record<string, string[]>;
}) {
  const router = useRouter();
  function refreshClusters() {
    notifyClustersUpdated();
    router.refresh();
  }
  const [tab, setTab] = useState<Tab>(initialTab);
  const [mode, setMode] = useState<"existing" | "create">("existing");
  const [selected, setSelected] = useState<string>("");
  const [newName, setNewName] = useState("");
  // Create-new cluster form — mirrors the standalone CreateClusterButton: district
  // dropdown, multi-select sub-counties, auto-suggested name, and a cluster leader.
  const [newDistrict, setNewDistrict] = useState("");
  const [newSubCounties, setNewSubCounties] = useState<string[]>([]);
  const [newAutoName, setNewAutoName] = useState("");
  const [leaderName, setLeaderName] = useState("");
  const [leaderPhone, setLeaderPhone] = useState("");
  const [leaderSchoolId, setLeaderSchoolId] = useState("");
  const [joinedVia, setJoinedVia] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changed, setChanged] = useState(false);

  // Project tab
  const [projectChoice, setProjectChoice] = useState("");
  // Partner tab
  const [partnerName, setPartnerName] = useState("");
  const [partnerArea, setPartnerArea] = useState("");
  const [pending, startTransition] = useTransition();

  const selectable = useMemo(
    () => (school ? [...school.matches.strong, ...school.matches.district] : []),
    [school],
  );
  const joinedProjectIds = useMemo(
    () => new Set((school?.projects ?? []).map((p) => p.projectId)),
    [school],
  );
  const availableProjects = useMemo(
    () => projectOptions.filter((p) => !joinedProjectIds.has(p.projectId)),
    [projectOptions, joinedProjectIds],
  );
  const recommendedSet = useMemo(
    () => new Set(school?.recommendedProjectIds ?? []),
    [school],
  );
  const recommendedAvailable = useMemo(
    () => availableProjects.filter((p) => recommendedSet.has(p.projectId)),
    [availableProjects, recommendedSet],
  );

  // Create-new cluster: sub-county choices for the chosen district + candidate
  // leaders drawn from schools in the chosen area (same helpers the standalone form uses).
  const useBackendGeo = Object.keys(geoByDistrict).length > 0;
  const districtOpts = useBackendGeo
    ? Object.keys(geoByDistrict).sort().map((d) => ({ value: d, label: d }))
    : DISTRICT_OPTIONS;
  const newSubCountyChoices = useMemo(
    () => (useBackendGeo
      ? (geoByDistrict[newDistrict] ?? [])
      : (newDistrict ? subCountiesOf(newDistrict).map((s) => s.name) : [])),
    [newDistrict, useBackendGeo, geoByDistrict],
  );
  const leaderCandidates = useMemo(
    () => (newDistrict ? candidateClusterLeaders(newDistrict, newSubCounties) : []),
    [newDistrict, newSubCounties],
  );

  if (!school) return null;
  function flashError(msg: string) { setError(msg); }
  function close() { onClose(changed); setChanged(false); setError(null); }

  // ── Cluster ──
  async function assignExisting() {
    setError(null);
    if (!selected) { flashError("Pick a cluster."); return; }
    setBusy(true);
    const res = await assignSchoolAction(school!.schoolId, selected);
    if (!res.ok) {
      setBusy(false);
      flashError(res.reason === "FORBIDDEN" ? "You don't have permission." : res.reason === "FAILED" ? res.message : "Failed.");
      return;
    }
    if (joinedVia) await markJoinedThroughClusterAction(school!.schoolId, selected, "cluster_referral");
    setBusy(false);
    refreshClusters();
    onClose(true);
  }

  // Enter create-new mode — default district + sub-county to the school's geography.
  function enterCreateMode() {
    setMode("create");
    setError(null);
    if (!newDistrict) {
      const d = school!.district;
      const sc = school!.subCounty ? [school!.subCounty] : [];
      setNewDistrict(d);
      setNewSubCounties(sc);
      const suggestion = suggestNewName(d, sc);
      setNewName(suggestion);
      setNewAutoName(suggestion);
    }
  }

  function suggestNewName(d: string, subs: string[]): string {
    if (subs.length === 1) return `${subs[0]} Cluster`;
    if (subs.length > 1) return `${d} Cluster`;
    return "";
  }

  function toggleNewSubCounty(sc: string) {
    setNewSubCounties((prev) => {
      const next = prev.includes(sc) ? prev.filter((x) => x !== sc) : [...prev, sc];
      // Keep the name synced while the user hasn't typed a custom one.
      if (newName === "" || newName === newAutoName) {
        const suggestion = suggestNewName(newDistrict, next);
        setNewName(suggestion);
        setNewAutoName(suggestion);
      }
      return next;
    });
  }

  function pickLeader(schoolId: string) {
    setLeaderSchoolId(schoolId);
    const c = leaderCandidates.find((x) => x.schoolId === schoolId);
    if (c) { setLeaderName(c.leaderName); setLeaderPhone(c.phone ?? ""); }
  }

  async function createAndAssign(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (newSubCounties.length === 0) { flashError("Select at least one sub-county."); return; }
    if (!newName.trim()) { flashError("Give the cluster a name."); return; }
    setBusy(true);
    // 1) Create the cluster with its full geography + leader (persists to the backend).
    const res = await createEmptyClusterAction({
      name: newName.trim(),
      district: newDistrict,
      subCounties: newSubCounties,
      clusterLeaderName: leaderName.trim() || undefined,
      clusterLeaderPhone: leaderPhone.trim() || undefined,
      clusterLeaderSchoolId: leaderSchoolId || undefined,
    });
    if (!res.ok) {
      setBusy(false);
      flashError(res.reason === "INVALID_INPUT" ? (Object.values(res.errors)[0] ?? "Invalid.") : res.reason === "FORBIDDEN" ? "You don't have permission." : res.reason === "FAILED" ? res.message : "Failed.");
      return;
    }
    // 2) Add this school as the cluster's first member.
    const assign = await assignSchoolAction(school!.schoolId, res.clusterId);
    if (!assign.ok) {
      setBusy(false);
      flashError(`Cluster created, but adding ${school!.schoolName} failed${assign.reason === "FAILED" ? `: ${assign.message}` : "."} You can add it from the cluster page.`);
      refreshClusters();
      return;
    }
    if (joinedVia) await markJoinedThroughClusterAction(school!.schoolId, res.clusterId, "cluster_onboarding");
    setBusy(false);
    refreshClusters();
    onClose(true);
  }

  // ── Special project ──
  function addProject(projectId: string) {
    setError(null);
    if (!projectId) { flashError("Pick a project."); return; }
    startTransition(async () => {
      const res = await assignSchoolToProjectAction(school!.schoolId, projectId);
      if (!res.ok) { flashError(res.reason === "FORBIDDEN" ? "You don't have permission." : res.message); return; }
      setProjectChoice("");
      setChanged(true);
      router.refresh();
    });
  }
  function addToProject() { addProject(projectChoice); }
  function removeFromProject(projectId: string) {
    startTransition(async () => {
      await removeSchoolFromProjectAction(school!.schoolId, projectId);
      setChanged(true);
      router.refresh();
    });
  }

  // ── Partner ──
  function addPartner() {
    setError(null);
    if (!partnerName.trim()) { flashError("Enter a partner name."); return; }
    startTransition(async () => {
      const res = await assignPartnerToSchool({ schoolId: school!.schoolId, partnerName, interventionArea: partnerArea || undefined });
      if (res.ok) {
        setPartnerName(""); setPartnerArea("");
        setChanged(true);
        router.refresh();
      } else {
        flashError(res.reason === "FORBIDDEN" ? "Only the owner (or their lead) can delegate this school." : res.reason === "INVALID_INPUT" ? "Enter a partner name." : "School not found.");
      }
    });
  }
  function cancelPartner(id: string) {
    startTransition(async () => {
      await cancelPartnerAssignment(id);
      setChanged(true);
      router.refresh();
    });
  }

  const hasSelectable = selectable.length > 0;
  const projects = school.projects ?? [];
  const delegations = school.delegations ?? [];

  return (
    <Modal
      open={open}
      onClose={close}
      title={`Manage ${school.schoolName}`}
      description="Assign to a cluster or tag into a special project. Ownership stays with the account owner."
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
            {school.clusterName && <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] inline-flex items-center gap-1"><Network size={9} />{school.clusterName}</span>}
            <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold", school.ssaStatus === "SSA Done" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500")}>{school.ssaStatus === "SSA Done" ? "SSA done" : "SSA pending"}</span>
          </div>
          <div className="muted inline-flex items-center gap-1"><MapPin size={10} className="text-[var(--color-edify-primary)]" />{school.district}{school.subCounty ? ` · ${school.subCounty}` : ""}{school.parish ? ` · ${school.parish}` : ""}</div>
          <div className="muted inline-flex items-center gap-1"><User size={10} />{school.assignedCceo ?? "Unassigned"}</div>
        </div>

        {/* Top-level tabs — the directory does exactly two things: assign to a
            CLUSTER and to a PROJECT. Partner delegation moved to the Planning
            page (Assign to Partner), so there's no Partner tab here. */}
        <div className="grid grid-cols-2 gap-1 p-1 rounded-lg bg-[var(--color-edify-soft)]/50">
          <TopTab active={tab === "cluster"} onClick={() => { setTab("cluster"); setError(null); }} Icon={Network} label="Cluster" />
          <TopTab active={tab === "project"} onClick={() => { setTab("project"); setError(null); }} Icon={Sparkles} label="Special project" count={projects.length} />
        </div>

        {/* ── CLUSTER TAB ── */}
        {tab === "cluster" && (
          !canManageClusters ? (
            // Read-only — cluster assignment is a CCEO / Program Lead responsibility.
            school.clusterStatus === "clustered" ? (
              <div className="rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 px-3 py-2.5 text-[12px] inline-flex items-start gap-1.5">
                <Network size={13} className="mt-0.5 shrink-0 text-[var(--color-edify-primary)]" />
                In <b className="mx-1">{school.clusterName}</b>. Cluster assignment is managed by the CCEO / Program Lead.
              </div>
            ) : (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-[12px] text-amber-800 inline-flex items-start gap-1.5">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                Not yet clustered. Cluster assignment is handled by the CCEO / Program Lead.
              </div>
            )
          ) : school.clusterStatus === "clustered" ? (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-[12px] text-emerald-800 inline-flex items-start gap-1.5">
              <CheckCircle2 size={13} className="mt-0.5 shrink-0" />
              Already in <b className="mx-1">{school.clusterName}</b>. Manage member schools from the cluster page.
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-1 p-1 rounded-lg bg-[var(--color-edify-soft)]/50">
                <ModeTab active={mode === "existing"} onClick={() => { setMode("existing"); setError(null); }}>Existing cluster</ModeTab>
                <ModeTab active={mode === "create"} onClick={enterCreateMode}>Create new</ModeTab>
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

                  {school.matches.region.length > 0 && (
                    <p className="text-[10.5px] muted">
                      {school.matches.region.length} cluster(s) elsewhere in {school.region} — not shown (different district; would need an override).
                    </p>
                  )}

                  <label className="flex items-center gap-2 cursor-pointer text-[11px]">
                    <input type="checkbox" checked={joinedVia} onChange={(e) => setJoinedVia(e.target.checked)} className="h-3.5 w-3.5 accent-[var(--color-edify-primary)]" />
                    This school joined Edify <span className="font-semibold">through this cluster</span> (onboarding / referral)
                  </label>

                  {hasSelectable && (
                    <Button size="sm" Icon={Network} disabled={busy || !selected} onClick={assignExisting}>
                      {busy ? "Adding…" : "Add to selected cluster"}
                    </Button>
                  )}
                </div>
              ) : (
                <form onSubmit={createAndAssign} className="space-y-3">
                  <Select
                    label="District"
                    required
                    value={newDistrict}
                    onChange={(e) => { setNewDistrict(e.target.value); setNewSubCounties([]); setLeaderSchoolId(""); }}
                    options={districtOpts}
                  />

                  {/* Sub-counties — multi-select (a cluster may span several); the
                      school's own sub-county is pre-checked so it's covered. */}
                  <div className="space-y-1">
                    <label className="block text-[12px] font-semibold text-[var(--color-edify-text)]">
                      Sub-counties <span className="text-rose-500">*</span>
                      <span className="ml-1 font-normal muted">({newSubCounties.length} selected)</span>
                    </label>
                    <div className="max-h-40 overflow-y-auto rounded-lg border border-[var(--color-edify-border)] divide-y divide-[var(--color-edify-divider)]">
                      {newSubCountyChoices.length === 0 ? (
                        <p className="px-3 py-3 text-[12px] muted">No sub-counties catalogued for this district.</p>
                      ) : (
                        newSubCountyChoices.map((sc) => {
                          const checked = newSubCounties.includes(sc);
                          return (
                            <label
                              key={sc}
                              className={cn(
                                "flex items-center gap-2.5 px-3 py-2 text-[12.5px] cursor-pointer transition-colors",
                                checked ? "bg-[var(--color-edify-primary)]/5 font-semibold" : "hover:bg-[var(--color-edify-soft)]/40",
                              )}
                            >
                              <input type="checkbox" checked={checked} onChange={() => toggleNewSubCounty(sc)} className="h-3.5 w-3.5 accent-[var(--color-edify-primary)]" />
                              {sc}
                            </label>
                          );
                        })
                      )}
                    </div>
                  </div>

                  <Input
                    label="Cluster name"
                    required
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="e.g. Mukono Central Cluster"
                    helper="Auto-suggested from your selection — edit if you like. Must be unique within the district."
                  />

                  {/* Cluster leader — a school leader from one of the cluster's schools. */}
                  <div className="space-y-2 rounded-lg border border-[var(--color-edify-border)] p-3">
                    <div className="flex items-center gap-1.5 text-[12px] font-extrabold tracking-tight">
                      <UserCheck size={13} className="text-[var(--color-edify-primary)]" />
                      Cluster leader
                    </div>
                    {leaderCandidates.length > 0 ? (
                      <Select
                        label="Pick a school leader"
                        value={leaderSchoolId}
                        onChange={(e) => pickLeader(e.target.value)}
                        options={leaderCandidates.map((c) => ({ value: c.schoolId, label: `${c.leaderName} — ${c.schoolName}${c.subCounty ? ` (${c.subCounty})` : ""}` }))}
                        placeholder="Select from schools in this area…"
                      />
                    ) : (
                      <p className="text-[11px] muted">No school leaders on file for the selected area yet — enter the leader’s details below.</p>
                    )}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <Input label="Leader name" value={leaderName} onChange={(e) => { setLeaderName(e.target.value); setLeaderSchoolId(""); }} placeholder="e.g. Esther Naluwu" />
                      <Input label="Leader phone" value={leaderPhone} onChange={(e) => setLeaderPhone(e.target.value)} placeholder="e.g. +256 772 000 000" />
                    </div>
                  </div>

                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11.5px] text-emerald-800 inline-flex items-start gap-1.5">
                    <CheckCircle2 size={12} className="mt-0.5 shrink-0" />
                    Creates the cluster and adds {school.schoolName} as its first school.
                  </div>
                  <Button size="sm" Icon={Plus} disabled={busy} onClick={() => { const f = document.activeElement as HTMLElement; f?.blur(); }} type="submit">
                    {busy ? "Creating…" : "Create cluster & add school"}
                  </Button>
                </form>
              )}
            </>
          )
        )}

        {/* ── SPECIAL PROJECT TAB ── */}
        {tab === "project" && (
          <div className="space-y-3">
            {projects.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {projects.map((p) => (
                  <span key={p.projectId} className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[11px] font-extrabold bg-violet-50 text-violet-700">
                    <Sparkles size={10} /> {p.projectShortName}
                    <button type="button" aria-label={`Remove ${p.projectShortName}`} disabled={pending} onClick={() => removeFromProject(p.projectId)} className="ml-0.5 hover:text-violet-900"><X size={11} /></button>
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-[11.5px] muted">Not in any special project yet. Special projects sit outside the SSA interventions but still count toward capacity, funding, and reporting.</p>
            )}

            {recommendedAvailable.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-[11px] font-bold inline-flex items-center gap-1 text-amber-700">
                  <Sparkles size={11} /> Recommended — SSA weakness matches the project focus
                </p>
                <ul className="space-y-1.5">
                  {recommendedAvailable.map((p) => (
                    <li key={p.projectId} className="flex items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50/60 px-2.5 py-2">
                      <span className="min-w-0">
                        <span className="text-[12px] font-extrabold">{p.projectShortName}</span>
                        {p.primaryInterventionId && (
                          <span className="block text-[10.5px] muted truncate">{p.primaryInterventionId}</span>
                        )}
                      </span>
                      <Button size="sm" Icon={Plus} disabled={pending} onClick={() => addProject(p.projectId)}>{pending ? "Adding…" : "Add"}</Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {availableProjects.length > 0 ? (
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <Select label="Add to special project" placeholder="Choose a project…" value={projectChoice}
                    options={availableProjects.map((p) => ({ value: p.projectId, label: `${p.projectShortName}${p.primaryInterventionId ? ` · ${p.primaryInterventionId}` : ` · ${p.projectType}`}${recommendedSet.has(p.projectId) ? " · ★ recommended" : ""}` }))}
                    onChange={(e) => setProjectChoice(e.target.value)} />
                </div>
                <Button size="sm" Icon={Plus} disabled={pending || !projectChoice} onClick={addToProject}>{pending ? "Adding…" : "Add"}</Button>
              </div>
            ) : (
              <p className="text-[10.5px] muted">In every available project.</p>
            )}
          </div>
        )}

        {/* ── PARTNER TAB ── */}
        {tab === "partner" && (
          <div className="space-y-3">
            {delegations.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {delegations.map((d) => (
                  <span key={d.id} className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[11px] font-extrabold bg-sky-100 text-sky-700">
                    <Handshake size={10} /> {d.partnerName}{d.interventionArea ? ` · ${d.interventionArea}` : ""}
                    <button type="button" aria-label={`Cancel ${d.partnerName}`} disabled={pending} onClick={() => cancelPartner(d.id)} className="ml-0.5 hover:text-sky-900"><X size={11} /></button>
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-[11.5px] muted">No partner delegated. Assigning a partner delegates delivery only — the school stays in your portfolio and ownership never transfers.</p>
            )}
            <div className="space-y-2">
              <div className="flex flex-col gap-1">
                <label htmlFor="drawer-partner" className="text-[11.5px] font-semibold">Partner</label>
                <input id="drawer-partner" list="drawer-partner-suggestions" value={partnerName} placeholder="Hope Education Partners"
                  onChange={(e) => setPartnerName(e.target.value)}
                  className="h-9 px-3 text-[12.5px] rounded-lg bg-white border border-[var(--color-edify-border)] outline-none focus:outline-2 focus:outline-[var(--color-edify-primary)]" />
                <datalist id="drawer-partner-suggestions">
                  {partnerOptions.map((p) => <option key={p} value={p} />)}
                </datalist>
              </div>
              <Select label="Intervention area (optional)" placeholder="Any / not specified" value={partnerArea}
                options={interventionAreas.map((a) => ({ value: a, label: a }))}
                onChange={(e) => setPartnerArea(e.target.value)} />
              <Button size="sm" Icon={Handshake} disabled={pending || !partnerName.trim()} onClick={addPartner}>{pending ? "Assigning…" : "Delegate to partner"}</Button>
            </div>
          </div>
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

function TopTab({ active, onClick, Icon, label, count }: { active: boolean; onClick: () => void; Icon: typeof Network; label: string; count?: number }) {
  return (
    <button type="button" onClick={onClick}
      className={cn("h-9 rounded-md text-[11.5px] font-bold transition-colors inline-flex items-center justify-center gap-1.5",
        active ? "bg-white shadow-sm text-[var(--color-edify-text)]" : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]")}>
      <Icon size={13} /> {label}
      {count ? <span className="px-1 rounded bg-[var(--color-edify-primary)]/10 text-[var(--color-edify-primary)] text-[10px]">{count}</span> : null}
    </button>
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
