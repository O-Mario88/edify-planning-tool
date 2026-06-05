"use client";

// Core School detail — the full lifecycle story for one schoolId across 11 tabs.
// Pure presentational: it reads a serializable view-model built from the unified
// store (src/lib/core/core-detail). Execution controls live on the planning
// board; this surface explains why the school is core and what changed.

import { useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import type { CoreSchoolDetailVM } from "@/lib/core/core-detail";

const TABS = [
  "Overview", "Baseline SSA", "Priority Interventions", "4 Visits", "4 Trainings",
  "Evidence", "Salesforce / IA", "Follow-Up SSA", "Impact", "Champion Review", "Timeline",
] as const;
type Tab = typeof TABS[number];

export function CoreSchoolDetail({ vm }: { vm: CoreSchoolDetailVM }) {
  const [tab, setTab] = useState<Tab>("Overview");
  return (
    <div className="px-3 sm:px-4 lg:px-6 pb-24 lg:pb-6 space-y-3 pt-3">
      {/* Tab strip */}
      <div className="flex gap-1 overflow-x-auto border-b border-[var(--color-edify-border)] -mx-1 px-1">
        {TABS.map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={cn("shrink-0 px-2.5 py-1.5 text-[11.5px] font-bold rounded-t-md border-b-2 -mb-px transition-colors",
              tab === t ? "border-[var(--color-edify-primary)] text-[var(--color-edify-primary)]" : "border-transparent muted hover:text-[var(--color-edify-text)]")}>
            {t}
          </button>
        ))}
      </div>

      {tab === "Overview" && <Overview vm={vm} />}
      {tab === "Baseline SSA" && <SsaScores title="Baseline SSA" snap={vm.baseline} areas={vm.areas} />}
      {tab === "Priority Interventions" && <Priorities vm={vm} />}
      {tab === "4 Visits" && <Slots vm={vm} kind="visit" />}
      {tab === "4 Trainings" && <Slots vm={vm} kind="training" />}
      {tab === "Evidence" && <Evidence vm={vm} />}
      {tab === "Salesforce / IA" && <SalesforceIa vm={vm} />}
      {tab === "Follow-Up SSA" && <FollowUp vm={vm} />}
      {tab === "Impact" && <Impact vm={vm} />}
      {tab === "Champion Review" && <Champion vm={vm} />}
      {tab === "Timeline" && <Timeline vm={vm} />}
    </div>
  );
}

function Card({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <section className="card p-3.5">
      {title && <h2 className="text-[12px] font-extrabold tracking-tight mb-2">{title}</h2>}
      {children}
    </section>
  );
}
function Empty({ children }: { children: React.ReactNode }) {
  return <p className="py-6 text-center text-[12px] muted italic">{children}</p>;
}
function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] font-semibold muted uppercase tracking-wide">{label}</div>
      <div className="text-[12.5px] font-bold mt-0.5">{value ?? "—"}</div>
    </div>
  );
}

function Overview({ vm }: { vm: CoreSchoolDetailVM }) {
  return (
    <Card title="Why this school is Core">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        <Field label="School" value={vm.schoolName} />
        <Field label="School ID" value={<span className="tabular">{vm.schoolId}</span>} />
        <Field label="District" value={vm.district} />
        <Field label="Region" value={vm.region} />
        <Field label="Cluster" value={vm.cluster ?? "—"} />
        <Field label="Account owner" value={vm.owner ?? "—"} />
        <Field label="Enrollment" value={vm.enrollment ?? "—"} />
        <Field label="Core plan FY" value={vm.plan?.fy ?? "—"} />
        <Field label="Baseline SSA" value={vm.baseline ? vm.baseline.average.toFixed(1) : "—"} />
        <Field label="Plan status" value={vm.plan?.status ?? "Not a core plan"} />
        <Field label="Package" value={vm.progress ? `${vm.progress.packageCompletionPercent}%` : "—"} />
        <Field label="Champion" value={vm.profile?.championStatus ?? "—"} />
      </div>
      {vm.onboarding?.onboardingReason && (
        <p className="text-[11.5px] muted mt-3 pt-3 border-t border-[var(--color-edify-divider)]">
          <span className="font-bold text-[var(--color-edify-text)]">Onboarding reason:</span> {vm.onboarding.onboardingReason}
        </p>
      )}
    </Card>
  );
}

function SsaScores({ title, snap, areas }: { title: string; snap?: { scores: Partial<Record<string, number>>; average: number; date: string }; areas: readonly string[] }) {
  if (!snap) return <Card title={title}><Empty>No {title.toLowerCase()} on file.</Empty></Card>;
  return (
    <Card title={`${title} · ${snap.date} · avg ${snap.average.toFixed(1)}`}>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {areas.map((a) => (
          <div key={a} className="rounded-lg border border-[var(--color-edify-divider)] px-2.5 py-1.5">
            <div className="text-[10px] muted leading-tight">{a}</div>
            <div className="text-[15px] font-extrabold tabular">{snap.scores[a] ?? "—"}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Priorities({ vm }: { vm: CoreSchoolDetailVM }) {
  if (vm.interventions.length === 0) return <Card title="Priority interventions"><Empty>No priority interventions selected.</Empty></Card>;
  const change = (area: string) => vm.impact?.priorityInterventionChange.find((c) => c.intervention === area);
  return (
    <Card title="4 priority interventions (weakest baseline areas)">
      <div className="space-y-1.5">
        {vm.interventions.map((i) => {
          const ch = change(i.intervention);
          return (
            <div key={i.id} className="flex items-center justify-between gap-2 rounded-lg border border-[var(--color-edify-divider)] px-2.5 py-2">
              <div className="min-w-0">
                <span className="text-[12px] font-bold"><span className="text-[var(--color-edify-primary)]">#{i.priorityRank}</span> {i.intervention}</span>
                <div className="text-[10.5px] muted">{i.reason ?? "Selected from baseline."}</div>
              </div>
              <div className="text-right shrink-0">
                <div className="text-[10px] muted">baseline → latest</div>
                <div className="text-[12px] font-extrabold tabular">
                  {i.baselineScore} → {ch ? ch.followUpScore : "—"}
                  {ch && <span className={cn("ml-1", ch.change >= 0 ? "text-emerald-700" : "text-rose-700")}>({ch.change >= 0 ? "+" : ""}{ch.change})</span>}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function Slots({ vm, kind }: { vm: CoreSchoolDetailVM; kind: "visit" | "training" }) {
  const slots = kind === "visit" ? vm.visits : vm.trainings;
  const label = kind === "visit" ? "Visit" : "Training";
  if (slots.length === 0) return <Card title={`4 ${label}s`}><Empty>No {label.toLowerCase()} slots.</Empty></Card>;
  return (
    <Card title={`4 ${label}s`}>
      <div className="space-y-1.5">
        {slots.map((s) => (
          <div key={s.id} className="flex items-center justify-between gap-2 rounded-lg border border-[var(--color-edify-divider)] px-2.5 py-2">
            <div className="min-w-0">
              <span className="text-[12px] font-bold">{label} {s.sequenceNumber}</span>
              <span className="text-[11px] muted"> · {s.intervention}</span>
              {s.scheduledFor && <div className="text-[10.5px] muted">Scheduled {s.scheduledFor}</div>}
            </div>
            <div className="text-right shrink-0">
              <StatusPill status={s.status} />
              {s.assignedStaffName && <div className="text-[10px] muted mt-0.5">{s.assignedStaffName}</div>}
              {s.assignedPartnerName && <div className="text-[10px] muted mt-0.5">Partner: {s.assignedPartnerName}</div>}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Evidence({ vm }: { vm: CoreSchoolDetailVM }) {
  const all = [...vm.visits, ...vm.trainings].filter((s) => s.evidenceUri || s.evidenceNotes);
  if (all.length === 0) return <Card title="Evidence"><Empty>No evidence uploaded yet.</Empty></Card>;
  return (
    <Card title="Evidence">
      <div className="space-y-1.5">
        {all.map((s) => (
          <div key={s.id} className="rounded-lg border border-[var(--color-edify-divider)] px-2.5 py-2">
            <div className="text-[12px] font-bold">{s.activityType === "visit" ? "Visit" : "Training"} {s.sequenceNumber} · {s.intervention}</div>
            {s.evidenceUri && <a href={s.evidenceUri} className="text-[11px] text-[var(--color-edify-primary)] font-bold hover:underline break-all">{s.evidenceUri}</a>}
            {s.evidenceNotes && <p className="text-[11px] muted mt-0.5">{s.evidenceNotes}</p>}
          </div>
        ))}
      </div>
    </Card>
  );
}

function SalesforceIa({ vm }: { vm: CoreSchoolDetailVM }) {
  const all = [...vm.visits, ...vm.trainings];
  return (
    <Card title="Salesforce IDs & IA verification">
      <div className="overflow-x-auto">
        <table className="w-full text-[11.5px]">
          <thead>
            <tr className="text-left muted uppercase text-[10px] tracking-wide border-b border-[var(--color-edify-border)]">
              <th className="py-1.5 pr-2">Activity</th><th className="py-1.5 px-2">Salesforce ID</th>
              <th className="py-1.5 px-2">IA</th><th className="py-1.5 px-2">Accountant</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-edify-divider)]">
            {all.map((s) => (
              <tr key={s.id}>
                <td className="py-1.5 pr-2 font-bold">{s.activityType === "visit" ? "V" : "T"}{s.sequenceNumber} <span className="muted font-normal">{s.intervention}</span></td>
                <td className="py-1.5 px-2 tabular">{s.salesforceId ?? <span className="muted">—</span>}</td>
                <td className="py-1.5 px-2">{s.iaVerificationStatus ?? <span className="muted">—</span>}</td>
                <td className="py-1.5 px-2">{s.accountantStatus ?? <span className="muted">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function FollowUp({ vm }: { vm: CoreSchoolDetailVM }) {
  if (!vm.followUp) {
    return <Card title="Follow-Up SSA"><Empty>{vm.progress?.readyForFollowUpSSA ? "Package complete — Follow-Up SSA is due." : "Follow-Up SSA runs after the 4 visits + 4 trainings package is complete and IA-verified."}</Empty></Card>;
  }
  return <SsaScores title="Follow-Up SSA" snap={vm.followUp} areas={vm.areas} />;
}

function Impact({ vm }: { vm: CoreSchoolDetailVM }) {
  if (!vm.impact) return <Card title="Impact"><Empty>Impact is computed once the Follow-Up SSA is recorded.</Empty></Card>;
  const im = vm.impact;
  return (
    <Card title={`Impact — ${im.impactStatus}`}>
      <div className="flex items-baseline gap-2 text-[14px] font-extrabold">
        <span className="tabular">{im.baselineAverage.toFixed(1)}</span>
        <span className="muted">→</span>
        <span className="tabular">{im.followUpAverage.toFixed(1)}</span>
        <span className={cn("tabular text-[12px]", im.averageChange >= 0 ? "text-emerald-700" : "text-rose-700")}>({im.averageChange >= 0 ? "+" : ""}{im.averageChange})</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 mt-3">
        {im.allInterventionChange.map((c) => (
          <div key={c.intervention} className={cn("flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-[11px]",
            c.classification === "Improved" ? "bg-emerald-50" : c.classification === "Declined" ? "bg-rose-50" : "bg-[var(--color-edify-soft)]/50")}>
            <span className="font-bold">{c.intervention}{c.priority && <span className="text-[var(--color-edify-primary)]"> ★</span>}</span>
            <span className="tabular font-extrabold">{c.baselineScore} → {c.followUpScore} <span className={c.change >= 0 ? "text-emerald-700" : "text-rose-700"}>({c.change >= 0 ? "+" : ""}{c.change})</span></span>
          </div>
        ))}
      </div>
      <p className="text-[11px] muted mt-3">Best improved: <b className="text-[var(--color-edify-text)]">{im.bestImproved ?? "—"}</b> · Weakest remaining: <b className="text-[var(--color-edify-text)]">{im.weakestRemaining ?? "—"}</b></p>
    </Card>
  );
}

function Champion({ vm }: { vm: CoreSchoolDetailVM }) {
  const status = vm.profile?.championStatus ?? "Not Eligible";
  const stages = ["Potential Champion", "Under Review", "IA Verified", "PL Recommended", "CD Approved", "Verified Champion", "Champion Mentor School"];
  const reached = stages.indexOf(status);
  return (
    <Card title="Champion review">
      {status === "Not Eligible" ? (
        <Empty>Not yet champion-eligible. A school becomes a Potential Champion when the package is complete, follow-up average clears the threshold, and every priority intervention improved.</Empty>
      ) : (
        <ol className="space-y-1.5">
          {stages.map((st, i) => (
            <li key={st} className={cn("flex items-center gap-2 text-[12px] font-bold", i <= reached ? "text-emerald-700" : "muted")}>
              <span className={cn("inline-flex items-center justify-center w-4 h-4 rounded-full text-[9px] text-white", i <= reached ? "bg-emerald-600" : "bg-slate-300")}>{i + 1}</span>
              {st}
            </li>
          ))}
        </ol>
      )}
      {vm.impact && <p className="text-[11px] muted mt-3">Champion eligibility is bound to the impact snapshot: follow-up average {vm.impact.followUpAverage.toFixed(1)}, priority interventions {vm.impact.championCandidate ? "all improved" : "not all improved"}.</p>}
    </Card>
  );
}

function Timeline({ vm }: { vm: CoreSchoolDetailVM }) {
  if (vm.timeline.length === 0) return <Card title="Timeline"><Empty>No lifecycle events yet.</Empty></Card>;
  return (
    <Card title="Lifecycle timeline">
      <ol className="relative border-l border-[var(--color-edify-border)] ml-1.5 space-y-3">
        {vm.timeline.map((e, i) => (
          <li key={i} className="ml-3.5">
            <span className="absolute -left-[5px] w-2.5 h-2.5 rounded-full bg-[var(--color-edify-primary)]" />
            <div className="text-[11.5px] font-bold">{e.label}</div>
            <div className="text-[10.5px] muted">{e.at}{e.detail ? ` · ${e.detail}` : ""}</div>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function StatusPill({ status }: { status: string }) {
  const done = status === "Completed";
  const blocked = status === "Returned" || status === "Rejected";
  return <span className={cn("inline-flex px-1.5 py-[2px] rounded text-[10px] font-bold",
    done ? "bg-emerald-100 text-emerald-700" : blocked ? "bg-rose-100 text-rose-700" : status === "Not Planned" ? "bg-slate-100 text-slate-600" : "bg-amber-100 text-amber-700")}>{status}</span>;
}

export function CoreDetailBackLink() {
  return <Link href="/core-schools" className="text-[11.5px] font-bold text-[var(--color-edify-primary)] hover:underline">← Core Schools</Link>;
}
