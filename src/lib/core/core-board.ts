// Core board projection — scoped CorePlan cards for the planning board + the
// core directory. Reads the unified store (no hardcoded plans). Role-scoped:
// CCEO/PL see their directory schools; broader roles see all.

import "server-only";
import type { EdifyRole } from "@/lib/auth-public";
import { isBackendEnabled } from "@/lib/api/backend";
import { fetchCorePlans } from "@/lib/api/surfaces";
import type { BackendUser } from "@/lib/api/backend";
import { directoryRecords } from "@/lib/school-directory/directory";
import { intakeSchools } from "@/lib/intake/intake-mock";
import {
  corePlans, slotsForPlan, interventionsForPlan, profileFor,
} from "./core-store";
import { corePlanProgress, type CorePlanProgress } from "./core-progress";
import { coreImpactFor } from "./core-impact";
import type {
  CorePlan, CoreActivitySlot, CorePlanIntervention, CoreImpactSnapshot, ChampionStatus,
} from "./core-types";

export type CorePlanCardVM = {
  plan: CorePlan;
  schoolName: string;
  district: string;
  cluster?: string;
  owner?: string;
  baselineAverage: number;
  championStatus: ChampionStatus;
  progress: CorePlanProgress;
  interventions: CorePlanIntervention[];
  slots: CoreActivitySlot[];
  impact?: CoreImpactSnapshot;
};

const PARTNER_ROLES: EdifyRole[] = ["PartnerAdmin", "PartnerFieldOfficer"];

function scopeIds(staffId: string, role: EdifyRole): Set<string> | "all" {
  if (role === "CCEO" || role === "CountryProgramLead") {
    return new Set(directoryRecords(staffId, role).map((s) => s.schoolId));
  }
  // Partners see only core schools that have partner-assigned work (§21).
  if (PARTNER_ROLES.includes(role)) {
    const ids = new Set<string>();
    for (const p of corePlans()) {
      if (slotsForPlan(p.id).some((s) => !!s.assignedPartnerId || s.owner === "partner" || s.owner === "partner_facilitator")) ids.add(p.schoolId);
    }
    return ids;
  }
  return "all";
}

export async function resolveCoreBoardData(user: BackendUser, staffId: string, role: EdifyRole): Promise<CorePlanCardVM[]> {
  if (isBackendEnabled()) {
    const r = await fetchCorePlans(user);
    if (r.live && Array.isArray(r.data)) return r.data as CorePlanCardVM[];
    return [];
  }
  return coreBoardData(staffId, role);
}

export function coreBoardData(staffId: string, role: EdifyRole): CorePlanCardVM[] {
  const ids = scopeIds(staffId, role);
  return corePlans()
    .filter((p) => ids === "all" || ids.has(p.schoolId))
    .map((p) => {
      const school = intakeSchools.find((s) => s.schoolId === p.schoolId);
      const profile = profileFor(p.schoolId);
      return {
        plan: p,
        schoolName: school?.schoolName ?? p.schoolId,
        district: school?.district ?? "—",
        cluster: school?.cluster,
        owner: school?.assignedCceo,
        baselineAverage: p.packageCompletionPercent >= 0 ? (impactBaseline(p) ?? 0) : 0,
        championStatus: profile?.championStatus ?? "Not Eligible",
        progress: corePlanProgress(p.id),
        interventions: interventionsForPlan(p.id),
        slots: slotsForPlan(p.id),
        impact: coreImpactFor(p.id),
      };
    })
    .sort((a, b) => b.progress.packageCompletionPercent - a.progress.packageCompletionPercent);
}

function impactBaseline(p: CorePlan): number | undefined {
  // baseline average lives on the snapshot referenced by the plan.
  const interventions = interventionsForPlan(p.id);
  if (interventions.length === 0) return undefined;
  return Math.round((interventions.reduce((s, i) => s + i.baselineScore, 0) / interventions.length) * 10) / 10;
}

// ─── My-Plan ownership rows (derived from CoreActivitySlots) ────────

import type { PlanningStatus } from "@/lib/planning/status-tokens";
import type { CoreActivitySlotStatus } from "./core-types";

export type CoreOwnershipRow = {
  schoolId: string;
  schoolName: string;
  kind: "visit" | "training";
  number: number;
  intervention: string;
  planningStatus: PlanningStatus;
  /** Display label, e.g. "May 2026 · Wk 2". */
  scheduledFor?: string;
  /** Canonical schedule fields (separate from the display label) — used by
   *  My Plan's Partner section to bucket partner work by week/month without
   *  re-parsing the label. */
  scheduledMonth?: string;
  scheduledWeek?: number;
  ownerName?: string;
};

export type CoreOwnership = {
  assignedToMe: CoreOwnershipRow[];
  assignedToPartner: CoreOwnershipRow[];
  awaitingPartner: CoreOwnershipRow[];
  plannedThisMonth: CoreOwnershipRow[];
};

function slotPlanningStatus(s: CoreActivitySlotStatus): PlanningStatus {
  switch (s) {
    case "Not Planned": return "pending";
    case "Planned": case "Scheduled": case "Rescheduled": case "Assigned to Partner": case "Partner Scheduled": return "scheduled";
    case "In Progress": case "Evidence Uploaded": case "Evidence Accepted": case "Salesforce ID Required": case "Awaiting IA Verification": return "in_flight";
    case "IA Verified": case "Accountant Confirmed": return "verified";
    case "Completed": return "done";
    case "Returned": case "Rejected": return "blocked";
  }
}

export function coreOwnershipRows(staffId: string, role: EdifyRole): CoreOwnership {
  const cards = coreBoardData(staffId, role);
  const assignedToMe: CoreOwnershipRow[] = [];
  const assignedToPartner: CoreOwnershipRow[] = [];
  const awaitingPartner: CoreOwnershipRow[] = [];
  const plannedThisMonth: CoreOwnershipRow[] = [];

  for (const card of cards) {
    for (const s of card.slots) {
      const row: CoreOwnershipRow = {
        schoolId: s.schoolId,
        schoolName: card.schoolName,
        kind: s.activityType,
        number: s.sequenceNumber,
        intervention: s.intervention,
        planningStatus: slotPlanningStatus(s.status),
        scheduledFor: s.scheduledFor,
        scheduledMonth: s.scheduledMonth,
        scheduledWeek: s.scheduledWeek,
        ownerName: s.assignedStaffName ?? s.assignedPartnerName,
      };
      const isPartner = s.owner === "partner" || s.owner === "partner_facilitator" || !!s.assignedPartnerId;
      if (s.assignedStaffId === staffId || s.owner === "myself") assignedToMe.push(row);
      if (isPartner) {
        assignedToPartner.push(row);
        if (s.status === "Assigned to Partner") awaitingPartner.push(row);
      }
      if (s.scheduledFor && s.status !== "Completed" && s.status !== "Returned" && s.status !== "Rejected") plannedThisMonth.push(row);
    }
  }
  return { assignedToMe, assignedToPartner, awaitingPartner, plannedThisMonth };
}

// Gap buckets (§10) live in core-gaps (pure, client-safe). Re-exported here so
// server callers can keep importing from the board.
export { CORE_GAP_TABS, coreCardGaps, coreGapCounts, type CoreGapTab } from "./core-gaps";

export function coreBoardSummary(cards: CorePlanCardVM[]) {
  return {
    plans: cards.length,
    active: cards.filter((c) => c.plan.status === "Active" || c.plan.status === "In Progress").length,
    pendingFollowUp: cards.filter((c) => c.plan.status === "Completed Pending Follow-Up SSA").length,
    impactMeasured: cards.filter((c) => !!c.impact).length,
    champions: cards.filter((c) => c.championStatus !== "Not Eligible").length,
    visitsDone: cards.reduce((s, c) => s + c.progress.visitsCompleted, 0),
    trainingsDone: cards.reduce((s, c) => s + c.progress.trainingsCompleted, 0),
  };
}
