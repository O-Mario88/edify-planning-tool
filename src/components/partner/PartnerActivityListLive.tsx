// PartnerActivityListLive — the partner's OWN assigned activities, straight from
// the backend, as a filterable list. This is the round-trip: when a CCEO/PL
// assigns an activity to a partner (Activity.assignedPartnerId), it lands here
// in that partner's session. The field officer authenticates as the partner user
// linked to the Partner org, so they see only their org's work.
//
// One source — fetchMyPartnerActivities — drives /partner/activities,
// /partner/inbox/[tab], and /partner/corrections. A `filter` narrows the list
// for the inbox-tab and corrections views. Every row shows type · school ·
// status · evidence status. No dead buttons: a row only carries an action when
// a live one exists (evidence upload, which is already a real proxy).
//
// When the backend is OFF (EDIFY_USE_BACKEND=false) we fall back to the legacy
// in-memory mock via a dynamic import inside the !live branch — so this module's
// top-level imports stay mock-free (the mock-audit gate keys on the import
// specifier).

import Link from "next/link";
import { Handshake, School2, Inbox, RotateCcw, ArrowRight } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { fetchMyPartnerActivities, type BeMyPartnerActivity } from "@/lib/api/surfaces";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

const STATUS_TONE: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-700",
  ia_verified: "bg-emerald-100 text-emerald-700",
  paid: "bg-emerald-100 text-emerald-700",
  in_progress: "bg-sky-100 text-sky-700",
  evidence_uploaded: "bg-sky-100 text-sky-700",
  awaiting_ia_verification: "bg-amber-100 text-amber-700",
  returned: "bg-amber-100 text-amber-700",
  planned: "bg-violet-100 text-violet-700",
  scheduled: "bg-violet-100 text-violet-700",
  partner_scheduled: "bg-violet-100 text-violet-700",
  assigned_to_partner: "bg-amber-100 text-amber-700",
};

const EVIDENCE_TONE: Record<string, string> = {
  accepted: "bg-emerald-50 text-emerald-700",
  verified: "bg-emerald-50 text-emerald-700",
  uploaded: "bg-sky-50 text-sky-700",
  submitted: "bg-sky-50 text-sky-700",
  pending: "bg-slate-100 text-slate-600",
  none: "bg-slate-100 text-slate-600",
  missing: "bg-rose-50 text-rose-700",
  rejected: "bg-amber-50 text-amber-800",
  returned: "bg-amber-50 text-amber-800",
};

function fmtType(t: string): string {
  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function fmtDate(iso: string | null): string {
  if (!iso) return "Unscheduled";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// Filters map each view to a predicate over the backend activity shape. Keys
// mirror /partner/inbox/[tab] route keys (plus "corrections"). Anything not
// listed shows the full list.
export type PartnerActivityFilter =
  | "all"
  | "assigned"
  | "due-this-week"
  | "needs-evidence"
  | "needs-report"
  | "returned"
  | "awaiting-verification"
  | "verified"
  | "completed"
  | "corrections";

const isReturned = (a: BeMyPartnerActivity) =>
  a.evidenceStatus === "rejected" || a.evidenceStatus === "returned" || a.status === "returned";
const needsEvidence = (a: BeMyPartnerActivity) =>
  a.evidenceStatus === "none" || a.evidenceStatus === "missing" || a.evidenceStatus === "pending" || a.evidenceStatus === "rejected" || a.evidenceStatus === "returned";

const FILTERS: Record<PartnerActivityFilter, (a: BeMyPartnerActivity) => boolean> = {
  all: () => true,
  assigned: (a) => a.status === "assigned_to_partner" || a.status === "planned" || a.status === "scheduled" || a.status === "partner_scheduled",
  "due-this-week": (a) => {
    if (!a.scheduledDate) return false;
    const d = new Date(a.scheduledDate);
    if (Number.isNaN(d.getTime())) return false;
    const now = new Date();
    const week = 7 * 24 * 60 * 60 * 1000;
    return d.getTime() >= now.getTime() - week && d.getTime() <= now.getTime() + week;
  },
  "needs-evidence": (a) => needsEvidence(a) && a.status !== "completed" && a.status !== "paid",
  "needs-report": (a) => a.status === "in_progress" || a.status === "evidence_uploaded",
  returned: isReturned,
  "awaiting-verification": (a) => a.status === "awaiting_ia_verification",
  verified: (a) => a.status === "ia_verified",
  completed: (a) => a.status === "completed" || a.status === "paid",
  corrections: isReturned,
};

export async function PartnerActivityListLive({
  filter = "all",
  limit = 50,
  variant = "list",
  emptyHint,
}: {
  filter?: PartnerActivityFilter;
  limit?: number;
  /** "list" = the full assigned queue; "corrections" = amber returns layout. */
  variant?: "list" | "corrections";
  emptyHint?: string;
}) {
  const user = await getCurrentUser();
  const r = await fetchMyPartnerActivities(user);

  if (!r.live) {
    // Backend off/unreachable. In production NEVER render the mock — a transient
    // backend blip must not surface fabricated partner data. Only fall back to the
    // legacy mock when mock data is explicitly allowed (dev). Dynamic import keeps
    // the mock specifier out of this module's top-level imports.
    if (!isMockAllowed()) {
      return <InsufficientData surface="partner activities" />;
    }
    const { PartnerActivityListMockFallback } = await import("@/components/partner/PartnerActivityListMockFallback");
    return <PartnerActivityListMockFallback variant={variant} />;
  }

  const { partner, counts, activities } = r.data;
  const rows = activities.filter(FILTERS[filter]).slice(0, limit);

  if (variant === "corrections") {
    return (
      <section className="card p-3.5">
        <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
          <div>
            <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
              <RotateCcw size={14} className="text-amber-700" /> Returned for correction
            </h3>
            <p className="text-[11.5px] muted">Items your CCEO / PL / M&amp;E sent back to {partner.name}. Re-upload corrected evidence to clear them.</p>
          </div>
          <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
        </header>

        {rows.length === 0 ? (
          <p className="text-[12px] muted py-6 text-center italic">
            {emptyHint ?? "Nothing returned — your evidence is clean. Keep it up."}
          </p>
        ) : (
          <ul className="space-y-2">
            {rows.map((a) => (
              <li key={a.id} className="rounded-xl border border-amber-200 bg-amber-50/40 p-3.5 flex items-center gap-3">
                <span className="grid place-items-center h-9 w-9 rounded-lg bg-amber-100 text-amber-700 shrink-0">
                  <School2 size={14} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-body font-extrabold tracking-tight truncate">{a.schoolName ?? "—"}</div>
                  <div className="text-caption muted truncate">{fmtType(a.activityType)}{a.district ? ` · ${a.district}` : ""} · {fmtDate(a.scheduledDate)}</div>
                </div>
                <Link
                  href={`/activities/${a.id}/evidence`}
                  className="inline-flex items-center gap-1 h-8 px-3 rounded-md bg-amber-500 text-white text-[11.5px] font-extrabold hover:bg-amber-600 whitespace-nowrap"
                >
                  Correct <ArrowRight size={11} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    );
  }

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div>
          <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <Handshake size={14} className="text-[var(--color-edify-primary)]" /> Assigned to {partner.name}
          </h3>
          <p className="text-[11.5px] muted">Activities routed to your organization by program staff.</p>
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
      </header>

      <MetricStrip
        bare
        className="mb-3"
        columns="grid-cols-2 sm:grid-cols-4"
        metrics={[
          { key: "total", label: "Assigned to us", value: counts.total },
          { key: "open", label: "Open", value: counts.open, tone: counts.open > 0 ? "alert" : "default" },
          { key: "scheduled", label: "Scheduled", value: counts.scheduled },
          { key: "awaitingEvidence", label: "Awaiting evidence", value: counts.awaitingEvidence, tone: counts.awaitingEvidence > 0 ? "alert" : "default" },
        ]}
      />

      {rows.length === 0 ? (
        <p className="text-[12px] muted py-6 text-center inline-flex items-center justify-center gap-1.5 w-full">
          <Inbox size={13} /> {emptyHint ?? "No activities in this queue right now."}
        </p>
      ) : (
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {rows.map((a) => {
            const evidenceLabel = (a.evidenceStatus ?? "none").replace(/_/g, " ");
            const needsUpload = needsEvidence(a) && a.status !== "completed" && a.status !== "paid";
            return (
              <li key={a.id} className="py-2.5 flex items-center gap-3">
                <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                  <School2 size={14} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-body font-extrabold tracking-tight truncate">{a.schoolName ?? "—"}</div>
                  <div className="text-caption muted truncate">{fmtType(a.activityType)}{a.district ? ` · ${a.district}` : ""} · {fmtDate(a.scheduledDate)}</div>
                </div>
                <span className={`inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap capitalize ${EVIDENCE_TONE[a.evidenceStatus] ?? "bg-[var(--color-edify-soft)]"}`}>
                  {evidenceLabel}
                </span>
                <span className={`inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap capitalize ${STATUS_TONE[a.status] ?? "bg-[var(--color-edify-soft)]"}`}>
                  {a.status.replace(/_/g, " ")}
                </span>
                {/* Only a live action: evidence upload is a real proxy. No dead buttons. */}
                {needsUpload && (
                  <Link
                    href={`/activities/${a.id}/evidence`}
                    className="inline-flex items-center gap-1 h-8 px-3 rounded-md text-[11.5px] font-semibold border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/60 whitespace-nowrap"
                  >
                    Evidence <ArrowRight size={11} />
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {activities.filter(FILTERS[filter]).length > limit && (
        <p className="text-[11px] muted mt-2">Showing {limit} of {activities.filter(FILTERS[filter]).length} activities.</p>
      )}
    </section>
  );
}
