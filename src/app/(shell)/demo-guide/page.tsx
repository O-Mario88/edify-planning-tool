import Link from "next/link";
import {
  PlayCircle,
  ChevronRight,
  Sparkles,
  Briefcase,
  Users,
  Globe,
  Wallet,
  ShieldCheck,
  Heart,
  UserCog,
  CalendarRange,
  Upload,
  Brain,
  type LucideIcon,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { cn } from "@/lib/utils";

// Demo Guide — internal walkthrough script for sales/founder demos. Each
// scenario lists the role to switch to, the page to open, and the
// "what to say / what to click" beats.

type Step = {
  say:    string;
  open?:  { label: string; href: string };
  click?: string;
  expect:string;
};

type Scenario = {
  id:       string;
  title:    string;
  blurb:    string;
  role:     string;
  roleIcon: LucideIcon;
  tone:     "edify" | "amber" | "green" | "rose" | "violet" | "sky" | "slate";
  steps:    Step[];
};

const SCENARIOS: Scenario[] = [
  {
    id: "fy-opening",
    title: "Scenario 1 — New Financial Year Opening",
    blurb: "Edify starts FY 2025/26 cleanly. Previous year locked, history preserved. Country Director can see whether the org is ready.",
    role: "Country Director (Sarah Okello)",
    roleIcon: Globe,
    tone: "violet",
    steps: [
      { say: "Every October 1, Edify rolls into a new financial year. Previous data is locked, not deleted.", open: { label: "Annual Operating Cycle", href: "/fy" }, expect: "FY 2024/25 Locked · FY 2025/26 Active · FY 2026/27 Draft" },
      { say: "Before we open the next year, the system checks if we're ready.",                            open: { label: "FY Readiness Center", href: "/fy/readiness" }, expect: "13 traffic-light checks. Critical items flagged." },
      { say: "Every school enters Improvement Training first, then SSA becomes due.",                       open: { label: "Improvement Gateway", href: "/fy/gateway" }, expect: "Gateway distribution + planning lock levels per school" },
      { say: "And we can already see year-on-year SSA performance — by district, cluster, and all 8 interventions.", open: { label: "Yearly SSA Comparison", href: "/fy/ssa-comparison" }, expect: "10 districts compared with insights at the top" },
    ],
  },
  {
    id: "monthly-plan",
    title: "Scenario 2 — Staff Submits a Monthly Plan",
    blurb: "Staff don't guess the budget. The system calculates it from approved planned activities × Country Cost Settings.",
    role: "Country Program Lead (Daniel Mwangi)",
    roleIcon: Users,
    tone: "amber",
    steps: [
      { say: "Field staff schedule monthly activities. The system pulls the unit cost from active Country Cost Settings.", open: { label: "Cost Settings", href: "/cost-settings" }, expect: "Country Director controls every unit cost" },
      { say: "Once submitted, the Program Lead sees the proposed plan + budget.",                          open: { label: "Open a submission", href: "/budget/approvals/mp-006" }, expect: "Submitted to Program Lead — PL can approve or return" },
      { say: "PL approves only the plan + proposed budget. PL never final-approves funds.",                click: "Try the Approve button — see the toast + audit append", expect: "Status moves to Approved by Program Lead. Audit entry is timestamped." },
    ],
  },
  {
    id: "funding-gap",
    title: "Scenario 3 — Funding Gap Detected",
    blurb: "The CD's screen reads like a control center. Requested vs available is reconciled with prioritisation copy.",
    role: "Country Director (Sarah Okello)",
    roleIcon: Globe,
    tone: "rose",
    steps: [
      { say: "When PL submissions land, the CD sees them all with funding gap detection.",                 open: { label: "Approvals", href: "/approvals" }, expect: "Country Director fund approvals view: header, KPI row, queue, plan detail, summary, budget mix." },
      { say: "If requested exceeds available, the system recommends prioritisation order.",                open: { label: "Funds Matching", href: "/budget/approvals/funds-matching" }, expect: "Per-PL matching with recommended prioritisation copy" },
      { say: "And before the CD amends, the system previews what will be protected, deferred, and risked.", open: { label: "Open a gap submission", href: "/budget/approvals/mp-002" }, expect: "Decision Impact Preview panel" },
    ],
  },
  {
    id: "cd-amend",
    title: "Scenario 4 — CD Amends the Budget",
    blurb: "Original budget is preserved permanently. Every amendment is append-only with reason + role + timestamp.",
    role: "Country Director (Sarah Okello)",
    roleIcon: Globe,
    tone: "amber",
    steps: [
      { say: "Open a submission that needs amendment — the original budget is shown strike-through.",      open: { label: "Submission detail", href: "/budget/approvals/mp-005" }, expect: "Strike-through requested + amber amended amount" },
      { say: "Click Amend budget. The modal asks for the new amount + reason + comment.",                   click: "Amend budget → enter reason → Save", expect: "New status: Amended by Country Director. Toast confirms. Audit gets a new entry." },
      { say: "Every amendment ever made is also rolled up by region and reason.",                          open: { label: "All amendments", href: "/budget/approvals/amendments" }, expect: "Aggregated metrics: total reduced, top reason, regions most amended" },
    ],
  },
  {
    id: "rvp-final",
    title: "Scenario 5 — RVP Final Approval",
    blurb: "RVP is the final gate. With full context — amendments, accountant note, decision impact — not blind trust.",
    role: "Regional VP (Esther Wanjiru)",
    roleIcon: Sparkles,
    tone: "violet",
    steps: [
      { say: "Switch to RVP. The queue shows CD-approved submissions awaiting final sign-off.",            open: { label: "RVP Queue", href: "/budget/approvals/rvp-queue" }, expect: "Submissions in 'Submitted to RVP'" },
      { say: "Each submission carries the full governance package.",                                       open: { label: "Open one", href: "/budget/approvals/mp-002" }, expect: "Status bar · Available funds source · Why-this-priority · Accountant note · Audit trail" },
      { say: "Final approve and the Funding Plan becomes active. Disbursement prep starts.",               click: "Final approve", expect: "Status: Final Approved. Active Funding Plans page now lists it." },
    ],
  },
  {
    id: "field-reality",
    title: "Scenario 6 — Field Reality Influences Next Week",
    blurb: "Daily debriefs aggregate into weekly leadership decisions. Staff aren't punished for problems they didn't cause.",
    role: "CCEO (Paul Chinyama)",
    roleIcon: Briefcase,
    tone: "edify",
    steps: [
      { say: "Field staff submit a Daily Field Debrief — 6 questions, under 2 minutes.",                   open: { label: "Daily Field Debrief", href: "/field-intelligence" }, expect: "Form + auto-saved indicator + classification engine" },
      { say: "By Friday, the system rolls debriefs into a Weekly Reflection + Leadership Decisions.",      open: { label: "Recent debriefs", href: "/debriefs" }, expect: "Per-debrief drill-in with barriers + outcomes" },
    ],
  },
  {
    id: "hr-fair-context",
    title: "Scenario 7 — HR Reviews Fair Performance Context",
    blurb: "Before any PIP, HR sees the support given and what's blocking the staff member. Performance is contextualised.",
    role: "Human Resource (Anne Wairimu)",
    roleIcon: Heart,
    tone: "rose",
    steps: [
      { say: "Open Team Targets. Raw achievement vs context-adjusted achievement is shown side-by-side.", open: { label: "Team Targets", href: "/team-targets" }, expect: "Pace status with humane support-review gate before any PIP" },
      { say: "Each staff page surfaces approved leave, route load, partner blocks, funding delay — explanatory context for any gap.", open: { label: "Open a staff member", href: "/staff/STF-PO-008" }, expect: "Engine flags + recommended support + Support Review status" },
    ],
  },
  {
    id: "data-governance",
    title: "Scenario 8 — Data Intake & Readiness",
    blurb: "The planning engine doesn't consume random uploads. Templates are system-generated; validation gates the data.",
    role: "Impact Assessment (Grace Alimo)",
    roleIcon: ShieldCheck,
    tone: "sky",
    steps: [
      { say: "Templates are system-generated. Users don't invent columns.",                                open: { label: "Template Builder", href: "/data-intake/templates" }, expect: "19 templates with required + optional columns + validation rules" },
      { say: "Each template downloads as a CSV with headers + an example row.",                            open: { label: "Open School Register", href: "/data-intake/templates/tpl-school-register" }, expect: "Schema, validation rules, downloadable CSV" },
      { say: "Uploads are validated, errors flagged, and only approved batches feed the planning engine.", open: { label: "Validation queue", href: "/data-intake/queue" }, expect: "Row counts: valid · errors · warnings per batch" },
      { say: "Readiness gates the FY opening + planning engine.",                                          open: { label: "Planning Readiness", href: "/data-intake/readiness" }, expect: "Blocked / Needs Attention / Ready verdict" },
    ],
  },
];

const TONE = {
  edify:  "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  amber:  "bg-amber-100   text-amber-700",
  green:  "bg-emerald-100 text-emerald-700",
  rose:   "bg-rose-100    text-rose-700",
  violet: "bg-violet-100  text-violet-700",
  sky:    "bg-sky-100     text-sky-700",
  slate:  "bg-slate-100   text-slate-700",
} as const;

export default function DemoGuidePage() {
  return (
    <StubPage
      title="Demo Guide"
      subtitle="8 scenarios that walk a client through the full operating model. Each scenario opens at a specific role, lists what to say and what to click, and tells you what the client should see."
    >
      <section className="card p-3.5 bg-[var(--color-edify-soft)]/40">
        <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
          <PlayCircle size={14} className="text-[var(--color-edify-primary)]" />
          Before you start
        </h2>
        <ul className="mt-2 text-[12px] space-y-1">
          <li>• Use the <span className="font-extrabold">Switch role</span> button (bottom-right) to hop between the 8 demo accounts instantly.</li>
          <li>• Any approve/return/amend action toasts and appends to the audit trail. Use <span className="font-extrabold">Reset demo state</span> on a submission to clear overlays.</li>
          <li>• Speak the value, not the screen: <em>&quot;the system recommends what to protect&quot;</em> &gt; <em>&quot;here is a table&quot;</em>.</li>
        </ul>
      </section>

      {SCENARIOS.map((sc) => (
        <article key={sc.id} className="card p-3.5">
          <header className="flex items-start gap-3 mb-3">
            <span className={cn("h-10 w-10 rounded-xl grid place-items-center shrink-0", TONE[sc.tone])}>
              <sc.roleIcon size={16} />
            </span>
            <div className="flex-1 min-w-0">
              <h2 className="text-[15px] font-extrabold tracking-tight">{sc.title}</h2>
              <div className="text-caption font-extrabold uppercase tracking-wide muted mt-0.5">{sc.role}</div>
              <p className="text-[11.5px] muted leading-snug mt-1">{sc.blurb}</p>
            </div>
          </header>

          <ol className="space-y-2 ml-4">
            {sc.steps.map((step, i) => (
              <li key={i} className="relative">
                <span className="absolute -left-4 top-1 w-3 h-3 rounded-full bg-[var(--color-edify-primary)] text-white text-[8px] font-extrabold grid place-items-center">{i + 1}</span>
                <div className="text-body leading-snug">
                  <span className="font-extrabold">Say: </span>
                  <span>&ldquo;{step.say}&rdquo;</span>
                </div>
                {step.open && (
                  <div className="mt-1">
                    <Link
                      href={step.open.href}
                      className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline"
                    >
                      Open: {step.open.label}
                      <ChevronRight size={11} />
                    </Link>
                  </div>
                )}
                {step.click && (
                  <div className="mt-0.5 text-[11.5px]">
                    <span className="font-extrabold">Click: </span>
                    <span className="muted">{step.click}</span>
                  </div>
                )}
                <div className="mt-0.5 text-[11px] muted italic leading-snug">
                  Expect → {step.expect}
                </div>
              </li>
            ))}
          </ol>
        </article>
      ))}

      <section className="card p-3.5 text-[11.5px] muted">
        <span className="font-extrabold text-[var(--color-edify-text)]">Closing line: </span>
        &ldquo;This prototype demonstrates the full operating model: planning, data readiness, SSA-driven recommendations,
        budget generation, approval governance, field execution, verification, and leadership reporting. The next
        phase wires these workflows to the live database, Salesforce, and production authentication.&rdquo;
      </section>
    </StubPage>
  );
}

// Imports below are used for the icon map above; keep alphabetised for the linter.
export const _icons = {
  Briefcase, Users, Globe, Wallet, ShieldCheck, Heart, UserCog, CalendarRange, Upload, Brain, Sparkles,
};
