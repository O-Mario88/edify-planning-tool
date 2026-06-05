// Core School detail view-model — assembles the full lifecycle story for one
// schoolId from the unified store: why it became core, the 4 priority
// interventions, the 4+4 package, evidence + Salesforce/IA state, follow-up
// SSA, computed impact, champion review, and a derived timeline. One identity.

import "server-only";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { SSA_INTERVENTION_AREAS, type SsaInterventionArea } from "@/lib/intake/intake-core";
import {
  profileFor, planForSchool, interventionsForPlan, slotsForPlan,
  baselineSnapshot, followUpForPlan, onboardingFor, verificationFor,
  effectiveSchoolType,
} from "./core-store";
import { corePlanProgress, type CorePlanProgress } from "./core-progress";
import { coreDeliverySplit, type CoreDeliverySplit } from "./core-split";
import { coreImpactFor } from "./core-impact";
import type {
  CorePlan, CorePlanIntervention, CoreActivitySlot, CoreSsaSnapshot,
  CoreFollowUpSsa, CoreImpactSnapshot, CoreSchoolProfile, CoreSchoolOnboarding,
  CoreCandidateVerification,
} from "./core-types";

export type CoreTimelineEvent = { at: string; label: string; detail?: string };

export type CoreSchoolDetailVM = {
  schoolId: string;
  schoolName: string;
  district: string;
  region: string;
  cluster?: string;
  owner?: string;
  enrollment?: number;
  isCore: boolean;
  profile?: CoreSchoolProfile;
  onboarding?: CoreSchoolOnboarding;
  verification?: CoreCandidateVerification;
  plan?: CorePlan;
  progress?: CorePlanProgress;
  /** 2-staff / 2-partner delivery split across the 4 visits + 4 trainings. */
  deliverySplit?: CoreDeliverySplit;
  baseline?: CoreSsaSnapshot;
  interventions: CorePlanIntervention[];
  visits: CoreActivitySlot[];
  trainings: CoreActivitySlot[];
  followUp?: CoreFollowUpSsa;
  impact?: CoreImpactSnapshot;
  areas: readonly SsaInterventionArea[];
  timeline: CoreTimelineEvent[];
};

export function coreSchoolDetail(schoolId: string): CoreSchoolDetailVM | undefined {
  const school = intakeSchools.find((s) => s.schoolId === schoolId);
  if (!school) return undefined;

  const plan = planForSchool(schoolId);
  const slots = plan ? slotsForPlan(plan.id) : [];
  const baseline = plan ? baselineSnapshot(plan.baselineSSARecordId) : undefined;
  const followUp = plan ? followUpForPlan(plan.id) : undefined;
  const impact = plan ? coreImpactFor(plan.id) : undefined;
  const verification = verificationFor(schoolId);
  const onboarding = onboardingFor(schoolId);

  const timeline: CoreTimelineEvent[] = [];
  if (verification) timeline.push({ at: verification.verifiedAt, label: `Verified — ${verification.status}`, detail: `SSA Verification ID ${verification.verificationId}` });
  if (onboarding) timeline.push({ at: onboarding.onboardedAt, label: "Onboarded as Core", detail: `Baseline SSA ${onboarding.baselineAverageScore.toFixed(1)} · ${onboarding.previousSchoolType} → Core` });
  if (plan) timeline.push({ at: plan.createdAt, label: "Core plan created", detail: "4 priority interventions · 4 visits + 4 trainings" });
  for (const s of slots) {
    if (s.completedAt) timeline.push({ at: s.completedAt, label: `${s.activityType === "visit" ? "Visit" : "Training"} ${s.sequenceNumber} completed`, detail: s.salesforceId ? `Salesforce ${s.salesforceId}` : undefined });
  }
  if (followUp) timeline.push({ at: followUp.date, label: "Follow-Up SSA recorded", detail: `Average ${followUp.average.toFixed(1)}` });
  if (impact) timeline.push({ at: impact.computedAt, label: `Impact measured — ${impact.impactStatus}`, detail: `${impact.averageChange >= 0 ? "+" : ""}${impact.averageChange} avg SSA` });
  timeline.sort((a, b) => a.at.localeCompare(b.at));

  return {
    schoolId,
    schoolName: school.schoolName,
    district: school.district,
    region: school.region,
    cluster: school.cluster,
    owner: school.assignedCceo,
    enrollment: school.enrollment,
    isCore: effectiveSchoolType(schoolId) === "Core",
    profile: profileFor(schoolId),
    onboarding,
    verification,
    plan,
    progress: plan ? corePlanProgress(plan.id) : undefined,
    deliverySplit: plan ? coreDeliverySplit(slots) : undefined,
    baseline,
    interventions: plan ? interventionsForPlan(plan.id) : [],
    visits: slots.filter((s) => s.activityType === "visit").sort((a, b) => a.sequenceNumber - b.sequenceNumber),
    trainings: slots.filter((s) => s.activityType === "training").sort((a, b) => a.sequenceNumber - b.sequenceNumber),
    followUp,
    impact,
    areas: SSA_INTERVENTION_AREAS,
    timeline,
  };
}
