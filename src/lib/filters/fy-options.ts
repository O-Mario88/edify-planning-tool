// FY + Quarter dropdown options.
//
// Operational cycle is fixed: Oct 1 → Sep 30. The FY ledger
// (`financialYears` in lib/fy-engine.ts) is the source of truth — it
// already encodes the cycle and the active FY. We pick three contiguous
// FYs around the active one (previous · active · next) so the user can
// always look one year back or one year forward, and the dropdown rolls
// forward automatically on Oct 1 because the ledger does.
//
// Quarters operate on whichever FY the user has picked, NOT on the
// active one — so picking FY 2026/27 shows Q1 = Oct–Dec 2026, etc.

import "server-only";

import {
  activeFinancialYear,
  financialYears,
  type FinancialYear,
} from "@/lib/fy-engine";
import { ALL_SENTINEL, type FilterOption } from "./types";

// Pretty short label for the FY chip. The ledger labels are "FY 2025/26"
// — we keep that exact form for now since the rest of the app uses it.
// The FY caption shows the operational range ("Oct 2025 – Sep 2026").
function fyCaption(fy: FinancialYear): string {
  const start = new Date(fy.startDate);
  const end = new Date(fy.endDate);
  const mo = (d: Date) =>
    d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  return `${mo(start)} ${start.getUTCFullYear()} – ${mo(end)} ${end.getUTCFullYear()}`;
}

// Build the FY dropdown. Includes the previous, active, and next FY
// whenever they exist in the ledger. We also include any FY with status
// Locked or Archived that the user might want for historical analytics
// — but we cap to the four most recent so the list doesn't grow forever.
export function buildFyOptions(): FilterOption[] {
  const active = activeFinancialYear();
  const idx = financialYears.findIndex((y) => y.id === active.id);

  // Window: from up to 2 prior FYs through the next FY (when present).
  const start = Math.max(0, idx - 2);
  const end = Math.min(financialYears.length, idx + 2);
  const window = financialYears.slice(start, end);

  // The active FY must be FIRST — the bar reads `options[0]` as the
  // default, and the spec is explicit: default = current operational FY.
  // Within the rest, sort newest first (next FY, then any prior FYs)
  // so the user looking back sees the most recent past year first.
  const activeInWindow = window.find((y) => y.status === "Active");
  const others = window
    .filter((y) => y.status !== "Active")
    .sort((a, b) => b.startDate.localeCompare(a.startDate));
  const ordered = activeInWindow ? [activeInWindow, ...others] : others;

  return ordered.map((fy) => ({
    id: fy.id,
    label: fy.label,
    caption: fyCaption(fy),
  }));
}

// Quarters for a given FY id. Q1 = Oct–Dec, Q2 = Jan–Mar, Q3 = Apr–Jun,
// Q4 = Jul–Sep. Returns [All Quarters] + Q1..Q4. The caption shows the
// month range and the year so Q1 vs Q2 is unambiguous when the user is
// looking at a multi-year report.
export function buildQuarterOptions(fyId: string): FilterOption[] {
  const fy = financialYears.find((y) => y.id === fyId) ?? activeFinancialYear();
  const startYear = new Date(fy.startDate).getUTCFullYear();   // e.g. 2025 for FY 2025/26
  const endYear = new Date(fy.endDate).getUTCFullYear();       // e.g. 2026

  return [
    { id: ALL_SENTINEL, label: "All Quarters" },
    { id: "Q1", label: "Q1", caption: `Oct – Dec ${startYear}`, parentKey: fyId },
    { id: "Q2", label: "Q2", caption: `Jan – Mar ${endYear}`,   parentKey: fyId },
    { id: "Q3", label: "Q3", caption: `Apr – Jun ${endYear}`,   parentKey: fyId },
    { id: "Q4", label: "Q4", caption: `Jul – Sep ${endYear}`,   parentKey: fyId },
  ];
}

// Resolve a quarter id ("Q2") + FY id → an ISO date range. Used by the
// data layer to scope queries; not consumed by the bar UI directly.
export function quarterDateRange(
  fyId: string,
  quarterId: string,
): { startDate: string; endDate: string } | undefined {
  if (quarterId === ALL_SENTINEL) return undefined;
  const fy = financialYears.find((y) => y.id === fyId);
  if (!fy) return undefined;
  const startYear = new Date(fy.startDate).getUTCFullYear();
  const endYear = new Date(fy.endDate).getUTCFullYear();
  switch (quarterId) {
    case "Q1": return { startDate: `${startYear}-10-01`, endDate: `${startYear}-12-31` };
    case "Q2": return { startDate: `${endYear}-01-01`,   endDate: `${endYear}-03-31`   };
    case "Q3": return { startDate: `${endYear}-04-01`,   endDate: `${endYear}-06-30`   };
    case "Q4": return { startDate: `${endYear}-07-01`,   endDate: `${endYear}-09-30`   };
    default:   return undefined;
  }
}
