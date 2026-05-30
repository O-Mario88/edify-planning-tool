"use client";

// Program Lead Weekly Field Report — full executive renderer.
//
// Adds, over the v1 renderer:
//   • Sticky table of contents (lg+) — scannable jumps for time-poor CDs.
//   • Executive view toggle that collapses non-decision sections.
//   • Inline "Raw vs Context-Adjusted" explainer so the two numbers are
//     never read without their meaning.
//   • Per-line "Create decision action" affordance in Section 11; new
//     decisions are appended to a client-side queue (localStorage) and
//     surface on the CD dashboard / /decisions queue on next render.
//   • Audit trail section at the bottom (Section 13).
//
// Status guard remains client-side cosmetic — server enforcement lands
// when the backend exists. The PL Editor (separate page) is where status
// transitions actually fire.

import { useEffect, useMemo, useState } from "react";
import {
  FileText,
  Download,
  CheckCircle2,
  AlertTriangle,
  Sparkles,
  Users,
  Building2,
  Lightbulb,
  ListChecks,
  ClipboardCheck,
  Calendar,
  Lock,
  Info,
  Plus,
  History,
  Maximize2,
  Minimize2,
  type LucideIcon,
} from "lucide-react";
import type {
  ProgramLeadWeeklyFieldReport,
  DecisionAction,
  DecisionOwnerRole,
  ReportEvent,
} from "@/lib/field-intelligence-mock";
import { DECISION_ROUTING, canRouteDecision } from "@/lib/field-intelligence-mock";
import { prettyRole } from "@/components/decisions/DecisionActionsCard";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<string, string> = {
  "Generated":                  "bg-slate-100   text-slate-700",
  "PL Editing":                 "bg-amber-100   text-amber-700",
  "Submitted to CD":            "bg-emerald-100 text-emerald-700",
  "Returned for Clarification": "bg-rose-100    text-rose-700",
  "Resubmitted":                "bg-violet-100  text-violet-700",
  "Reviewed by CD":             "bg-sky-100     text-sky-700",
  "Closed":                     "bg-slate-100   text-slate-500",
};

const SECTIONS = [
  { id: "exec",        label: "Executive summary",           always: true },
  { id: "activity",    label: "Team activity",               always: false },
  { id: "submission",  label: "Debrief submission",          always: false },
  { id: "well",        label: "What went well",              always: false },
  { id: "notwell",     label: "What did not go well",        always: false },
  { id: "barriers",    label: "Main barriers",               always: true },
  { id: "support",     label: "Staff support needs",         always: false },
  { id: "schools",     label: "Schools needing attention",   always: false },
  { id: "narrative",   label: "PL weekly debrief",           always: false },
  { id: "insights",    label: "System-generated insights",   always: false },
  { id: "decisions",   label: "Decisions required from CD",  always: true },
  { id: "next",        label: "Next week action plan",       always: false },
  { id: "audit",       label: "Audit trail",                 always: false },
] as const;

type SectionId = typeof SECTIONS[number]["id"];

export function ProgramLeadWeeklyReportRenderer({
  r,
  initialEvents = [],
  viewerRole,
  viewerName,
}: {
  r:              ProgramLeadWeeklyFieldReport;
  initialEvents?: ReportEvent[];
  viewerRole:     "CountryDirector" | "Admin" | "ProgramLead" | "RVP" | string;
  viewerName:     string;
}) {
  const isLocked = r.status === "Submitted to CD" || r.status === "Reviewed by CD" || r.status === "Closed";
  const canCreateDecision = viewerRole === "CountryDirector" || viewerRole === "Admin";

  const [exec, setExec] = useState(false);
  const visibleSectionIds = useMemo<Set<SectionId>>(
    () => new Set(exec ? SECTIONS.filter((s) => s.always).map((s) => s.id) : SECTIONS.map((s) => s.id)),
    [exec],
  );

  return (
    <article className="grid grid-cols-12 gap-4 items-start">
      {/* TOC sidebar */}
      <aside className="hidden lg:block col-span-3 lg:sticky lg:top-4 space-y-2">
        <div className="card rounded-2xl p-3">
          <div className="text-caption muted font-bold uppercase tracking-wide mb-2">In this report</div>
          <ul className="space-y-0.5">
            {SECTIONS.filter((s) => visibleSectionIds.has(s.id)).map((s) => (
              <li key={s.id}>
                <a
                  href={`#section-${s.id}`}
                  className="block text-[11.5px] font-extrabold py-1 px-2 rounded-md hover:bg-[var(--color-edify-soft)]/40 truncate"
                >
                  {s.label}
                </a>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => setExec((v) => !v)}
            className={cn(
              "mt-2 w-full h-9 rounded-xl text-[11.5px] font-extrabold inline-flex items-center justify-center gap-1.5",
              exec
                ? "bg-[var(--color-edify-primary)] text-white"
                : "border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/40",
            )}
          >
            {exec ? <><Maximize2 size={12} /> Full view</> : <><Minimize2 size={12} /> Executive view</>}
          </button>
          <p className="text-[10px] muted leading-snug mt-2">
            Executive view keeps only Executive summary, Main barriers, and Decisions required.
          </p>
        </div>
      </aside>

      <div className="col-span-12 lg:col-span-9 space-y-4">
        {/* Header */}
        <header className="card p-3.5 space-y-3">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="min-w-0 flex-1">
              <div className="text-[11px] muted font-bold uppercase tracking-wider">Program Lead Weekly Field Report</div>
              <h1 className="text-[22px] sm:text-[26px] font-extrabold tracking-tight mt-0.5">{r.programLeadName}</h1>
              <div className="text-body muted mt-0.5">
                {r.team} · {r.region} · {r.weekLabel} · FY {r.financialYearId}
                {r.submittedAt && <span> · Submitted {r.submittedAt}</span>}
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className={cn("inline-flex items-center px-2.5 py-[3px] rounded-md text-[11px] font-extrabold whitespace-nowrap", STATUS_TONE[r.status])}>
                {r.status}
              </span>
              {isLocked && (
                <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-caption font-extrabold bg-slate-100 text-slate-600 whitespace-nowrap">
                  <Lock size={10} />
                  Locked
                </span>
              )}
              <a
                href={r.downloadablePdfUrl ?? "#"}
                className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white inline-flex items-center gap-1.5 text-[12px] font-extrabold hover:bg-[var(--color-edify-soft)]/40"
              >
                <Download size={13} /> Download PDF
              </a>
              {viewerRole === "CountryDirector" || viewerRole === "Admin" ? (
                <ReturnForClarificationButton
                  reportId={r.id}
                  currentStatus={r.status}
                />
              ) : null}
            </div>
          </div>
        </header>

        {visibleSectionIds.has("exec") && (
          <Section id="exec" Icon={FileText} title="Executive summary">
            <p className="text-[13px] leading-relaxed">
              This Week, the team planned <Strong>{r.totalPlannedActivities}</Strong> activities and completed{" "}
              <Strong>{r.totalCompletedActivities}</Strong>. Verified completion stands at{" "}
              <Strong>{r.totalVerifiedActivities}</Strong>. Raw achievement is{" "}
              <Strong>{r.rawAchievementPercent}%</Strong>, context-adjusted achievement is{" "}
              <Strong className="text-emerald-700">{r.contextAdjustedAchievementPercent}%</Strong>.
              {r.decisionsRequiredFromCD.length > 0 && (
                <> <Strong className="text-rose-700">{r.decisionsRequiredFromCD.length}</Strong> decision{r.decisionsRequiredFromCD.length === 1 ? "" : "s"} required from the Country Director — see section 11.</>
              )}
            </p>
            <RawVsAdjustedExplainer raw={r.rawAchievementPercent} adjusted={r.contextAdjustedAchievementPercent} />
          </Section>
        )}

        {visibleSectionIds.has("activity") && (
          <Section id="activity" Icon={ListChecks} title="Team activity">
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
              <Stat label="Planned"            value={r.totalPlannedActivities} />
              <Stat label="Completed"          value={r.totalCompletedActivities} tone="green" />
              <Stat label="Verified"           value={r.totalVerifiedActivities}  tone="green" />
              <Stat label="Salesforce pending" value={r.salesforcePendingCount}   tone="amber" />
              <Stat label="Returned"           value={r.returnedRecordCount}      tone={r.returnedRecordCount > 0 ? "rose" : "edify"} />
              <Stat label="Overdue"            value={r.overdueActivitiesCount}   tone={r.overdueActivitiesCount > 5 ? "rose" : "amber"} />
            </div>
          </Section>
        )}

        {visibleSectionIds.has("submission") && (
          <Section id="submission" Icon={ClipboardCheck} title="Debrief submission">
            <div className="flex items-baseline justify-between gap-2 flex-wrap">
              <p className="text-[13px] leading-relaxed">
                <Strong>{r.submittedDebriefs}/{r.expectedDebriefs}</Strong> debriefs submitted ({r.debriefSubmissionRate}%) across <Strong>{r.cceoCount}</Strong> CCEO{r.cceoCount === 1 ? "" : "s"}.
              </p>
              <div className="w-full sm:w-[200px]">
                <div className="h-2 rounded-full bg-[#eef2f4] overflow-hidden">
                  <div
                    className={cn("h-full rounded-full",
                      r.debriefSubmissionRate >= 90 ? "bg-emerald-500"
                    : r.debriefSubmissionRate >= 75 ? "bg-amber-500"
                    :                                  "bg-rose-500"
                    )}
                    style={{ width: `${r.debriefSubmissionRate}%` }}
                  />
                </div>
              </div>
            </div>
            {r.debriefSubmissionRate < 90 && (
              <p className="text-[11px] text-amber-800 leading-snug mt-2">
                Submission rate below 90% — Program Lead should chase missing debriefs before next cycle.
              </p>
            )}
          </Section>
        )}

        {visibleSectionIds.has("well") && (
          <Section id="well" Icon={CheckCircle2} title="What went well" tone="green">
            <ul className="space-y-1 text-[13px] leading-relaxed">
              {r.topSuccesses.map((s, i) => <li key={i}>· {s}</li>)}
            </ul>
          </Section>
        )}

        {visibleSectionIds.has("notwell") && (
          <Section id="notwell" Icon={AlertTriangle} title="What did not go well" tone="amber">
            <p className="text-[13px] leading-relaxed">{r.programLeadWeeklyDebrief.whatDidNotGoWell}</p>
          </Section>
        )}

        {visibleSectionIds.has("barriers") && (
          <Section id="barriers" Icon={AlertTriangle} title="Main barriers this week">
            <ul className="space-y-2">
              {r.topBarriers.map((b, i) => (
                <li key={i} className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3">
                  <div className="flex items-baseline justify-between gap-2 flex-wrap">
                    <span className="text-[13px] font-extrabold tracking-tight">{b.category}</span>
                    <span className="text-caption muted">{b.count} occurrence{b.count === 1 ? "" : "s"}</span>
                  </div>
                  <p className="text-[12px] leading-snug muted mt-1">{b.recommendedAction}</p>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {visibleSectionIds.has("support") && (
          <Section id="support" Icon={Users} title="Staff support needs">
            <ul className="space-y-2">
              {r.staffSupportNeeds.map((s, i) => (
                <li key={i} className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3">
                  <div className="flex items-baseline justify-between gap-2 flex-wrap">
                    <span className="text-[13px] font-extrabold tracking-tight">{s.cceoName}</span>
                    {s.decisionNeeded && (
                      <span className="text-[10px] font-extrabold uppercase tracking-wide text-rose-700">Decision needed</span>
                    )}
                  </div>
                  <p className="text-[12px] leading-snug mt-0.5"><span className="muted">Issue:</span> <span className="font-extrabold">{s.issue}</span></p>
                  <p className="text-[12px] leading-snug"><span className="muted">PL action taken:</span> {s.action}</p>
                  {s.decisionNeeded && (
                    <p className="text-[12px] leading-snug mt-1 text-rose-800"><span className="font-extrabold">Decision needed:</span> {s.decisionNeeded}</p>
                  )}
                </li>
              ))}
            </ul>
            <p className="text-caption muted leading-snug pt-2 border-t border-[var(--color-edify-border)]">
              CD acts on staff support via the Program Lead — decisions assigned here always route to PL / IA / Program Accountant / Special Project Coordinator.
            </p>
          </Section>
        )}

        {visibleSectionIds.has("schools") && (
          <Section id="schools" Icon={Building2} title="Schools / clusters needing attention">
            <div className="overflow-x-auto -mx-2 px-2">
              <table className="w-full text-body min-w-[600px]">
                <thead>
                  <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                    <th scope="col" className="py-2 pr-2">School / cluster</th>
                    <th scope="col" className="py-2 px-2">Reason</th>
                    <th scope="col" className="py-2 px-2">Next step</th>
                    <th scope="col" className="py-2 pl-2">Owner</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-edify-border)]">
                  {r.schoolsNeedingFollowUp.map((s, i) => (
                    <tr key={i}>
                      <td className="py-2 pr-2 font-extrabold tracking-tight">{s.school}</td>
                      <td className="py-2 px-2 muted">{s.reason}</td>
                      <td className="py-2 px-2">{s.nextStep}</td>
                      <td className="py-2 pl-2 muted">{s.owner}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {visibleSectionIds.has("narrative") && (
          <Section id="narrative" Icon={FileText} title="Program Lead weekly debrief">
            <div className="space-y-2 text-[13px] leading-relaxed">
              <Narrative label="What went well"            body={r.programLeadWeeklyDebrief.whatWentWell} />
              <Narrative label="What did not go well"      body={r.programLeadWeeklyDebrief.whatDidNotGoWell} />
              <Narrative label="Team support provided"     body={r.programLeadWeeklyDebrief.teamSupportProvided} />
              <Narrative label="Decisions needed from CD"  body={r.programLeadWeeklyDebrief.decisionsNeededFromCD} />
              <Narrative label="Next week priorities"      body={r.programLeadWeeklyDebrief.nextWeekPriorities} />
            </div>
          </Section>
        )}

        {visibleSectionIds.has("insights") && (
          <Section id="insights" Icon={Lightbulb} title="System-generated insights">
            <ul className="space-y-1 text-[13px] leading-relaxed">
              {r.systemGeneratedInsights.map((s, i) => <li key={i}>· {s}</li>)}
            </ul>
          </Section>
        )}

        {visibleSectionIds.has("decisions") && (
          <Section id="decisions" Icon={Sparkles} title="Decisions required from the Country Director" tone="rose">
            {r.decisionsRequiredFromCD.length === 0 ? (
              <p className="text-body muted">No decisions required this week.</p>
            ) : (
              <ul className="space-y-3">
                {r.decisionsRequiredFromCD.map((d, i) => (
                  <DecisionLine
                    key={i}
                    line={d}
                    sourceReportId={r.id}
                    canCreate={canCreateDecision}
                    creatorRole={viewerRole === "CountryDirector" || viewerRole === "Admin" ? "CountryDirector" : "ProgramLead"}
                    creatorName={viewerName}
                  />
                ))}
              </ul>
            )}
          </Section>
        )}

        {visibleSectionIds.has("next") && (
          <Section id="next" Icon={Calendar} title="Next week action plan">
            <ul className="space-y-1 text-[13px] leading-relaxed">
              {r.nextWeekPriorities.map((p, i) => <li key={i}>· {p}</li>)}
            </ul>
          </Section>
        )}

        {visibleSectionIds.has("audit") && initialEvents.length > 0 && (
          <Section id="audit" Icon={History} title="Audit trail">
            <ul className="space-y-1">
              {initialEvents.map((e, i) => (
                <li key={i} className="text-[12px] leading-snug flex items-baseline gap-2">
                  <span className="font-mono tabular text-caption muted whitespace-nowrap">{e.at}</span>
                  <span className="font-extrabold">{e.byName}</span>
                  <span className="muted">({e.byRole})</span>
                  <span>· {e.kind}</span>
                  {e.detail && <span className="muted truncate">— {e.detail}</span>}
                </li>
              ))}
            </ul>
          </Section>
        )}
      </div>
    </article>
  );
}

// ────────── Decision creation (inline) ──────────

function DecisionLine({
  line, sourceReportId, canCreate, creatorRole, creatorName,
}: {
  line: string;
  sourceReportId: string;
  canCreate: boolean;
  creatorRole: "CountryDirector" | "ProgramLead";
  creatorName: string;
}) {
  const [open, setOpen]           = useState(false);
  const [created, setCreated]     = useState(false);
  const [assigneeRole, setRole]   = useState<DecisionOwnerRole>(DECISION_ROUTING[creatorRole][0]);
  const [assigneeName, setName]   = useState("");
  const [priority, setPriority]   = useState<"Low" | "Medium" | "High" | "Critical">("High");
  const [deadline, setDeadline]   = useState("");

  // Default deadline = today + 7 days. Migrate to a lazy initial
  // useState during the React-19 sweep — left as effect-driven to keep
  // SSR snapshot deterministic.
  useEffect(() => {
    if (deadline) return;
    const d = new Date("2025-05-12"); d.setDate(d.getDate() + 7);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDeadline(d.toISOString().slice(0, 10));
  }, [deadline]);

  function submit() {
    if (!canCreate || !assigneeName.trim()) return;
    if (!canRouteDecision(creatorRole, assigneeRole)) return;
    const newAction: DecisionAction = {
      id:              `DA-LOCAL-${Date.now()}`,
      title:           line,
      description:     `Created from ${sourceReportId} by ${creatorName}.`,
      createdAt:       new Date().toISOString().replace("T", " ").slice(0, 16),
      createdByRole:   creatorRole,
      createdByName:   creatorName,
      sourceReportId,
      sourceLine:      line,
      assigneeRole,
      assigneeName:    assigneeName.trim(),
      deadline,
      priority,
      status:          "Pending",
      history:         [{ at: new Date().toISOString().replace("T", " ").slice(0, 16), byRole: creatorRole, byName: creatorName, event: `Decision created from ${sourceReportId}` }],
    };
    try {
      const raw  = localStorage.getItem("decisionActions.local") ?? "[]";
      const list = JSON.parse(raw) as DecisionAction[];
      list.unshift(newAction);
      localStorage.setItem("decisionActions.local", JSON.stringify(list));
    } catch {/* ignore */}
    setCreated(true);
    setOpen(false);
  }

  return (
    <li className="rounded-xl border border-rose-200 bg-rose-50/60 p-3 space-y-2">
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <p className="text-[13px] leading-relaxed text-rose-900 font-extrabold min-w-0 flex-1">{line}</p>
        {canCreate && !created && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="h-8 px-2.5 rounded-md bg-[var(--color-edify-primary)] text-white text-[11.5px] font-extrabold inline-flex items-center gap-1.5 whitespace-nowrap hover:brightness-110"
          >
            <Plus size={11} />
            Create decision action
          </button>
        )}
        {created && (
          <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-caption font-extrabold bg-emerald-100 text-emerald-700">
            <CheckCircle2 size={11} /> Action created
          </span>
        )}
      </div>

      {open && !created && (
        <div className="rounded-lg bg-white border border-[var(--color-edify-border)] p-3 grid grid-cols-1 md:grid-cols-2 gap-2 text-[11.5px]">
          <Field label="Assign to role">
            <select
              aria-label="Assignee role"
              value={assigneeRole}
              onChange={(e) => setRole(e.target.value as DecisionOwnerRole)}
              className="w-full h-9 rounded-md border border-[var(--color-edify-border)] bg-white px-2 font-semibold"
            >
              {DECISION_ROUTING[creatorRole].map((role) => (
                <option key={role} value={role}>{prettyRole(role)}</option>
              ))}
            </select>
          </Field>
          <Field label="Assignee name">
            <input
              aria-label="Assignee name"
              value={assigneeName}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Daniel Mwangi"
              className="w-full h-9 rounded-md border border-[var(--color-edify-border)] bg-white px-2 font-semibold"
            />
          </Field>
          <Field label="Priority">
            <select
              aria-label="Priority"
              value={priority}
              onChange={(e) => setPriority(e.target.value as "Low" | "Medium" | "High" | "Critical")}
              className="w-full h-9 rounded-md border border-[var(--color-edify-border)] bg-white px-2 font-semibold"
            >
              {(["Critical", "High", "Medium", "Low"] as const).map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </Field>
          <Field label="Deadline">
            <input
              type="date"
              aria-label="Deadline"
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
              className="w-full h-9 rounded-md border border-[var(--color-edify-border)] bg-white px-2 font-semibold"
            />
          </Field>
          <div className="md:col-span-2 flex items-center gap-2">
            <button
              type="button"
              onClick={submit}
              disabled={!assigneeName.trim()}
              className={cn(
                "h-9 px-3 rounded-md text-[12px] font-extrabold",
                assigneeName.trim()
                  ? "bg-emerald-500 hover:bg-emerald-600 text-white"
                  : "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] cursor-not-allowed",
              )}
            >
              Save decision
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="h-9 px-3 rounded-md text-[12px] font-extrabold border border-[var(--color-edify-border)] bg-white"
            >
              Cancel
            </button>
            <span className="text-caption muted ml-auto">
              Routing constraint: {creatorRole === "CountryDirector"
                ? "CD → Program Lead / Impact Assessment / Program Accountant / Special Project Coordinator (never directly to CCEOs)."
                : "PL → Program Lead / IA / Program Accountant."}
            </span>
          </div>
        </div>
      )}
    </li>
  );
}

function ReturnForClarificationButton({ reportId, currentStatus }: { reportId: string; currentStatus: string }) {
  const [open, setOpen]   = useState(false);
  const [note, setNote]   = useState("");
  const [sent, setSent]   = useState(false);
  const canReturn = currentStatus === "Submitted to CD" || currentStatus === "Resubmitted";

  if (!canReturn && !sent) {
    return (
      <button
        type="button"
        disabled
        className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] inline-flex items-center gap-1.5 text-[12px] font-extrabold cursor-not-allowed"
        title="Return is only available on submitted / resubmitted reports"
      >
        <AlertTriangle size={13} /> Return for clarification
      </button>
    );
  }
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={sent}
        className={cn(
          "h-9 px-3 rounded-xl inline-flex items-center gap-1.5 text-[12px] font-extrabold",
          sent
            ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] cursor-not-allowed"
            : "border border-rose-200 bg-white text-rose-700 hover:bg-rose-50",
        )}
      >
        <AlertTriangle size={13} />
        {sent ? "Returned" : "Return for clarification"}
      </button>
      {open && !sent && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4" role="dialog" aria-modal>
          <div className="card p-3.5 max-w-md w-full space-y-3">
            <h3 className="text-[15px] font-extrabold tracking-tight">Return for clarification</h3>
            <p className="text-[12px] muted leading-snug">
              The Program Lead will be notified. Status will flip to <span className="font-extrabold">Returned for Clarification</span>. They can resubmit after addressing your note.
            </p>
            <textarea
              aria-label="Clarification note to Program Lead"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={4}
              placeholder="What specifically needs clarification?"
              className="w-full rounded-xl border border-[var(--color-edify-border)] bg-white p-3 text-[12px] leading-snug focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-[12px] font-extrabold"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!note.trim()}
                onClick={() => {
                  try {
                    const raw  = localStorage.getItem(`report.${reportId}.events`) ?? "[]";
                    const list = JSON.parse(raw) as ReportEvent[];
                    list.push({
                      at:    new Date().toISOString().replace("T", " ").slice(0, 16),
                      byRole:"CountryDirector",
                      byName:"Sarah Okello",
                      kind:  "CD Returned for Clarification",
                      detail: note.trim(),
                    });
                    localStorage.setItem(`report.${reportId}.events`, JSON.stringify(list));
                  } catch {/* ignore */}
                  setSent(true);
                  setOpen(false);
                }}
                className={cn(
                  "h-9 px-3 rounded-xl text-[12px] font-extrabold",
                  note.trim()
                    ? "bg-rose-500 hover:bg-rose-600 text-white"
                    : "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] cursor-not-allowed",
                )}
              >
                Return with note
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ────────── Pieces ──────────

function Section({ id, Icon, title, tone, children }: { id: SectionId; Icon: LucideIcon; title: string; tone?: "green" | "amber" | "rose"; children: React.ReactNode }) {
  const toneClass =
    tone === "green" ? "border-emerald-200 bg-emerald-50/40" :
    tone === "amber" ? "border-amber-200   bg-amber-50/40"   :
    tone === "rose"  ? "border-rose-200    bg-rose-50/40"    :
                       "";
  return (
    <section id={`section-${id}`} className={cn("card p-3.5 space-y-2 scroll-mt-4", toneClass)}>
      <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
        <Icon size={14} className="text-[var(--color-edify-primary)]" />
        {title}
      </h2>
      <div>{children}</div>
    </section>
  );
}

function Strong({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("font-extrabold text-[var(--color-edify-text)] tabular", className)}>{children}</span>;
}

function Narrative({ label, body }: { label: string; body: string }) {
  return (
    <div className="rounded-lg bg-[var(--color-edify-soft)]/30 border border-[var(--color-edify-border)] p-3">
      <div className="text-[10px] font-bold uppercase tracking-wide muted">{label}</div>
      <p className="mt-0.5">{body || <span className="muted italic">(not provided)</span>}</p>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "edify" | "green" | "amber" | "rose" }) {
  const tones = {
    edify:  "bg-[var(--color-edify-soft)]/40 border-[var(--color-edify-border)]",
    green:  "bg-emerald-50 border-emerald-200",
    amber:  "bg-amber-50   border-amber-200",
    rose:   "bg-rose-50    border-rose-200",
  } as const;
  return (
    <div className={cn("rounded-xl border px-3 py-2", tones[tone ?? "edify"])}>
      <div className="text-[10px] muted font-bold uppercase tracking-wide truncate">{label}</div>
      <div className="text-[18px] font-extrabold tabular leading-tight">{value}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[10px] muted font-bold uppercase tracking-wide">{label}</span>
      <div className="mt-0.5">{children}</div>
    </label>
  );
}

function RawVsAdjustedExplainer({ raw, adjusted }: { raw: number; adjusted: number }) {
  const delta = adjusted - raw;
  return (
    <div className="mt-3 rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/30 p-3 flex items-start gap-2">
      <Info size={12} className="text-[var(--color-edify-primary)] mt-0.5 shrink-0" />
      <div className="text-[11.5px] leading-snug">
        <span className="font-extrabold">Raw {raw}% vs Context-Adjusted {adjusted}%.</span>
        <span className="muted"> Raw counts every planned activity that was not verified. Context-adjusted excludes protected field constraints (school closures, public holidays, weather, road conditions, emergency assignments).
        {delta > 0 ? <> The {delta}-point gap is the share of &ldquo;missed&rdquo; activities explained by field reality, not staff inaction.</> : null}</span>
      </div>
    </div>
  );
}
