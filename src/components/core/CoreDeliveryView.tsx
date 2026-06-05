"use client";

// Shared table for core delivery surfaces — accountant payments + partner work.
// Accountant rows get an inline Confirm-pay action (the real mutation).

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Wallet, Loader2, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDemoStore } from "@/components/demo/DemoStore";
import { accountantConfirmCoreSlot } from "@/lib/actions/core-actions";
import type { CoreDeliveryRow } from "@/lib/core/core-delivery";

export function CoreDeliveryView({ rows, mode }: { rows: CoreDeliveryRow[]; mode: "accountant" | "partner" }) {
  if (rows.length === 0) {
    return <div className="card p-8 text-center text-[12px] muted italic">No partner-delivered core activities in your scope yet.</div>;
  }
  return (
    <section className="card p-3.5">
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
              <th className="py-2 pr-2">School</th>
              <th className="py-2 px-2">Activity</th>
              <th className="py-2 px-2">Partner</th>
              <th className="py-2 px-2">Salesforce</th>
              <th className="py-2 px-2">IA</th>
              <th className="py-2 px-2">{mode === "accountant" ? "Payment" : "Status"}</th>
              {mode === "accountant" && <th className="py-2 pl-2" />}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-edify-divider)]">
            {rows.map((r) => (
              <tr key={r.slotId} className="hover:bg-[var(--color-edify-soft)]/30">
                <td className="py-2 pr-2">
                  <Link href={`/core-schools/${r.schoolId}`} className="font-bold hover:underline">{r.schoolName}</Link>
                  <div className="text-[10px] muted">{r.district}</div>
                </td>
                <td className="py-2 px-2">{r.activity} <span className="muted">· {r.intervention}</span></td>
                <td className="py-2 px-2 muted">{r.partnerName ?? "—"}</td>
                <td className="py-2 px-2 tabular">{r.salesforceId ?? <span className="muted">—</span>}</td>
                <td className="py-2 px-2"><Pill v={r.iaStatus} ok={r.iaStatus === "Verified"} /></td>
                <td className="py-2 px-2">
                  {mode === "accountant"
                    ? <Pill v={r.accountantStatus === "Confirmed" ? "Confirmed" : r.paymentDue ? "Payment due" : "Awaiting IA"} ok={r.accountantStatus === "Confirmed"} warn={r.paymentDue} />
                    : <Pill v={r.slotStatus} ok={r.slotStatus === "Completed"} />}
                </td>
                {mode === "accountant" && (
                  <td className="py-2 pl-2 text-right">{r.paymentDue && <ConfirmPay slotId={r.slotId} />}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Pill({ v, ok, warn }: { v: string; ok?: boolean; warn?: boolean }) {
  return <span className={cn("inline-flex px-1.5 py-[2px] rounded text-[10px] font-bold",
    ok ? "bg-emerald-100 text-emerald-700" : warn ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600")}>{v}</span>;
}

function ConfirmPay({ slotId }: { slotId: string }) {
  const [isPending, start] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();
  return (
    <button type="button" disabled={isPending}
      onClick={() => start(async () => {
        const res = await accountantConfirmCoreSlot(slotId);
        if (res.ok) { pushToast({ tone: "success", title: "Payment confirmed", body: "Partner payment cleared." }); router.refresh(); }
        else pushToast({ tone: "warning", title: "Couldn't confirm", body: res.reason === "FORBIDDEN" ? "Accountant only." : "Try again." });
      })}
      className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-teal-600 text-white text-[11px] font-bold hover:bg-teal-700 disabled:opacity-50">
      {isPending ? <Loader2 size={11} className="animate-spin" /> : <Wallet size={11} />} Confirm
    </button>
  );
}

export function CoreDeliverySummaryCards({ summary, mode }: { summary: { total: number; paymentDue: number; confirmed: number; awaitingIa: number }; mode: "accountant" | "partner" }) {
  return (
    <section className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
      <Kpi label="Partner activities" value={summary.total} />
      {mode === "accountant" && <Kpi label="Payment due" value={summary.paymentDue} tone="text-amber-700" />}
      <Kpi label="Confirmed paid" value={summary.confirmed} tone="text-emerald-700" />
      <Kpi label="Awaiting IA" value={summary.awaitingIa} />
    </section>
  );
}
function Kpi({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="card px-3 py-2.5">
      <div className="text-[10px] font-semibold muted leading-tight">{label}</div>
      <div className={cn("text-[18px] font-extrabold tabular leading-none mt-1 inline-flex items-center gap-1", tone)}>
        {value === 0 && <CheckCircle2 size={13} className="text-emerald-500" />}{value}
      </div>
    </div>
  );
}
