"use client";

import { ArrowUpRight } from "lucide-react";
import {
  rvpApprovalComments,
  rvpRecentRequests,
  type RvpApprovalComment,
  type RvpRecentRequest,
} from "@/lib/rvp-fund-approvals-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<RvpRecentRequest["status"], string> = {
  "Pending":      "bg-amber-100   text-amber-700",
  "Approved":     "bg-emerald-100 text-emerald-700",
  "Under Review": "bg-sky-100     text-sky-700",
};

const CATEGORY_TONE: Record<RvpRecentRequest["category"], string> = {
  "Staff Visits": "bg-blue-50    text-blue-700    border-blue-200",
  "Cluster":      "bg-violet-50  text-violet-700  border-violet-200",
  "Training":     "bg-rose-50    text-rose-700    border-rose-200",
};

// Two-card row at the bottom of the detail view:
//   LEFT  — Recent Fund Requests (3 rows)
//   RIGHT — Approvals & Comments (2 comment threads)
export function RvpDetailFooter() {
  return (
    <section className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
      <div className="col-span-12 lg:col-span-7">
        <RecentRequestsCard />
      </div>
      <div className="col-span-12 lg:col-span-5">
        <ApprovalsCommentsCard />
      </div>
    </section>
  );
}

function RecentRequestsCard() {
  return (
    <article className="card p-3.5 h-full flex flex-col">
      <header className="flex items-center justify-between gap-2 mb-2.5">
        <h3 className="text-[13px] font-extrabold tracking-tight">Recent Fund Requests</h3>
        <a href="#requests-all" className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)]">
          View All
          <ArrowUpRight size={10} />
        </a>
      </header>
      <ul className="flex flex-col gap-2">
        {rvpRecentRequests.map((r, i) => {
          const stagger = ["stagger-1","stagger-2","stagger-3"][i] ?? "";
          return (
            <li
              key={r.id}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] bg-white px-3 py-2.5 flex items-center gap-3 tile-in card-lift cursor-pointer",
                stagger,
              )}
            >
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-extrabold text-slate-900 truncate">
                  {r.title} <span className="text-slate-400 font-medium">—</span> <span className="text-slate-600 font-semibold">{r.scope}</span>
                </div>
              </div>
              <span className={cn("inline-flex items-center px-2 py-[2px] rounded-md text-[10px] font-semibold border whitespace-nowrap", CATEGORY_TONE[r.category])}>
                {r.category}
              </span>
              <span className="text-body font-extrabold tabular text-slate-900 shrink-0 num-hero w-[80px] text-right">{r.amount}</span>
              <span className={cn("inline-flex items-center px-2 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", STATUS_TONE[r.status])}>
                {r.status}
              </span>
              <span className="text-caption muted font-semibold tabular shrink-0 w-[44px] text-right">{r.date}</span>
            </li>
          );
        })}
      </ul>
    </article>
  );
}

function ApprovalsCommentsCard() {
  return (
    <article className="card p-3.5 h-full flex flex-col">
      <h3 className="text-[13px] font-extrabold tracking-tight mb-2.5">Approvals & Comments</h3>
      <ul className="flex flex-col gap-2.5">
        {rvpApprovalComments.map((c, i) => (
          <CommentRow key={c.id} c={c} stagger={["stagger-1","stagger-2"][i] ?? ""} />
        ))}
      </ul>
    </article>
  );
}

function CommentRow({ c, stagger }: { c: RvpApprovalComment; stagger: string }) {
  const isMe = c.role === "RVP";
  return (
    <li className={cn("flex items-start gap-2.5 tile-in", stagger)}>
      <span className={cn(
        "w-8 h-8 rounded-full grid place-items-center text-[11px] font-extrabold text-white shrink-0 shadow-sm",
        isMe
          ? "bg-gradient-to-br from-emerald-500 to-emerald-700"
          : "bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f]",
      )}>
        {c.initials}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-1.5 flex-wrap">
          <span className="text-[12px] font-extrabold text-slate-900">{c.who}</span>
          <span className="text-[10px] muted font-semibold">({c.role})</span>
          {c.badge && (
            <span className="inline-flex items-center px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold bg-emerald-100 text-emerald-700">
              ✓ {c.badge}
            </span>
          )}
          <span className="text-[10px] muted font-semibold ml-auto">{c.when}</span>
        </div>
        <p className="text-[11.5px] text-slate-700 leading-snug mt-0.5">{c.message}</p>
      </div>
    </li>
  );
}
