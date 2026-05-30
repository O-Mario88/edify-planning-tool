// Partner Scope Engine — the security boundary.
//
// Every write to a PartnerActivity must pass `canPartnerAct(...)`.
// Reads to scope-limited resources go through `partnerVisibleSchoolIds`
// + `partnerVisibleActivityKinds`. If this file has a bug, partner
// users can submit work outside their contract — which is exactly the
// failure mode the spec calls out as enterprise-disqualifying.
//
// Pure functions. No I/O. Always testable. Always auditable.

import type {
  PartnerActivityKind,
  PartnerScope,
  InterventionArea,
} from "./partner-types";

// ────────── canPartnerAct — the single guard ──────────

export type ScopeCheckInput = {
  scope: PartnerScope;
  schoolId: string;
  /// District the school is in (caller resolves; engine doesn't query schools).
  schoolDistrictId: string;
  /// Cluster the school is in, if known.
  schoolClusterId?: string;
  /// Activity the partner wants to perform.
  activityKind: PartnerActivityKind;
  /// Intervention area the activity targets. Optional — when omitted,
  /// the engine treats the scope's interventionAreas as a soft signal.
  intervention?: InterventionArea;
  /// When the activity will occur. Used to enforce contract window.
  scheduledDate: string;
};

export type ScopeCheckResult =
  | { ok: true }
  | { ok: false; reason: string; ruleId: ScopeRuleId };

export type ScopeRuleId =
  | "scope-inactive"
  | "before-start"
  | "after-end"
  | "school-not-assigned"
  | "district-out-of-scope"
  | "activity-not-allowed"
  | "intervention-out-of-scope";

export function canPartnerAct(input: ScopeCheckInput): ScopeCheckResult {
  const { scope, schoolId, schoolDistrictId, schoolClusterId, activityKind, intervention, scheduledDate } = input;

  // 1) Scope must be active.
  if (scope.status !== "Active") {
    return { ok: false, ruleId: "scope-inactive", reason: `Scope is ${scope.status}. Reactivate the contract first.` };
  }

  // 2) Contract window check — never allow work outside dates.
  const t = Date.parse(scheduledDate);
  if (Number.isNaN(t)) {
    return { ok: false, ruleId: "before-start", reason: "Invalid scheduled date." };
  }
  if (t < Date.parse(scope.startDate)) {
    return { ok: false, ruleId: "before-start", reason: `Activity scheduled before contract start (${scope.startDate}).` };
  }
  if (t > Date.parse(scope.endDate)) {
    return { ok: false, ruleId: "after-end", reason: `Activity scheduled after contract end (${scope.endDate}).` };
  }

  // 3) School assignment — if specific schoolIds were listed in scope,
  // the school MUST be in that list. If schoolIds is empty, fall back
  // to cluster / district checks.
  if (scope.schoolIds.length > 0) {
    if (!scope.schoolIds.includes(schoolId)) {
      return { ok: false, ruleId: "school-not-assigned", reason: "School is not in the partner's assigned school list." };
    }
  } else if (scope.clusterIds.length > 0) {
    if (!schoolClusterId || !scope.clusterIds.includes(schoolClusterId)) {
      return { ok: false, ruleId: "school-not-assigned", reason: "School is not in any of the partner's assigned clusters." };
    }
  } else if (scope.districtIds.length > 0) {
    if (!scope.districtIds.includes(schoolDistrictId)) {
      return { ok: false, ruleId: "district-out-of-scope", reason: "School's district is outside the partner's scope." };
    }
  } else {
    // No geographic scope at all — strict failure (scope cannot be
    // empty; the partner has no defined area).
    return { ok: false, ruleId: "district-out-of-scope", reason: "Scope has no schools, clusters, or districts defined." };
  }

  // 4) Activity-kind allowlist.
  if (!scope.allowedActivityKinds.includes(activityKind)) {
    return { ok: false, ruleId: "activity-not-allowed", reason: `${activityKind} is not in the partner's allowed activity types.` };
  }

  // 5) Intervention area — only enforced when intervention is supplied
  // AND the scope has a specific intervention list. Some partners are
  // intentionally cross-area, which we represent as an empty list.
  if (intervention && scope.interventionAreas.length > 0 && !scope.interventionAreas.includes(intervention)) {
    return { ok: false, ruleId: "intervention-out-of-scope", reason: `Intervention area "${intervention}" is outside this scope's focus.` };
  }

  return { ok: true };
}

// ────────── Read-side helpers ──────────
//
// Partner users see a heavily-filtered slice of the data layer. These
// helpers centralise the "what's visible" rule so every list / detail
// query goes through one place.

export function partnerVisibleSchoolIds(scope: PartnerScope, allSchools: Array<{ id: string; districtId: string; clusterId?: string }>): string[] {
  // Fast paths first.
  if (scope.schoolIds.length > 0) return scope.schoolIds;
  if (scope.clusterIds.length > 0) {
    return allSchools.filter((s) => s.clusterId && scope.clusterIds.includes(s.clusterId)).map((s) => s.id);
  }
  if (scope.districtIds.length > 0) {
    return allSchools.filter((s) => scope.districtIds.includes(s.districtId)).map((s) => s.id);
  }
  return [];
}

export function partnerVisibleActivityKinds(scope: PartnerScope): PartnerActivityKind[] {
  return [...scope.allowedActivityKinds];
}

// ────────── Aggregation helpers (multi-scope partners) ──────────
//
// A partner organization may hold several contracts. These helpers
// reduce multiple scopes into a single visible set for that org.

export function mergedVisibleSchoolIds(
  scopes: PartnerScope[],
  allSchools: Array<{ id: string; districtId: string; clusterId?: string }>,
): string[] {
  const out = new Set<string>();
  for (const s of scopes) {
    for (const id of partnerVisibleSchoolIds(s, allSchools)) out.add(id);
  }
  return Array.from(out);
}

export function mergedAllowedActivityKinds(scopes: PartnerScope[]): PartnerActivityKind[] {
  const out = new Set<PartnerActivityKind>();
  for (const s of scopes) for (const k of s.allowedActivityKinds) out.add(k);
  return Array.from(out);
}

// ────────── Coverage gap helper ──────────
//
// Used by the Partner Gap Finder UI on CPL dashboards: for a scope +
// the schools the engine has data on, returns the schools that the
// partner could be serving but isn't yet (this period). Pure compute.

export type CoverageInput = {
  scope: PartnerScope;
  schoolsInScope: Array<{ id: string; name: string; lastPartnerActivityAt?: string }>;
  /// If a school has had a partner activity in the last N days, treat
  /// it as "reached" for the period. Default 30 days.
  reachedWindowDays?: number;
};

export type CoverageGap = {
  schoolId: string;
  schoolName: string;
  daysSinceLastActivity: number | null;
};

export function partnerCoverageGaps(input: CoverageInput): CoverageGap[] {
  const windowDays = input.reachedWindowDays ?? 30;
  const cutoff = Date.now() - windowDays * 24 * 60 * 60 * 1000;
  const gaps: CoverageGap[] = [];
  for (const s of input.schoolsInScope) {
    const t = s.lastPartnerActivityAt ? Date.parse(s.lastPartnerActivityAt) : null;
    if (t === null || t < cutoff) {
      gaps.push({
        schoolId: s.id,
        schoolName: s.name,
        daysSinceLastActivity: t === null ? null : Math.round((Date.now() - t) / (24 * 60 * 60 * 1000)),
      });
    }
  }
  return gaps;
}
