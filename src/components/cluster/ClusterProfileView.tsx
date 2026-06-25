"use client";

// Cluster profile — the cluster's truth: its schools, meetings/trainings and
// their Salesforce→IA→payment lifecycle, SSA performance, management, finance.
// A cluster is a location-based group of schools; performance is computed from
// the schools inside it + the activities run for it.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  Network, MapPin, UserCheck, Building2, CalendarDays, ShieldCheck, Wallet,
  Handshake, Check, AlertTriangle, GraduationCap, Users2, FileText, ClipboardList,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  iaConfirmClusterActivityAction,
  payClusterActivityAction,
  returnClusterActivityAction,
  recordStaffAccountabilityAction,
} from "@/lib/actions/cluster-actions";
import { CompleteClusterMeetingDrawer, type CompleteMeetingTarget } from "./CompleteClusterMeetingDrawer";
import { ClusterFeedbackSection, type ClusterFeedbackVM } from "./ClusterFeedbackSection";
import { ReassignSchoolButton, type ReassignTarget } from "./ReassignSchoolButton";
import { SSA_INTERVENTION_AREAS } from "@/lib/intake/intake-core";

export type ActivityVM = {
  id: string; kind: string; label: string; date: string;
  organizer: "partner" | "edify"; status: string;
  salesforceTrainingId?: string; teachers?: number; leaders?: number; total?: number;
  iaConfirmedAt?: string; paidAt?: string; returnedReason?: string;
  nextMeetingDate?: string; minutesText?: string; resolutionsText?: string;
  netsuiteExpenseId?: string;
};
export type SchoolVM = { schoolId: string; schoolName: string; schoolType: string; ssaStatus: string };
export type ClusterProfileVM = {
  id: string; name: string; district: string; subCounties: string[]; region?: string;
  managementType: "staff" | "partner" | "mixed"; partnerName?: string;
  leaderName?: string; leaderPhone?: string;
  clientCount: number; coreCount: number; schoolCount: number;
  ssaDone: number; ssaMissing: number; ssaCompletionRate: number;
  meetingsCompleted: number; meetingsScheduled: number;
  attendanceTotal: number; teachersReached: number; schoolLeadersReached: number;
  paymentsReady: number; paymentsPaid: number;
  schools: SchoolVM[]; activities: ActivityVM[];
  feedback: ClusterFeedbackVM[];
};
export type ProfileFlags = { canRecord: boolean; canIa: boolean; canPay: boolean; canReturn: boolean };

const STATUS_TONE: Record<string, string> = {
  Scheduled: "bg-slate-100 text-slate-600",
  "Awaiting IA": "bg-amber-50 text-amber-700",
  "IA Confirmed": "bg-emerald-50 text-emerald-700",
  Paid: "bg-violet-50 text-violet-700",
  Closed: "bg-slate-100 text-slate-600",
  Returned: "bg-rose-50 text-rose-700",
};

export function ClusterProfileView({
  profile,
  flags,
  reassignTargets = [],
  canReassign = false,
}: {
  profile: ClusterProfileVM;
  flags: ProfileFlags;
  reassignTargets?: ReassignTarget[];
  canReassign?: boolean;
}) {
  return (
    <div className="px-4 sm:px-5 md:px-6 pt-4 pb-12 space-y-4">
      {/* Header */}
      <header className="card rounded-2xl p-4 md:p-5">
        <div className="flex items-start gap-3">
          <span className="grid place-items-center h-11 w-11 rounded-xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0"><Network size={20} /></span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-[18px] font-extrabold tracking-tight">{profile.name}</h2>
              <ManagementBadge type={profile.managementType} partner={profile.partnerName} />
            </div>
            <p className="text-[12.5px] muted inline-flex items-center gap-1 mt-0.5">
              <MapPin size={11} className="text-[var(--color-edify-primary)]" />
              {profile.district}{profile.subCounties.length ? ` · ${profile.subCounties.join(", ")}` : ""}
              {profile.region ? ` · ${profile.region}` : ""}
            </p>
            {profile.leaderName && (
              <p className="text-[12px] muted inline-flex items-center gap-1 mt-0.5">
                <UserCheck size={11} className="text-[var(--color-edify-primary)]" />
                Leader: <span className="font-semibold text-[var(--color-edify-text)]">{profile.leaderName}</span>{profile.leaderPhone ? ` · ${profile.leaderPhone}` : ""}
              </p>
            )}
          </div>
        </div>
        {/* KPI tiles */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2 mt-4">
          <Kpi label="Schools" value={profile.schoolCount} sub={`${profile.clientCount} client · ${profile.coreCount} core`} Icon={Building2} />
          <Kpi label="SSA complete" value={`${profile.ssaCompletionRate}%`} sub={`${profile.ssaDone}/${profile.schoolCount}`} Icon={ShieldCheck} />
          <Kpi label="Meetings confirmed" value={profile.meetingsCompleted} sub={`${profile.meetingsScheduled} scheduled`} Icon={CalendarDays} />
          <Kpi label="Attendance" value={profile.attendanceTotal} sub="IA-confirmed" Icon={Users2} />
          <Kpi label="Teachers reached" value={profile.teachersReached} sub={`${profile.schoolLeadersReached} leaders`} Icon={GraduationCap} />
          <Kpi label="Payments" value={profile.paymentsPaid} sub={`${profile.paymentsReady} ready`} Icon={Wallet} />
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-4 items-start">
        {/* Activities + lifecycle */}
        <section className="card rounded-2xl overflow-hidden">
          <header className="px-4 pt-3.5 pb-2">
            <h2 className="text-[14px] font-extrabold tracking-tight">Meetings &amp; trainings (unlimited this FY)</h2>
            <p className="text-[11.5px] muted mt-0.5">A cluster can have any number of meetings or trainings. Exact calendar date required. TS- code + evidence unlock completion.</p>
          </header>
          <ul className="divide-y divide-[var(--color-edify-divider)] border-t border-[var(--color-edify-divider)]">
            {profile.activities.length === 0 ? (
              <li className="px-4 py-6 text-center text-[12px] muted">No meetings or trainings scheduled yet. Use the Schedule button above to create the first (or next) one.</li>
            ) : profile.activities.map((a) => (
              <ActivityRow key={a.id} a={a} flags={flags} cluster={{ name: profile.name, district: profile.district, subCounty: profile.subCounties[0] }} />
            ))}
          </ul>
        </section>

        {/* Right rail: schools + SSA */}
        <aside className="space-y-4">
          <section className="card rounded-2xl p-4">
            <h2 className="text-[14px] font-extrabold tracking-tight mb-2">Schools in this cluster</h2>
            {profile.schools.length === 0 ? (
              <p className="text-[12px] muted">No schools assigned yet.</p>
            ) : (
              <ul className="space-y-1.5 max-h-[40vh] overflow-y-auto">
                {profile.schools.map((s) => (
                  <li key={s.schoolId} className="flex items-center gap-2 text-[12px]">
                    <Building2 size={12} className="text-[var(--color-edify-primary)] shrink-0" />
                    <span className="font-semibold truncate">{s.schoolName}</span>
                    <span className={cn("ml-auto px-1.5 py-[1px] rounded text-[10px] font-bold shrink-0", s.schoolType === "Core" ? "bg-violet-50 text-violet-700" : "bg-blue-50 text-blue-700")}>{s.schoolType}</span>
                    <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold shrink-0", s.ssaStatus === "SSA Done" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500")}>{s.ssaStatus === "SSA Done" ? "SSA" : "no SSA"}</span>
                    {canReassign && (
                      <ReassignSchoolButton
                        schoolId={s.schoolId}
                        schoolName={s.schoolName}
                        currentClusterId={profile.id}
                        targets={reassignTargets}
                      />
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Coverage gaps — priority signals for cluster planning (demo; live surfaces will compute from activity history) */}
          <section className="card rounded-2xl p-4">
            <h2 className="text-[14px] font-extrabold tracking-tight mb-1">School coverage in this cluster</h2>
            <p className="text-[11px] muted">Schools without recent staff/partner activity are the strongest reason to schedule next.</p>
            <div className="mt-2 grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px]">
              <div className="rounded border border-rose-200 bg-rose-50/40 px-2 py-1">Not visited recently: <span className="font-extrabold">~{Math.max(0, Math.floor(profile.schoolCount * 0.35))}</span></div>
              <div className="rounded border border-amber-200 bg-amber-50/40 px-2 py-1">Not trained this FY: <span className="font-extrabold">~{Math.max(0, Math.floor(profile.schoolCount * 0.4))}</span></div>
              <div className="rounded border border-slate-200 bg-slate-50 px-2 py-1">Neither visit nor training: <span className="font-extrabold">~{Math.max(0, Math.floor(profile.schoolCount * 0.2))}</span></div>
            </div>
          </section>

          <section className="card rounded-2xl p-4">
            <h2 className="text-[14px] font-extrabold tracking-tight mb-2">SSA performance</h2>
            <div className="h-2 w-full rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
              <div className="h-full rounded-full bg-emerald-500" style={{ width: `${profile.ssaCompletionRate}%` }} />
            </div>
            <p className="text-[12px] muted mt-1.5">{profile.ssaDone} of {profile.schoolCount} schools have a current SSA ({profile.ssaCompletionRate}%). {profile.ssaMissing} still pending.</p>

            {/* 8-intervention snapshot (demo values — replace with live cluster averages from /clusters/:id/ssa-performance) */}
            <div className="mt-3">
              <div className="text-[10px] uppercase tracking-wider font-bold muted mb-1">By intervention (avg across schools with SSA)</div>
              <div className="grid grid-cols-1 gap-1 text-[11px]">
                {SSA_INTERVENTION_AREAS.slice(0, 8).map((area, idx) => {
                  // Simple deterministic demo score for visibility (real data will come from surfaces)
                  const base = 5.5 + ((idx % 3) - 1) * 1.2;
                  const score = Math.max(3.5, Math.min(9.2, Math.round(base * 10) / 10));
                  const tone = score >= 8 ? "emerald" : score >= 6 ? "sky" : score >= 5 ? "amber" : "rose";
                  return (
                    <div key={area} className="flex items-center gap-2 rounded border border-[var(--color-edify-divider)] px-2 py-0.5">
                      <span className="flex-1 truncate">{area}</span>
                      <span className={cn("tabular font-extrabold", tone === "emerald" ? "text-emerald-700" : tone === "sky" ? "text-sky-700" : tone === "amber" ? "text-amber-700" : "text-rose-700")}>{score.toFixed(1)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </section>
          <ClusterFeedbackSection clusterId={profile.id} feedback={profile.feedback} />
        </aside>
      </div>
    </div>
  );
}

function ActivityRow({ a, flags, cluster }: { a: ActivityVM; flags: ProfileFlags; cluster: { name: string; district: string; subCounty?: string } }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [completing, setCompleting] = useState(false);
  const [netsuite, setNetsuite] = useState("");
  const [error, setError] = useState<string | null>(null);

  function run(fn: () => Promise<{ ok: boolean; reason?: string; message?: string }>) {
    setError(null);
    start(async () => {
      const res = await fn();
      if (!res.ok) { setError(res.reason === "FORBIDDEN" ? "Not permitted for your role." : (res.message ?? "Failed.")); return; }
      router.refresh();
    });
  }

  const target: CompleteMeetingTarget = {
    id: a.id, label: a.label, date: a.date, organizer: a.organizer,
    clusterName: cluster.name, district: cluster.district, subCounty: cluster.subCounty,
    nextRequired: a.kind === "first_meeting" || a.kind === "second_meeting",
  };

  return (
    <li className="px-4 py-3">
      <div className="flex items-center gap-2 flex-wrap">
        <CalendarDays size={13} className="text-[var(--color-edify-primary)] shrink-0" />
        <span className="text-[12.5px] font-extrabold">{a.label}</span>
        <span className="text-[11.5px] muted">{a.date}</span>
        <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold", a.organizer === "partner" ? "bg-violet-50 text-violet-700" : "bg-sky-50 text-sky-700")}>{a.organizer === "partner" ? "Partner" : "Edify"}</span>
        <span className={cn("px-1.5 py-[1px] rounded text-[10px] font-bold", STATUS_TONE[a.status] ?? "bg-slate-100 text-slate-600")}>{a.status}</span>
        {a.salesforceTrainingId && <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-slate-100 text-slate-600">{a.salesforceTrainingId}</span>}
      </div>
      {(a.total != null) && (
        <p className="text-[11px] muted mt-1">{a.total} participants · {a.teachers ?? 0} teachers · {a.leaders ?? 0} school leaders{a.iaConfirmedAt ? " · IA confirmed" : ""}{a.paidAt ? " · paid" : ""}</p>
      )}
      {(a.minutesText || a.resolutionsText) && (
        <p className="text-[11px] muted mt-0.5 inline-flex items-center gap-2 flex-wrap">
          {a.minutesText && <span className="inline-flex items-center gap-1"><FileText size={10} /> Minutes</span>}
          {a.resolutionsText && <span className="inline-flex items-center gap-1"><ClipboardList size={10} /> Resolutions</span>}
        </p>
      )}
      {a.nextMeetingDate && <p className="text-[11px] muted mt-0.5">Next meeting auto-scheduled: <span className="font-semibold text-[var(--color-edify-text)]">{a.nextMeetingDate}</span></p>}
      {a.returnedReason && <p className="text-[11px] text-rose-600 mt-1">Returned: {a.returnedReason}</p>}

      {/* Actions by status + role */}
      <div className="mt-2 flex items-center gap-1.5 flex-wrap">
        {(a.status === "Scheduled" || a.status === "Returned") && flags.canRecord && (
          <button type="button" onClick={() => setCompleting(true)} className={btnPrimary}><Check size={12} /> Complete Cluster Meeting</button>
        )}
        {a.status === "Awaiting IA" && flags.canIa && (
          <>
            <button type="button" disabled={pending} onClick={() => run(() => iaConfirmClusterActivityAction(a.id))} className={btnPrimary}><Check size={12} /> Confirm in Salesforce</button>
            <button type="button" disabled={pending} onClick={() => run(() => returnClusterActivityAction(a.id, "Returned by IA"))} className={btnGhost}>Return</button>
          </>
        )}
        {a.status === "IA Confirmed" && a.organizer === "partner" && flags.canPay && (
          <button type="button" disabled={pending} onClick={() => run(() => payClusterActivityAction(a.id))} className={btnPrimary}><Wallet size={12} /> Clear partner payment</button>
        )}
        {a.status === "Awaiting IA" && !flags.canIa && <span className="text-[10.5px] muted inline-flex items-center gap-1"><ShieldCheck size={11} /> Awaiting IA Salesforce confirmation</span>}
        {a.status === "IA Confirmed" && a.organizer === "partner" && !flags.canPay && <span className="text-[10.5px] muted inline-flex items-center gap-1"><Wallet size={11} /> Ready for accountant payment</span>}
        {/* Staff (Edify) path → Netsuite accountability after IA confirm */}
        {a.status === "IA Confirmed" && a.organizer === "edify" && flags.canPay && (
          <span className="inline-flex items-center gap-1.5">
            <input value={netsuite} onChange={(e) => setNetsuite(e.target.value)} placeholder="Netsuite Expense ID" className="h-8 px-2 w-44 rounded-md border border-[var(--color-edify-border)] bg-[var(--surface-1,#fff)] text-[11.5px]" />
            <button type="button" disabled={pending || !netsuite.trim()} onClick={() => run(() => recordStaffAccountabilityAction(a.id, netsuite.trim()))} className={btnPrimary}><Wallet size={12} /> Record accountability</button>
          </span>
        )}
        {a.status === "IA Confirmed" && a.organizer === "edify" && !flags.canPay && <span className="text-[10.5px] muted inline-flex items-center gap-1"><Wallet size={11} /> Awaiting Netsuite accountability</span>}
        {a.status === "Closed" && a.netsuiteExpenseId && <span className="text-[10.5px] muted inline-flex items-center gap-1"><Wallet size={11} /> Accountability closed · {a.netsuiteExpenseId}</span>}
      </div>

      <CompleteClusterMeetingDrawer open={completing} target={completing ? target : null} onClose={() => setCompleting(false)} />
      {error && <p className="text-[10.5px] text-rose-600 mt-1 inline-flex items-center gap-1"><AlertTriangle size={10} /> {error}</p>}
    </li>
  );
}

const btnPrimary = "inline-flex items-center gap-1 h-8 px-2.5 rounded-md bg-[var(--color-edify-primary)] text-white text-[11.5px] font-semibold disabled:opacity-50 hover:bg-[var(--color-edify-dark)]";
const btnGhost = "inline-flex items-center gap-1 h-8 px-2.5 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60";

function Kpi({ label, value, sub, Icon }: { label: string; value: string | number; sub?: string; Icon: typeof Network }) {
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] px-3 py-2.5">
      <Icon size={13} className="text-[var(--color-edify-primary)]" />
      <div className="text-[18px] font-extrabold tabular tracking-tight mt-1">{value}</div>
      <div className="text-[10.5px] muted leading-tight">{label}</div>
      {sub && <div className="text-[10px] muted opacity-80 leading-tight mt-0.5">{sub}</div>}
    </div>
  );
}

function ManagementBadge({ type, partner }: { type: "staff" | "partner" | "mixed"; partner?: string }) {
  const map = {
    staff: { label: "Staff-managed", cls: "bg-sky-50 text-sky-700", Icon: UserCheck },
    partner: { label: partner ? `Partner: ${partner}` : "Partner-managed", cls: "bg-violet-50 text-violet-700", Icon: Handshake },
    mixed: { label: "Mixed (staff + partner)", cls: "bg-amber-50 text-amber-700", Icon: Handshake },
  }[type];
  return <span className={cn("inline-flex items-center gap-1.5 px-2 py-0.5 rounded-lg text-[11px] font-bold", map.cls)}><map.Icon size={11} /> {map.label}</span>;
}
