// Core School health-check / data-integrity engine. Walks the unified store and
// flags every "no-excuse" violation from the spec (§22–23): records that break
// the one-schoolId lifecycle invariants. Read-only — surfaced on /core-schools
// so a reviewer can see, at a glance, whether the lifecycle is sound.

import "server-only";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { ssaAverage } from "@/lib/intake/intake-core";
import {
  coreSeedActive,
  corePlans,
  coreProfiles,
  coreSlots,
  coreOnboardings,
  coreVerifications,
  coreFollowUps,
  interventionsForPlan,
  slotsForPlan,
  baselineSnapshot,
  followUpForPlan,
  candidateSnapshotFor,
} from "./core-store";
import { corePlanProgress } from "./core-progress";
import { coreImpactFor } from "./core-impact";
import { CORE_SSA_THRESHOLD, VISITS_TARGET, TRAININGS_TARGET } from "./core-types";

export type CoreHealthSeverity = "error" | "warning" | "info";

export type CoreHealthFinding = {
  id: string;
  severity: CoreHealthSeverity;
  rule: string;          // short rule label (the integrity rule that fired)
  message: string;       // human-readable detail
  schoolId?: string;
  planId?: string;
  slotId?: string;
};

export type CoreHealthReport = {
  ok: boolean;
  errors: number;
  warnings: number;
  checkedPlans: number;
  checkedSlots: number;
  findings: CoreHealthFinding[];
  seedActive: boolean;
};

const directoryHas = (schoolId: string) => intakeSchools.some((s) => s.schoolId === schoolId);

/** Run every core integrity check and return a categorised report. */
export function coreHealthReport(): CoreHealthReport {
  const findings: CoreHealthFinding[] = [];
  const add = (f: Omit<CoreHealthFinding, "id">) =>
    findings.push({ ...f, id: `chk-${findings.length + 1}` });

  const plans = corePlans();
  const slots = coreSlots();

  // 0. Production must reject mock core data (§23 "production mock data active").
  if (process.env.NODE_ENV === "production" && coreSeedActive() && plans.length > 0) {
    add({
      severity: "error",
      rule: "production-mock-active",
      message: "Mock core-school seed is active in production. Unset EDIFY_SEED_CORE or clear seeded plans.",
    });
  }

  // 1. Verifications / candidates resolve to a real directory school.
  for (const v of coreVerifications()) {
    if (!directoryHas(v.schoolId)) {
      add({ severity: "error", rule: "candidate-without-schoolId", schoolId: v.schoolId,
        message: `Verification ${v.verificationId} references a school not in the Directory.` });
    }
  }

  // 2. Verified candidate must reach the onboarding queue (not stall).
  for (const v of coreVerifications()) {
    if (v.status !== "Verified Potential Core") continue;
    const onboarded = coreOnboardings().some((o) => o.schoolId === v.schoolId && o.status === "Onboarded");
    const stillCandidate = !!candidateSnapshotFor(v.schoolId);
    if (!onboarded && !stillCandidate) {
      add({ severity: "warning", rule: "verified-not-onboarded", schoolId: v.schoolId,
        message: "Verified Potential Core is neither onboarded nor in the candidate queue." });
    }
  }

  // 3. Every onboarded Core school must own a plan.
  for (const o of coreOnboardings()) {
    if (o.status !== "Onboarded") continue;
    if (!plans.some((p) => p.schoolId === o.schoolId)) {
      add({ severity: "error", rule: "onboarded-without-plan", schoolId: o.schoolId,
        message: "Onboarded as Core but no CorePlan exists." });
    }
  }

  // 4. Plan-level invariants: baseline SSA, 4 interventions, 8 slots, directory link.
  for (const p of plans) {
    if (!directoryHas(p.schoolId)) {
      add({ severity: "error", rule: "plan-not-in-directory", schoolId: p.schoolId, planId: p.id,
        message: "CorePlan school is not in the School Directory." });
    }
    if (!p.baselineSSARecordId || !baselineSnapshot(p.baselineSSARecordId)) {
      add({ severity: "error", rule: "plan-without-baseline", schoolId: p.schoolId, planId: p.id,
        message: "CorePlan has no baseline SSA snapshot." });
    }
    const interventions = interventionsForPlan(p.id);
    if (interventions.length !== 4) {
      add({ severity: "error", rule: "plan-not-4-interventions", schoolId: p.schoolId, planId: p.id,
        message: `CorePlan has ${interventions.length} priority interventions (expected 4).` });
    }
    const planSlots = slotsForPlan(p.id);
    const visits = planSlots.filter((s) => s.activityType === "visit").length;
    const trainings = planSlots.filter((s) => s.activityType === "training").length;
    if (visits !== VISITS_TARGET || trainings !== TRAININGS_TARGET) {
      add({ severity: "error", rule: "plan-not-8-slots", schoolId: p.schoolId, planId: p.id,
        message: `CorePlan has ${visits} visit + ${trainings} training slots (expected ${VISITS_TARGET}+${TRAININGS_TARGET}).` });
    }
    // Plan marked complete but no follow-up SSA scheduled/recorded.
    if (p.status === "Completed Pending Follow-Up SSA" && !followUpForPlan(p.id)) {
      add({ severity: "info", rule: "package-complete-awaiting-followup", schoolId: p.schoolId, planId: p.id,
        message: "Package complete — Follow-Up SSA is due." });
    }
    // Follow-up recorded but impact never computed.
    if (p.followUpSSARecordId && !coreImpactFor(p.id)) {
      add({ severity: "error", rule: "followup-without-impact", schoolId: p.schoolId, planId: p.id,
        message: "Follow-Up SSA on file but impact snapshot could not be computed." });
    }
  }

  // 5. Slot-level invariants for slots claiming completion.
  for (const s of slots) {
    const isDone = s.status === "Completed";
    const isVerifying = s.status === "Awaiting IA Verification";
    if ((isDone || isVerifying)) {
      const sf = s.salesforceId ?? "";
      const want = s.activityType === "visit" ? "SVE" : "TS";
      if (!sf.toUpperCase().startsWith(want)) {
        add({ severity: "error", rule: s.activityType === "visit" ? "visit-without-SVE" : "training-without-TS",
          schoolId: s.schoolId, slotId: s.id,
          message: `Completed ${s.activityType} is missing a valid ${want}- Salesforce ID.` });
      }
      if (s.activityType === "training" && (!s.teachers || !s.leaders)) {
        add({ severity: "warning", rule: "training-without-counts", schoolId: s.schoolId, slotId: s.id,
          message: "Completed training is missing teachers/leaders counts." });
      }
    }
    if (isDone && s.iaVerificationStatus !== "Verified") {
      add({ severity: "error", rule: "complete-without-ia", schoolId: s.schoolId, slotId: s.id,
        message: "Slot is Completed but not IA-verified." });
    }
    if (isDone && !s.activityId) {
      add({ severity: "error", rule: "complete-without-activity", schoolId: s.schoolId, slotId: s.id,
        message: "Completed slot has no linked Activity record." });
    }
    if (s.plVerificationStatus === "Pending") {
      add({ severity: "info", rule: "awaiting-pl-signoff", schoolId: s.schoolId, slotId: s.id,
        message: "CCEO core visit is awaiting PL sign-off before IA verification." });
    }
    // IA-verified partner work waiting on accountant.
    if (s.iaVerificationStatus === "Verified" && s.assignedPartnerId && s.accountantStatus !== "Confirmed") {
      add({ severity: "info", rule: "partner-payment-pending", schoolId: s.schoolId, slotId: s.id,
        message: "IA-verified partner activity awaiting accountant confirmation." });
    }
  }

  // 6. Profiles point at a real plan; champions need an impact snapshot.
  for (const prof of coreProfiles()) {
    if (prof.activeCorePlanId && !plans.some((p) => p.id === prof.activeCorePlanId)) {
      add({ severity: "error", rule: "profile-without-plan", schoolId: prof.schoolId,
        message: "Core profile references a missing active plan." });
    }
    if (prof.championStatus !== "Not Eligible") {
      const plan = plans.find((p) => p.schoolId === prof.schoolId);
      if (!plan || !coreImpactFor(plan.id)) {
        add({ severity: "error", rule: "champion-without-impact", schoolId: prof.schoolId,
          message: `Champion status "${prof.championStatus}" without a computed impact snapshot.` });
      }
    }
  }

  // 7. Follow-up SSAs must link back to a plan and look sane.
  for (const f of coreFollowUps()) {
    if (!plans.some((p) => p.id === f.corePlanId)) {
      add({ severity: "error", rule: "followup-not-linked", schoolId: f.schoolId,
        message: "Follow-Up SSA is not linked to any CorePlan." });
    }
    if (Math.abs((f.average ?? 0) - ssaAverage(f.scores)) > 0.05) {
      add({ severity: "warning", rule: "followup-average-mismatch", schoolId: f.schoolId,
        message: "Follow-Up SSA stored average does not match its scores." });
    }
  }

  const errors = findings.filter((f) => f.severity === "error").length;
  const warnings = findings.filter((f) => f.severity === "warning").length;
  return {
    ok: errors === 0,
    errors,
    warnings,
    checkedPlans: plans.length,
    checkedSlots: slots.length,
    findings,
    seedActive: coreSeedActive(),
  };
}

/** True when a candidate score clears the core threshold — small shared helper. */
export function meetsCoreThreshold(average: number): boolean {
  return average >= CORE_SSA_THRESHOLD;
}
