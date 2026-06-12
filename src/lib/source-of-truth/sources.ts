// One Source of Truth Locks (spec layer #11).
//
// "School comes only from the School Directory. Cluster only from the Cluster
// Dashboard. Cost only from the Cost Catalogue. Partner only from CD onboarding.
// Completed work only from executed activities. Impact only from SSA." This
// module is the single import that hands back the ONE canonical accessor per
// domain — so new code can't quietly spin up a parallel source — plus the locks
// that were missing (active-partner, completed-work, impact) and a manifest the
// System Health page renders so the locks are visible.
//
// server-only: the completed-work + impact accessors read the unified model / SSA.

import "server-only";

import { partners, partnerById } from "@/lib/partner/partner-mock";
import type { Partner } from "@/lib/partner/partner-types";
import { ssaUploads } from "@/lib/intake/intake-mock";
import { missingCostSettings, activeCostFor } from "@/lib/cost-settings-mock";
import type { CostItem } from "@/lib/cost-settings-mock";
import { allUnifiedActivities } from "@/lib/activity/unified-activity-source";
import type { UnifiedActivity } from "@/lib/activity/unified-activity";

// ── Partner: only from the CD-onboarded registry, only if the contract is active ──

export function activePartners(): Partner[] {
  return partners.filter((p) => p.contractActive);
}

/** The lock: a partner may only be assigned work if its contract is active. */
export function isPartnerActive(partnerId: string): boolean {
  return partnerById(partnerId)?.contractActive ?? false;
}

// ── Cost: only from the Cost Catalogue; detect the fork instead of silently falling back ──

/** True when the catalogue actually carries a rate for this item (no silent fork). */
export function hasCanonicalCost(item: CostItem, fyId?: string): boolean {
  return !missingCostSettings(fyId).includes(item);
}

/** The canonical cost — pair with hasCanonicalCost() so callers never silently
 *  substitute an activity's own estimate for a missing catalogue rate. */
export function canonicalCost(item: CostItem, fyId?: string): { cents: number; canonical: boolean } {
  return { cents: activeCostFor(item, fyId), canonical: hasCanonicalCost(item, fyId) };
}

// ── Completed work: only from executed activities (unified closed stage) ──

export function completedActivities(): UnifiedActivity[] {
  return allUnifiedActivities().filter((a) => a.stage === "closed");
}

// ── Impact: only from SSA (current vs prior assessment) ──

export type SchoolImpact = {
  schoolId: string;
  current: number;
  prior: number;
  delta: number;
  trend: "improved" | "held" | "declined";
};

export function schoolImpact(schoolId: string): SchoolImpact | null {
  const ssas = ssaUploads
    .filter((u) => u.schoolId === schoolId)
    .slice()
    .sort((a, b) => (a.ssaDate < b.ssaDate ? 1 : -1)); // newest first
  if (ssas.length < 2) return null;
  const current = ssas[0].averageScore;
  const prior = ssas[1].averageScore;
  const delta = Math.round((current - prior) * 10) / 10;
  return {
    schoolId,
    current,
    prior,
    delta,
    trend: delta > 0 ? "improved" : delta < 0 ? "declined" : "held",
  };
}

// ── Manifest — the visible record of every lock ──

export type SourceLock = {
  domain: string;
  canonicalSource: string;
  accessor: string;
  locked: boolean;
  note?: string;
};

export function sourceOfTruthManifest(): SourceLock[] {
  return [
    { domain: "School", canonicalSource: "School Directory (intake)", accessor: "directoryRecords()", locked: true },
    { domain: "Cluster", canonicalSource: "Cluster engine", accessor: "activeClusters()", locked: true },
    { domain: "Cost", canonicalSource: "Cost Catalogue", accessor: "canonicalCost() + hasCanonicalCost()", locked: true, note: "An activity estimate is used only when the catalogue is incomplete — and that gap is now flagged, not silent." },
    { domain: "Budget", canonicalSource: "Plan-derived", accessor: "generateAnnualBudget()", locked: true, note: "Computed from planned activities at catalogue rates — never entered directly." },
    { domain: "Partner", canonicalSource: "CD onboarding registry", accessor: "activePartners() + isPartnerActive()", locked: true },
    { domain: "Project schools", canonicalSource: "School Directory", accessor: "projectSchoolDirectory()", locked: true },
    { domain: "Completed work", canonicalSource: "Executed activities", accessor: "completedActivities()", locked: true },
    { domain: "Impact", canonicalSource: "SSA (current vs prior)", accessor: "schoolImpact()", locked: true },
  ];
}
