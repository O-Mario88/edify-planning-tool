import Link from "next/link";
import { Wallet } from "lucide-react";
import { findRequestsForStaff } from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";

// FundSlipStatusCard — dashboard section G (spec §17). The CCEO never
// calculates costs: the weekly request is auto-generated from scheduled
// activities priced by the CD cost catalogue. This card surfaces the
// CURRENT week's slip (status + total + activity count) and flags any
// slip waiting on the CCEO (draft / returned / accountability due), with
// one button into /weekly-funds to review it.

const NEEDS_ME: ReadonlySet<string> = new Set([
  "AUTO_GENERATED",
  "DRAFT",
  "RETURNED_TO_STAFF",
]);

const STATUS_LABEL: Record<string, string> = {
  AUTO_GENERATED: "Generated — review & submit",
  DRAFT: "Draft — finish & submit",
  SUBMITTED: "Submitted — with your Program Lead",
  RETURNED_TO_STAFF: "Returned — fix & resubmit",
  APPROVED: "Approved — awaiting disbursement",
};

export function FundSlipStatusCard({ staffId }: { staffId: string }) {
  const slips = findRequestsForStaff(staffId);
  if (slips.length === 0) {
    return (
      <div className="card rounded-2xl p-4">
        <h3 className="text-[16px] font-extrabold tracking-tight flex items-center gap-2">
          <Wallet className="h-4 w-4 text-[var(--color-edify-primary)]" />
          This week's fund slip
        </h3>
        <p className="muted text-[12px] mt-2">
          No fund requests yet — schedule activities in Planning and the weekly slip
          generates itself from the cost catalogue.
        </p>
      </div>
    );
  }

  // The week that needs the CCEO first; otherwise the most recent slip.
  const focus = slips.find((s) => NEEDS_ME.has(s.status)) ?? slips[slips.length - 1];
  const needsMe = NEEDS_ME.has(focus.status);

  return (
    <div className="card rounded-2xl p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[16px] font-extrabold tracking-tight flex items-center gap-2">
          <Wallet className="h-4 w-4 text-[var(--color-edify-primary)]" />
          This week's fund slip
        </h3>
        <span
          className={`text-[11px] font-bold px-2 py-0.5 rounded-md ${
            needsMe ? "bg-amber-100 text-amber-700" : "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]"
          }`}
        >
          {needsMe ? "Needs you" : "On track"}
        </span>
      </div>

      <div className="rounded-xl border border-[var(--color-edify-border)] px-3 py-2.5">
        <div className="text-[13px] font-bold text-[var(--color-edify-text)]">
          Week {focus.period.weekOfMonth} · {focus.activities.length} planned{" "}
          {focus.activities.length === 1 ? "activity" : "activities"} ·{" "}
          {formatMoney(focus.requestedAmount)}
        </div>
        <div className="muted text-[11.5px] mt-0.5">
          {STATUS_LABEL[focus.status] ?? focus.status.replaceAll("_", " ").toLowerCase()}
          {" · "}amount auto-priced from your scheduled activities + the CD cost catalogue.
        </div>
      </div>

      <Link
        href="/weekly-funds"
        className="inline-flex items-center h-9 px-3.5 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12.5px] font-bold hover:opacity-90 transition-opacity"
      >
        Review weekly fund request
      </Link>
    </div>
  );
}
