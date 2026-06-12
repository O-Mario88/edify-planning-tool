// Quality Gates (spec layer #5).
//
// "Keep work moving, but protect trust." Two levels:
//   • warn  — soft gate: surface a warning, never block (missing prior-FY SSA,
//             evidence without attendance, out-of-sub-county cluster school,
//             no catalogue cost match, fund changed by reschedule).
//   • block — hard gate: must be satisfied (no School ID, incomplete SSA, no
//             catalogue item, partner inactive, unauthorized role, missing
//             evidence before IA, invalid Salesforce prefix, payment before IA).
//
// Pure + client-safe — reads only client-safe stores so it can run in a drawer
// before submit AND server-side before a mutation commits.

import { partnerById } from "@/lib/partner/partner-mock";
import { missingCostSettings, type CostItem } from "@/lib/cost-settings-mock";
import { ssaUploads } from "@/lib/intake/intake-mock";
import { isValidSalesforceId, salesforceKindFor } from "@/lib/salesforce-id";

export type GateLevel = "ok" | "warn" | "block";

export type GateResult = {
  level: GateLevel;
  code: string;
  message: string;
};

const ok = (code: string): GateResult => ({ level: "ok", code, message: "" });
const warn = (code: string, message: string): GateResult => ({ level: "warn", code, message });
const block = (code: string, message: string): GateResult => ({ level: "block", code, message });

// ── Hard gates (block) ─────────────────────────────────────────────

export function gateSchoolId(schoolId: string | undefined): GateResult {
  return schoolId && schoolId.trim()
    ? ok("school_id")
    : block("school_id", "No School ID — a school must have an ID before any workflow.");
}

export function gateSsaComplete(ssaDone: boolean): GateResult {
  return ssaDone
    ? ok("ssa_complete")
    : block("ssa_complete", "SSA is incomplete — planning is locked until the current-FY SSA is done.");
}

export function gateCostCatalogue(item: CostItem, fyId?: string): GateResult {
  return missingCostSettings(fyId).includes(item)
    ? block("cost_catalogue", `No cost-catalogue rate for "${item}" — set it before raising a fund request.`)
    : ok("cost_catalogue");
}

export function gatePartnerActive(partnerId: string | undefined): GateResult {
  if (!partnerId) return ok("partner_active");
  return partnerById(partnerId)?.contractActive
    ? ok("partner_active")
    : block("partner_active", "Partner contract is inactive — cannot assign work to an inactive partner.");
}

export function gateRoleAuthorized(role: string, allowed: readonly string[]): GateResult {
  return allowed.includes(role)
    ? ok("role_authorized")
    : block("role_authorized", `Role ${role} is not authorized for this action.`);
}

export function gateEvidenceBeforeIa(hasEvidence: boolean): GateResult {
  return hasEvidence
    ? ok("evidence_before_ia")
    : block("evidence_before_ia", "Evidence is required before this activity can go to IA.");
}

export function gateSalesforcePrefix(id: string, activityType: string): GateResult {
  const kind = salesforceKindFor(activityType);
  return isValidSalesforceId(id, kind)
    ? ok("salesforce_prefix")
    : block("salesforce_prefix", `Invalid Salesforce ID — a ${kind} needs the correct prefix.`);
}

export function gatePaymentAfterIa(iaConfirmed: boolean): GateResult {
  return iaConfirmed
    ? ok("payment_after_ia")
    : block("payment_after_ia", "Payment cannot clear before IA has confirmed the activity.");
}

// ── Soft gates (warn) ──────────────────────────────────────────────

export function warnPriorFySsa(schoolId: string): GateResult {
  const count = ssaUploads.filter((u) => u.schoolId === schoolId).length;
  return count >= 2
    ? ok("prior_fy_ssa")
    : warn("prior_fy_ssa", "No prior-FY SSA on record — impact comparison won't be available for this school.");
}

export function warnAttendanceForm(hasAttendance: boolean): GateResult {
  return hasAttendance
    ? ok("attendance_form")
    : warn("attendance_form", "Partner evidence is missing the attendance form — add it before IA review.");
}

export function warnClusterSubcounty(allInEligibleSubcounties: boolean): GateResult {
  return allInEligibleSubcounties
    ? ok("cluster_subcounty")
    : warn("cluster_subcounty", "This cluster includes schools outside its eligible sub-counties.");
}

export function warnCostMatch(hasCatalogueMatch: boolean): GateResult {
  return hasCatalogueMatch
    ? ok("cost_match")
    : warn("cost_match", "This activity has no cost-catalogue match — its estimate may be off.");
}

export function warnFundReschedule(changedByReschedule: boolean): GateResult {
  return changedByReschedule
    ? warn("fund_reschedule", "This fund request changed because an activity was rescheduled — re-check the total.")
    : ok("fund_reschedule");
}

// ── Aggregation ────────────────────────────────────────────────────

export type GateEvaluation = {
  ok: boolean; // no hard blocks
  blocks: GateResult[];
  warnings: GateResult[];
};

export function evaluateGates(results: GateResult[]): GateEvaluation {
  const blocks = results.filter((r) => r.level === "block");
  const warnings = results.filter((r) => r.level === "warn");
  return { ok: blocks.length === 0, blocks, warnings };
}

// ── Per-entity convenience aggregators ─────────────────────────────

/** Gates for a school record (used on the profile + before planning). */
export function schoolQualityGates(school: {
  schoolId: string;
  ssaDone: boolean;
}): GateEvaluation {
  return evaluateGates([
    gateSchoolId(school.schoolId),
    gateSsaComplete(school.ssaDone),
    warnPriorFySsa(school.schoolId),
  ]);
}
