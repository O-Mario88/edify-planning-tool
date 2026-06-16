"use client";

// AccountantPartnerPaymentsQueue — the accountant's final-stage view.
// Only PL-approved requests appear here; the workflow gate
// (partner-workflow.REQUIRED_PATH) guarantees both CCEO confirmation
// AND PL approval already happened, so the accountant only sees
// requests that are ready to clear.
//
// Actions:
//   • Clear payment + add reference  — happy path
//   • Return for correction          — accountant finds an issue
//   • Hold payment with reason       — pause

import { useState } from "react";
import {
  Wallet, CheckCircle2, ShieldCheck, RotateCcw, PauseCircle, ArrowRight, MoreHorizontal,
} from "lucide-react";
import {
  accountantQueue,
  fmtUgx,
  type PartnerPaymentRequest,
} from "@/lib/partner/partner-payment-requests-mock";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

export function AccountantPartnerPaymentsQueue() {
  const requests = accountantQueue();
  const [toast, setToast] = useState<string | null>(null);
  // Mock payment requests with non-functional Clear/Return/Hold buttons that would
  // falsely confirm payment. Never render fake clearable money in production.
  if (!isMockAllowed()) return <InsufficientData surface="partner payments ready to clear" />;

  function handleAction(req: PartnerPaymentRequest, action: "clear" | "return" | "hold") {
    const labels = {
      clear:  `Paid — ${req.partner} ${fmtUgx(req.totalUgx)} cleared. Partner dashboard updated.`,
      return: `Returned — ${req.partner} request sent back for correction.`,
      hold:   `Held — ${req.partner} request paused. Add reason in the next step.`,
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
              <Wallet size={14} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Partner Payments Ready to Clear</h3>
          </div>
          <p className="text-[12px] muted mt-1">
            PL-approved requests awaiting your clearance. CCEO confirmation + PL approval already complete.
          </p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10px] uppercase tracking-wide font-bold muted">Ready to clear</div>
          <div className="text-[18px] font-extrabold tabular num-hero text-blue-700 leading-none mt-1">
            {fmtUgx(total)}
          </div>
          <div className="text-caption muted mt-0.5">{requests.length} requests</div>
        </div>
      </header>

      {requests.length === 0 ? (
        <div className="text-center py-8 text-[12px] muted italic">
          Nothing ready to clear. Approved requests appear here automatically.
        </div>
      ) : (
        <ul className="space-y-2">
          {requests.map((req) => (
            <RequestCard key={req.id} req={req} onAction={handleAction} />
          ))}
        </ul>
      )}

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-body font-semibold px-4 py-3 max-w-[400px]">
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
  onAction: (req: PartnerPaymentRequest, action: "clear" | "return" | "hold") => void;
}) {
  const [reference, setReference] = useState("");
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
              <div className="text-[10px] uppercase tracking-wide muted mt-0.5">to clear</div>
            </div>
          </div>

          {/* Audit trail — every gate that's been cleared. */}
          <div className="flex items-center gap-3 mt-2 text-caption font-bold text-emerald-700">
            <span className="inline-flex items-center gap-1">
              <ShieldCheck size={11} /> CCEO confirmed
            </span>
            <span className="inline-flex items-center gap-1">
              <ShieldCheck size={11} /> PL approved ({req.approvedBy?.split(" (")[0]})
            </span>
            <span className="inline-flex items-center gap-1">
              <CheckCircle2 size={11} /> Evidence complete
            </span>
          </div>

          {/* Reference + clear */}
          <div className="mt-3 flex items-center gap-2">
            <input
              type="text"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="Payment reference (e.g. BANK-2026-04891)"
              className="flex-1 h-8 px-2.5 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
            <button
              type="button"
              disabled={!reference.trim()}
              onClick={() => onAction(req, "clear")}
              className="inline-flex items-center gap-1 h-8 px-3 rounded-md bg-emerald-500 text-white text-[11.5px] font-extrabold hover:bg-emerald-600 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Clear payment <ArrowRight size={11} />
            </button>
            <div className="relative">
              <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                aria-label="More actions"
                className="h-8 w-8 grid place-items-center rounded-md border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/60"
              >
                <MoreHorizontal size={13} className="text-[var(--color-edify-muted)]" />
              </button>
              {open && (
                <div className="absolute right-0 top-9 z-20 w-48 rounded-lg border border-[var(--color-edify-border)] bg-white shadow-lg py-1">
                  <MenuItem Icon={RotateCcw} label="Return for correction" tone="amber" onClick={() => { setOpen(false); onAction(req, "return"); }} />
                  <MenuItem Icon={PauseCircle} label="Hold payment" tone="amber" onClick={() => { setOpen(false); onAction(req, "hold"); }} />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </li>
  );
}

function MenuItem({
  Icon, label, tone, onClick,
}: {
  Icon: typeof RotateCcw;
  label: string;
  tone: "amber";
  onClick: () => void;
}) {
  void tone;
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left px-3 py-2 text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60 inline-flex items-center gap-2"
    >
      <Icon size={12} className="text-amber-700" />
      {label}
    </button>
  );
}
