// Core school planning — data model + engine + mock.
//
// Core rule: No completed SSA → no core school visit/training schedule.
// After SSA, the system identifies the 4 weakest interventions and
// generates a 4-visit + 4-training support cycle. The planning page
// shows where each core school is stuck.

export type SsaInterventionArea =
  | "Teaching & Learning"
  | "Leadership"
  | "Financial Health"
  | "Learning Environment"
  | "Government Requirements & Compliance"
  | "Education Technology"
  | "Christlike Behaviour"
  | "Exposure to the Word of God";

export type CoreActivityStatus =
  | "blocked"        // SSA not done → activity not yet scheduled and shouldn't be
  | "not_started"    // SSA done, activity in plan but no schedule yet
  | "scheduled"      // assigned + date chosen
  | "delivered"      // happened on the ground
  | "verified"       // M&E verified
  | "completed";     // counts toward the 4/4 progress

export type CoreActivityOwner =
  | "unassigned"
  | "myself"
  | "staff"
  | "partner"
  | "partner_facilitator";

export type CoreActivity = {
  number: 1 | 2 | 3 | 4;
  intervention: SsaInterventionArea;
  status: CoreActivityStatus;
  scheduledFor?: string;     // "Wk 24" or "Jun 12, 2026"
  owner: CoreActivityOwner;
  ownerName?: string;
};

export type CoreSchoolPlan = {
  id: string;
  schoolName: string;
  district: string;
  subCounty: string;
  parish?: string;
  assignedCceo: string;
  assignedPartner?: string;
  /**
   * School Improvement Training status for the CURRENT cycle. SIT is
   * the FIRST gate in the planning unlock — a school cannot plan
   * activities until it has attended SIT. SIT alone is NOT enough;
   * SSA must also complete (see `ssaStatus`). The system enforces
   * SIT → SSA → Planning Enabled in that order.
   */
  sitStatus: "not_started" | "scheduled" | "completed";
  /** Date the most recent SIT cohort was attended (ISO). */
  sitDate?: string;
  ssaStatus: "not_started" | "in_progress" | "complete";
  ssaDate?: string;
  /**
   * The most recent SSA date on file regardless of cycle (ISO).
   * When `ssaStatus === "complete"` this equals `ssaDate`. When
   * `ssaStatus === "not_started"` but the school had an SSA in a
   * prior cycle, this is that previous-cycle date — the planning UI
   * uses it to render "Historical Only · Last: <date>" so planners
   * aren't confused by a school that "looks new" on Oct 1 just because
   * the current cycle reset its counters.
   */
  lastSsaIso?: string;
  /// 4 priority interventions ranked weakest-first. Each is paired
  /// with the SSA score that drove the prioritisation.
  priorityInterventions: { area: SsaInterventionArea; score: number }[];
  visits:    [CoreActivity, CoreActivity, CoreActivity, CoreActivity];
  trainings: [CoreActivity, CoreActivity, CoreActivity, CoreActivity];
};

// ────────── Planning readiness ──────────
//
// One-call status that every card and approval workflow reads to
// decide whether the school can be planned for. The rule is strict:
//
//   1. No SIT       → fully locked. Only "Schedule SIT with SSA" allowed.
//   2. SIT done, no SSA → partially locked. Only "Complete SSA" allowed.
//   3. SIT + SSA both done → planning enabled. Activities allowed.
//   4. Previous-cycle SSA only → expired. Current-cycle SSA required.
//   5. Conflicting records → blocked. Admin resolves data issue.
//
// Surfaced via the PlanningReadiness type and `planningReadiness()`
// helper so the UI never re-implements the rule.

export type PlanningReadinessStatus =
  | "locked_sit"      // Fully locked — no SIT (and therefore no SSA recs)
  | "locked_ssa"      // Partial — SIT done, but SSA missing
  | "ready"           // SIT + SSA done — planning enabled
  | "expired"         // Previous-cycle SSA exists; current cycle missing
  | "blocked";        // Data conflict — admin must resolve

export type PlanningReadiness = {
  status:        PlanningReadinessStatus;
  label:         string;       // user-facing pill ("Locked: SIT Required" etc.)
  reason:        string;       // one-sentence rationale shown under the pill
  /** Single allowed action while locked — undefined when ready. */
  allowedAction?:
    | "schedule_sit_with_ssa"
    | "complete_ssa"
    | "schedule_current_cycle_ssa"
    | "resolve_data_issue";
  /** Convenience flag for callers that just need yes/no on planning. */
  planningEnabled: boolean;
};

export function planningReadiness(plan: CoreSchoolPlan): PlanningReadiness {
  // 1. No SIT — fully locked.
  if (plan.sitStatus !== "completed") {
    return {
      status:          "locked_sit",
      label:           "Locked: SIT Required",
      reason:          "School has not completed School Improvement Training. All planning is disabled until SIT runs and SSA completes within it.",
      allowedAction:   "schedule_sit_with_ssa",
      planningEnabled: false,
    };
  }
  // 2. SIT done, no current-cycle SSA — partially locked.
  if (plan.ssaStatus !== "complete") {
    // Distinguish "had a prior-cycle SSA but not current" from "never had one"
    // for a sharper user-facing label.
    if (plan.lastSsaIso) {
      return {
        status:          "expired",
        label:           "Expired: New Cycle SSA Required",
        reason:          `Previous-cycle SSA on file (${plan.lastSsaIso}). All planning waits for the current-cycle SSA — recommendations from last cycle are archived but no longer drive activities.`,
        allowedAction:   "schedule_current_cycle_ssa",
        planningEnabled: false,
      };
    }
    return {
      status:          "locked_ssa",
      label:           "Locked: SSA Missing",
      reason:          "School Improvement Training was completed, but SSA is missing. Planning remains locked because every activity depends on SSA recommendations.",
      allowedAction:   "complete_ssa",
      planningEnabled: false,
    };
  }
  // 3. Both done — planning enabled.
  return {
    status:          "ready",
    label:           "Ready: SSA Recommendations Available",
    reason:          "SIT and SSA are both complete for the current cycle. Use the priority interventions below to plan visits, trainings, partner assignments, and cluster activities.",
    planningEnabled: true,
  };
}

// ────────── Engine ──────────

export type CoreGapKey =
  | "no_sit"
  | "no_ssa"
  | "expired_ssa"
  | "no_first_visit"  | "no_second_visit"  | "no_third_visit"  | "no_fourth_visit"
  | "no_first_training" | "no_second_training" | "no_third_training" | "no_fourth_training"
  | "cycle_complete";

export type CoreRecommendation = {
  gap: CoreGapKey;
  headline: string;
  purpose: string;
  primaryAction:
    | "schedule_sit_with_ssa"
    | "schedule_ssa"
    | "schedule_visit"
    | "schedule_training"
    | "schedule_followup_ssa"
    | "view";
  primaryLabel: string;
  activityNumber?: 1 | 2 | 3 | 4;
  intervention?: SsaInterventionArea;
  /// Set when SIT/SSA not complete — UI disables intervention-based
  /// actions and surfaces only the single allowed CTA.
  blockedReason?: string;
};

function isComplete(a: CoreActivity): boolean {
  return a.status === "completed" || a.status === "verified";
}

export function nextCoreGap(plan: CoreSchoolPlan): CoreRecommendation {
  // ── Gate 1: SIT must be completed for the current cycle. ──────────
  // No SIT = no planning of any kind. SSA happens during/through SIT,
  // so the single allowed action is "Schedule SIT with SSA".
  if (plan.sitStatus !== "completed") {
    return {
      gap: "no_sit",
      headline: `Schedule School Improvement Training (with SSA) for ${plan.schoolName}`,
      purpose:
        "Planning is fully locked until School Improvement Training is delivered and SSA completes within it. SIT generates the SSA recommendations that drive every downstream activity — no visit, training, partner assignment, or budget can be planned before this step.",
      primaryAction: "schedule_sit_with_ssa",
      primaryLabel: "Schedule SIT with SSA",
      blockedReason: "Planning is locked — School Improvement Training has not been completed.",
    };
  }

  // ── Gate 2: SSA must be complete for the current cycle. ──────────
  // SIT can complete while SSA is still in progress; in that window
  // planning is partially locked and the only allowed action is
  // "Complete SSA". When SSA exists only for a prior cycle, the
  // expired_ssa label sharpens the user-facing message.
  if (plan.ssaStatus !== "complete") {
    if (plan.lastSsaIso) {
      return {
        gap: "expired_ssa",
        headline: `Complete current-cycle SSA for ${plan.schoolName}`,
        purpose:
          `Previous-cycle SSA on file (${plan.lastSsaIso}) — recommendations from that cycle are archived but no longer drive planning. The current cycle's SSA must complete before any visits, trainings, or partner activities can be scheduled.`,
        primaryAction: "schedule_ssa",
        primaryLabel: "Complete current-cycle SSA",
        blockedReason: "Planning is locked — current-cycle SSA missing (previous-cycle SSA is archived only).",
      };
    }
    return {
      gap: "no_ssa",
      headline: `Complete SSA for ${plan.schoolName}`,
      purpose:
        "School Improvement Training was completed, but SSA is missing. Planning remains locked because every activity (visit, training, partner support, budget) depends on SSA recommendations. The single allowed action is to complete SSA.",
      primaryAction: "schedule_ssa",
      primaryLabel: "Complete SSA",
      blockedReason: "Planning is locked — SSA recommendations required.",
    };
  }

  // Visits + trainings progress in lock-step. We interleave —
  // the spec lists Visit 1 → Training 1 → Visit 2 → Training 2 …
  // so the partner reaches all 4 interventions in alternating
  // delivery + training cycles.
  for (let n = 1 as 1 | 2 | 3 | 4; n <= 4; n++) {
    const visit = plan.visits[(n - 1) as 0 | 1 | 2 | 3];
    if (!isComplete(visit)) {
      const inter = plan.priorityInterventions[(n - 1) as 0 | 1 | 2 | 3];
      return {
        gap: `no_${ordinal(n)}_visit` as CoreGapKey,
        headline: `Schedule ${ordinalLabel(n)} Visit focused on ${inter.area}`,
        purpose: visitPurposeFor(inter.area, inter.score, n),
        primaryAction: "schedule_visit",
        primaryLabel: `Schedule Visit ${n}`,
        activityNumber: n,
        intervention: inter.area,
      };
    }
    const training = plan.trainings[(n - 1) as 0 | 1 | 2 | 3];
    if (!isComplete(training)) {
      const inter = plan.priorityInterventions[(n - 1) as 0 | 1 | 2 | 3];
      return {
        gap: `no_${ordinal(n)}_training` as CoreGapKey,
        headline: `Schedule ${ordinalLabel(n)} Training focused on ${inter.area}`,
        purpose: trainingPurposeFor(inter.area, inter.score, n),
        primaryAction: "schedule_training",
        primaryLabel: `Schedule Training ${n}`,
        activityNumber: n,
        intervention: inter.area,
      };
    }
  }

  // All 8 complete → recommend the follow-up SSA.
  return {
    gap: "cycle_complete",
    headline: "Schedule follow-up SSA to measure impact",
    purpose: "Core support cycle completed. Compare baseline SSA against the new SSA to measure improvement across the four supported interventions.",
    primaryAction: "schedule_followup_ssa",
    primaryLabel: "Schedule follow-up SSA",
  };
}

function ordinal(n: 1 | 2 | 3 | 4): string {
  return n === 1 ? "first" : n === 2 ? "second" : n === 3 ? "third" : "fourth";
}
function ordinalLabel(n: 1 | 2 | 3 | 4): string {
  return n === 1 ? "First" : n === 2 ? "Second" : n === 3 ? "Third" : "Fourth";
}
function visitPurposeFor(area: SsaInterventionArea, score: number, n: 1 | 2 | 3 | 4): string {
  if (n === 1) return `Support the school to improve ${area} because the latest SSA score is ${score}/10, below the acceptable threshold.`;
  return `${ordinalLabel(n)} core support visit focused on ${area} (SSA ${score}/10) — the ${ordinal(n)} priority intervention in this school's plan.`;
}
function trainingPurposeFor(area: SsaInterventionArea, score: number, n: 1 | 2 | 3 | 4): string {
  if (n === 1) return `Conduct School Improvement Training focused on ${area} because the school scored ${score}/10 in ${area} during the latest SSA.`;
  return `${ordinalLabel(n)} core training focused on ${area} (SSA ${score}/10) — the ${ordinal(n)} priority intervention in this school's plan.`;
}

export function progressOf(plan: CoreSchoolPlan): { visits: number; trainings: number; pct: number } {
  // Activities only count toward progress when the planning gate is open.
  // SIT-locked or SSA-locked schools always show 0 / 0 / 0% so the cycle
  // bar doesn't lie about how far along the school is.
  if (plan.sitStatus !== "completed" || plan.ssaStatus !== "complete") {
    return { visits: 0, trainings: 0, pct: 0 };
  }
  const v = plan.visits.filter(isComplete).length;
  const t = plan.trainings.filter(isComplete).length;
  const pct = Math.round(((v + t) / 8) * 100);
  return { visits: v, trainings: t, pct };
}

// ────────── Mock ──────────

function blockedActivity(n: 1 | 2 | 3 | 4, area: SsaInterventionArea): CoreActivity {
  return { number: n, intervention: area, status: "blocked", owner: "unassigned" };
}
function pendingActivity(n: 1 | 2 | 3 | 4, area: SsaInterventionArea): CoreActivity {
  return { number: n, intervention: area, status: "not_started", owner: "unassigned" };
}
function doneActivity(n: 1 | 2 | 3 | 4, area: SsaInterventionArea, when: string, owner: CoreActivityOwner, ownerName?: string): CoreActivity {
  return { number: n, intervention: area, status: "completed", owner, ownerName, scheduledFor: when };
}
function scheduledActivity(n: 1 | 2 | 3 | 4, area: SsaInterventionArea, when: string, owner: CoreActivityOwner, ownerName?: string): CoreActivity {
  return { number: n, intervention: area, status: "scheduled", owner, ownerName, scheduledFor: when };
}

// 12 core schools at varied stages of the 4×4 cycle.
export const coreSchoolPlans: CoreSchoolPlan[] = [
  // ─── No SSA — fully blocked ───
  {
    id: "CS-GRACE", schoolName: "Grace Primary School", district: "Pader", subCounty: "Atanga", parish: "Laguti",
    assignedCceo: "Sarah Nanyongo",
    sitStatus: "not_started",   // Demo: Locked: SIT Required — fully locked
    ssaStatus: "not_started",
    priorityInterventions: [],
    visits:    [blockedActivity(1, "Teaching & Learning"), blockedActivity(2, "Leadership"), blockedActivity(3, "Financial Health"), blockedActivity(4, "Learning Environment")],
    trainings: [blockedActivity(1, "Teaching & Learning"), blockedActivity(2, "Leadership"), blockedActivity(3, "Financial Health"), blockedActivity(4, "Learning Environment")],
  },
  {
    // Demo: this school completed SSA last cycle (Jul 2025) but no
    // current-cycle SSA — surfaces the "Historical Only · Last: …"
    // badge so planners see the prior record and the reset requirement.
    id: "CS-MAPLE", schoolName: "Maple Grove Primary", district: "Kayunga", subCounty: "Bbaale",
    assignedCceo: "Sarah Nanyongo",
    sitStatus: "completed", sitDate: "2025-11-04",  // Demo: Expired — SIT done this cycle but only prior-cycle SSA on file
    ssaStatus: "not_started",
    lastSsaIso: "2025-07-22",
    priorityInterventions: [],
    visits:    [blockedActivity(1, "Teaching & Learning"), blockedActivity(2, "Leadership"), blockedActivity(3, "Financial Health"), blockedActivity(4, "Learning Environment")],
    trainings: [blockedActivity(1, "Teaching & Learning"), blockedActivity(2, "Leadership"), blockedActivity(3, "Financial Health"), blockedActivity(4, "Learning Environment")],
  },
  {
    id: "CS-GALIRAAYA", schoolName: "Galiraaya Primary", district: "Kayunga", subCounty: "Galiraaya",
    assignedCceo: "Sarah Nanyongo",
    sitStatus: "completed", sitDate: "2025-10-28",  // Demo: Locked: SSA Missing — SIT done, SSA in progress but not complete
    ssaStatus: "in_progress",
    priorityInterventions: [],
    visits:    [blockedActivity(1, "Teaching & Learning"), blockedActivity(2, "Leadership"), blockedActivity(3, "Financial Health"), blockedActivity(4, "Learning Environment")],
    trainings: [blockedActivity(1, "Teaching & Learning"), blockedActivity(2, "Leadership"), blockedActivity(3, "Financial Health"), blockedActivity(4, "Learning Environment")],
  },

  // ─── SSA done, nothing scheduled yet ───
  {
    id: "CS-HOPE", schoolName: "Hope Primary School", district: "Mukono", subCounty: "Ntenjeru", parish: "Ntenjeru",
    assignedCceo: "Sarah Nanyongo",
    assignedPartner: "Bright Future Education Partners",
    sitStatus: "completed", sitDate: "2026-02-26", ssaStatus: "complete", ssaDate: "2026-03-12",
    priorityInterventions: [
      { area: "Teaching & Learning", score: 4 },
      { area: "Leadership",          score: 5 },
      { area: "Financial Health",    score: 5 },
      { area: "Learning Environment",score: 6 },
    ],
    visits:    [pendingActivity(1, "Teaching & Learning"), pendingActivity(2, "Leadership"), pendingActivity(3, "Financial Health"), pendingActivity(4, "Learning Environment")],
    trainings: [pendingActivity(1, "Teaching & Learning"), pendingActivity(2, "Leadership"), pendingActivity(3, "Financial Health"), pendingActivity(4, "Learning Environment")],
  },
  {
    id: "CS-SUNRISE", schoolName: "Sunrise Junior School", district: "Mukono", subCounty: "Mukono Central",
    assignedCceo: "Sarah Nanyongo",
    sitStatus: "completed", sitDate: "2026-01-22", ssaStatus: "complete", ssaDate: "2026-02-08",
    priorityInterventions: [
      { area: "Teaching & Learning", score: 5 },
      { area: "Learning Environment",score: 5 },
      { area: "Financial Health",    score: 6 },
      { area: "Education Technology",score: 7 },
    ],
    visits:    [pendingActivity(1, "Teaching & Learning"), pendingActivity(2, "Learning Environment"), pendingActivity(3, "Financial Health"), pendingActivity(4, "Education Technology")],
    trainings: [pendingActivity(1, "Teaching & Learning"), pendingActivity(2, "Learning Environment"), pendingActivity(3, "Financial Health"), pendingActivity(4, "Education Technology")],
  },

  // ─── Mid-cycle: Visit 1 done, Training 1 next ───
  {
    id: "CS-KIREKA", schoolName: "Kireka Primary School", district: "Mukono", subCounty: "Kireka",
    assignedCceo: "Sarah Nanyongo",
    assignedPartner: "Bright Future Education Partners",
    sitStatus: "completed", sitDate: "2025-12-30", ssaStatus: "complete", ssaDate: "2026-01-15",
    priorityInterventions: [
      { area: "Leadership",          score: 5 },
      { area: "Teaching & Learning", score: 6 },
      { area: "Financial Health",    score: 6 },
      { area: "Learning Environment",score: 7 },
    ],
    visits: [
      doneActivity(1, "Leadership",          "Apr 22, 2026", "staff", "Sarah Nanyongo"),
      pendingActivity(2, "Teaching & Learning"),
      pendingActivity(3, "Financial Health"),
      pendingActivity(4, "Learning Environment"),
    ],
    trainings: [
      pendingActivity(1, "Leadership"),
      pendingActivity(2, "Teaching & Learning"),
      pendingActivity(3, "Financial Health"),
      pendingActivity(4, "Learning Environment"),
    ],
  },

  // ─── Mid-cycle: Visit 1 + Training 1 done, Visit 2 next ───
  {
    id: "CS-GRACE-PR", schoolName: "Grace Primary School (Mukono)", district: "Mukono", subCounty: "Nsumba",
    assignedCceo: "Sarah Nanyongo",
    assignedPartner: "Bright Future Education Partners",
    sitStatus: "completed", sitDate: "2026-01-24", ssaStatus: "complete", ssaDate: "2026-02-10",
    priorityInterventions: [
      { area: "Teaching & Learning", score: 5 },
      { area: "Leadership",          score: 5 },
      { area: "Financial Health",    score: 6 },
      { area: "Learning Environment",score: 7 },
    ],
    visits: [
      doneActivity(1, "Teaching & Learning", "May 13, 2026", "partner", "BFEP"),
      pendingActivity(2, "Leadership"),
      pendingActivity(3, "Financial Health"),
      pendingActivity(4, "Learning Environment"),
    ],
    trainings: [
      doneActivity(1, "Teaching & Learning", "Apr 22, 2026", "partner_facilitator", "BFEP"),
      pendingActivity(2, "Leadership"),
      pendingActivity(3, "Financial Health"),
      pendingActivity(4, "Learning Environment"),
    ],
  },

  // ─── Mid-cycle: visits ahead of trainings ───
  {
    id: "CS-STMARY", schoolName: "St. Mary's Primary", district: "Kayunga", subCounty: "Kayunga Central",
    assignedCceo: "Sarah Nanyongo",
    assignedPartner: "Bright Future Education Partners",
    sitStatus: "completed", sitDate: "2026-02-05", ssaStatus: "complete", ssaDate: "2026-02-22",
    priorityInterventions: [
      { area: "Leadership",          score: 5 },
      { area: "Teaching & Learning", score: 6 },
      { area: "Financial Health",    score: 6 },
      { area: "Learning Environment",score: 7 },
    ],
    visits: [
      doneActivity(1, "Leadership",          "Apr 12, 2026", "staff", "Sarah Nanyongo"),
      scheduledActivity(2, "Teaching & Learning", "Wk 24 · May 27", "partner", "BFEP"),
      pendingActivity(3, "Financial Health"),
      pendingActivity(4, "Learning Environment"),
    ],
    trainings: [
      pendingActivity(1, "Leadership"),
      pendingActivity(2, "Teaching & Learning"),
      pendingActivity(3, "Financial Health"),
      pendingActivity(4, "Learning Environment"),
    ],
  },

  // ─── Late cycle: 3 visits + 2 trainings done ───
  {
    id: "CS-NAMI", schoolName: "Namilyango Primary", district: "Mukono", subCounty: "Namilyango",
    assignedCceo: "Sarah Nanyongo",
    assignedPartner: "Bright Future Education Partners",
    sitStatus: "completed", sitDate: "2026-01-04", ssaStatus: "complete", ssaDate: "2026-01-20",
    priorityInterventions: [
      { area: "Learning Environment",score: 5 },
      { area: "Teaching & Learning", score: 6 },
      { area: "Financial Health",    score: 6 },
      { area: "Leadership",          score: 7 },
    ],
    visits: [
      doneActivity(1, "Learning Environment", "Feb 24, 2026", "partner", "BFEP"),
      doneActivity(2, "Teaching & Learning",  "Mar 18, 2026", "partner", "BFEP"),
      doneActivity(3, "Financial Health",     "Apr 28, 2026", "staff",   "Sarah Nanyongo"),
      pendingActivity(4, "Leadership"),
    ],
    trainings: [
      doneActivity(1, "Learning Environment", "Mar 02, 2026", "partner_facilitator", "BFEP"),
      doneActivity(2, "Teaching & Learning",  "Apr 06, 2026", "partner_facilitator", "BFEP"),
      pendingActivity(3, "Financial Health"),
      pendingActivity(4, "Leadership"),
    ],
  },

  // ─── Cycle complete — follow-up SSA recommended ───
  {
    id: "CS-EAST", schoolName: "Eastview Junior", district: "Mukono", subCounty: "Nakifuma",
    assignedCceo: "Sarah Nanyongo",
    assignedPartner: "Bright Future Education Partners",
    sitStatus: "completed", sitDate: "2025-11-22", ssaStatus: "complete", ssaDate: "2025-12-10",
    priorityInterventions: [
      { area: "Leadership",          score: 6 },
      { area: "Teaching & Learning", score: 6 },
      { area: "Christlike Behaviour",score: 7 },
      { area: "Financial Health",    score: 7 },
    ],
    visits: [
      doneActivity(1, "Leadership",           "Jan 16, 2026", "staff", "Sarah Nanyongo"),
      doneActivity(2, "Teaching & Learning",  "Feb 20, 2026", "partner", "BFEP"),
      doneActivity(3, "Christlike Behaviour", "Mar 24, 2026", "staff", "Sarah Nanyongo"),
      doneActivity(4, "Financial Health",     "Apr 30, 2026", "partner", "BFEP"),
    ],
    trainings: [
      doneActivity(1, "Leadership",           "Feb 02, 2026", "partner_facilitator", "BFEP"),
      doneActivity(2, "Teaching & Learning",  "Mar 06, 2026", "partner_facilitator", "BFEP"),
      doneActivity(3, "Christlike Behaviour", "Apr 04, 2026", "staff", "Sarah Nanyongo"),
      doneActivity(4, "Financial Health",     "May 12, 2026", "partner_facilitator", "BFEP"),
    ],
  },

  // ─── Scheduled-but-not-delivered visit (counts as in-flight) ───
  {
    id: "CS-BRIGHT", schoolName: "Bright Future PS", district: "Mukono", subCounty: "Bukoto",
    assignedCceo: "Sarah Nanyongo",
    sitStatus: "completed", sitDate: "2025-12-18", ssaStatus: "complete", ssaDate: "2026-01-05",
    priorityInterventions: [
      { area: "Financial Health",    score: 5 },
      { area: "Leadership",          score: 6 },
      { area: "Teaching & Learning", score: 6 },
      { area: "Learning Environment",score: 7 },
    ],
    visits: [
      scheduledActivity(1, "Financial Health", "Wk 24 · May 26", "myself", "Sarah Nanyongo"),
      pendingActivity(2, "Leadership"),
      pendingActivity(3, "Teaching & Learning"),
      pendingActivity(4, "Learning Environment"),
    ],
    trainings: [
      pendingActivity(1, "Financial Health"),
      pendingActivity(2, "Leadership"),
      pendingActivity(3, "Teaching & Learning"),
      pendingActivity(4, "Learning Environment"),
    ],
  },

  // ─── Late-cycle — 4 visits done, 3 trainings done, last training next ───
  {
    id: "CS-LAKEVIEW", schoolName: "Lakeview Primary", district: "Kayunga", subCounty: "Galiraaya",
    assignedCceo: "Sarah Nanyongo",
    assignedPartner: "Bright Future Education Partners",
    sitStatus: "completed", sitDate: "2025-12-24", ssaStatus: "complete", ssaDate: "2026-01-10",
    priorityInterventions: [
      { area: "Teaching & Learning",  score: 4 },
      { area: "Education Technology", score: 5 },
      { area: "Financial Health",     score: 6 },
      { area: "Leadership",           score: 7 },
    ],
    visits: [
      doneActivity(1, "Teaching & Learning",  "Feb 18, 2026", "partner", "BFEP"),
      doneActivity(2, "Education Technology", "Mar 12, 2026", "staff",   "Sarah Nanyongo"),
      doneActivity(3, "Financial Health",     "Apr 14, 2026", "partner", "BFEP"),
      doneActivity(4, "Leadership",           "May 02, 2026", "staff",   "Sarah Nanyongo"),
    ],
    trainings: [
      doneActivity(1, "Teaching & Learning",  "Mar 04, 2026", "partner_facilitator", "BFEP"),
      doneActivity(2, "Education Technology", "Apr 02, 2026", "partner_facilitator", "BFEP"),
      doneActivity(3, "Financial Health",     "Apr 28, 2026", "staff", "Sarah Nanyongo"),
      pendingActivity(4, "Leadership"),
    ],
  },
];

// ────────── Aggregates ──────────

export type CorePlanningTab =
  | "no_ssa"
  | "visit_gaps"
  | "training_gaps"
  | "ready_to_plan"
  | "assigned_to_partner"
  | "awaiting_partner_schedule"
  | "completed";

/**
 * Granular per-step counts powering the 2-row summary tile grid + tab
 * counts on the Core Schools Gap Planning section. Each visit/training
 * tile counts the *next-needed step* for SSA-complete schools — they
 * don't overlap, so the numbers stay informative across the row.
 *
 * `noVisits` / `noTraining` are the lifetime "0 done" counts — by
 * construction equal to the corresponding "no 1st …" counts but
 * surfaced with friendlier labels in the tile row.
 */
export function coreSchoolSummary() {
  let noSsa = 0;
  let noVisits = 0, no1V = 0, no2V = 0, no3V = 0, no4V = 0;
  let noTraining = 0, no1T = 0, no2T = 0, no3T = 0, no4T = 0;
  let ready = 0, inFlight = 0, cycleComplete = 0;
  let assignedToPartner = 0, awaitingPartnerSchedule = 0;

  for (const p of coreSchoolPlans) {
    const rec = nextCoreGap(p);
    const prog = progressOf(p);

    if (rec.gap === "no_ssa") {
      noSsa++;
      continue; // SSA-blocked schools don't contribute to visit/training tiles
    }
    if (rec.gap === "cycle_complete") {
      cycleComplete++;
      continue;
    }

    // Next-needed step counts — strictly non-overlapping.
    if (prog.visits === 0)                       { noVisits++; no1V++; }
    else if (rec.gap === "no_second_visit")      { no2V++; }
    else if (rec.gap === "no_third_visit")       { no3V++; }
    else if (rec.gap === "no_fourth_visit")      { no4V++; }

    if (prog.trainings === 0)                    { noTraining++; no1T++; }
    else if (rec.gap === "no_second_training")   { no2T++; }
    else if (rec.gap === "no_third_training")    { no3T++; }
    else if (rec.gap === "no_fourth_training")   { no4T++; }

    if (prog.visits === 0 && prog.trainings === 0) ready++;
    else                                            inFlight++;

    // Ownership counts (any activity in the plan).
    const allActivities = [...p.visits, ...p.trainings];
    if (allActivities.some((a) => a.owner === "partner" || a.owner === "partner_facilitator")) {
      assignedToPartner++;
    }
    if (allActivities.some(
      (a) => (a.owner === "partner" || a.owner === "partner_facilitator") && a.status === "not_started",
    )) {
      awaitingPartnerSchedule++;
    }
  }

  return {
    total: coreSchoolPlans.length,
    noSsa,
    // Row 1 — SSA + Visits
    noVisits,
    noFirstVisit:  no1V,
    noSecondVisit: no2V,
    noThirdVisit:  no3V,
    noFourthVisit: no4V,
    // Row 2 — Trainings
    noTraining,
    noFirstTraining:  no1T,
    noSecondTraining: no2T,
    noThirdTraining:  no3T,
    noFourthTraining: no4T,
    // Pipeline state (for tab counts + downstream cards)
    ready,
    inFlight,
    cycleComplete,
    assignedToPartner,
    awaitingPartnerSchedule,
  };
}

/** True if a plan belongs in the given Core Schools Gap Planning tab. */
export function planMatchesTab(p: CoreSchoolPlan, tab: CorePlanningTab): boolean {
  const rec  = nextCoreGap(p);
  const prog = progressOf(p);
  const all  = [...p.visits, ...p.trainings];

  switch (tab) {
    case "no_ssa":
      return p.ssaStatus !== "complete";
    case "visit_gaps":
      return p.ssaStatus === "complete" && p.visits.some((v) => v.status !== "completed" && v.status !== "verified");
    case "training_gaps":
      return p.ssaStatus === "complete" && p.trainings.some((t) => t.status !== "completed" && t.status !== "verified");
    case "ready_to_plan":
      return p.ssaStatus === "complete" && prog.visits === 0 && prog.trainings === 0
        && all.every((a) => a.status === "not_started" || a.status === "blocked");
    case "assigned_to_partner":
      return all.some((a) => a.owner === "partner" || a.owner === "partner_facilitator");
    case "awaiting_partner_schedule":
      return all.some(
        (a) => (a.owner === "partner" || a.owner === "partner_facilitator") && a.status === "not_started",
      );
    case "completed":
      return rec.gap === "cycle_complete";
  }
}

/** Filter the full plan list by tab. */
export function corePlansByTab(tab: CorePlanningTab): CoreSchoolPlan[] {
  return coreSchoolPlans.filter((p) => planMatchesTab(p, tab));
}

/** Activities (with parent school name) for the ownership sections. */
export type CoreActivityWithSchool = CoreActivity & {
  schoolId: string;
  schoolName: string;
  kind: "visit" | "training";
};

export function coreActivitiesAssignedTo(owner: CoreActivityOwner | "any_partner"): CoreActivityWithSchool[] {
  const out: CoreActivityWithSchool[] = [];
  for (const p of coreSchoolPlans) {
    for (const v of p.visits) {
      if (matchesOwner(v.owner, owner)) {
        out.push({ ...v, schoolId: p.id, schoolName: p.schoolName, kind: "visit" });
      }
    }
    for (const t of p.trainings) {
      if (matchesOwner(t.owner, owner)) {
        out.push({ ...t, schoolId: p.id, schoolName: p.schoolName, kind: "training" });
      }
    }
  }
  return out;
}

function matchesOwner(actual: CoreActivityOwner, query: CoreActivityOwner | "any_partner"): boolean {
  if (query === "any_partner") return actual === "partner" || actual === "partner_facilitator";
  return actual === query;
}

/** Activities scheduled within the current calendar month (mock-time-aware). */
export function corePlanningThisMonth(): CoreActivityWithSchool[] {
  const mockToday = new Date("2026-05-24"); // matches the project's frozen demo date
  const yyyy = mockToday.getFullYear();
  const mm   = mockToday.getMonth();

  const out: CoreActivityWithSchool[] = [];
  for (const p of coreSchoolPlans) {
    for (const v of p.visits)    pushIfThisMonth(v, p, "visit", out);
    for (const t of p.trainings) pushIfThisMonth(t, p, "training", out);
  }
  return out;

  function pushIfThisMonth(a: CoreActivity, plan: CoreSchoolPlan, kind: "visit" | "training", sink: CoreActivityWithSchool[]) {
    if (!a.scheduledFor) return;
    const parsed = parseScheduledFor(a.scheduledFor);
    if (parsed && parsed.getFullYear() === yyyy && parsed.getMonth() === mm) {
      sink.push({ ...a, schoolId: plan.id, schoolName: plan.schoolName, kind });
    }
  }
}

function parseScheduledFor(s: string): Date | null {
  // Mock data uses "MMM DD, YYYY" or "Wk NN · MMM DD".
  const cleaned = s.replace(/^Wk\s+\d+\s*·\s*/, "");
  const d = new Date(cleaned.includes(",") ? cleaned : `${cleaned}, 2026`);
  return isNaN(d.getTime()) ? null : d;
}

export const INTERVENTION_LABEL: Record<SsaInterventionArea, string> = {
  "Teaching & Learning":                  "Teaching & Learning",
  "Leadership":                           "Leadership",
  "Financial Health":                     "Financial Health",
  "Learning Environment":                 "Learning Environment",
  "Government Requirements & Compliance": "Compliance",
  "Education Technology":                 "Education Technology",
  "Christlike Behaviour":                 "Christlike Behaviour",
  "Exposure to the Word of God":          "Bible Integration",
};
