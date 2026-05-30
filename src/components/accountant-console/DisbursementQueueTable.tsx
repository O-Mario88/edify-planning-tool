"use client";

import { useMemo, useState } from "react";
import {
  ArrowUpDown,
  Banknote,
  Building2,
  CheckCircle2,
  ChevronDown,
  Filter,
  MoreHorizontal,
  PauseCircle,
  Send,
  Smartphone,
  Split,
  Wallet,
  X,
} from "lucide-react";
import {
  queueRows,
  type QueueRow,
} from "@/lib/accountant-console-mock";
import { cn } from "@/lib/utils";
import { useUrlState } from "@/hooks/use-url-state";

const PRIORITY_TONE: Record<QueueRow["priority"], { pill: string; dot: string }> = {
  High:   { pill: "bg-rose-50   text-rose-700   ring-1 ring-rose-200/70",   dot: "bg-rose-500" },
  Medium: { pill: "bg-amber-50  text-amber-700  ring-1 ring-amber-200/70", dot: "bg-amber-500" },
  Low:    { pill: "bg-slate-50  text-slate-600  ring-1 ring-slate-200/70", dot: "bg-slate-400" },
};

const STATUS_TONE: Record<QueueRow["status"], { pill: string; dot: string }> = {
  Ready:    { pill: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200/70", dot: "bg-emerald-500" },
  Partial:  { pill: "bg-amber-50   text-amber-700   ring-1 ring-amber-200/70",   dot: "bg-amber-500" },
  "On Hold":{ pill: "bg-rose-50    text-rose-700    ring-1 ring-rose-200/70",    dot: "bg-rose-500" },
};

const TABS = [
  { key: "all",     label: "All",               match: (_: QueueRow) => true },
  { key: "ready",   label: "Ready to Disburse", match: (r: QueueRow) => r.status === "Ready" },
  { key: "partial", label: "Partial",           match: (r: QueueRow) => r.status === "Partial" },
  { key: "hold",    label: "On Hold",           match: (r: QueueRow) => r.status === "On Hold" },
  { key: "high",    label: "High Priority",     match: (r: QueueRow) => r.priority === "High" },
] as const;

type TabKey = (typeof TABS)[number]["key"];
const TAB_KEYS = TABS.map((t) => t.key) as readonly TabKey[];

type SortKey = "priority" | "amount" | "approvedOn";
const SORT_KEYS = ["priority", "amount", "approvedOn"] as const;
const SORT_LABEL: Record<SortKey, string> = {
  priority:   "Priority",
  amount:     "Amount",
  approvedOn: "Most recent",
};
const PRIORITY_RANK: Record<QueueRow["priority"], number> = { High: 0, Medium: 1, Low: 2 };

// Disbursement Queue — primary work surface.
//
// Each row in the table is now an inline-expandable accordion: clicking
// the chevron / "Disburse" reveals a detail panel beneath the row with
// the request breakdown + a compact disburse form so the Accountant can
// confirm release without leaving the table.
export function DisbursementQueueTable() {
  const [activeTab, setActiveTab] = useUrlState<TabKey>({
    key: "tab",
    defaultValue: "all",
    allowed: TAB_KEYS,
  });
  const [sortBy, setSortBy] = useUrlState<SortKey>({
    key: "sort",
    defaultValue: "priority",
    allowed: SORT_KEYS,
  });
  const [openRowId, setOpenRowId] = useState<string | null>(null);

  const tabCounts = useMemo(
    () => TABS.map((t) => ({ key: t.key, label: t.label, count: queueRows.filter(t.match).length })),
    [],
  );

  const rows = useMemo(() => {
    const tab = TABS.find((t) => t.key === activeTab) ?? TABS[0];
    const filtered = queueRows.filter(tab.match);
    const sorted = [...filtered];
    sorted.sort((a, b) => {
      if (sortBy === "amount") return b.amountUgx - a.amountUgx;
      if (sortBy === "approvedOn") return b.approvedOn.localeCompare(a.approvedOn);
      return PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority];
    });
    return sorted;
  }, [activeTab, sortBy]);

  const nextSort: Record<SortKey, SortKey> = {
    priority:   "amount",
    amount:     "approvedOn",
    approvedOn: "priority",
  };

  return (
    <article className="card p-5 lg:p-6 flex flex-col h-full overflow-hidden">
      <header className="flex items-center justify-between gap-3 mb-3 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <h3 className="text-[14.5px] font-extrabold tracking-tight text-slate-900">
            Disbursement Queue
          </h3>
          <span className="inline-flex items-center justify-center min-w-[22px] h-[20px] px-1.5 rounded-md text-caption font-extrabold bg-slate-900 text-white shadow-[0_4px_10px_-4px_rgba(15,23,32,0.45)]">
            {rows.length}
          </span>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          <button
            type="button"
            onClick={() => setSortBy(nextSort[sortBy])}
            title={`Sort by ${SORT_LABEL[nextSort[sortBy]]}`}
            className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-[11.5px] font-semibold text-slate-700 shadow-sm"
          >
            <ArrowUpDown size={11} className="text-slate-400" />
            <span className="text-slate-500">Sort by:</span>
            <span className="font-extrabold text-slate-700">{SORT_LABEL[sortBy]}</span>
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-[11.5px] font-semibold text-slate-700 shadow-sm"
          >
            <Filter size={11} className="text-slate-400" />
            Filters
          </button>
        </div>
      </header>

      <nav className="flex items-center gap-1.5 mb-3 overflow-x-auto pb-1 -mx-1 px-1">
        {tabCounts.map((t) => {
          const active = t.key === activeTab;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setActiveTab(t.key)}
              aria-pressed={active}
              className={cn(
                "h-8 px-3 rounded-lg text-[11.5px] font-extrabold whitespace-nowrap inline-flex items-center gap-1.5 transition-all duration-200",
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
                {t.count}
              </span>
            </button>
          );
        })}
      </nav>

      <div className="overflow-x-auto -mx-1 px-1">
        <table className="w-full min-w-[760px]">
          <thead>
            <tr className="text-[9.5px] text-slate-500 font-extrabold uppercase tracking-[0.08em] border-b border-[var(--color-edify-divider)]">
              <th scope="col" className="w-[28px]" />
              <th scope="col" className="text-left  py-2.5 pr-3">Priority</th>
              <th scope="col" className="text-left  py-2.5 pr-3">Request ID</th>
              <th scope="col" className="text-left  py-2.5 pr-3">Requester</th>
              <th scope="col" className="text-left  py-2.5 pr-3">Activity / Purpose</th>
              <th scope="col" className="text-right py-2.5 pr-3">Amount (UGX)</th>
              <th scope="col" className="text-left  py-2.5 pr-3">Approved By</th>
              <th scope="col" className="text-left  py-2.5 pr-3">Approved On</th>
              <th scope="col" className="text-left  py-2.5 pr-3">Status</th>
              <th scope="col" className="text-right py-2.5 w-[80px]">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={10} className="py-10 text-center text-[12px] muted italic">
                  No requests match this filter.
                </td>
              </tr>
            )}
            {rows.map((r, i) => {
              const stagger = `stagger-${(i % 6) + 1}`;
              const priority = PRIORITY_TONE[r.priority];
              const status = STATUS_TONE[r.status];
              const open = openRowId === r.requestId;
              const onHold = r.status === "On Hold";
              const onToggle = () => setOpenRowId(open ? null : r.requestId);
              return (
                <RowFragment
                  key={r.requestId}
                  r={r}
                  open={open}
                  onHold={onHold}
                  onToggle={onToggle}
                  priority={priority}
                  status={status}
                  stagger={stagger}
                  onConfirm={() => setOpenRowId(null)}
                />
              );
            })}
          </tbody>
        </table>
      </div>

      <a
        href="#all-requests"
        className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-extrabold text-sky-700 hover:text-sky-800"
      >
        View All {rows.length} requests →
      </a>
    </article>
  );
}

function RowFragment({
  r,
  open,
  onHold,
  onToggle,
  priority,
  status,
  stagger,
  onConfirm,
}: {
  r: QueueRow;
  open: boolean;
  onHold: boolean;
  onToggle: () => void;
  priority: { pill: string; dot: string };
  status: { pill: string; dot: string };
  stagger: string;
  onConfirm: () => void;
}) {
  const panelId = `disb-${r.requestId}-detail`;
  return (
    <>
      <tr
        className={cn(
          "border-b border-[#F4F6F8] hover:bg-slate-50/60 transition-colors tile-in cursor-pointer",
          stagger,
          open && "tr-active-glow",
        )}
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={panelId}
      >
        <td className="py-3 pl-1 align-top">
          <ChevronDown
            size={13}
            className={cn("text-slate-400 transition-transform", open && "rotate-180")}
            aria-hidden
          />
        </td>
        <td className="py-3 pr-3">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 pl-1.5 pr-2 py-[2px] rounded-md text-[10px] font-extrabold",
              priority.pill,
            )}
          >
            <span className={cn("w-1.5 h-1.5 rounded-full", priority.dot)} />
            {r.priority}
          </span>
        </td>
        <td className="py-3 pr-3">
          <span className="text-[11.5px] font-extrabold text-sky-700 tabular whitespace-nowrap">
            {r.requestId}
          </span>
        </td>
        <td className="py-3 pr-3 text-[11.5px] font-semibold text-slate-700 whitespace-nowrap">
          {r.requester}{" "}
          <span className="text-slate-400 font-semibold">({r.requesterRole})</span>
        </td>
        <td className="py-3 pr-3 text-[11.5px] text-slate-700 max-w-[220px] truncate">
          {r.activity}
        </td>
        <td className="py-3 pr-3 text-right text-body font-extrabold tabular num-hero text-slate-900 whitespace-nowrap">
          {r.amountUgx.toLocaleString()}
        </td>
        <td className="py-3 pr-3 text-[11.5px] font-semibold text-slate-700 whitespace-nowrap">
          {r.approvedBy}{" "}
          <span className="text-slate-400 font-semibold">({r.approverRole})</span>
        </td>
        <td className="py-3 pr-3 text-[11px] text-slate-500 font-semibold whitespace-nowrap">
          {r.approvedOn}
        </td>
        <td className="py-3 pr-3">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 pl-1.5 pr-2 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
              status.pill,
            )}
          >
            <span className={cn("w-1.5 h-1.5 rounded-full", status.dot)} />
            {r.status}
          </span>
        </td>
        <td className="py-3 text-right">
          <div className="inline-flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              title={open ? "Close" : "Disburse"}
              disabled={onHold}
              onClick={onToggle}
              className={cn(
                "inline-flex items-center justify-center w-7 h-7 rounded-md text-white transition-all",
                onHold
                  ? "bg-slate-200 text-slate-400 cursor-not-allowed"
                  : open
                    ? "bg-slate-700"
                    : "bg-slate-900 hover:bg-slate-800 hover:-translate-y-0.5 shadow-[0_4px_10px_-4px_rgba(15,23,32,0.5)]",
              )}
            >
              {open ? <X size={11} /> : <Send size={11} strokeWidth={2.2} />}
            </button>
            <button
              type="button"
              aria-label="More"
              className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 hover:border-slate-300 text-slate-500 transition-colors"
            >
              <MoreHorizontal size={12} />
            </button>
          </div>
        </td>
      </tr>

      {open && (
        <tr id={panelId} className="border-b border-[#F4F6F8] tr-active-glow-body">
          <td colSpan={10} className="p-0">
            <DisburseInlinePanel r={r} onConfirm={onConfirm} />
          </td>
        </tr>
      )}
    </>
  );
}

function DisburseInlinePanel({ r, onConfirm }: { r: QueueRow; onConfirm: () => void }) {
  const [method, setMethod] = useState<"MobileMoney" | "BankTransfer" | "Cash" | "Cheque">("MobileMoney");
  const [reference, setReference] = useState("");
  const [amount, setAmount] = useState(r.amountUgx);
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [notes, setNotes] = useState("");
  const validRef = reference.trim().length >= 4;
  const validAmt = amount > 0 && amount <= r.amountUgx;
  const canSubmit = validRef && validAmt && r.status !== "On Hold";
  return (
    <div className="px-5 lg:px-6 py-4 flex flex-col gap-3 border-l-[3px] border-slate-300">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-[11.5px]">
        <Detail label="Request total" value={`UGX ${r.amountUgx.toLocaleString()}`} strong />
        <Detail label="Approved by" value={`${r.approvedBy} · ${r.approverRole}`} />
        <Detail label="Approved on" value={r.approvedOn} />
      </div>

      <div className="rounded-xl bg-white border border-slate-200/70 p-3 flex flex-col gap-2.5">
        <h4 className="text-[12px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <Send size={11} className="text-slate-600" />
          Confirm disbursement
        </h4>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Amount (UGX)">
            <input
              type="number"
              min={1}
              value={amount}
              onChange={(e) => setAmount(Number(e.target.value))}
              className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[13px] font-extrabold tabular text-slate-900 outline-none focus:ring-2 focus:ring-slate-400"
            />
            {!validAmt && (
              <span className="mt-1 inline-flex items-center gap-1 text-[10px] text-rose-700 font-semibold">
                Amount must be ≤ {r.amountUgx.toLocaleString()}
              </span>
            )}
          </Field>
          <Field label="Date">
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold text-slate-700 outline-none focus:ring-2 focus:ring-slate-400"
            />
          </Field>
          <Field label="Payment method" fullWidth>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
              <MethodBtn label="Mobile Money" Icon={Smartphone} active={method === "MobileMoney"} onClick={() => setMethod("MobileMoney")} />
              <MethodBtn label="Bank"         Icon={Building2}  active={method === "BankTransfer"} onClick={() => setMethod("BankTransfer")} />
              <MethodBtn label="Cash"         Icon={Wallet}     active={method === "Cash"}         onClick={() => setMethod("Cash")} />
              <MethodBtn label="Cheque"       Icon={Banknote}   active={method === "Cheque"}       onClick={() => setMethod("Cheque")} />
            </div>
          </Field>
          <Field label="Transaction reference *" fullWidth>
            <input
              type="text"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="M-Pesa code · bank ref · cheque #"
              className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold text-slate-700 outline-none focus:ring-2 focus:ring-slate-400"
            />
          </Field>
          <Field label="Notes" fullWidth>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Optional"
              className="w-full min-h-[56px] px-2.5 py-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] text-slate-700 outline-none focus:ring-2 focus:ring-slate-400"
            />
          </Field>
        </div>

        <footer className="flex items-center justify-end gap-2">
          <button
            type="button"
            title="Mark as partial"
            className="inline-flex items-center gap-1 h-8 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-[11.5px] font-semibold text-slate-700"
          >
            <Split size={11} /> Mark Partial
          </button>
          <button
            type="button"
            title="Hold"
            className="inline-flex items-center gap-1 h-8 px-2.5 rounded-lg border border-amber-200 bg-amber-50 hover:bg-amber-100 text-amber-700 text-[11.5px] font-extrabold"
          >
            <PauseCircle size={11} /> Hold
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={!canSubmit}
            className={cn(
              "inline-flex items-center gap-1.5 h-9 px-3 rounded-lg text-[12px] font-extrabold transition-colors",
              canSubmit
                ? "bg-slate-900 hover:bg-slate-800 text-white shadow-[0_10px_28px_-12px_rgba(15,23,32,0.45)]"
                : "bg-slate-100 text-slate-400 cursor-not-allowed",
            )}
          >
            <CheckCircle2 size={12} />
            Mark Disbursed
          </button>
        </footer>
      </div>
    </div>
  );
}

function Detail({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <div className="text-[9.5px] muted font-bold uppercase tracking-wide">{label}</div>
      <div className={cn(
        "mt-0.5",
        strong ? "text-[13px] font-extrabold tabular text-slate-900 num-hero" : "font-semibold text-slate-700",
      )}>
        {value}
      </div>
    </div>
  );
}

function Field({
  label,
  children,
  fullWidth,
}: {
  label: string;
  children: React.ReactNode;
  fullWidth?: boolean;
}) {
  return (
    <section className={cn(fullWidth && "sm:col-span-2")}>
      <label className="block text-[11px] font-extrabold text-slate-700 mb-1">
        {label}
      </label>
      {children}
    </section>
  );
}

function MethodBtn({
  label, Icon, active, onClick,
}: {
  label: string;
  Icon: typeof Smartphone;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "h-10 px-2 rounded-lg border text-[11.5px] font-extrabold flex items-center justify-center gap-1.5 transition-colors",
        active
          ? "border-slate-900 bg-slate-900 text-white"
          : "border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-slate-700",
      )}
    >
      <Icon size={12} />
      {label}
    </button>
  );
}
