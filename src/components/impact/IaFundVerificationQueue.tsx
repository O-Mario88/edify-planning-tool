// IA fund-verification queue (B12) — the surface that was missing.
//
// CCEO weekly fund requests must clear Impact Assessment before the
// accountant disburses (disburseFundRequest blocks on iaVerifiedAt).
// This server component lists APPROVED CCEO requests that haven't been
// IA-verified yet, each with a "Verify for disbursement" button. Without
// it the gate had no caller and every CCEO weekly disbursement was stuck.

import "server-only";

import { ShieldCheck } from "lucide-react";
import { fundRequests } from "@/lib/actions/store";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import { IaFundVerifyButton } from "./IaFundVerifyButton";

export function IaFundVerificationQueue() {
  // CCEO requests that the lead has approved but IA hasn't verified.
  const rows = fundRequests().filter((r) => {
    const requester = r.requesterRole ?? r.staffRole;
    return requester === "CCEO" && r.status === "APPROVED" && !r.iaVerifiedAt;
  });

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <ShieldCheck size={14} /> Fund requests awaiting IA verification
        </h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">
          {rows.length} pending
        </span>
      </header>

      {rows.length === 0 ? (
        <p className="px-3 py-6 text-center text-[12px] muted italic">
          No CCEO fund requests are waiting on your verification. Approved requests appear here so the accountant can disburse once you sign off.
        </p>
      ) : (
        <>
          <p className="text-[11.5px] muted mb-2.5">
            {rows.length} approved CCEO request{rows.length === 1 ? "" : "s"} blocked at the IA gate — verify each before the accountant can disburse.
          </p>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {rows.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-2 py-2.5 text-[12px]">
                <span className="min-w-0">
                  <span className="font-bold">{r.staffName}</span>
                  <span className="muted"> · Week {r.period.weekOfMonth} · {r.period.monthLabel}</span>
                  <span className="block muted truncate">
                    {r.district} · <span className="font-mono">{formatMoney(r.requestedAmount)}</span> · {r.activities.length} activit{r.activities.length === 1 ? "y" : "ies"}
                  </span>
                </span>
                <IaFundVerifyButton reqId={r.id} label={`${r.staffName} · Week ${r.period.weekOfMonth}`} />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
