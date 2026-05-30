"use client";

import {
  AlertCircle,
  ArrowUpRight,
  Banknote,
  Building2,
  CheckCircle2,
  CornerDownLeft,
  Eye,
  Smartphone,
  Wallet,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { balanceReturnQueue, type BalanceReturnRow } from "@/lib/accountant-console-mock";
import { cn } from "@/lib/utils";
import { useUrlState } from "@/hooks/use-url-state";

// All BalanceReturn statuses are single-word, so the status string is
// already a valid URL slug. Kept lowercase in the URL for tidiness.
const TAB_DEFS = [
  { slug: "all",       label: "All",       status: null },
  { slug: "pending",   label: "Pending",   status: "Pending"   as const },
  { slug: "confirmed", label: "Confirmed", status: "Confirmed" as const },
  { slug: "disputed",  label: "Disputed",  status: "Disputed"  as const },
] as const;
type TabSlug = (typeof TAB_DEFS)[number]["slug"];
const TAB_SLUGS = TAB_DEFS.map((t) => t.slug) as readonly TabSlug[];

const STATUS_TONE: Record<BalanceReturnRow["status"], string> = {
  Pending:   "bg-amber-100   text-amber-700   border-amber-200",
  Confirmed: "bg-emerald-100 text-emerald-700 border-emerald-200",
  Disputed:  "bg-rose-100    text-rose-700    border-rose-200",
};

const METHOD_ICON: Record<NonNullable<BalanceReturnRow["method"]>, LucideIcon> = {
  MobileMoney:               Smartphone,
  Bank:                      Building2,
  Cash:                      Wallet,
  OffsetAgainstNextRequest:  CornerDownLeft,
};

const METHOD_LABEL: Record<NonNullable<BalanceReturnRow["method"]>, string> = {
  MobileMoney:               "Mobile Money",
  Bank:                      "Bank",
  Cash:                      "Cash",
  OffsetAgainstNextRequest:  "Offset · next request",
};

// Balance Return Queue.
//
// Auto-created when the staff's reconciled spend is *less* than the
// advance. The staff member then declares the return method (MoMo,
// Bank, Cash, or offset against the next approved request). The
// accountant confirms the return — only then does the originating
// accountability close.
export function BalanceReturnQueue() {
  const [activeSlug, setActiveSlug] = useUrlState<TabSlug>({
    key: "tab",
    defaultValue: "all",
    allowed: TAB_SLUGS,
  });
  const tabs = TAB_DEFS.map((t) => ({
    slug: t.slug,
    label: t.label,
    count: t.status == null
      ? balanceReturnQueue.length
      : balanceReturnQueue.filter((r) => r.status === t.status).length,
  }));
  const activeStatus = TAB_DEFS.find((t) => t.slug === activeSlug)?.status ?? null;
  const rows = activeStatus == null
    ? balanceReturnQueue
    : balanceReturnQueue.filter((r) => r.status === activeStatus);

  const totalPending = balanceReturnQueue
    .filter((r) => r.status === "Pending")
    .reduce((a, r) => a + r.balanceToReturnUgx, 0);

  return (
    <article className="card p-5 lg:p-6 flex flex-col h-full overflow-hidden">
      <header className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div className="min-w-0">
          <h3 className="text-[14.5px] font-extrabold tracking-tight text-slate-900 inline-flex items-center gap-1.5">
            <CornerDownLeft size={14} className="text-amber-600" />
            Balance Return Queue
          </h3>
          <p className="text-caption muted font-semibold mt-0.5">
            Auto-created when reconciled spend &lt; advanced — staff confirms return method
          </p>
        </div>
        <div className="px-2.5 py-1 rounded-lg bg-amber-50 border border-amber-200">
          <div className="text-[9.5px] muted font-extrabold uppercase tracking-[0.1em] text-amber-700">
            Pending Return
          </div>
          <div className="text-[13px] font-extrabold tabular num-hero text-amber-700 leading-none mt-0.5">
            UGX {(totalPending / 1_000_000).toFixed(2)}M
          </div>
        </div>
      </header>

      <nav className="flex items-center gap-1.5 mb-3 overflow-x-auto pb-1 -mx-1 px-1">
        {tabs.map((t) => {
          const isActive = t.slug === activeSlug;
          return (
            <button
              key={t.slug}
              type="button"
              onClick={() => setActiveSlug(t.slug)}
              aria-pressed={isActive}
              className={cn(
                "h-8 px-3 rounded-lg text-[11.5px] font-extrabold whitespace-nowrap inline-flex items-center gap-1.5 transition-all duration-200",
                isActive
                  ? "bg-slate-900 text-white shadow-[0_8px_18px_-8px_rgba(15,23,32,0.4)]"
                  : "bg-white text-slate-600 border border-[var(--color-edify-border)] hover:bg-slate-50 hover:border-slate-300",
              )}
            >
              {t.label}
              <span
                className={cn(
                  "inline-flex items-center justify-center min-w-[18px] h-[16px] px-1 rounded-md text-[9.5px] font-extrabold",
                  isActive ? "bg-white/15 text-white" : "bg-slate-100 text-slate-700",
                )}
              >
                {t.count}
              </span>
            </button>
          );
        })}
      </nav>

      <ul className="flex flex-col gap-2 flex-1">
        {rows.length === 0 && (
          <li className="text-[12px] muted italic py-8 text-center">
            No balance returns match this filter.
          </li>
        )}
        {rows.map((row, i) => {
          const isPending = row.status === "Pending";
          const isConfirmed = row.status === "Confirmed";
          const MethodIcon = row.method ? METHOD_ICON[row.method] : undefined;
          return (
            <li
              key={row.id}
              className={cn(
                "rounded-xl border p-3 flex flex-col gap-2 card-lift tile-in min-w-0",
                isPending
                  ? "border-amber-200 bg-amber-50/30"
                  : isConfirmed
                    ? "border-emerald-100 bg-emerald-50/30"
                    : "border-rose-200 bg-rose-50/40",
                `stagger-${(i % 6) + 1}`,
              )}
            >
              <div className="flex items-start gap-2.5 flex-wrap">
                <span
                  className={cn(
                    "w-9 h-9 rounded-full grid place-items-center text-[11px] font-extrabold text-white shrink-0 bg-gradient-to-br shadow-[0_4px_10px_-4px_rgba(15,23,32,0.35)]",
                    isPending ? "from-amber-400 to-amber-600"
                      : isConfirmed ? "from-emerald-400 to-emerald-600"
                        : "from-rose-400 to-rose-600",
                  )}
                >
                  {row.initials}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-body font-extrabold text-slate-900 truncate">
                      {row.staff}
                    </span>
                    <span className="text-[10px] muted font-semibold">({row.staffRole})</span>
                  </div>
                  <div className="text-[11px] text-slate-700 font-semibold truncate mt-0.5">
                    {row.weekLabel}
                  </div>
                  <div className="text-[10px] muted font-semibold truncate tabular">
                    {row.id} · created {row.createdAt} ·{" "}
                    <span className="text-sky-700 font-extrabold">{row.netsuiteExpenseId}</span>
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-body-lg font-extrabold tabular num-hero text-slate-900 leading-none glow-amber">
                    UGX {(row.balanceToReturnUgx / 1_000_000).toFixed(2)}M
                  </div>
                  <div className="text-[9.5px] muted font-semibold mt-1">
                    to return
                  </div>
                </div>
              </div>

              {/* Decomposition strip */}
              <div className="grid grid-cols-3 gap-1.5">
                <Mini label="Advanced" value={row.amountAdvancedUgx} tone="slate" />
                <Mini label="Spent"    value={row.amountSpentUgx}    tone="sky" />
                <Mini label="Returning" value={row.balanceToReturnUgx} tone="amber" />
              </div>

              {/* Return method (when set) */}
              {row.method && MethodIcon && (
                <div className="rounded-lg border border-emerald-200 bg-white px-2.5 py-1.5 flex items-center gap-2">
                  <span className="w-6 h-6 rounded-md grid place-items-center bg-emerald-100">
                    <MethodIcon size={12} className="text-emerald-600" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-caption font-extrabold text-slate-900">
                      Returned via {METHOD_LABEL[row.method]}
                    </div>
                    {row.reference && (
                      <div className="text-[10px] muted font-semibold tabular truncate">
                        ref · {row.reference}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Action row */}
              <div className="flex items-center justify-between gap-2 flex-wrap pt-1 border-t border-dashed border-[var(--color-edify-divider)]">
                <span
                  className={cn(
                    "inline-flex items-center px-2 py-[3px] rounded-full text-[10px] font-extrabold border whitespace-nowrap",
                    STATUS_TONE[row.status],
                  )}
                >
                  {row.status === "Confirmed" ? (
                    <CheckCircle2 size={10} className="mr-1" />
                  ) : row.status === "Disputed" ? (
                    <AlertCircle size={10} className="mr-1" />
                  ) : null}
                  {row.status}
                </span>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 h-7 px-2 rounded-md bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-caption font-extrabold text-slate-700"
                  >
                    <Eye size={11} />
                    Review
                  </button>
                  {isPending && (
                    <>
                      <button
                        type="button"
                        title="Mark balance return confirmed"
                        className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md bg-emerald-600 hover:bg-emerald-700 text-white text-caption font-extrabold shadow-[0_6px_14px_-6px_rgba(16,185,129,0.55)]"
                      >
                        <CheckCircle2 size={11} />
                        Confirm Return
                      </button>
                      <button
                        type="button"
                        title="Flag dispute (amount or method incorrect)"
                        className="inline-flex items-center justify-center w-7 h-7 rounded-md bg-white border border-rose-200 hover:bg-rose-50 text-rose-600"
                      >
                        <XCircle size={11} />
                      </button>
                    </>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <a
        href="#balance-returns-all"
        className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-extrabold text-sky-700 hover:text-sky-800"
      >
        View All balance returns
        <ArrowUpRight size={11} />
      </a>
    </article>
  );
}

function Mini({
  label, value, tone,
}: {
  label: string;
  value: number;
  tone: "slate" | "sky" | "amber";
}) {
  const palette: Record<string, string> = {
    slate: "bg-slate-50 text-slate-700",
    sky:   "bg-sky-50    text-sky-700",
    amber: "bg-amber-50  text-amber-700",
  };
  return (
    <div className={cn("rounded-lg px-2 py-1.5", palette[tone])}>
      <div className="text-[9.5px] font-extrabold uppercase tracking-[0.08em] opacity-80">
        {label}
      </div>
      <div className="text-[12px] font-extrabold tabular num-hero leading-none mt-0.5 inline-flex items-center gap-1">
        <Banknote size={10} className="opacity-70" />
        UGX {(value / 1_000_000).toFixed(2)}M
      </div>
    </div>
  );
}
