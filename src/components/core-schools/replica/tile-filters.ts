// Core School tile filter registry.
//
// Every interactive tile on the Core School dashboard registers here
// with a stable id (the URL value), the entity it filters, and a small
// matcher function that turns the mock dataset into the focused result
// list shown in the filtered view.
//
// When real backend lands the matchers swap to server queries — the
// page only needs the spec + result count to render the filter
// affordances, and the URL contract stays identical.

import {
  replicaAttention,
  replicaBestPerforming,
  replicaPackageTiles,
  type ReplicaAttentionRow,
  type ReplicaBestRow,
} from "@/lib/core-school-replica-mock";
import type { TileFilterSpec } from "@/components/tile-filter/types";

export type CoreSchoolResultRow = {
  id: string;
  schoolName: string;
  district: string;
  cceo: string;
  ssaScore: number;
  visits: string;            // "0/4" .. "4/4"
  trainings: string;
  packageStatus: "Complete" | "Nearly Complete" | "In Progress" | "Not Started";
  status: string;            // tile-specific status label, e.g. "Missing 2nd Visit"
  nextAction: string;
  evidenceStatus: "Submitted" | "Missing" | "Verified" | "—";
  riskTone: "rose" | "amber" | "violet" | "emerald";
};

// ────────── Registry of every clickable tile on Core Schools ──────────

export type CoreSchoolTileFilterSpec = TileFilterSpec & {
  // tile category for grouping inside the filter result counts panel
  category:
    | "ssa"
    | "visit"
    | "training"
    | "package"
    | "champion"
    | "risk"
    | "score"
    | "summary";
  visitNumber?: 1 | 2 | 3 | 4;
  trainingNumber?: 1 | 2 | 3 | 4;
};

export const CORE_TILE_FILTERS: CoreSchoolTileFilterSpec[] = [
  // ── KPI row tiles
  {
    id: "total",
    category: "summary",
    label: "All Core Schools",
    description: "Every core school in the selected FY / quarter scope.",
    entityType: "school",
  },
  {
    id: "ssa-complete",
    category: "ssa",
    label: "SSA Complete",
    description: "Core schools with a completed SSA in the selected period.",
    entityType: "school",
    primaryAction: { label: "Plan Action", href: "/plans/new" },
  },
  {
    id: "ssa-not-done",
    category: "ssa",
    label: "SSA Not Done",
    description: "Core schools without a completed SSA in the selected period.",
    entityType: "school",
    primaryAction: { label: "Schedule SSA", href: "/plans/new?type=ssa" },
  },
  {
    id: "avg-ssa",
    category: "score",
    label: "Average Core SSA Score",
    description: "Schools with a recorded SSA score, sorted by score.",
    entityType: "school",
  },
  {
    id: "on-track",
    category: "risk",
    label: "On Track",
    description: "Core schools meeting the expected core package progress cadence.",
    entityType: "school",
  },
  {
    id: "behind-schedule",
    category: "risk",
    label: "Behind Schedule",
    description: "Schools whose visit + training cadence has fallen behind plan.",
    entityType: "school",
    primaryAction: { label: "Plan Action", href: "/plans/new" },
  },
  {
    id: "critical-gap",
    category: "risk",
    label: "Critical Gap",
    description: "Schools in critical risk of falling further behind their core package targets.",
    entityType: "school",
    primaryAction: { label: "Plan Action", href: "/plans/new" },
  },
  {
    id: "salesforce-compliance",
    category: "summary",
    label: "Salesforce Compliance",
    description: "Schools whose activity records meet Salesforce reporting compliance.",
    entityType: "school",
  },

  // ── Package progress funnel tiles
  {
    id: "pkg-0ssa",
    category: "ssa",
    label: "0 SSA Completed",
    description: "Schools that have not yet started a Self-Sufficiency Assessment.",
    entityType: "school",
    primaryAction: { label: "Schedule SSA", href: "/plans/new?type=ssa" },
  },
  {
    id: "pkg-0v",
    category: "visit",
    label: "0 Visits Completed",
    description: "Schools missing the first required core visit.",
    entityType: "school",
    primaryAction: { label: "Schedule First Visit", href: "/plans/new?type=visit&n=1" },
  },
  {
    id: "pkg-0t",
    category: "training",
    label: "0 Trainings Completed",
    description: "Schools missing the first required core training.",
    entityType: "school",
    primaryAction: { label: "Schedule First Training", href: "/plans/new?type=training&n=1" },
  },
  {
    id: "pkg-1v1t",
    category: "package",
    label: "1 Visit + 1 Training",
    description: "Schools that have completed at least 1 visit and 1 training.",
    entityType: "school",
  },
  {
    id: "pkg-2v2t",
    category: "package",
    label: "2 Visits + 2 Trainings",
    description: "Schools that have completed 2 visits and 2 trainings.",
    entityType: "school",
  },
  {
    id: "pkg-3v3t",
    category: "package",
    label: "3 Visits + 3 Trainings",
    description: "Schools that have completed 3 visits and 3 trainings.",
    entityType: "school",
  },
  {
    id: "pkg-4v4t",
    category: "package",
    label: "Full Core Package (4 Visits + 4 Trainings)",
    description: "Schools that have completed the full core service package.",
    entityType: "school",
    primaryAction: { label: "Review for Champion", href: "/leaderboard" },
  },
  {
    id: "pkg-champ",
    category: "champion",
    label: "Potential Champion Schools",
    description: "Schools that have completed the package and qualify for champion review.",
    entityType: "school",
    primaryAction: { label: "Open Champion Pipeline", href: "/leaderboard" },
  },

  // ── Visit / training granularity (derived from completion strings)
  {
    id: "visit-1-missing",
    category: "visit",
    label: "Missing First Visit",
    description: "Core schools that have not completed their first required visit.",
    entityType: "school",
    visitNumber: 1,
    primaryAction: { label: "Schedule First Visit", href: "/plans/new?type=visit&n=1" },
  },
  {
    id: "visit-2-missing",
    category: "visit",
    label: "Missing Second Visit",
    description: "Core schools that have not completed their second required visit.",
    entityType: "school",
    visitNumber: 2,
    primaryAction: { label: "Schedule Second Visit", href: "/plans/new?type=visit&n=2" },
  },
  {
    id: "visit-3-missing",
    category: "visit",
    label: "Missing Third Visit",
    description: "Core schools that have not completed their third required visit.",
    entityType: "school",
    visitNumber: 3,
    primaryAction: { label: "Schedule Third Visit", href: "/plans/new?type=visit&n=3" },
  },
  {
    id: "visit-4-missing",
    category: "visit",
    label: "Missing Fourth Visit",
    description: "Core schools that have not completed their fourth required visit.",
    entityType: "school",
    visitNumber: 4,
    primaryAction: { label: "Schedule Fourth Visit", href: "/plans/new?type=visit&n=4" },
  },
  {
    id: "training-1-missing",
    category: "training",
    label: "Missing First Training",
    description: "Core schools that have not completed their first required training.",
    entityType: "school",
    trainingNumber: 1,
    primaryAction: { label: "Schedule First Training", href: "/plans/new?type=training&n=1" },
  },
  {
    id: "training-2-missing",
    category: "training",
    label: "Missing Second Training",
    description: "Core schools that have not completed their second required training.",
    entityType: "school",
    trainingNumber: 2,
    primaryAction: { label: "Schedule Second Training", href: "/plans/new?type=training&n=2" },
  },
  {
    id: "training-3-missing",
    category: "training",
    label: "Missing Third Training",
    description: "Core schools that have not completed their third required training.",
    entityType: "school",
    trainingNumber: 3,
    primaryAction: { label: "Schedule Third Training", href: "/plans/new?type=training&n=3" },
  },
  {
    id: "training-4-missing",
    category: "training",
    label: "Missing Fourth Training",
    description: "Core schools that have not completed their fourth required training.",
    entityType: "school",
    trainingNumber: 4,
    primaryAction: { label: "Schedule Fourth Training", href: "/plans/new?type=training&n=4" },
  },

  // ── Bottom row & remaining tasks
  {
    id: "trainings-overdue",
    category: "training",
    label: "Trainings Overdue",
    description: "Core training engagements past their planned date.",
    entityType: "school",
    primaryAction: { label: "Plan Action", href: "/plans/new" },
  },
  {
    id: "trainings-due-month",
    category: "training",
    label: "Trainings Due This Month",
    description: "Core training engagements scheduled for completion this month.",
    entityType: "school",
  },
  {
    id: "verifications-pending",
    category: "package",
    label: "Final Verifications Pending",
    description: "Schools at the verification stage of the core package.",
    entityType: "school",
  },
  {
    id: "remaining-visits",
    category: "visit",
    label: "Remaining Visits Across Cohort",
    description: "Visits required across the cohort to complete every core package.",
    entityType: "school",
  },
  {
    id: "remaining-trainings",
    category: "training",
    label: "Remaining Trainings Across Cohort",
    description: "Trainings required across the cohort to complete every core package.",
    entityType: "school",
  },
];

// ────────── Result lookup ──────────────────────────────────────────────
// Maps each filter id to the actual records that should appear in the
// filtered detail view. Tile counts are the source of truth — for tiles
// that map directly to a count in the replica mock we trust that count
// and pad the list when there are more records than the mock provides
// (the mock is shaped for a dashboard, not a detail list — when real
// backend lands these queries swap to db.* and the count + list come
// from the same query naturally).

function visitsCompleted(s: ReplicaBestRow | ReplicaAttentionRow): number {
  const raw = ("visits" in s ? s.visits : s.visitsCompleted) as string;
  const n = parseInt(raw?.split("/")?.[0] ?? "0", 10);
  return Number.isFinite(n) ? n : 0;
}
function trainingsCompleted(s: ReplicaBestRow | ReplicaAttentionRow): number {
  const raw = ("trainings" in s ? s.trainings : s.trainingsCompleted) as string;
  const n = parseInt(raw?.split("/")?.[0] ?? "0", 10);
  return Number.isFinite(n) ? n : 0;
}

function rowFromBest(r: ReplicaBestRow, status: string, nextAction: string): CoreSchoolResultRow {
  return {
    id: `best-${r.rank}`,
    schoolName: r.schoolName,
    district: r.district,
    cceo: r.cceo,
    ssaScore: r.ssaAvg,
    visits: r.visits,
    trainings: r.trainings,
    packageStatus: r.packageStatus,
    status,
    nextAction,
    evidenceStatus: r.salesforceCompliance >= 95 ? "Verified" : "Submitted",
    riskTone: "emerald",
  };
}
function rowFromAttention(r: ReplicaAttentionRow, status: string): CoreSchoolResultRow {
  return {
    id: `att-${r.schoolName}`,
    schoolName: r.schoolName,
    district: r.district,
    cceo: r.cceo,
    ssaScore: r.ssaScore,
    visits: r.visitsCompleted,
    trainings: r.trainingsCompleted,
    packageStatus: "In Progress",
    status,
    nextAction: r.recommendedAction,
    evidenceStatus: "Missing",
    riskTone: r.riskTone,
  };
}

const allBest = (status: string, action: string) =>
  replicaBestPerforming.map((r) => rowFromBest(r, status, action));
const allAttention = (status: string) =>
  replicaAttention.map((r) => rowFromAttention(r, status));

export function getTileFilterCount(id: string): number {
  // Match against the canonical funnel counts first
  const pkg = replicaPackageTiles.find((t) => `pkg-${t.key}` === id);
  if (pkg) return pkg.count;
  switch (id) {
    case "total":                  return 512;
    case "ssa-complete":           return 462;
    case "ssa-not-done":           return 50;
    case "avg-ssa":                return 462;
    case "on-track":               return 286;
    case "behind-schedule":        return 148;
    case "critical-gap":           return 78;
    case "salesforce-compliance":  return 471;
    case "visit-1-missing":        return 42;
    case "visit-2-missing":        return 78;
    case "visit-3-missing":        return 132;
    case "visit-4-missing":        return 248;
    case "training-1-missing":     return 39;
    case "training-2-missing":     return 82;
    case "training-3-missing":     return 124;
    case "training-4-missing":     return 196;
    case "trainings-overdue":      return 12;
    case "trainings-due-month":    return 36;
    case "verifications-pending":  return 42;
    case "remaining-visits":       return 248;
    case "remaining-trainings":    return 196;
    default:                       return 0;
  }
}

export function getTileFilterResults(id: string): CoreSchoolResultRow[] {
  switch (id) {
    case "total":
      return [
        ...allBest("Active", "Maintain cadence"),
        ...allAttention("Active"),
      ];
    case "ssa-complete":
    case "avg-ssa":
      return [
        ...allBest("SSA Complete", "Plan next visit"),
        ...replicaAttention
          .filter((r) => r.ssaScore > 0)
          .map((r) => rowFromAttention(r, "SSA Complete")),
      ];
    case "ssa-not-done":
      return replicaAttention
        .filter((r) => r.riskReason.toLowerCase().includes("no ssa"))
        .map((r) => rowFromAttention(r, "SSA Not Done"));
    case "on-track":
      return allBest("On Track", "Maintain cadence");
    case "behind-schedule":
      return replicaAttention
        .filter((r) => r.riskReason.toLowerCase().includes("behind"))
        .map((r) => rowFromAttention(r, "Behind Schedule"));
    case "critical-gap":
      return replicaAttention
        .filter((r) => r.riskTone === "rose")
        .map((r) => rowFromAttention(r, "Critical Gap"));
    case "salesforce-compliance":
      return allBest("Compliant", "Maintain logging");
    case "pkg-0ssa":
    case "pkg-0v":
    case "pkg-0t":
      return replicaAttention
        .filter((r) => visitsCompleted(r) === 0 || trainingsCompleted(r) === 0)
        .map((r) => rowFromAttention(r, "Missing initial milestones"));
    case "pkg-1v1t":
      return replicaAttention
        .filter((r) => visitsCompleted(r) >= 1 && trainingsCompleted(r) >= 1)
        .map((r) => rowFromAttention(r, "1 visit + 1 training"));
    case "pkg-2v2t":
      return replicaBestPerforming
        .filter((r) => visitsCompleted(r) >= 2 && trainingsCompleted(r) >= 2)
        .map((r) => rowFromBest(r, "2 visits + 2 trainings", "Plan next visit"));
    case "pkg-3v3t":
      return replicaBestPerforming
        .filter((r) => visitsCompleted(r) >= 3 && trainingsCompleted(r) >= 3)
        .map((r) => rowFromBest(r, "3 visits + 3 trainings", "Plan final visit"));
    case "pkg-4v4t":
      return replicaBestPerforming
        .filter((r) => r.packageStatus === "Complete")
        .map((r) => rowFromBest(r, "Full Core Package", "Review for Champion"));
    case "pkg-champ":
      return replicaBestPerforming
        .filter((r) => r.championRecommendation !== undefined)
        .map((r) => rowFromBest(r, r.championRecommendation, "Open champion pipeline"));
    case "visit-1-missing":
    case "visit-2-missing":
    case "visit-3-missing":
    case "visit-4-missing": {
      const n = Number(id.split("-")[1]);
      return replicaAttention
        .filter((r) => visitsCompleted(r) < n)
        .map((r) => rowFromAttention(r, `Missing visit ${n}`));
    }
    case "training-1-missing":
    case "training-2-missing":
    case "training-3-missing":
    case "training-4-missing": {
      const n = Number(id.split("-")[1]);
      return replicaAttention
        .filter((r) => trainingsCompleted(r) < n)
        .map((r) => rowFromAttention(r, `Missing training ${n}`));
    }
    case "trainings-overdue":
    case "trainings-due-month":
    case "verifications-pending":
    case "remaining-visits":
    case "remaining-trainings":
      return allAttention("Action needed");
    default:
      return [];
  }
}

export function getCoreTileFilter(id: string): CoreSchoolTileFilterSpec | undefined {
  return CORE_TILE_FILTERS.find((t) => t.id === id);
}
