// School Improvement Decision Engine — the daily-driver Decisions surface.
//
// This page answers one question every morning:
//
//   "Based on all our school, staff, partner, finance, geography,
//    performance, and impact data — what is the best decision we
//    should make next to improve schools?"
//
// Composition:
//   1. Mission header  — greeting, role mission, period, one-line summary
//   2. DecisionHero    — the single most important decision today (full reasoning visible)
//   3. Next Best Actions    — operational queue ("you do this") — compact cards, expandable
//   4. Next Best Decisions  — judgment queue ("you choose A or B")  — compact cards, expandable
//   5. Routed decisions inbox — the existing CD/RVP-routed action queue,
//      moved below the engine surface as a secondary "what others
//      assigned to me" section so the engine-generated content leads.
//
// The Decision type is the contract; the engine wiring lands in a later
// turn. Today the board is hand-mocked so the UX is real.

import Link from "next/link";
import { AlertTriangle, ChevronRight, ClipboardCheck, Inbox, Sparkles } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { PageHeader } from "@/components/ui/PageHeader";
import { decisionBoardFor } from "@/lib/decisions/decisions-mock";
import { DecisionCard } from "@/components/decisions/DecisionCard";
import {
  decisionActionsForAssignee,
  decisionActionsForCreator,
  type DecisionAction,
  type DecisionStatus,
} from "@/lib/field-intelligence-mock";
import { prettyRole } from "@/components/decisions/DecisionActionsCard";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<DecisionStatus, string> = {
  Pending:       "bg-amber-100   text-amber-800",
  "In Progress": "bg-sky-100     text-sky-800",
  Approved:      "bg-emerald-100 text-emerald-700",
  Returned:      "bg-rose-100    text-rose-700",
  Closed:        "bg-slate-100   text-slate-500",
};

const PRIORITY_TONE: Record<DecisionAction["priority"], string> = {
  Critical: "text-rose-700",
  High:     "text-amber-700",
  Medium:   "text-sky-700",
  Low:      "text-slate-600",
};

export default async function DecisionsPage() {
  const user = await getCurrentUser();
  const board = decisionBoardFor(user.role);

  // ─── Routed decisions (existing inbox) ───
  const created  = decisionActionsForCreator(user.name);
  const assigned = decisionActionsForAssignee(user.name);
  const isCreatorRole = ["CountryDirector", "RVP", "Admin", "CountryProgramLead"].includes(user.role);
  const routedVisible: DecisionAction[] =
    user.role === "CountryDirector" || user.role === "Admin"
      ? [...created, ...assigned.filter((a) => a.createdByName !== user.name)]
      : user.role === "RVP"
        ? [...created, ...assigned.filter((a) => a.createdByName !== user.name)]
        : assigned;
  const routedOpen = routedVisible.filter((a) => a.status === "Pending" || a.status === "In Progress" || a.status === "Returned");

  return (
    <>
      {/* ─── Header ─── */}
      <PageHeader
        title={board.header.greeting}
        subtitle={board.header.mission}
        showTitleOnMobile
        backFallbackHref="/dashboard"
        meta={
          <div className="space-y-1.5">
            <div className="text-[11px] muted font-bold uppercase tracking-wider inline-flex items-center gap-1.5">
              <Sparkles size={11} className="text-[var(--color-edify-primary)]" />
              {user.role} · Decision Intelligence
            </div>
            <p className="text-[13px] text-[var(--color-edify-text)] max-w-[820px] leading-snug">
              <span className="font-extrabold">{board.header.periodLabel}.</span>{" "}
              {board.header.summary}
            </p>
          </div>
        }
      />

      <div className="px-4 sm:px-5 md:px-6 pb-10 md:pb-6 space-y-5">
        {/* Hero retired per global hero removal pass. The top decision is
            still surfaced as the first card in the Next Best Decisions list
            below. Empty-state copy moves into that section's header. */}

        {/* ─── Next Best Decisions (judgment) ─── */}
        {board.nextBestDecisions.length > 0 && (
          <section className="space-y-3">
            <SectionHeader
              icon={<Sparkles size={13} className="text-[var(--color-edify-primary)]" />}
              title="Next best decisions"
              subtitle="Leadership judgments the engine surfaced. Choose, reassign, or defer."
              count={board.nextBestDecisions.length}
            />
            <div className="grid lg:grid-cols-2 gap-3">
              {board.nextBestDecisions.map((d, i) => (
                <DecisionCard key={d.id} decision={d} index={i + 2 /* hero is #1 */} />
              ))}
            </div>
          </section>
        )}

        {/* ─── Next Best Actions (operational) ─── */}
        {board.nextBestActions.length > 0 && (
          <section className="space-y-3">
            <SectionHeader
              icon={<ClipboardCheck size={13} className="text-[var(--color-edify-primary)]" />}
              title="Next best actions"
              subtitle="What to do today, in order. Each card opens the screen where the work happens."
              count={board.nextBestActions.length}
            />
            <div className="grid lg:grid-cols-2 gap-3">
              {board.nextBestActions.map((d, i) => (
                <DecisionCard key={d.id} decision={d} index={i + 2 /* hero is #1 */} />
              ))}
            </div>
          </section>
        )}

        {/* ─── Routed decisions inbox (existing system) ─── */}
        {routedVisible.length > 0 && (
          <section className="space-y-3">
            <SectionHeader
              icon={<Inbox size={13} className="text-[var(--color-edify-primary)]" />}
              title="Routed to you"
              subtitle={
                isCreatorRole
                  ? "Decisions routed by your working circle plus anything assigned to you."
                  : "Decisions leadership has asked you to handle. The system's memory of what was requested."
              }
              count={routedOpen.length}
            />
            <div className="card p-3.5 space-y-2">
              {routedOpen.length === 0 ? (
                <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-3 text-[11.5px] text-emerald-800 leading-snug">
                  Nothing open in your routed inbox. Good shape.
                </div>
              ) : (
                <ul className="space-y-2">
                  {routedOpen.map((a) => (
                    <RoutedRow key={a.id} a={a} />
                  ))}
                </ul>
              )}
              <p className="text-caption muted leading-snug pt-1">
                Working circle constraint:{" "}
                {user.role === "RVP"
                  ? "RVP → Country Director · Human Resource only."
                  : user.role === "CountryDirector" || user.role === "Admin"
                    ? "CD → Program Lead · Impact Assessment · Program Accountant · Special Project Coordinator."
                    : "You see decisions assigned directly to you."}
              </p>
            </div>
          </section>
        )}

        {/* ─── Trust footer ─── */}
        <footer className="pt-4 border-t border-[var(--color-edify-divider)] text-[11px] muted leading-snug">
          Every decision shown here was generated from system signals. The engine surfaces the recommendation; you make the call. Choices are recorded as a decision trail so the team can learn what worked.
        </footer>
      </div>
    </>
  );
}

// ────────── Helpers ──────────

function SectionHeader({
  icon,
  title,
  subtitle,
  count,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  count: number;
}) {
  return (
    <header className="flex items-baseline justify-between gap-3 flex-wrap">
      <div className="min-w-0 flex-1">
        <h2 className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-2">
          {icon}
          {title}
          <span className="text-[12px] muted font-bold">({count})</span>
        </h2>
        <p className="text-[11.5px] muted leading-snug mt-0.5">{subtitle}</p>
      </div>
    </header>
  );
}

function RoutedRow({ a }: { a: DecisionAction }) {
  const isOverdue =
    new Date(a.deadline) < new Date("2025-05-12") &&
    (a.status === "Pending" || a.status === "In Progress" || a.status === "Returned");
  return (
    <li
      className={cn(
        "rounded-xl border bg-white p-3 space-y-1 border-[var(--color-edify-border)]",
        isOverdue && "ring-2 ring-rose-200",
      )}
    >
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-extrabold tracking-tight">{a.title}</div>
          <div className="text-[11px] muted leading-snug mt-0.5">{a.description}</div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={cn("text-[10px] font-extrabold uppercase tracking-wide", PRIORITY_TONE[a.priority])}>
            {a.priority}
          </span>
          <span
            className={cn(
              "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
              STATUS_TONE[a.status],
            )}
          >
            {a.status}
          </span>
        </div>
      </div>
      <div className="text-caption muted flex items-center gap-x-3 gap-y-1 flex-wrap">
        <span>
          Assigned to <span className="font-extrabold text-[var(--color-edify-text)]">{a.assigneeName}</span> ({prettyRole(a.assigneeRole)})
        </span>
        <span>
          · Created by <span className="font-extrabold text-[var(--color-edify-text)]">{a.createdByName}</span>
        </span>
        <span>
          · Due{" "}
          <span className={cn("font-extrabold", isOverdue ? "text-rose-700" : "text-[var(--color-edify-text)]")}>
            {a.deadline}
          </span>
        </span>
        {isOverdue && (
          <span className="inline-flex items-center gap-1 text-rose-700 font-extrabold">
            <AlertTriangle size={9} /> Overdue
          </span>
        )}
        <Link
          href={`/dashboards/director/weekly-debrief-reports/${a.sourceReportId}`}
          className="ml-auto inline-flex items-center gap-1 font-extrabold text-[var(--color-edify-primary)] hover:underline"
        >
          Source report <ChevronRight size={9} />
        </Link>
      </div>
    </li>
  );
}
