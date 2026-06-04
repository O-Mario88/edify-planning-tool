"use client";

// Staff NetSuite Accountability — Phase 8 finance closure.
//
// Activities the IA has confirmed in Salesforce (status Verified) land here for
// the accountant to close: enter the NetSuite Expense ID (digits) → the activity
// moves to AccountabilityClosed and leaves the queue. The accountant cannot act
// before IA confirmation (enforced server-side: status must be Verified).

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Receipt, CheckCircle2, Copy, Check } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { confirmActivityAccountability } from "@/lib/actions/activity-actions";
import { ID_FORMATS } from "@/lib/intake/id-formats";

export type AccountabilityRow = {
  id: string;
  title: string;
  salesforceId?: string;
  assigneeName?: string;
};

export type ClosedAccountabilityRow = {
  id: string;
  title: string;
  netsuiteExpenseId?: string;
  assigneeName?: string;
};

export function StaffAccountabilityQueue({
  rows,
  closed = [],
}: {
  rows: AccountabilityRow[];
  closed?: ClosedAccountabilityRow[];
}) {
  return (
    <section className="card rounded-2xl overflow-hidden">
      <header className="px-4 py-3 border-b border-[var(--color-edify-divider)]">
        <h2 className="text-body-lg font-extrabold tracking-tight">Staff NetSuite Accountability</h2>
        <p className="text-caption muted mt-0.5">
          IA-confirmed staff activities awaiting accountability closure. Enter the NetSuite Expense ID to close.
        </p>
      </header>
      <div className="p-3">
        {rows.length === 0 ? (
          <p className="px-3 py-8 text-center text-[12px] muted italic">Nothing awaiting accountability — all IA-confirmed activities are closed.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {rows.map((r) => <li key={r.id}><AccountabilityRowView row={r} /></li>)}
          </ul>
        )}
      </div>

      {/* Closed — echoes the EXACT NetSuite Expense ID the accountant entered
          (ID-consistency: the console shows back precisely what closed each
          activity, never a re-typed value). */}
      {closed.length > 0 && (
        <div className="border-t border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/30 p-3">
          <div className="text-[11px] font-extrabold uppercase tracking-wide muted mb-2 px-1">Recently closed · NetSuite</div>
          <ul className="flex flex-col gap-1.5">
            {closed.map((r) => (
              <li key={r.id} className="flex items-center gap-2 rounded-lg border border-[var(--color-edify-border)] bg-white px-3 py-2">
                <CheckCircle2 size={13} className="text-emerald-600 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="text-[12px] font-bold truncate">{r.title}</div>
                  <div className="text-[10.5px] muted truncate">{r.assigneeName ?? "Unassigned"} · accountability closed</div>
                </div>
                {r.netsuiteExpenseId && <NetsuiteIdChip id={r.netsuiteExpenseId} />}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

// Echo + one-click copy of the exact NetSuite Expense ID that closed an
// activity — the single source of truth, never re-typed.
function NetsuiteIdChip({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    void navigator.clipboard?.writeText(id);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }
  return (
    <button type="button" onClick={copy} title="Copy NetSuite Expense ID"
      className="inline-flex items-center gap-1 rounded-md border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/50 px-1.5 py-[2px] text-[10.5px] font-extrabold hover:bg-[var(--color-edify-soft)] shrink-0">
      <span className="muted font-bold">NS:</span>
      <span className="font-mono">{id}</span>
      {copied ? <Check size={11} className="text-emerald-600" /> : <Copy size={11} className="text-[var(--color-edify-muted)]" />}
    </button>
  );
}

function AccountabilityRowView({ row }: { row: AccountabilityRow }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const [nsId, setNsId] = useState("");
  const [copied, setCopied] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  function copySf() {
    if (!row.salesforceId) return;
    void navigator.clipboard?.writeText(row.salesforceId);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  function submit() {
    setMsg(null);
    start(async () => {
      const res = await confirmActivityAccountability(row.id, nsId);
      if (res.ok) {
        setMsg("Accountability closed.");
        router.refresh();
        setTimeout(() => setOpen(false), 900);
      } else {
        setMsg(res.reason === "INVALID_INPUT" ? `NetSuite ID must be ${ID_FORMATS.expense.hint}.`
          : res.reason === "FORBIDDEN" ? "Only the accountant can close accountability."
          : `Could not close (${res.reason}).`);
      }
    });
  }

  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3 flex items-center gap-3 flex-wrap">
      <div className="flex-1 min-w-0">
        <div className="text-body font-extrabold tracking-tight truncate">{row.title}</div>
        <div className="text-caption muted mt-0.5 truncate">{row.assigneeName ?? "Unassigned"} · IA confirmed</div>
        {row.salesforceId && (
          <button type="button" onClick={copySf} title="Copy Salesforce ID"
            className="mt-1 inline-flex items-center gap-1 rounded-md border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/50 px-1.5 py-[2px] text-[10.5px] font-extrabold hover:bg-[var(--color-edify-soft)]">
            <span className="muted font-bold">SF:</span>
            <span className="font-mono">{row.salesforceId}</span>
            {copied ? <Check size={11} className="text-emerald-600" /> : <Copy size={11} className="text-[var(--color-edify-muted)]" />}
          </button>
        )}
      </div>
      <Button variant="primary" size="sm" Icon={Receipt} onClick={() => setOpen(true)}>Confirm accountability</Button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Confirm NetSuite accountability"
        description={`Enter the NetSuite Expense ID for "${row.title}". This closes accountability and removes it from the queue.`}
        variant="drawer-right"
        size="md"
        footer={
          <div className="flex items-center justify-between gap-3 w-full">
            <span className="text-[11px] muted truncate">{msg}</span>
            <div className="flex items-center gap-2 shrink-0">
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)} disabled={pending}>Cancel</Button>
              <Button variant="primary" size="sm" onClick={submit} disabled={pending || !nsId.trim()} Icon={CheckCircle2}>
                {pending ? "Closing…" : "Close accountability"}
              </Button>
            </div>
          </div>
        }
      >
        <Input label="NetSuite Expense ID" placeholder={`e.g. ${ID_FORMATS.expense.example}`} helper={ID_FORMATS.expense.hint}
          value={nsId} onChange={(e) => setNsId(e.target.value)} />
      </Modal>
    </div>
  );
}
