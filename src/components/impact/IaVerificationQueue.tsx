"use client";

// IA Verification Queue — the live IA work surface.
//
// Three sub-queues, one per workflow:
//   • W6 Activity verification (PlannedActivity.status =
//     SubmittedForVerification)
//   • W6 Evidence verification (TrainingParticipant.evidenceStatus =
//     Uploaded or CceoConfirmed → MeVerified)
//   • W8 Partner activities (PartnerActivity.status = CceoConfirmed →
//     MeVerified)
//
// Tab state lives in the URL so a Slack link to ?qview=participants
// drops you on the right pane. Each row's Approve / Return buttons are
// a tiny client-side wrapper around the relevant server action, using
// the same useTransition + pushToast + router.refresh pattern as the
// canonical FundPlanActionRow.

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2, RotateCcw } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import {
  rejectEvidence,
  returnActivity,
  verifyActivity,
  verifyEvidenceByME,
} from "@/lib/actions/activity-actions";
import {
  meVerifyPartnerActivity,
  rejectPartnerActivity,
} from "@/lib/actions/partner-actions";
import { useUrlState } from "@/hooks/use-url-state";
import { cn } from "@/lib/utils";

type ActivityRow = {
  id: string;
  title: string;
  status: string;
  planId?: string;
  assigneeName?: string;
  weekOfMonth: number;
};

type ParticipantRow = {
  id: string;
  participantName: string;
  participantType: string;
  evidenceStatus: string;
  activityId: string;
};

type PartnerRow = {
  id: string;
  title: string;
  partnerName: string;
  schoolId: string;
  status: string;
  evidenceStatus: string;
};

type QueuesProps = {
  activities: ActivityRow[];
  participants: ParticipantRow[];
  partnerActivities: PartnerRow[];
};

const TABS = [
  { key: "activities",   label: "Activities",        accessor: (q: QueuesProps) => q.activities.length },
  { key: "participants", label: "Training evidence", accessor: (q: QueuesProps) => q.participants.length },
  { key: "partners",     label: "Partner activities",accessor: (q: QueuesProps) => q.partnerActivities.length },
] as const;

type TabKey = (typeof TABS)[number]["key"];
const TAB_KEYS = TABS.map((t) => t.key) as readonly TabKey[];

export function IaVerificationQueue(props: QueuesProps) {
  const [tab, setTab] = useUrlState<TabKey>({
    key: "qview",
    defaultValue: "activities",
    allowed: TAB_KEYS,
  });

  return (
    <section className="card rounded-2xl overflow-hidden">
      <header className="px-4 py-3 border-b border-[var(--color-edify-divider)] flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-body-lg font-extrabold tracking-tight">M&E Verification Queue</h2>
          <p className="text-caption muted mt-0.5">
            Live. Approving a row advances Plan % (activities) or unlocks donor counts (evidence + partner).
          </p>
        </div>
        <nav className="flex items-center gap-1.5 flex-wrap">
          {TABS.map((t) => {
            const active = tab === t.key;
            const count = t.accessor(props);
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                aria-pressed={active}
                className={cn(
                  "h-8 px-3 rounded-lg text-[11.5px] font-extrabold whitespace-nowrap inline-flex items-center gap-1.5 transition-all",
                  active
                    ? "bg-slate-900 text-white shadow-[0_8px_18px_-8px_rgba(15,23,32,0.4)]"
                    : "bg-white text-slate-600 border border-[var(--color-edify-border)] hover:bg-slate-50 hover:border-slate-300",
                )}
              >
                {t.label}
                <span
                  className={cn(
                    "inline-flex items-center justify-center min-w-[18px] h-[16px] px-1 rounded-md text-[9.5px] font-extrabold tabular",
                    active ? "bg-white/15 text-white" : "bg-slate-100 text-slate-600",
                  )}
                >
                  {count}
                </span>
              </button>
            );
          })}
        </nav>
      </header>

      <div className="p-3">
        {tab === "activities" && (
          <RowList rows={props.activities} empty="No activities awaiting verification." renderRow={(r) => <ActivityRowView row={r} />} />
        )}
        {tab === "participants" && (
          <RowList rows={props.participants} empty="No participant evidence pending verification." renderRow={(r) => <ParticipantRowView row={r} />} />
        )}
        {tab === "partners" && (
          <RowList rows={props.partnerActivities} empty="No partner activities pending M&E sign-off." renderRow={(r) => <PartnerRowView row={r} />} />
        )}
      </div>
    </section>
  );
}

// ─── Sub-row components ────────────────────────────────────────────

function RowList<T extends { id: string }>({
  rows,
  empty,
  renderRow,
}: {
  rows: T[];
  empty: string;
  renderRow: (row: T) => React.ReactNode;
}) {
  if (rows.length === 0) {
    return <p className="px-3 py-8 text-center text-[12px] muted italic">{empty}</p>;
  }
  return (
    <ul className="flex flex-col gap-2">
      {rows.map((r) => (
        <li key={r.id}>{renderRow(r)}</li>
      ))}
    </ul>
  );
}

function ActivityRowView({ row }: { row: ActivityRow }) {
  const [pending, startTransition] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();

  function runApprove() {
    startTransition(async () => {
      const res = await verifyActivity(row.id);
      if (res.ok) {
        pushToast({ tone: "success", title: "Activity verified", body: `${row.title} now counts toward plan completion.` });
      } else {
        pushToast({ tone: "warning", title: "Couldn't verify", body: `Reason: ${res.reason}` });
      }
      router.refresh();
    });
  }
  function runReturn() {
    const reason = prompt(`Return ${row.title}? Add a short reason (5+ chars):`)?.trim() ?? "";
    if (reason.length < 5) return;
    startTransition(async () => {
      const res = await returnActivity(row.id, reason);
      if (res.ok) pushToast({ tone: "info", title: "Returned for correction", body: row.title });
      else pushToast({ tone: "warning", title: "Couldn't return", body: `Reason: ${res.reason}` });
      router.refresh();
    });
  }
  return <RowChrome
    title={row.title}
    subtitle={`Week ${row.weekOfMonth} · ${row.assigneeName ?? "Unassigned"} · ${row.status}`}
    pending={pending}
    onApprove={runApprove}
    onReturn={runReturn}
  />;
}

function ParticipantRowView({ row }: { row: ParticipantRow }) {
  const [pending, startTransition] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();

  function runVerify() {
    startTransition(async () => {
      const res = await verifyEvidenceByME(row.id);
      if (res.ok) pushToast({ tone: "success", title: "Evidence verified", body: `${row.participantName} now counts toward donor metrics.` });
      else pushToast({ tone: "warning", title: "Couldn't verify", body: `Reason: ${res.reason}` });
      router.refresh();
    });
  }
  function runReject() {
    const reason = prompt(`Reject evidence for ${row.participantName}? Add a short reason (5+ chars):`)?.trim() ?? "";
    if (reason.length < 5) return;
    startTransition(async () => {
      const res = await rejectEvidence(row.id, reason);
      if (res.ok) pushToast({ tone: "info", title: "Evidence rejected", body: row.participantName });
      else pushToast({ tone: "warning", title: "Couldn't reject", body: `Reason: ${res.reason}` });
      router.refresh();
    });
  }
  return <RowChrome
    title={row.participantName}
    subtitle={`${row.participantType} · evidence: ${row.evidenceStatus}`}
    pending={pending}
    onApprove={runVerify}
    onReturn={runReject}
    approveLabel="Verify"
    returnLabel="Reject"
  />;
}

function PartnerRowView({ row }: { row: PartnerRow }) {
  const [pending, startTransition] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();

  function runVerify() {
    startTransition(async () => {
      const res = await meVerifyPartnerActivity(row.id);
      if (res.ok) pushToast({ tone: "success", title: "Partner activity verified", body: `${row.title} — payment gate unlocked.` });
      else pushToast({ tone: "warning", title: "Couldn't verify", body: `Reason: ${res.reason}` });
      router.refresh();
    });
  }
  function runReject() {
    const reason = prompt(`Reject ${row.title}? Add a short reason (5+ chars):`)?.trim() ?? "";
    if (reason.length < 5) return;
    startTransition(async () => {
      const res = await rejectPartnerActivity(row.id, reason);
      if (res.ok) pushToast({ tone: "info", title: "Activity rejected", body: row.title });
      else pushToast({ tone: "warning", title: "Couldn't reject", body: `Reason: ${res.reason}` });
      router.refresh();
    });
  }
  return <RowChrome
    title={row.title}
    subtitle={`${row.partnerName} · school ${row.schoolId} · evidence ${row.evidenceStatus}`}
    pending={pending}
    onApprove={runVerify}
    onReturn={runReject}
    approveLabel="Verify"
    returnLabel="Reject"
  />;
}

function RowChrome({
  title, subtitle, pending, onApprove, onReturn,
  approveLabel = "Verify", returnLabel = "Return",
}: {
  title: string;
  subtitle: string;
  pending: boolean;
  onApprove: () => void;
  onReturn: () => void;
  approveLabel?: string;
  returnLabel?: string;
}) {
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3 flex items-center gap-3 flex-wrap">
      <div className="flex-1 min-w-0">
        <div className="text-body font-extrabold tracking-tight truncate">{title}</div>
        <div className="text-caption muted mt-0.5 truncate">{subtitle}</div>
      </div>
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={onReturn}
          disabled={pending}
          className="inline-flex items-center gap-1 h-8 px-2.5 rounded-md bg-white border border-rose-200 hover:bg-rose-50 text-[11.5px] font-extrabold text-rose-700 disabled:opacity-50"
        >
          <RotateCcw size={11} /> {returnLabel}
        </button>
        <button
          type="button"
          onClick={onApprove}
          disabled={pending}
          className="inline-flex items-center gap-1 h-8 px-2.5 rounded-md bg-slate-900 hover:bg-slate-800 text-white text-[11.5px] font-extrabold disabled:opacity-50 shadow-[0_4px_10px_-4px_rgba(15,23,32,0.45)]"
        >
          {pending ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle2 size={11} />}
          {approveLabel}
        </button>
      </div>
    </div>
  );
}
