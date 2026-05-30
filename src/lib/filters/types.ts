// Analytics filter bar — shared type contract.
//
// The filter bar is rendered on multiple analytics surfaces (Core Schools
// dashboard today; PL/CD/RVP dashboards next). Every surface reads from
// the same scope service and the same selection hook, so the types live
// in one place and the UI is just a projection.

import type { EdifyRole } from "@/lib/auth-public";

// The 10 filter slots on the bar. Stable string keys are also the URL
// query keys (see hooks/use-filter-bar.ts for the mapping).
export type FilterKey =
  | "fy"
  | "quarter"
  | "region"
  | "district"
  | "cluster"
  | "cceo"
  | "partner"
  | "package"
  | "ssa"
  | "champion";

// Every dropdown renders the same shape. `caption` is the small line
// under the main label (used for FY date range, district region, etc.).
// `parentKey` carries the dependent-filter relationship — selecting a
// region narrows districts to those whose `parentKey === region.id`.
export type FilterOption = {
  id: string;
  label: string;
  caption?: string;
  // Single parent id (e.g. cluster's district) OR set of parent ids
  // (e.g. a district that appears under more than one region in
  // overlapping-name mock data). Array form is required for slice 1
  // because the schools mock uses district names that recur across
  // regions; the real Prisma data will collapse this to single-parent.
  parentKey?: string | readonly string[];
};

// The default "All …" sentinel for every non-required filter. FY and
// Quarter always carry a real value — the bar boots into the active FY
// and an "All Quarters" sentinel.
export const ALL_SENTINEL = "__all__";

// The scope service returns one of these per filter key. `visible`
// signals whether the filter should render at all for this role (HR
// hides Partner; RVP hides Partner unless contract-cleared, etc.).
//
// `disabledReason` is shown in a small tooltip / muted state when the
// filter exists for the role but is gated (e.g. RVP partner access).
export type FilterScopeEntry = {
  visible: boolean;
  disabledReason?: string;
  options: FilterOption[];
};

export type FilterScope = Record<FilterKey, FilterScopeEntry>;

// The current selection. ALL_SENTINEL = "no filter applied on this
// dimension". FY and Quarter must always resolve to a real option id.
export type FilterSelection = Record<FilterKey, string>;

// Helper — derives a clean FilterSelection given a scope.
export function defaultSelection(scope: FilterScope): FilterSelection {
  const fy = scope.fy.options[0]?.id ?? ALL_SENTINEL;
  return {
    fy,
    quarter: ALL_SENTINEL,
    region: ALL_SENTINEL,
    district: ALL_SENTINEL,
    cluster: ALL_SENTINEL,
    cceo: ALL_SENTINEL,
    partner: ALL_SENTINEL,
    package: ALL_SENTINEL,
    ssa: ALL_SENTINEL,
    champion: ALL_SENTINEL,
  };
}

// Per-role visibility matrix. The scope service writes this into every
// FilterScopeEntry.visible so the bar can render the same component
// tree for everyone — invisible slots just don't paint.
export type VisibilityMatrix = Record<EdifyRole, Record<FilterKey, boolean>>;
