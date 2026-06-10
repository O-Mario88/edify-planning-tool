import Link from "next/link";
import { redirect } from "next/navigation";
import { PageHeader } from "@/components/ui/PageHeader";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { EmptyState } from "@/components/ui/DataStates";
import { ConfirmCompletionButton } from "@/components/my-targets/ConfirmCompletionButton";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import {
  buildEvidenceQueues,
  type AccountabilityQueueItem,
  type EvidenceQueueItem,
} from "@/lib/cceo/evidence-queues";
import { cn } from "@/lib/utils";

// /evidence — Evidence & Accountability (spec §16).
//
// The CCEO's guided clean-up queues: every one of THEIR completed
// activities that is stuck before it can count — missing evidence,
// missing Salesforce ID, returned by IA, or money disbursed without
// closed accountability. Each row carries the blocking reason, how long
// it has waited, and exactly one action.
//
// Derivation lives in src/lib/cceo/evidence-queues.ts (shared with the
// dashboard card and any future API route).
export const dynamic = "force-dynamic";

export default async function EvidencePage() {
  const user = await getCurrentUser();
  if (!["CCEO", "Admin"].includes(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }

  const q = buildEvidenceQueues(user);

  const metrics: MetricCell[] = [
    { key: "evidence",       label: "Evidence required",     value: q.counts.evidence,       tone: q.counts.evidence > 0 ? "alert" : "good",       caption: "completed, no evidence",   href: "#evidence-required" },
    { key: "salesforce",     label: "Salesforce ID required", value: q.counts.salesforce,    tone: q.counts.salesforce > 0 ? "alert" : "good",     caption: "evidence done, no SF ID",  href: "#salesforce-id-required" },
    { key: "returned",       label: "IA returned",           value: q.counts.returned,       tone: q.counts.returned > 0 ? "alert" : "good",       caption: "fix & resubmit",           href: "#ia-returned" },
    { key: "accountability", label: "Accountability pending", value: q.counts.accountability, tone: q.counts.accountability > 0 ? "alert" : "good", caption: "disbursed, not closed",    href: "#accountability-pending" },
  ];

  return (
    <>
      <PageHeader
        title="Evidence & Accountability"
        subtitle="Your completed work that can't count yet — clear each queue so activities reach verification and payment."
      />
      <div className="px-3 sm:px-4 md:px-5 pb-24 md:pb-5 pt-3 md:pt-4 space-y-4">
        <MetricStrip metrics={metrics} columns="grid-cols-2 md:grid-cols-4" />

        <QueueSection
          id="evidence-required"
          title="Evidence Required"
          subtitle="Completed activities with no evidence captured. Upload Evidence opens the same completion gate used on Visits & Trainings (participants, attendance, notes)."
          count={q.counts.evidence}
          emptyTitle="No activities waiting on evidence"
          emptyMessage="Activities you mark complete on My Plan appear here until their evidence is captured."
        >
          {q.evidenceRequired.map((item) => (
            <ActivityRow key={item.id} item={item} action={
              <ConfirmCompletionButton
                label="Upload Evidence"
                activity={{ id: item.id, schoolId: item.schoolId, schoolName: item.schoolOrCluster, activityType: item.activityType }}
              />
            } />
          ))}
        </QueueSection>

        <QueueSection
          id="salesforce-id-required"
          title="Salesforce ID Required"
          subtitle="Evidence is in, but the Salesforce Activity ID is missing — visits need SVE-, trainings / cluster meetings / SIT need TS-."
          count={q.counts.salesforce}
          emptyTitle="No activities waiting on a Salesforce ID"
          emptyMessage="Once evidence is captured, activities without an SVE- / TS- ID queue here until you enter one."
        >
          {q.sfIdRequired.map((item) => (
            <ActivityRow key={item.id} item={item} showPrefix action={
              <ConfirmCompletionButton
                label="Enter Salesforce ID"
                activity={{ id: item.id, schoolId: item.schoolId, schoolName: item.schoolOrCluster, activityType: item.activityType }}
              />
            } />
          ))}
        </QueueSection>

        <QueueSection
          id="ia-returned"
          title="IA Returned"
          subtitle="Items the Impact Assessment verifier bounced back, with their return reason. Fix the issue and resubmit from the plan."
          count={q.counts.returned}
          emptyTitle="Nothing returned by IA"
          emptyMessage="If IA returns one of your submissions for correction, it lands here with the reason."
        >
          {q.iaReturned.map((item) => (
            <ActivityRow key={item.id} item={item} reasonTone="rose" action={
              <Link href={item.href} className="btn btn-sm whitespace-nowrap">Fix &amp; Resubmit</Link>
            } />
          ))}
        </QueueSection>

        <QueueSection
          id="accountability-pending"
          title="Accountability Pending"
          subtitle="Weekly funds disbursed to you that aren't fully accounted for yet — submit the NetSuite Expense ID at week close on Weekly Funds."
          count={q.counts.accountability}
          emptyTitle="No open accountability"
          emptyMessage="Disbursed weekly fund requests appear here until their accountability is approved and the week closes."
        >
          {q.accountabilityPending.map((item) => (
            <AccountabilityRow key={item.id} item={item} />
          ))}
        </QueueSection>
      </div>
    </>
  );
}

// ────────── Presentational pieces (server-rendered) ──────────

function QueueSection({
  id,
  title,
  subtitle,
  count,
  emptyTitle,
  emptyMessage,
  children,
}: {
  id: string;
  title: string;
  subtitle: string;
  count: number;
  emptyTitle: string;
  emptyMessage: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="card p-3.5 rounded-2xl scroll-mt-4">
      <header className="mb-2.5">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-2">
          {title}
          <span className={cn(
            "px-1.5 py-px rounded-full text-[10px] font-bold tabular",
            count > 0 ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700",
          )}>
            {count}
          </span>
        </h2>
        <p className="text-[11.5px] muted mt-0.5 leading-snug max-w-2xl">{subtitle}</p>
      </header>
      {count === 0
        ? <EmptyState compact title={emptyTitle} message={emptyMessage} />
        : <ul className="divide-y divide-[var(--color-edify-divider)]">{children}</ul>}
    </section>
  );
}

function DuenessChip({ days }: { days: number }) {
  const label = days === 0 ? "today" : `${days}d waiting`;
  return (
    <span className={cn(
      "px-1.5 py-px rounded text-[10px] font-bold whitespace-nowrap",
      days >= 3 ? "bg-rose-100 text-rose-700" : days >= 1 ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600",
    )}>
      {label}
    </span>
  );
}

function ActivityRow({
  item,
  action,
  showPrefix = false,
  reasonTone = "amber",
}: {
  item: EvidenceQueueItem;
  action: React.ReactNode;
  /** Show the expected SVE-/TS- prefix chip (Salesforce queue). */
  showPrefix?: boolean;
  reasonTone?: "amber" | "rose";
}) {
  return (
    <li className="py-2.5 first:pt-0 last:pb-0 flex items-start gap-3 flex-wrap sm:flex-nowrap">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap text-[12.5px]">
          <span className="font-bold">{item.activityType}</span>
          <span className="muted">·</span>
          <span className="muted truncate">{item.schoolOrCluster}</span>
          <span className="muted">·</span>
          <span className="muted tabular">{item.dateLabel}</span>
          {showPrefix && (
            <span className="px-1.5 py-px rounded bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] text-[10px] font-extrabold tabular">
              expects {item.expectedPrefix}…
            </span>
          )}
        </div>
        <p className={cn(
          "text-[11.5px] mt-0.5 leading-snug",
          reasonTone === "rose" ? "text-rose-600" : "text-amber-600",
        )}>
          {item.blockedReason}
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0 ml-auto">
        <DuenessChip days={item.daysWaiting} />
        {action}
      </div>
    </li>
  );
}

function AccountabilityRow({ item }: { item: AccountabilityQueueItem }) {
  return (
    <li className="py-2.5 first:pt-0 last:pb-0 flex items-start gap-3 flex-wrap sm:flex-nowrap">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap text-[12.5px]">
          <span className="font-bold">{item.weekLabel}</span>
          <span className="muted">·</span>
          <span className="font-semibold tabular">{item.amountLabel}</span>
          <span className="px-1.5 py-px rounded bg-slate-100 text-slate-600 text-[10px] font-bold">{item.statusLabel}</span>
        </div>
        <p className="text-[11.5px] mt-0.5 leading-snug text-amber-600">{item.blockedReason}</p>
      </div>
      <div className="flex items-center gap-2 shrink-0 ml-auto">
        <DuenessChip days={item.daysWaiting} />
        <Link href={item.href} className="btn btn-sm whitespace-nowrap">Open Weekly Funds</Link>
      </div>
    </li>
  );
}
