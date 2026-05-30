// Status tone map used by every weekly-fund surface (Accountant, PL, Staff).
//
// Owning this in one place keeps the badge colors consistent across all
// three role views and the audit log.

import type { WeeklyFundRequestStatus } from "@/lib/funds/weekly-fund-types";

export type ToneClass = {
  // text + bg + border for chip badges
  chip: string;
  // dot color for inline status indicators
  dot: string;
  // short human label (overrides the raw enum)
  label: string;
};

export const STATUS_TONE: Record<WeeklyFundRequestStatus, ToneClass> = {
  AUTO_GENERATED:           { label: "Auto-generated",         chip: "bg-slate-100  text-slate-700  border-slate-200",  dot: "bg-slate-400" },
  DRAFT:                    { label: "Draft",                  chip: "bg-slate-100  text-slate-700  border-slate-200",  dot: "bg-slate-400" },
  SUBMITTED:                { label: "Pending Lead",           chip: "bg-amber-100  text-amber-700  border-amber-200",  dot: "bg-amber-500" },
  RETURNED_TO_STAFF:        { label: "Returned",               chip: "bg-rose-100   text-rose-700   border-rose-200",   dot: "bg-rose-500" },
  APPROVED:                 { label: "Approved",               chip: "bg-sky-100    text-sky-700    border-sky-200",    dot: "bg-sky-500" },
  CANCELLED:                { label: "Cancelled",              chip: "bg-slate-200  text-slate-700  border-slate-300",  dot: "bg-slate-500" },
  HOLD_NO_FUNDS_AVAILABLE:  { label: "Hold · No Funds",        chip: "bg-amber-100  text-amber-800  border-amber-300",  dot: "bg-amber-600" },
  BLOCKED_PRIOR_OUTSTANDING:{ label: "Blocked · Prior Open",   chip: "bg-rose-100   text-rose-700   border-rose-200",   dot: "bg-rose-500" },
  READY_TO_DISBURSE:        { label: "Ready to Disburse",      chip: "bg-emerald-100 text-emerald-700 border-emerald-200", dot: "bg-emerald-500" },
  DISBURSED:                { label: "Disbursed",              chip: "bg-emerald-100 text-emerald-800 border-emerald-200", dot: "bg-emerald-600" },
  RECEIVED:                 { label: "Received",               chip: "bg-sky-100    text-sky-800    border-sky-200",    dot: "bg-sky-600" },
  IN_USE:                   { label: "In Field",               chip: "bg-violet-100 text-violet-700 border-violet-200", dot: "bg-violet-500" },
  ACCOUNTABILITY_SUBMITTED: { label: "Accountability Pending", chip: "bg-amber-100  text-amber-700  border-amber-200",  dot: "bg-amber-500" },
  ACCOUNTABILITY_RETURNED:  { label: "Accountability Returned",chip: "bg-rose-100   text-rose-700   border-rose-200",   dot: "bg-rose-500" },
  ACCOUNTABILITY_APPROVED:  { label: "Accounted",              chip: "bg-emerald-100 text-emerald-700 border-emerald-200", dot: "bg-emerald-500" },
  CLOSED:                   { label: "Closed",                 chip: "bg-slate-100  text-slate-700  border-slate-200",  dot: "bg-slate-400" },
  ARCHIVED:                 { label: "Archived",               chip: "bg-slate-100  text-slate-600  border-slate-200",  dot: "bg-slate-400" },
};
