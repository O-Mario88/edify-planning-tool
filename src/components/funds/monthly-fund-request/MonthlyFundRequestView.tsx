"use client";

// Monthly Fund Request — composed view.
//
// Stitches the header, validation, staff filter, weekly summary strip,
// the matrix (in one of two view modes), admin budget, and the
// drilldown drawer.
//
// Role-aware visibility (matches the policy spec):
//   • PL  — sees ONLY the program activity slice. No admin budget,
//           no admin totals. PL submits the program plan; CD adds
//           administration budget items AFTER PL approval.
//   • CD  — sees the full program plan plus the admin budget editor.
//           CD adds rent / airtime / etc., then submits to RVP.
//   • RVP — sees the full request (program + admin), but only AFTER
//           CD approval. Approves / returns / holds.
//   • Accountant — sees the full RVP-approved request and inherits
//           it for disbursement + accountability follow-up.
//
// State owned here:
//   • Approval state + admin item edits (server-action round-trip in production).
//   • View-mode selection (summary vs. detail).
//   • Staff filter selection.
//   • Selected-week filter shared between the strip + summary table.

import { useMemo, useState } from "react";
import { CalendarDays, Table } from "lucide-react";
import { MobileMonthlyFundRequest } from "./MobileMonthlyFundRequest";
import {
  MonthlyFundRequestHeader,
  type MfrViewerRole,
} from "./MonthlyFundRequestHeader";
import {
  MonthlyFundRequestMatrix,
  type MfrCellTarget,
} from "./MonthlyFundRequestMatrix";
import { ActivityWeekSummary } from "./ActivityWeekSummary";
import {
  WeeklyTotalsStrip,
  type WeekSelection,
} from "./WeeklyTotalsStrip";
import { AdminBudgetSection } from "./AdminBudgetSection";
import { ValidationWarnings } from "./ValidationWarnings";
import { CellDrilldownDrawer } from "./CellDrilldownDrawer";
import { MfrStaffFilter } from "./MfrStaffFilter";
import {
  POST_CD_APPROVAL_STATUSES,
  type MfrAdminItem,
  type MonthlyFundRequest,
  type MonthlyFundRequestStatus,
} from "@/lib/funds/monthly-fund-request-types";
import { computeActivityWeekMatrix } from "@/lib/funds/mfr-activity-week";
import { cn } from "@/lib/utils";

type ViewMode = "summary" | "detail";

// PL never sees admin items or admin totals — only the program slice
// they are responsible for approving. CD layers admin on top after PL
// approval, then routes the package to RVP.
function adminVisibleFor(role: MfrViewerRole): boolean {
  return role !== "PL";
}

export function MonthlyFundRequestView({
  initial,
  viewerRole,
}: {
  initial: MonthlyFundRequest;
  viewerRole: MfrViewerRole;
}) {
  const [mfr, setMfr] = useState<MonthlyFundRequest>(initial);
  const [target, setTarget] = useState<MfrCellTarget | null>(null);
  const [selectedWeek, setSelectedWeek] = useState<WeekSelection>(null);
  const [selectedStaffIds, setSelectedStaffIds] = useState<string[]>([]);

  const [viewMode, setViewMode] = useState<ViewMode>(
    viewerRole === "PL" ? "detail" : "summary",
  );

  const showAdmin = adminVisibleFor(viewerRole);

  // Role-scoped MFR. PL gets a slice with adminItems stripped + totals
  // recomputed to the program subset; every other role sees the full
  // request. The original `mfr` stays intact so admin edits round-trip
  // cleanly.
  const roleMfr: MonthlyFundRequest = useMemo(() => {
    if (showAdmin) return mfr;
    return {
      ...mfr,
      adminItems: [],
      totalAdminCost: { ...mfr.totalAdminCost, amount: 0 },
      grandTotal:     { ...mfr.grandTotal,     amount: mfr.totalProgramCost.amount },
    };
  }, [mfr, showAdmin]);

  // Derive a filtered MFR when the staff selection is non-empty. Built
  // on top of roleMfr so PL never sees admin even through the filter.
  const filterActive = selectedStaffIds.length > 0;
  const viewMfr: MonthlyFundRequest = useMemo(() => {
    if (!filterActive) return roleMfr;
    const idSet = new Set(selectedStaffIds);
    const filteredLines = roleMfr.lines.filter((l) => idSet.has(l.id));
    const lineIdSet = new Set(filteredLines.map((l) => l.id));
    const filteredSources = roleMfr.sources.filter((s) => lineIdSet.has(s.lineId));
    const totalProgramCost = filteredLines.reduce((s, l) => s + l.totalMonthlyAllocation, 0);
    return {
      ...roleMfr,
      lines: filteredLines,
      sources: filteredSources,
      totalProgramCost: { ...roleMfr.totalProgramCost, amount: totalProgramCost },
      grandTotal: {
        ...roleMfr.grandTotal,
        amount: totalProgramCost + roleMfr.totalAdminCost.amount,
      },
    };
  }, [roleMfr, filterActive, selectedStaffIds]);

  const activityMatrix = useMemo(() => computeActivityWeekMatrix(viewMfr), [viewMfr]);

  const onAction = (next: MonthlyFundRequestStatus) => {
    setMfr({ ...mfr, status: next });
  };

  const onAdminItemsChange = (items: MfrAdminItem[]) => {
    const totalAdmin = items.reduce((s, i) => s + i.totalCost, 0);
    const newGrand = mfr.totalProgramCost.amount + totalAdmin;
    setMfr({
      ...mfr,
      adminItems: items,
      totalAdminCost: { ...mfr.totalAdminCost, amount: totalAdmin },
      grandTotal:     { ...mfr.grandTotal,     amount: newGrand },
    });
  };

  // RVP gate — never see pre-CD-approval drafts.
  const rvpGated =
    viewerRole === "RVP" && !POST_CD_APPROVAL_STATUSES.has(mfr.status);

  if (rvpGated) {
    return (
      <div className="card p-8 text-center">
        <h2 className="text-[16px] font-extrabold tracking-tight">
          Awaiting CD approval
        </h2>
        <p className="text-[12.5px] muted mt-2 max-w-md mx-auto">
          The {mfr.monthLabel} Monthly Fund Request for {mfr.countryName} is still
          under PL / CD review. It will appear here once the Country Director approves it
          and attaches the administration budget.
        </p>
        <div className="mt-3 text-[11px] muted">
          Current status: <span className="font-bold text-slate-700">{mfr.status.replace(/_/g, " ")}</span>
        </div>
      </div>
    );
  }

  const canEditAdmin = viewerRole === "CD";

  return (
    <div className="space-y-3 lg:space-y-4">
      {/* Header — totals reflect role scope. PL sees Program Total only;
          CD/RVP/Accountant see Program + Admin = Grand Total. */}
      <MonthlyFundRequestHeader
        mfr={roleMfr}
        viewerRole={viewerRole}
        onAction={onAction}
      />

      <ValidationWarnings issues={mfr.validationIssues} />

      {/* Staff filter — sits between the validation panel and the
          executive summary. Multi-select with team quick-picks. */}
      <MfrStaffFilter
        mfr={roleMfr}
        selectedIds={selectedStaffIds}
        onChange={setSelectedStaffIds}
      />

      {/* Filtered scope read-out — only shows when a filter is active. */}
      {filterActive && (
        <div className="card p-3 px-4 flex items-center justify-between gap-3 flex-wrap row-active-glow border-transparent">
          <div>
            <div className="text-[10px] muted font-extrabold uppercase tracking-wide">
              Filtered scope
            </div>
            <div className="text-[13px] font-extrabold tracking-tight text-slate-900">
              {selectedStaffIds.length} of {roleMfr.lines.length} lines · UGX {viewMfr.totalProgramCost.amount.toLocaleString()} program subset
            </div>
          </div>
          {showAdmin && (
            <div className="text-[11px] muted">
              Admin items below are country-level and aren&apos;t allocated per staff.
            </div>
          )}
        </div>
      )}

      {/* Weekly totals strip — auto-recomputes from role + filter scope. */}
      <WeeklyTotalsStrip
        weekTotals={activityMatrix.weekTotals}
        monthlyTotal={activityMatrix.monthlyTotal}
        selected={selectedWeek}
        onSelectWeek={setSelectedWeek}
      />

      {/* View-mode toggle (desktop only) */}
      <div className="hidden xl:flex items-center justify-between gap-3 flex-wrap">
        <div className="text-[11px] muted font-bold uppercase tracking-wide">
          View
        </div>
        <ViewModeSwitch value={viewMode} onChange={setViewMode} />
      </div>

      {/* Mobile + tablet card stack */}
      <div className="block xl:hidden">
        <MobileMonthlyFundRequest mfr={viewMfr} onCellClick={setTarget} />
      </div>

      {/* Desktop matrix */}
      <div className="hidden xl:block">
        {viewMode === "summary" ? (
          <ActivityWeekSummary
            matrix={activityMatrix}
            selectedWeek={selectedWeek}
            onCellClick={setTarget}
          />
        ) : (
          <MonthlyFundRequestMatrix mfr={viewMfr} onCellClick={setTarget} />
        )}
      </div>

      {/* Administration Budget — CD, RVP, and Accountant. PL never
          sees this section because admin items are added by CD AFTER
          PL signs off on the program plan. */}
      {showAdmin && (
        <AdminBudgetSection
          fundRequestId={mfr.id}
          items={mfr.adminItems}
          canEdit={canEditAdmin}
          cdName={mfr.countryDirectorName ?? "Country Director"}
          onItemsChange={onAdminItemsChange}
        />
      )}

      <CellDrilldownDrawer
        open={target !== null}
        target={target}
        sources={viewMfr.sources}
        onClose={() => setTarget(null)}
      />
    </div>
  );
}

function ViewModeSwitch({
  value,
  onChange,
}: {
  value: ViewMode;
  onChange: (v: ViewMode) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="View mode"
      className="inline-flex items-center rounded-lg border border-[var(--color-edify-border)] bg-white p-0.5"
    >
      <SwitchBtn
        active={value === "summary"}
        onClick={() => onChange("summary")}
        label="By Activity × Week"
        icon={<CalendarDays size={12} />}
      />
      <SwitchBtn
        active={value === "detail"}
        onClick={() => onChange("detail")}
        label="By Staff (detail)"
        icon={<Table size={12} />}
      />
    </div>
  );
}

function SwitchBtn({
  active,
  onClick,
  label,
  icon,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  icon: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-[11.5px] font-extrabold transition-colors",
        active
          ? "bg-slate-900 text-white"
          : "bg-transparent text-slate-600 hover:bg-slate-50",
      )}
    >
      {icon}
      {label}
    </button>
  );
}
