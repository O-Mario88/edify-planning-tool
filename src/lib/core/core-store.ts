// Unified Core School store — globalThis-backed, keyed on directory schoolId.
// Single home for SSA snapshots, candidate verifications, onboardings, core
// profiles, plans, interventions, activity slots, and follow-up SSAs. Seeded
// THROUGH the real School Directory (intakeSchools) with consistent ids so the
// whole lifecycle shares one identity. Production swap: replace the arrays with
// Prisma tables; accessors/mutators keep the same signatures.

import "server-only";
import { SSA_INTERVENTION_AREAS, ssaAverage, deriveFyFromDate, type SsaInterventionArea } from "@/lib/intake/intake-core";
import { intakeSchools } from "@/lib/intake/intake-mock";
import type {
  CoreSsaSnapshot,
  CoreCandidateVerification,
  CoreSchoolOnboarding,
  CoreSchoolProfile,
  CorePlan,
  CorePlanIntervention,
  CoreActivitySlot,
  CoreFollowUpSsa,
  CoreSsaScores,
} from "./core-types";
import { VISITS_TARGET, TRAININGS_TARGET } from "./core-types";

type CoreStore = {
  ssaSnapshots:    CoreSsaSnapshot[];
  verifications:   CoreCandidateVerification[];
  onboardings:     CoreSchoolOnboarding[];
  profiles:        CoreSchoolProfile[];
  plans:           CorePlan[];
  interventions:   CorePlanIntervention[];
  slots:           CoreActivitySlot[];
  followUps:       CoreFollowUpSsa[];
  /** schoolType overrides applied by onboarding (directory is immutable seed). */
  schoolTypeOverrides: Record<string, "Core">;
};

const STORE_KEY = "__edify_core_store__";
type GlobalWithStore = typeof globalThis & { [STORE_KEY]?: CoreStore };

// ─── Score helpers ──────────────────────────────────────────────────

function scoresOf(partial: Partial<Record<SsaInterventionArea, number>>, fill: number): CoreSsaScores {
  const out: CoreSsaScores = {};
  for (const a of SSA_INTERVENTION_AREAS) out[a] = partial[a] ?? fill;
  return out;
}

// ─── Seed ───────────────────────────────────────────────────────────

function seed(s: CoreStore) {
  if (process.env.NODE_ENV === "test") return;

  // 1. Candidate SSA snapshots (avg ≥ 7.5) for Client schools with SSA done —
  //    makes them Potential Core candidates derived from the directory.
  const candidates: { id: string; date: string; sc: CoreSsaScores }[] = [
    { id: "40118", date: "2026-03-14", sc: scoresOf({ "Teaching Environment": 8, "Leadership Best Practice": 8, "Learning Environment": 7, "Education Technology": 7 }, 8) },     // ~7.6
    { id: "61015", date: "2026-02-18", sc: scoresOf({ "Christlike Behaviour": 9, "Exposure to the Word of God": 8, "Learning Environment": 7, "Education Technology": 7 }, 8) }, // ~7.8
    { id: "70233", date: "2026-03-20", sc: scoresOf({ "Teaching Environment": 8, "Government Requirement": 7, "Fees/Budget and Accounts": 7, "Education Technology": 6 }, 8) },   // ~7.5
    { id: "52066", date: "2026-04-28", sc: scoresOf({ "Leadership Best Practice": 9, "Teaching Environment": 8, "Learning Environment": 8, "Education Technology": 7 }, 8) },     // ~8.1
  ];
  for (const c of candidates) {
    s.ssaSnapshots.push({
      id: `cssa-${c.id}-cand`, schoolId: c.id, kind: "candidate",
      fy: deriveFyFromDate(c.date), date: c.date, scores: c.sc, average: ssaAverage(c.sc),
    });
  }

  // 2. Existing Core schools → full lifecycle seeded through the directory.
  //    Each gets a baseline snapshot + onboarding + profile + plan + 4
  //    interventions + 8 slots, at varying progress.
  seedCoreSchool(s, {
    schoolId: "51884", baselineDate: "2026-01-20",
    baseline: scoresOf({ "Teaching Environment": 8, "Leadership Best Practice": 8, "Learning Environment": 7, "Education Technology": 6 }, 8),
    visitsDone: 2, trainingsDone: 1, onboardedAt: "2025-10-02",
  });
  seedCoreSchool(s, {
    schoolId: "61140", baselineDate: "2026-03-02",
    baseline: scoresOf({ "Government Requirement": 7, "Fees/Budget and Accounts": 7, "Teaching Environment": 8, "Education Technology": 7 }, 8),
    visitsDone: 1, trainingsDone: 0, onboardedAt: "2025-10-02",
  });
  seedCoreSchool(s, {
    schoolId: "90050", baselineDate: "2026-05-15",
    baseline: scoresOf({ "Leadership Best Practice": 8, "Learning Environment": 7, "Education Technology": 6, "Government Requirement": 7 }, 8),
    visitsDone: 0, trainingsDone: 0, onboardedAt: "2025-10-02",
  });
  // 33145 Goma Hill — completed package + follow-up SSA on file (drives impact).
  seedCoreSchool(s, {
    schoolId: "33145", baselineDate: "2025-11-10",
    baseline: scoresOf({ "Teaching Environment": 7, "Leadership Best Practice": 7, "Learning Environment": 7, "Education Technology": 6 }, 7),
    visitsDone: 4, trainingsDone: 4, onboardedAt: "2025-10-02",
    followUp: { date: "2026-05-20", scores: scoresOf({ "Teaching Environment": 9, "Leadership Best Practice": 9, "Learning Environment": 8, "Education Technology": 8 }, 9) },
  });
}

function seedCoreSchool(
  s: CoreStore,
  opts: {
    schoolId: string;
    baselineDate: string;
    baseline: CoreSsaScores;
    visitsDone: number;
    trainingsDone: number;
    onboardedAt: string;
    followUp?: { date: string; scores: CoreSsaScores };
  },
) {
  const { schoolId } = opts;
  const fy = deriveFyFromDate(opts.baselineDate);
  const baselineAvg = ssaAverage(opts.baseline);
  const baselineId = `cssa-${schoolId}-base`;
  s.ssaSnapshots.push({
    id: baselineId, schoolId, kind: "baseline", fy, date: opts.baselineDate,
    scores: opts.baseline, average: baselineAvg,
  });

  s.onboardings.push({
    id: `con-${schoolId}`, schoolId, fy, previousSchoolType: "Client", newSchoolType: "Core",
    baselineSSARecordId: baselineId, baselineAverageScore: baselineAvg,
    onboardedById: "STF-SO-007", onboardedByName: "Sarah Okello", onboardedAt: opts.onboardedAt,
    onboardingReason: "Verified Potential Core — SSA ≥ 7.5 across all areas.", status: "Onboarded",
  });
  s.schoolTypeOverrides[schoolId] = "Core";

  const planId = `cplan-${schoolId}`;
  const completed = opts.visitsDone >= VISITS_TARGET && opts.trainingsDone >= TRAININGS_TARGET;
  s.plans.push({
    id: planId, schoolId, fy, baselineSSARecordId: baselineId,
    followUpSSARecordId: opts.followUp ? `cssa-${schoolId}-follow` : undefined,
    status: opts.followUp ? "Impact Measured" : completed ? "Completed Pending Follow-Up SSA" : (opts.visitsDone + opts.trainingsDone > 0 ? "In Progress" : "Active"),
    visitsTarget: VISITS_TARGET, trainingsTarget: TRAININGS_TARGET,
    visitsCompleted: opts.visitsDone, trainingsCompleted: opts.trainingsDone,
    packageCompletionPercent: Math.round(((opts.visitsDone + opts.trainingsDone) / (VISITS_TARGET + TRAININGS_TARGET)) * 100),
    createdById: "STF-SO-007", createdByName: "Sarah Okello", createdAt: opts.onboardedAt, updatedAt: opts.onboardedAt,
  });

  s.profiles.push({
    id: `cprof-${schoolId}`, schoolId, activeCorePlanId: planId, coreStartFy: fy,
    championStatus: "Not Eligible", status: "Active",
  });

  // 4 priority interventions = the 4 weakest baseline areas.
  const ranked = [...SSA_INTERVENTION_AREAS]
    .map((a) => ({ area: a, score: opts.baseline[a] ?? 0 }))
    .sort((a, b) => a.score - b.score)
    .slice(0, 4);
  ranked.forEach((r, i) => {
    s.interventions.push({
      id: `cint-${schoolId}-${i + 1}`, corePlanId: planId, intervention: r.area,
      baselineScore: r.score, priorityRank: (i + 1) as 1 | 2 | 3 | 4,
      reason: "Auto-selected (weakest baseline).", selectedById: "STF-SO-007", selectedAt: opts.onboardedAt,
    });
  });

  // 8 activity slots (4 visits + 4 trainings), each tied to a priority area.
  (["visit", "training"] as const).forEach((type) => {
    const done = type === "visit" ? opts.visitsDone : opts.trainingsDone;
    for (let n = 1; n <= 4; n++) {
      const seq = n as 1 | 2 | 3 | 4;
      const inter = ranked[(n - 1) % ranked.length].area;
      const isDone = n <= done;
      s.slots.push({
        id: `cslot-${schoolId}-${type[0]}${n}`, corePlanId: planId, schoolId,
        intervention: inter, activityType: type, sequenceNumber: seq,
        status: isDone ? "Completed" : "Not Planned",
        owner: isDone ? "myself" : "unassigned",
        assignedStaffId: isDone ? "STF-PC-001" : undefined,
        assignedStaffName: isDone ? "Paul Chinyama" : undefined,
        salesforceId: isDone ? (type === "visit" ? `SVE-${5000 + n}` : `TS-${6000 + n}`) : undefined,
        iaVerificationStatus: isDone ? "Verified" : undefined,
        completedAt: isDone ? opts.onboardedAt : undefined,
        createdAt: opts.onboardedAt, updatedAt: opts.onboardedAt,
      });
    }
  });

  if (opts.followUp) {
    s.followUps.push({
      id: `cssa-${schoolId}-follow`, corePlanId: planId, schoolId,
      baselineSSARecordId: baselineId, fy: deriveFyFromDate(opts.followUp.date), date: opts.followUp.date,
      scores: opts.followUp.scores, average: ssaAverage(opts.followUp.scores),
      uploadedById: "STF-GA-042", uploadedByName: "Grace Alimo",
    });
    s.ssaSnapshots.push({
      id: `cssa-${schoolId}-follow`, schoolId, kind: "followup",
      fy: deriveFyFromDate(opts.followUp.date), date: opts.followUp.date,
      scores: opts.followUp.scores, average: ssaAverage(opts.followUp.scores),
    });
  }
}

function getStore(): CoreStore {
  const g = globalThis as GlobalWithStore;
  if (!g[STORE_KEY]) {
    const fresh: CoreStore = {
      ssaSnapshots: [], verifications: [], onboardings: [], profiles: [],
      plans: [], interventions: [], slots: [], followUps: [], schoolTypeOverrides: {},
    };
    seed(fresh);
    g[STORE_KEY] = fresh;
  }
  return g[STORE_KEY]!;
}

// ─── Accessors ──────────────────────────────────────────────────────

export function coreSsaSnapshots(): CoreSsaSnapshot[] { return getStore().ssaSnapshots; }
export function coreVerifications(): CoreCandidateVerification[] { return getStore().verifications; }
export function coreOnboardings(): CoreSchoolOnboarding[] { return getStore().onboardings; }
export function coreProfiles(): CoreSchoolProfile[] { return getStore().profiles; }
export function corePlans(): CorePlan[] { return getStore().plans; }
export function corePlanInterventions(): CorePlanIntervention[] { return getStore().interventions; }
export function coreSlots(): CoreActivitySlot[] { return getStore().slots; }
export function coreFollowUps(): CoreFollowUpSsa[] { return getStore().followUps; }

/** Effective school type — directory seed overlaid with onboarding promotions. */
export function effectiveSchoolType(schoolId: string): string {
  const override = getStore().schoolTypeOverrides[schoolId];
  if (override) return override;
  return intakeSchools.find((s) => s.schoolId === schoolId)?.schoolType ?? "Client";
}

export function candidateSnapshotFor(schoolId: string): CoreSsaSnapshot | undefined {
  return getStore().ssaSnapshots
    .filter((x) => x.schoolId === schoolId && x.kind === "candidate")
    .sort((a, b) => b.date.localeCompare(a.date))[0];
}
export function baselineSnapshot(id: string): CoreSsaSnapshot | undefined {
  return getStore().ssaSnapshots.find((x) => x.id === id);
}
export function verificationFor(schoolId: string): CoreCandidateVerification | undefined {
  return getStore().verifications.find((v) => v.schoolId === schoolId);
}
export function onboardingFor(schoolId: string): CoreSchoolOnboarding | undefined {
  return getStore().onboardings.find((o) => o.schoolId === schoolId);
}
export function profileFor(schoolId: string): CoreSchoolProfile | undefined {
  return getStore().profiles.find((p) => p.schoolId === schoolId);
}
export function planById(id: string): CorePlan | undefined {
  return getStore().plans.find((p) => p.id === id);
}
export function planForSchool(schoolId: string): CorePlan | undefined {
  return getStore().plans.find((p) => p.schoolId === schoolId);
}
export function interventionsForPlan(planId: string): CorePlanIntervention[] {
  return getStore().interventions.filter((i) => i.corePlanId === planId).sort((a, b) => a.priorityRank - b.priorityRank);
}
export function slotsForPlan(planId: string): CoreActivitySlot[] {
  return getStore().slots.filter((s) => s.corePlanId === planId);
}
export function slotById(id: string): CoreActivitySlot | undefined {
  return getStore().slots.find((s) => s.id === id);
}
export function followUpForPlan(planId: string): CoreFollowUpSsa | undefined {
  return getStore().followUps.find((f) => f.corePlanId === planId);
}

// ─── Mutators ───────────────────────────────────────────────────────

export function addSsaSnapshot(snap: CoreSsaSnapshot): CoreSsaSnapshot { getStore().ssaSnapshots.push(snap); return snap; }
export function addVerification(v: CoreCandidateVerification): CoreCandidateVerification { getStore().verifications.push(v); return v; }
export function addOnboarding(o: CoreSchoolOnboarding): CoreSchoolOnboarding {
  getStore().onboardings.push(o);
  if (o.status === "Onboarded") getStore().schoolTypeOverrides[o.schoolId] = "Core";
  return o;
}
export function addProfile(p: CoreSchoolProfile): CoreSchoolProfile { getStore().profiles.push(p); return p; }
export function addPlan(p: CorePlan): CorePlan { getStore().plans.push(p); return p; }
export function addIntervention(i: CorePlanIntervention): CorePlanIntervention { getStore().interventions.push(i); return i; }
export function addSlot(s: CoreActivitySlot): CoreActivitySlot { getStore().slots.push(s); return s; }
export function addFollowUp(f: CoreFollowUpSsa): CoreFollowUpSsa { getStore().followUps.push(f); return f; }

export function updatePlan(id: string, patch: Partial<CorePlan>): CorePlan | undefined {
  const store = getStore();
  const idx = store.plans.findIndex((p) => p.id === id);
  if (idx === -1) return undefined;
  store.plans[idx] = { ...store.plans[idx], ...patch, updatedAt: new Date().toISOString() };
  return store.plans[idx];
}
export function updateSlot(id: string, patch: Partial<CoreActivitySlot>): CoreActivitySlot | undefined {
  const store = getStore();
  const idx = store.slots.findIndex((s) => s.id === id);
  if (idx === -1) return undefined;
  store.slots[idx] = { ...store.slots[idx], ...patch, updatedAt: new Date().toISOString() };
  return store.slots[idx];
}
export function updateProfile(schoolId: string, patch: Partial<CoreSchoolProfile>): CoreSchoolProfile | undefined {
  const store = getStore();
  const idx = store.profiles.findIndex((p) => p.schoolId === schoolId);
  if (idx === -1) return undefined;
  store.profiles[idx] = { ...store.profiles[idx], ...patch };
  return store.profiles[idx];
}

export function __resetCoreStore() {
  const g = globalThis as GlobalWithStore;
  g[STORE_KEY] = undefined;
}
