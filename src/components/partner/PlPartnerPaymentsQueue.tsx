"use client";

// PlPartnerPaymentsQueue — what the Program Lead sees after a CCEO
// confirms partner work. Only requests with status AwaitingPlApproval
// appear here; the workflow gate (see partner-workflow.REQUIRED_PATH)
// guarantees CCEO confirmation has already happened, so the PL never
// sees a request that hasn't been vetted.
//
// Actions:
//   • Approve and Send to IA          — happy path (IA verifies the
//                                        Salesforce entry before the
//                                        accountant can clear payment)
//   • Return to CCEO                  — needs clarification
//   • Return to Partner               — evidence weak
//   • Reject                          — work invalid
//   • Hold                            — pause with reason

import { useState } from "react";
import {
  Handshake, CheckCircle2, RotateCcw, XCircle, PauseCircle, AlertTriangle, ArrowRight, MoreHorizontal,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  plQueue,
  fmtUgx,
  type PartnerPaymentRequest,
} from "@/lib/partner/partner-payment-requests-mock";

export function PlPartnerPaymentsQueue() {
  const requests = plQueue();
  const [toast, setToast] = useState<string | null>(null);

  function handleAction(req: PartnerPaymentRequest, action: "approve" | "returnCceo" | "returnPartner" | "reject" | "hold") {
    const labels = {
      approve:       `Approved — ${req.partner} ${fmtUgx(req.totalUgx)} sent to IA for Salesforce verification.`,
      returnCceo:    `Returned to CCEO — ${req.confirmedBy} will receive a clarification request.`,
      returnPartner: `Returned to partner — ${req.partner} will receive an evidence-correction request.`,
      reject:        `Rejected — ${req.partner} request will not move forward.`,
      hold:          `Held — ${req.partner} request paused. Add reason in the next step.`,
    } as const;
    setToast(labels[action]);
    setTimeout(() => setToast(null), 3500);
  }

  const total = requests.reduce((sum, r) => sum + r.totalUgx, 0);

  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
              <Handshake size={14} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Partner Payments Awaiting Approval</h3>
          </div>
          <p className="text-[12px] muted mt-1">
            CCEO-confirmed payment requests waiting on your approval before going to IA for Salesforce verification.
          </p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10px] uppercase tracking-wide font-bold muted">In queue</div>
          <div className="text-[18px] font-extrabold tabular num-hero text-amber-700 leading-none mt-1">
            {fmtUgx(total)}
          </div>
          <div className="text-caption muted mt-0.5">{requests.length} requests</div>
        </div>
      </header>

      {requests.length === 0 ? (
        <div className="text-center py-8 text-[12px] muted italic">
          Inbox zero — nothing waiting for your approval right now.
        </div>
      ) : (
        <ul className="space-y-2">
          {requests.map((req) => (
            <RequestCard key={req.id} req={req} onAction={handleAction} />
          ))}
        </ul>
      )}

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-[var(--color-edify-deep)] text-white text-body font-semibold px-4 py-3 max-w-[400px]">
          {toast}
        </div>
      )}
    </section>
  );
}

function RequestCard({
  req, onAction,
}: {
  req: PartnerPaymentRequest;
  onAction: (req: PartnerPaymentRequest, action: "approve" | "returnCceo" | "returnPartner" | "reject" | "hold") => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-xl border border-[var(--color-edify-divider)] bg-white p-3.5">
      <div className="flex items-start gap-3">
        <span className="grid place-items-center h-10 w-10 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] font-extrabold text-[12px] shrink-0">
          {req.partnerOrgInitials}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h4 className="text-[13.5px] font-extrabold tracking-tight truncate">{req.partner}</h4>
              <p className="text-[11.5px] muted mt-0.5">
                {req.activitiesCount} activities · {req.schools.slice(0, 2).join(", ")}
                {req.schools.length > 2 ? ` · +${req.schools.length - 2} more` : ""}
              </p>
            </div>
            <div className="text-right shrink-0">
              <div className="text-[15px] font-extrabold tabular num-hero text-[var(--color-edify-text)] leading-none">
                {fmtUgx(req.totalUgx)}
              </div>
              <div className="text-[10px] uppercase tracking-wide muted mt-0.5">total</div>
            </div>
          </div>

          {/* Pre-approval checklist — surfaces the gate state at a glance. */}
          <div className="flex items-center gap-3 mt-2 text-caption font-bold">
            <Badge ok={req.cceoConfirmed} label={`CCEO confirmed (${req.confirmedBy.split(" (")[0]})`} />
            <Badge ok={req.evidenceComplete} label="Evidence complete" />
            <Badge ok={req.scopeOk} label="Within scope" warnIfFalse />
          </div>

          {req.notes && (
            <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 text-amber-800 text-[11px] px-2 py-1.5 inline-flex items-start gap-1.5">
              <AlertTriangle size={11} className="shrink-0 mt-0.5" />
              {req.notes}
            </div>
          )}

          <div className="mt-3 flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => onAction(req, "approve")}
              className="inline-flex items-center gap-1 h-8 px-3 rounded-md bg-emerald-500 text-white text-[11.5px] font-extrabold hover:bg-emerald-600"
            >
              Approve and send <ArrowRight size={11} />
            </button>
            <button
              type="button"
              onClick={() => onAction(req, "returnCceo")}
              className="inline-flex items-center h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60"
            >
              Return to CCEO
            </button>
            <button
              type="button"
              onClick={() => onAction(req, "returnPartner")}
              className="inline-flex items-center h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60"
            >
              Return to partner
            </button>
            <div className="relative ml-auto">
              <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                className="h-8 w-8 grid place-items-center rounded-md border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/60"
                aria-label="More actions"
              >
                <MoreHorizontal size={13} className="text-[var(--color-edify-muted)]" />
              </button>
              {open && (
                <div className="absolute right-0 top-9 z-20 w-44 rounded-lg border border-[var(--color-edify-border)] bg-white shadow-lg py-1">
                  <MenuItem Icon={PauseCircle} label="Hold payment" tone="amber" onClick={() => { setOpen(false); onAction(req, "hold"); }} />
                  <MenuItem Icon={XCircle} label="Reject" tone="rose" onClick={() => { setOpen(false); onAction(req, "reject"); }} />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </li>
  );
}

function Badge({ ok, label, warnIfFalse }: { ok: boolean; label: string; warnIfFalse?: boolean }) {
  if (ok) {
    return (
      <span className="inline-flex items-center gap-1 text-emerald-700">
        <CheckCircle2 size={11} /> {label}
      </span>
    );
  }
  const cls = warnIfFalse ? "text-amber-700" : "text-rose-700";
  return (
    <span className={cn("inline-flex items-center gap-1", cls)}>
      <AlertTriangle size={11} /> {label}
    </span>
  );
}

function MenuItem({
  Icon, label, tone, onClick,
}: {
  Icon: typeof RotateCcw;
  label: string;
  tone: "amber" | "rose";
  onClick: () => void;
}) {
  const cls = tone === "amber" ? "text-amber-700" : "text-rose-700";
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left px-3 py-2 text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60 inline-flex items-center gap-2"
    >
      <Icon size={12} className={cls} />
      {label}
    </button>
  );
}
