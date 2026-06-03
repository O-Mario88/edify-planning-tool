"use client";

// School 360 — the school record as the operational source of truth. Shows the
// full record, the canonical workflow state (Owner → Cluster → SSA → Planning)
// with the next action launched FROM here, the linked cluster, and every
// activity that links back to this school.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Building2, MapPin, User, Phone, Network, CalendarDays, ShieldCheck, ArrowRight,
  AlertTriangle, CheckCircle2, Users2, ClipboardList, Sparkles, TrendingUp, TrendingDown, Minus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { DirectoryClusterDrawer, type DirectorySchoolVM } from "./DirectoryClusterDrawer";
import { activateSsaAction } from "@/lib/actions/ssa-activation-actions";
import type { SsaActivationMethod } from "@/lib/school-directory/ssa-activation";

const SSA_ACTION_METHOD: Record<string, SsaActivationMethod> = {
  schedule_sit: "sit",
  assign_ssa_partner: "partner",
  schedule_ssa_self: "self",
};

export type School360Record = {
  schoolId: string;
  schoolName: string;
  schoolType: string;
  region: string;
  district: string;
  subCounty?: string;
  parish?: string;
  assignedCceo?: string;
  enrollment?: number;
  phone?: string;
  primaryContact?: string;
  shippingAddress?: string;
  dateAdded: string;
  addedBy: string;
};

export type School360State = {
  stage: string;
  stageLabel: string;
  blocker?: string;
  flags: string[];
  clusterId?: string;
  clusterName?: string;
  ssaDone: boolean;
  nextActions: { key: string; label: string; href?: string; primary?: boolean }[];
};

export type School360Activity = { kind: string; label: string; date: string; status: string; ref?: string };

export type School360ProjectVM = {
  projectId: string;
  projectShortName: string;
  projectType: string;
  primaryInterventionId: string;
  status: string;
  partnerName?: string;
  trainings: number;
  followUps: number;
  interventionChange?: number;
};

const STAGE_TONE: Record<string, string> = {
  needs_owner: "bg-rose-50 text-rose-700",
  unclustered: "bg-rose-50 text-rose-700",
  ssa_required: "bg-amber-50 text-amber-700",
  planning_ready: "bg-emerald-50 text-emerald-700",
};

export function School360View({
  record, state, activities, addToClusterVM, projects = [],
}: {
  record: School360Record;
  state: School360State;
  activities: School360Activity[];
  addToClusterVM: DirectorySchoolVM | null;
  projects?: School360ProjectVM[];
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function activate(method: SsaActivationMethod) {
    startTransition(async () => {
      const res = await activateSsaAction(record.schoolId, method);
      if (res.ok) router.refresh();
    });
  }

  return (
    <div className="px-4 sm:px-5 md:px-6 pt-4 pb-12 space-y-4">
      {/* Header */}
      <header className="card rounded-2xl p-4 md:p-5">
        <div className="flex items-start gap-3">
          <span className="grid place-items-center h-11 w-11 rounded-xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0"><Building2 size={20} /></span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-[18px] font-extrabold tracking-tight">{record.schoolName}</h1>
              <span className="muted text-[12px]">#{record.schoolId}</span>
              <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold", record.schoolType === "Core" ? "bg-violet-50 text-violet-700" : "bg-blue-50 text-blue-700")}>{record.schoolType}</span>
              <span className={cn("px-2 py-0.5 rounded-lg text-[11px] font-bold", STAGE_TONE[state.stage] ?? "bg-slate-100 text-slate-600")}>{state.stageLabel}</span>
              {state.flags.map((f) => (
                <span key={f} className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-amber-50 text-amber-700 inline-flex items-center gap-1"><AlertTriangle size={9} />{f}</span>
              ))}
            </div>
            <p className="text-[12.5px] muted inline-flex items-center gap-1 mt-0.5">
              <MapPin size={11} className="text-[var(--color-edify-primary)]" />
              {record.district}{record.subCounty ? ` · ${record.subCounty}` : ""}{record.parish ? ` · ${record.parish}` : ""} · {record.region}
            </p>
            <p className="text-[12px] muted inline-flex items-center gap-1 mt-0.5"><User size={11} />{record.assignedCceo ?? "Unassigned"}</p>
          </div>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-4 items-start">
        <div className="space-y-4">
          {/* Workflow state + next action */}
          <section className="card rounded-2xl p-4">
            <h2 className="text-[14px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><ClipboardList size={14} className="text-[var(--color-edify-primary)]" /> Workflow status</h2>
            <p className="text-[11.5px] muted mt-0.5">Owner → Cluster → SSA → Planning. The next step is launched from this record.</p>
            {state.blocker && (
              <div className="mt-2 rounded-lg bg-[var(--color-edify-soft)]/50 px-3 py-2 text-[12px] inline-flex items-start gap-1.5">
                <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-600" /> {state.blocker}
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {state.nextActions.map((a) => {
                if (a.key === "add_to_cluster" && addToClusterVM) {
                  return (
                    <button key={a.key} type="button" onClick={() => setDrawerOpen(true)}
                      className={a.primary ? btnPrimary : btnGhost}>
                      {a.label} <ArrowRight size={12} />
                    </button>
                  );
                }
                if (SSA_ACTION_METHOD[a.key]) {
                  return (
                    <button key={a.key} type="button" disabled={pending} onClick={() => activate(SSA_ACTION_METHOD[a.key])}
                      className={cn(a.primary ? btnPrimary : btnGhost, pending && "opacity-60")}>
                      {a.label} <ArrowRight size={12} />
                    </button>
                  );
                }
                if (a.href) {
                  return (
                    <Link key={a.key} href={a.href} className={a.primary ? btnPrimary : btnGhost}>
                      {a.label} <ArrowRight size={12} />
                    </Link>
                  );
                }
                return <span key={a.key} className={btnGhost}>{a.label}</span>;
              })}
            </div>
          </section>

          {/* Linked activities */}
          <section className="card rounded-2xl overflow-hidden">
            <header className="px-4 pt-3.5 pb-2">
              <h2 className="text-[14px] font-extrabold tracking-tight">Linked activities</h2>
              <p className="text-[11.5px] muted mt-0.5">Everything traceable to this school — SSA uploads and its cluster's meetings/trainings.</p>
            </header>
            <ul className="divide-y divide-[var(--color-edify-divider)] border-t border-[var(--color-edify-divider)]">
              {activities.length === 0 ? (
                <li className="px-4 py-5 text-center text-[12px] muted">No activities yet. Complete cluster + SSA to begin.</li>
              ) : activities.map((a, i) => (
                <li key={i} className="px-4 py-2.5 flex items-center gap-2 text-[12px]">
                  {a.kind === "ssa_upload" ? <ShieldCheck size={13} className="text-emerald-600 shrink-0" /> : <CalendarDays size={13} className="text-[var(--color-edify-primary)] shrink-0" />}
                  <span className="font-semibold">{a.label}</span>
                  <span className="muted">{a.date}</span>
                  {a.ref && <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-slate-100 text-slate-600">{a.ref}</span>}
                  <span className="ml-auto muted text-[11px]">{a.status}</span>
                </li>
              ))}
            </ul>
          </section>

          {/* Special projects — targeted initiatives this school is in */}
          <section className="card rounded-2xl overflow-hidden">
            <header className="px-4 pt-3.5 pb-2">
              <h2 className="text-[14px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
                <Sparkles size={14} className="text-[var(--color-edify-primary)]" /> Special projects
              </h2>
              <p className="text-[11.5px] muted mt-0.5">Targeted initiatives mapped to SSA interventions. Separate from the 8 interventions; ownership stays with the account owner.</p>
            </header>
            {projects.length === 0 ? (
              <p className="px-4 py-5 text-center text-[12px] muted border-t border-[var(--color-edify-divider)]">Not enrolled in any special project.</p>
            ) : (
              <ul className="divide-y divide-[var(--color-edify-divider)] border-t border-[var(--color-edify-divider)]">
                {projects.map((p) => (
                  <li key={p.projectId} className="px-4 py-2.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Link href={`/projects/${p.projectId}`} className="text-[12.5px] font-extrabold hover:text-[var(--color-edify-primary)] hover:underline">{p.projectShortName}</Link>
                      <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">{p.primaryInterventionId}</span>
                      <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-slate-100 text-slate-600">{p.status}</span>
                      {p.interventionChange !== undefined && (
                        <span className="ml-auto inline-flex items-center gap-1 text-[11.5px] font-bold">
                          {p.interventionChange > 0 ? <TrendingUp size={12} className="text-emerald-600" /> : p.interventionChange < 0 ? <TrendingDown size={12} className="text-rose-600" /> : <Minus size={12} className="text-slate-400" />}
                          {p.interventionChange > 0 ? "+" : ""}{p.interventionChange.toFixed(1)} on {p.primaryInterventionId}
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 text-[11px] muted">
                      {p.trainings} training{p.trainings === 1 ? "" : "s"} · {p.followUps} follow-up{p.followUps === 1 ? "" : "s"}
                      {p.partnerName ? ` · Partner: ${p.partnerName}` : ""}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* Right rail */}
        <aside className="space-y-4">
          <section className="card rounded-2xl p-4">
            <h2 className="text-[14px] font-extrabold tracking-tight mb-2">Cluster</h2>
            {state.clusterName ? (
              <Link href={state.clusterId ? `/clusters/${state.clusterId}` : "/clusters"} className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-[var(--color-edify-primary)] hover:underline">
                <Network size={13} /> {state.clusterName} <ArrowRight size={12} />
              </Link>
            ) : (
              <p className="text-[12px] muted inline-flex items-center gap-1"><AlertTriangle size={11} className="text-rose-500" /> Not clustered yet</p>
            )}
            <div className="mt-2 text-[12px] inline-flex items-center gap-1.5">
              {state.ssaDone ? <><CheckCircle2 size={13} className="text-emerald-600" /> Current-FY SSA complete</> : <><AlertTriangle size={13} className="text-amber-600" /> SSA pending</>}
            </div>
          </section>
          <section className="card rounded-2xl p-4 space-y-1.5 text-[12px]">
            <h2 className="text-[14px] font-extrabold tracking-tight mb-1">Record</h2>
            <Fact icon={<Users2 size={11} />} label="Enrollment" value={record.enrollment != null ? String(record.enrollment) : "—"} />
            <Fact icon={<User size={11} />} label="Primary contact" value={record.primaryContact ?? "—"} />
            <Fact icon={<Phone size={11} />} label="Phone" value={record.phone ?? "—"} />
            <Fact icon={<MapPin size={11} />} label="Shipping" value={record.shippingAddress ?? "—"} />
            <Fact icon={<CalendarDays size={11} />} label="Added" value={`${record.dateAdded} · ${record.addedBy}`} />
          </section>
        </aside>
      </div>

      {addToClusterVM && (
        <DirectoryClusterDrawer open={drawerOpen} school={addToClusterVM} onClose={() => setDrawerOpen(false)} />
      )}
    </div>
  );
}

const btnPrimary = "inline-flex items-center gap-1 h-9 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-extrabold hover:bg-[var(--color-edify-dark)] transition-colors";
const btnGhost = "inline-flex items-center gap-1 h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60 transition-colors";

function Fact({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[var(--color-edify-muted)]">{icon}</span>
      <span className="muted">{label}</span>
      <span className="ml-auto font-semibold text-[var(--color-edify-text)] text-right">{value}</span>
    </div>
  );
}
