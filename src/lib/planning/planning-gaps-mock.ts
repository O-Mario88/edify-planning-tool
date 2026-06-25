// Planning gaps — data model + mock.
//
// Answers the question the planning page should land with:
// "Which client schools and clusters are missing required support,
// and what is the next valid action?"
//
// Core rule: No SSA → no intervention-based planning. The engine
// enforces this by returning an empty `allowedActions` list when the
// school's SSA isn't complete, with a single "Schedule SSA" CTA
// surfaced instead.

// ────────── Types ──────────

export type SsaInterventionArea =
  | "Teaching & Learning"
  | "Financial Health"
  | "Christlike Behaviour"
  | "Exposure to the Word of God"
  | "Government Requirements & Compliance"
  | "Leadership"
  | "Education Technology"
  | "Learning Environment";

export type SchoolGapCategory =
  | "no_ssa"
  | "no_visit"
  | "no_training"
  | "no_cluster";

export type SchoolGapAction =
  | "schedule_ssa"
  | "schedule_support_visit"
  | "schedule_training"
  | "schedule_follow_up"
  | "schedule_coaching"
  | "add_to_cluster"
  | "assign_partner"
  | "view_school"
  | "view_ssa";

export type SchoolGap = {
  id: string;
  schoolName: string;
  district: string;
  subCounty: string;
  parish?: string;
  clusterName?: string;
  assignedCceo: string;
  assignedPartner?: string;
  ssaCompleted: boolean;
  ssaDate?: string;
  weakestArea?: { area: SsaInterventionArea; score: number };
  secondWeakArea?: { area: SsaInterventionArea; score: number };
  lastVisitLabel?: string;
  lastTrainingLabel?: string;
  inCluster: boolean;
  riskLevel: "Critical" | "High" | "Medium" | "Low";
  gapCategory: SchoolGapCategory;
  daysSinceLastSupport?: number;
};

export type ClusterMeetingStatus =
  | "Completed"
  | "Scheduled"       // date proposed by cluster leader, not yet delivered
  | "Rescheduled"     // moved at least once from its original date
  | "Missing"         // due but no date proposed
  | "Not Yet Due";

/**
 * One entry per time a meeting's date has been moved. Append-only —
 * the audit trail of "the cluster leader had to push this back" lives
 * here, and the reschedule modal renders it so the next person who
 * touches the schedule sees the pattern.
 */
export type ClusterMeetingReschedule = {
  from:     string;   // previous scheduled date ("Jun 12, 2026")
  to:       string;   // new scheduled date
  reason:   string;   // free text or one of RESCHEDULE_REASONS below
  movedBy:  string;   // person who initiated — usually the cluster leader
  movedAt:  string;   // timestamp the move was logged
};

/** Canonical reasons offered in the reschedule modal. */
export const RESCHEDULE_REASONS = [
  "School closure / public holiday",
  "Exam week — schools unavailable",
  "Weather / road impassable",
  "Cluster leader unavailable",
  "Facilitator unavailable",
  "Low turnout expected — wait for term break",
  "Other",
] as const;

// Open-ended cluster planning categories — replaces the legacy 3-slot model
// (no_first_meeting / no_second_meeting / no_third_meeting / no_sit). A
// cluster may have any number of meetings per FY; categories now classify
// the cluster by INTELLIGENCE signal (cadence, SSA, coverage), not by an
// ordinal meeting slot. See `cluster-intelligence.ts` for the producer.
export type {
  ClusterGapCategory,
  ClusterRecommendation,
  RecommendationPriority,
} from "@/lib/cluster/cluster-intelligence";
import type {
  ClusterGapCategory as _ClusterGapCategory,
  ClusterRecommendation as _ClusterRecommendation,
} from "@/lib/cluster/cluster-intelligence";

export type ClusterGap = {
  id: string;
  clusterName: string;
  district: string;
  schoolsCount: number;
  schoolsWithSsa: number;
  assignedCceo: string;
  partnerFacilitator?: string;

  // ── Open-ended cadence (the new model) ─────────────────────────────
  /** Completed (IA-confirmed) cluster meetings this FY. Unlimited. */
  meetingsThisFy: number;
  /** Scheduled-but-not-yet-completed cluster meetings this FY. */
  meetingsScheduledThisFy: number;
  /** Completed cluster trainings (cluster_training + SIT) this FY. */
  trainingsThisFy: number;
  /** ISO date of the last completed cluster meeting, if any. */
  lastMeetingDate?: string;
  /** ISO date of the next upcoming scheduled cluster activity, if any. */
  nextScheduledMeetingDate?: string;
  /** True when the cluster met (completed a meeting) this calendar quarter. */
  metThisQuarter: boolean;
  /** Schools with no visit this period. */
  schoolsNotVisited: number;
  /** Schools with no training this period. */
  schoolsNotTrained: number;
  /** Schools with NEITHER visit NOR training — the priority signal. */
  schoolsNeitherVisitNorTraining: number;

  /** The planning category the recommendation engine assigned. */
  gapCategory: _ClusterGapCategory;
  /** Headline recommendation for this cluster (intelligence-derived). */
  recommendation?: _ClusterRecommendation;

  // ── Legacy slot fields (preserved for in-flight RESCHEDULES of meetings
  // that were scheduled under the old model). New scheduling no longer
  // uses ordinal slots — the backend persists meetings as plain
  // cluster_meeting Activity rows with no `clusterSlot`. These fields
  // remain OPTIONAL so the reschedule drawer can still operate on old
  // already-scheduled meetings without crashing. They MUST NOT drive
  // recommendation logic.
  firstMeeting?: ClusterMeetingStatus;
  secondMeeting?: ClusterMeetingStatus;
  thirdMeeting?: ClusterMeetingStatus;
  schoolImprovementTraining?: ClusterMeetingStatus;
  firstMeetingDate?:                string;
  firstMeetingProposedBy?:          string;
  firstMeetingReschedules?:         ClusterMeetingReschedule[];
  secondMeetingDate?:               string;
  secondMeetingProposedBy?:         string;
  secondMeetingReschedules?:        ClusterMeetingReschedule[];
  thirdMeetingDate?:                string;
  thirdMeetingProposedBy?:          string;
  thirdMeetingReschedules?:         ClusterMeetingReschedule[];
  sitDate?:                         string;
  sitProposedBy?:                   string;
  sitReschedules?:                  ClusterMeetingReschedule[];
};

/** Which meeting slot on a cluster — used by the reschedule modal. */
export type ClusterMeetingSlot = "first" | "second" | "third" | "sit";

export const CLUSTER_MEETING_SLOT_LABEL: Record<ClusterMeetingSlot, string> = {
  first:  "Cluster Meeting",
  second: "Cluster Meeting",
  third:  "Cluster Meeting",
  sit:    "School Improvement Training",
};

// ────────── Action engine ──────────
//
// Given a SchoolGap, derive: the recommended next action sentence,
// the list of allowed actions, and the disabled-action reason (if
// any) so the UI can render disabled buttons with tooltips.

export type RecommendedAction = {
  headline: string;
  purpose: string;
  primaryAction: SchoolGapAction;
  primaryLabel: string;
  allowedActions: SchoolGapAction[];
  disabledReason?: string;
};

export function recommendFor(g: SchoolGap): RecommendedAction {
  // Cluster-first gate (the mandatory Cluster Assignment Gate): an
  // unclustered school's only setup action is to join a cluster — even
  // before SSA. Clusters drive SIT, SSA, cluster meetings, partner
  // assignment, travel, and reporting, so full support planning stays
  // limited until the school is clustered.
  if (g.gapCategory === "no_cluster" || !g.inCluster) {
    return {
      headline: `Assign ${g.schoolName} to a cluster`,
      purpose:
        `${g.schoolName} isn't in a cluster yet. Cluster assignment is the next required setup step ` +
        `after upload — it unlocks School Improvement Training, SSA, cluster meetings, partner ` +
        `assignment, and reporting. Full support planning stays limited until the school is clustered.`,
      primaryAction: "add_to_cluster",
      primaryLabel: "Assign to Cluster",
      allowedActions: ["add_to_cluster", "view_school"],
      disabledReason: "Assign this school to a cluster to unlock SSA / SIT and full planning.",
    };
  }

  // Clustered but no current-FY SSA → the SSA-activation state. SSA can be
  // completed three ways: during School Improvement Training (SIT), by a
  // partner, or by the staff member. All other support planning stays locked
  // until the SSA is complete (and IA-confirmed).
  if (g.gapCategory === "no_ssa" || !g.ssaCompleted) {
    return {
      headline: `Activate SSA for ${g.schoolName} — via SIT, a partner, or yourself`,
      purpose:
        `${g.schoolName} is clustered but has no current-FY SSA, so support planning stays locked. ` +
        `Complete the SSA one of three ways: schedule School Improvement Training (the SSA is done during SIT), ` +
        `assign the SSA to a partner, or schedule it yourself. Planning unlocks once the SSA is confirmed.`,
      primaryAction: "schedule_training",
      primaryLabel: "Schedule SIT (completes SSA)",
      allowedActions: ["schedule_training", "assign_partner", "schedule_ssa", "view_school"],
      disabledReason: "Complete the current-FY SSA (via SIT, partner, or yourself) to unlock support planning.",
    };
  }

  const weak = g.weakestArea;

  switch (g.gapCategory) {
    case "no_visit":
      return {
        headline: `Schedule initial support visit focused on ${weak?.area ?? "the weakest SSA area"}`,
        purpose:
          weak
            ? `Support the school to improve ${weak.area} because the latest SSA score is ${weak.score}/10, below the acceptable threshold.`
            : `Conduct an initial support visit to baseline the school's support relationship.`,
        primaryAction: "schedule_support_visit",
        primaryLabel: "Schedule Support Visit",
        allowedActions: [
          "schedule_support_visit",
          "schedule_coaching",
          "assign_partner",
          "view_school",
          "view_ssa",
        ],
      };
    case "no_training":
      return {
        headline: `Schedule School Improvement Training focused on ${weak?.area ?? "the weakest SSA area"}`,
        purpose:
          weak
            ? `Conduct School Improvement Training focused on ${weak.area} because the school scored ${weak.score}/10 in ${weak.area} during the latest SSA.`
            : `Schedule School Improvement Training aligned to the school's SSA priority areas.`,
        primaryAction: "schedule_training",
        primaryLabel: "Schedule Training",
        allowedActions: [
          "schedule_training",
          "assign_partner",
          "schedule_follow_up",
          "view_school",
          "view_ssa",
        ],
      };
  }

  // no_cluster is handled by the cluster-first early return above; this is the
  // exhaustiveness fallback (clustered, SSA done, no specific gap).
  return {
    headline: `Review ${g.schoolName}`,
    purpose: "No outstanding setup gap — review the school or schedule follow-up support.",
    primaryAction: "view_school",
    primaryLabel: "View School",
    allowedActions: ["view_school", "view_ssa"],
  };
}

/**
 * Open-ended cluster recommendation. The new "primary action" surface no
 * longer encodes ordinal meeting slots (1st/2nd/3rd) — every recommended
 * activity routes through the unified `schedule_cluster_activity` action
 * with a focus intervention + suggested activity type. The board owns the
 * scheduling drawer, so this object just carries enough copy + signal for
 * the UI to render the recommendation card and route the click.
 */
export type ClusterRecommendedAction = {
  headline: string;
  purpose: string;
  /** UI action keys — `view` is the on-track fallback, `add_schools` is
   *  the empty-cluster fallback. Every other recommendation routes to
   *  `schedule_cluster_activity` and supplies activityType + focus. */
  primaryAction: "schedule_cluster_activity" | "add_schools" | "view";
  primaryLabel: string;
  /** Suggested activity type for the schedule drawer. Always present when
   *  primaryAction is `schedule_cluster_activity`. */
  suggestedActivity?: "meeting" | "training" | "support_visit" | "follow_up" | "review";
  /** SSA intervention to prefill in the drawer (where applicable). */
  focusIntervention?: SsaInterventionArea;
  /** SIT gating note — retained for back-compat with the school-improvement
   *  -training-blocked surface (used when no school has SSA yet). */
  sitDisabledReason?: string;
};

/**
 * In-session schedule overlay. Records the cluster activities the user
 * just scheduled in the current page session, so the recommendation
 * engine can effectively "advance past" them without mutating the
 * underlying ClusterGap. The legacy 3-slot keys are preserved for
 * existing reschedule chips; new opaque-id overlays (keyed by activity
 * id) live alongside.
 */
export type ClusterScheduleOverlay = Partial<
  Record<ClusterMeetingSlot, { date?: string } | undefined>
>;

export function recommendForCluster(
  c: ClusterGap,
  _overlay: ClusterScheduleOverlay = {},
): ClusterRecommendedAction {
  // The intelligence engine already classified this cluster — reuse its
  // recommendation directly so the planning board, the cluster detail
  // page, and System Health all speak with one voice. Overlays no longer
  // influence the headline (the intelligence engine reads from authoritative
  // counts), but they still tell the board that the user just took action
  // — the board uses that to show a Scheduled chip locally.
  void _overlay;

  const rec = c.recommendation;
  // No intelligence available yet — fall through to a benign view action.
  if (!rec) {
    if (c.schoolsCount === 0) {
      return {
        headline: `${c.clusterName} has no schools yet`,
        purpose: "Add schools to this cluster before planning meetings or trainings.",
        primaryAction: "add_schools",
        primaryLabel: "Add schools to cluster",
      };
    }
    return {
      headline: `${c.clusterName} — view cluster`,
      purpose: "Open the cluster intelligence page to review SSA performance, coverage, and recent activities.",
      primaryAction: "view",
      primaryLabel: "View cluster",
    };
  }

  if (rec.priority === "on_track") {
    return {
      headline: `${c.clusterName} is on track`,
      purpose: rec.reason,
      primaryAction: "view",
      primaryLabel: "View cluster",
      focusIntervention: rec.focusIntervention,
    };
  }

  // SIT-blocked surface — keep the explanatory disabled reason for the
  // shrinking case where no school in the cluster has any SSA at all.
  const sitBlocked = rec.suggestedActivity === "training" && c.schoolsWithSsa === 0 && c.schoolsCount > 0;
  return {
    headline: rec.focusIntervention
      ? `Recommended Focus: ${rec.headline}`
      : rec.headline,
    purpose: rec.reason,
    primaryAction: "schedule_cluster_activity",
    primaryLabel: rec.suggestedActivityLabel,
    suggestedActivity: rec.suggestedActivity,
    focusIntervention: rec.focusIntervention,
    sitDisabledReason: sitBlocked
      ? "Complete SSA for at least one client school first."
      : undefined,
  };
}

// ────────── Mock data ──────────

export const schoolGaps: SchoolGap[] = [
  // ─── No SSA (most-blocking, listed first) ───
  {
    id: "GAP-NSSA-1",
    schoolName: "Galiraaya Primary School", district: "Kayunga", subCounty: "Galiraaya", parish: "Galiraaya",
    clusterName: "Bbaale Cluster",
    assignedCceo: "Sarah Nanyongo",
    ssaCompleted: false,
    lastVisitLabel: "Mar 10, 2026",
    lastTrainingLabel: "Never",
    inCluster: true,
    riskLevel: "Critical",
    gapCategory: "no_ssa",
    daysSinceLastSupport: 65,
  },
  {
    id: "GAP-NSSA-2",
    schoolName: "Kayunga Hill School", district: "Kayunga", subCounty: "Bbaale", parish: "Bbaale",
    clusterName: "Bbaale Cluster",
    assignedCceo: "Sarah Nanyongo",
    ssaCompleted: false,
    lastVisitLabel: "Never",
    lastTrainingLabel: "Never",
    inCluster: true,
    riskLevel: "High",
    gapCategory: "no_ssa",
  },
  {
    id: "GAP-NSSA-3",
    schoolName: "Nakawuka Primary", district: "Kayunga", subCounty: "Galiraaya",
    clusterName: "Galiraaya Cluster",
    assignedCceo: "Sarah Nanyongo",
    ssaCompleted: false,
    lastVisitLabel: "Never",
    lastTrainingLabel: "Never",
    inCluster: true,
    riskLevel: "High",
    gapCategory: "no_ssa",
  },

  // ─── No Training (SSA complete, training missing) ───
  {
    id: "GAP-NTR-1",
    schoolName: "Hope Primary School", district: "Mukono", subCounty: "Ntenjeru", parish: "Ntenjeru",
    clusterName: "Ntenjeru Cluster",
    assignedCceo: "Sarah Nanyongo",
    assignedPartner: "Bright Future Education Partners",
    ssaCompleted: true,
    ssaDate: "2026-03-12",
    weakestArea: { area: "Teaching & Learning", score: 4 },
    secondWeakArea: { area: "Leadership", score: 5 },
    lastVisitLabel: "May 13, 2026",
    lastTrainingLabel: "Never",
    inCluster: true,
    riskLevel: "High",
    gapCategory: "no_training",
  },
  {
    id: "GAP-NTR-2",
    schoolName: "Sunrise Junior School", district: "Mukono", subCounty: "Mukono Central",
    clusterName: "Mukono Central Cluster",
    assignedCceo: "Sarah Nanyongo",
    ssaCompleted: true,
    ssaDate: "2026-01-08",
    weakestArea: { area: "Teaching & Learning", score: 5 },
    lastVisitLabel: "Apr 26, 2026",
    lastTrainingLabel: "Never",
    inCluster: true,
    riskLevel: "Medium",
    gapCategory: "no_training",
  },
  {
    id: "GAP-NTR-3",
    schoolName: "Pope John PS", district: "Mukono", subCounty: "Nakifuma",
    clusterName: "Nakifuma Cluster",
    assignedCceo: "Sarah Nanyongo",
    assignedPartner: "Bright Future Education Partners",
    ssaCompleted: true,
    ssaDate: "2026-02-04",
    weakestArea: { area: "Leadership", score: 5 },
    lastVisitLabel: "Apr 10, 2026",
    lastTrainingLabel: "Never",
    inCluster: true,
    riskLevel: "Medium",
    gapCategory: "no_training",
  },
  {
    id: "GAP-NTR-4",
    schoolName: "Bbaale Primary", district: "Kayunga", subCounty: "Bbaale",
    clusterName: "Bbaale Cluster",
    assignedCceo: "Sarah Nanyongo",
    ssaCompleted: true,
    ssaDate: "2026-02-10",
    weakestArea: { area: "Learning Environment", score: 5 },
    lastVisitLabel: "Apr 09, 2026",
    lastTrainingLabel: "Never",
    inCluster: true,
    riskLevel: "Medium",
    gapCategory: "no_training",
  },

  // ─── No Visit (SSA complete, no support visit yet) ───
  {
    id: "GAP-NV-1",
    schoolName: "Victory Primary School", district: "Kayunga", subCounty: "Kayunga Central",
    clusterName: "Kayunga Cluster",
    assignedCceo: "Sarah Nanyongo",
    ssaCompleted: true,
    ssaDate: "2026-02-22",
    weakestArea: { area: "Leadership", score: 5 },
    lastVisitLabel: "Never",
    lastTrainingLabel: "Never",
    inCluster: true,
    riskLevel: "High",
    gapCategory: "no_visit",
  },
  {
    id: "GAP-NV-2",
    schoolName: "Hilltop Basic School", district: "Mukono", subCounty: "Kireka",
    clusterName: "Kireka Cluster",
    assignedCceo: "Sarah Nanyongo",
    ssaCompleted: true,
    ssaDate: "2026-01-22",
    weakestArea: { area: "Teaching & Learning", score: 4 },
    lastVisitLabel: "Never",
    lastTrainingLabel: "Apr 12, 2026",
    inCluster: true,
    riskLevel: "Critical",
    gapCategory: "no_visit",
  },
  {
    id: "GAP-NV-3",
    schoolName: "Nsumba Primary", district: "Mukono", subCounty: "Nsumba",
    clusterName: "Nsumba Cluster",
    assignedCceo: "Sarah Nanyongo",
    ssaCompleted: true,
    ssaDate: "2026-02-12",
    weakestArea: { area: "Numeracy" as SsaInterventionArea, score: 4 },
    lastVisitLabel: "Never",
    lastTrainingLabel: "Never",
    inCluster: true,
    riskLevel: "High",
    gapCategory: "no_visit",
  },

  // ─── No Cluster (school assigned but not in a cluster) ───
  {
    id: "GAP-NC-1",
    schoolName: "Bukoto Community School", district: "Mukono", subCounty: "Bukoto",
    assignedCceo: "Sarah Nanyongo",
    ssaCompleted: true,
    ssaDate: "2026-03-01",
    weakestArea: { area: "Christlike Behaviour", score: 6 },
    lastVisitLabel: "Apr 04, 2026",
    lastTrainingLabel: "Mar 18, 2026",
    inCluster: false,
    riskLevel: "Low",
    gapCategory: "no_cluster",
  },
  {
    id: "GAP-NC-2",
    schoolName: "Wakiso Foundation", district: "Mukono", subCounty: "Wakiso",
    assignedCceo: "Sarah Nanyongo",
    ssaCompleted: true,
    ssaDate: "2026-02-28",
    weakestArea: { area: "Education Technology", score: 5 },
    lastVisitLabel: "Apr 14, 2026",
    lastTrainingLabel: "Never",
    inCluster: false,
    riskLevel: "Medium",
    gapCategory: "no_cluster",
  },
];

// Mock cluster gaps — representative of the OPEN-ENDED intelligence model.
// Each row carries the new cadence + coverage signals + intelligence-derived
// `recommendation`. The legacy slot fields stay populated when the cluster
// has already-scheduled meetings (so the reschedule drawer can still
// operate on them) but they no longer drive bucket assignment.
export const clusterGaps: ClusterGap[] = [
  // No meetings this FY — newly-onboarded cluster, no cadence yet.
  {
    id: "CG-1",
    clusterName: "Galiraaya Cluster", district: "Kayunga",
    schoolsCount: 7, schoolsWithSsa: 4,
    assignedCceo: "Sarah Nanyongo",
    meetingsThisFy: 0, meetingsScheduledThisFy: 0, trainingsThisFy: 0,
    metThisQuarter: false,
    schoolsNotVisited: 5, schoolsNotTrained: 7, schoolsNeitherVisitNorTraining: 4,
    gapCategory: "no_meetings_this_fy",
    recommendation: {
      priority: "no_meetings_this_fy",
      suggestedActivity: "meeting",
      suggestedActivityLabel: "Schedule Cluster Meeting",
      headline: "Cluster has not met this fiscal year",
      reason: "Schedule a cluster meeting to establish the planning rhythm for this FY.",
      schoolsAffected: 7,
    },
  },
  // SSA performance drop — Teaching & Learning declined across multiple
  // schools; recommendation surfaces it as the focus intervention.
  {
    id: "CG-2",
    clusterName: "Ntenjeru Cluster", district: "Mukono",
    schoolsCount: 6, schoolsWithSsa: 6,
    assignedCceo: "Sarah Nanyongo",
    partnerFacilitator: "Bright Future Education Partners",
    meetingsThisFy: 2, meetingsScheduledThisFy: 0, trainingsThisFy: 1,
    lastMeetingDate: "2026-04-24",
    metThisQuarter: true,
    schoolsNotVisited: 1, schoolsNotTrained: 0, schoolsNeitherVisitNorTraining: 0,
    gapCategory: "ssa_performance_drop",
    recommendation: {
      priority: "ssa_drop",
      focusIntervention: "Teaching & Learning",
      suggestedActivity: "training",
      suggestedActivityLabel: "Schedule Cluster Training",
      headline: "Teaching & Learning",
      reason: "Average score dropped from 6.2 to 4.8 (1.4 point drop) across 4 schools.",
      schoolsAffected: 4,
    },
    firstMeetingDate: "Apr 24, 2026", firstMeetingProposedBy: "Esther Naluwu (Ntenjeru CL)",
    firstMeeting: "Completed", schoolImprovementTraining: "Completed",
  },
  // Not met this quarter — last meeting ~70 days ago, cadence slipping.
  {
    id: "CG-3",
    clusterName: "Kayunga Cluster", district: "Kayunga",
    schoolsCount: 5, schoolsWithSsa: 4,
    assignedCceo: "Sarah Nanyongo",
    partnerFacilitator: "Bright Future Education Partners",
    meetingsThisFy: 1, meetingsScheduledThisFy: 0, trainingsThisFy: 0,
    lastMeetingDate: "2026-04-18",
    metThisQuarter: false,
    schoolsNotVisited: 2, schoolsNotTrained: 4, schoolsNeitherVisitNorTraining: 1,
    gapCategory: "not_met_this_quarter",
    recommendation: {
      priority: "no_meeting_this_quarter",
      suggestedActivity: "meeting",
      suggestedActivityLabel: "Schedule Cluster Meeting",
      headline: "Cluster has not met this quarter",
      reason: "Last cluster meeting was 67 days ago. Schedule a cluster meeting to maintain cadence.",
      schoolsAffected: 5,
      focusIntervention: "Leadership",
    },
    firstMeeting: "Completed", firstMeetingDate: "Apr 18, 2026", firstMeetingProposedBy: "John Mubiru (Kayunga CL)",
  },
  // Weak SSA intervention — Financial Health critical across the cluster.
  {
    id: "CG-4",
    clusterName: "Mukono Central Cluster", district: "Mukono",
    schoolsCount: 5, schoolsWithSsa: 5,
    assignedCceo: "Sarah Nanyongo",
    meetingsThisFy: 2, meetingsScheduledThisFy: 1, trainingsThisFy: 1,
    lastMeetingDate: "2026-05-14",
    nextScheduledMeetingDate: "2026-07-08",
    metThisQuarter: true,
    schoolsNotVisited: 0, schoolsNotTrained: 0, schoolsNeitherVisitNorTraining: 0,
    gapCategory: "weak_ssa_intervention",
    recommendation: {
      priority: "weak_intervention",
      focusIntervention: "Financial Health",
      suggestedActivity: "training",
      suggestedActivityLabel: "Schedule Cluster Training",
      headline: "Financial Health",
      reason: "Cluster average is 4.6/10 (Critical) across 5 schools with SSA.",
      schoolsAffected: 5,
    },
    firstMeeting: "Completed", firstMeetingDate: "Apr 10, 2026",
    secondMeeting: "Completed", secondMeetingDate: "May 14, 2026",
  },
  // Schools not trained — 4 of 6 schools without any training this FY.
  {
    id: "CG-5",
    clusterName: "Bbaale Cluster", district: "Kayunga",
    schoolsCount: 6, schoolsWithSsa: 3,
    assignedCceo: "Sarah Nanyongo",
    meetingsThisFy: 2, meetingsScheduledThisFy: 0, trainingsThisFy: 0,
    lastMeetingDate: "2026-05-27",
    metThisQuarter: true,
    schoolsNotVisited: 1, schoolsNotTrained: 4, schoolsNeitherVisitNorTraining: 1,
    gapCategory: "schools_not_trained",
    recommendation: {
      priority: "schools_not_trained",
      suggestedActivity: "training",
      suggestedActivityLabel: "Schedule Cluster Training",
      headline: "4 schools have not been trained",
      reason: "Schedule cluster training to reach 4 schools that haven't participated in any training this period.",
      schoolsAffected: 4,
      focusIntervention: "Leadership",
    },
    firstMeeting: "Completed", firstMeetingDate: "Apr 22, 2026",
    secondMeeting: "Completed", secondMeetingDate: "May 27, 2026",
  },
  // Schools with neither visit nor training — the URGENT category.
  {
    id: "CG-6",
    clusterName: "Kireka Cluster", district: "Mukono",
    schoolsCount: 4, schoolsWithSsa: 4,
    assignedCceo: "Sarah Nanyongo",
    partnerFacilitator: "Bright Future Education Partners",
    meetingsThisFy: 1, meetingsScheduledThisFy: 1, trainingsThisFy: 0,
    lastMeetingDate: "2026-04-15",
    nextScheduledMeetingDate: "2026-07-15",
    metThisQuarter: false,
    schoolsNotVisited: 3, schoolsNotTrained: 4, schoolsNeitherVisitNorTraining: 3,
    gapCategory: "schools_neither_visit_nor_training",
    recommendation: {
      priority: "schools_neither",
      suggestedActivity: "support_visit",
      suggestedActivityLabel: "Schedule Urgent Cluster Support",
      headline: "Urgent: 3 schools without visit or training",
      reason: "3 of 4 schools in this cluster have received neither a visit nor a training this period. Prioritise targeted cluster support.",
      schoolsAffected: 3,
    },
    firstMeeting: "Completed", firstMeetingDate: "Apr 15, 2026",
  },
];

// ────────── Aggregates ──────────

export function planningSummary() {
  const clusterOpen = clusterGaps.filter((c) => c.gapCategory !== "on_track");
  return {
    noSsa:                     schoolGaps.filter((s) => s.gapCategory === "no_ssa").length,
    noVisit:                   schoolGaps.filter((s) => s.gapCategory === "no_visit").length,
    noTraining:                schoolGaps.filter((s) => s.gapCategory === "no_training").length,
    noCluster:                 schoolGaps.filter((s) => s.gapCategory === "no_cluster").length,
    /** Open cluster planning items — count of clusters with any recommendation
     *  signal (no-meetings, missed-quarter, weak/declining SSA, coverage gap). */
    clusterMeetingsMissing:    clusterOpen.length,
    /** Clusters with training-related recommendations (weak intervention,
     *  SSA drop, schools-not-trained, training-needed). */
    clusterTrainingNeeded:     clusterGaps.filter(
      (c) =>
        c.gapCategory === "weak_ssa_intervention" ||
        c.gapCategory === "ssa_performance_drop" ||
        c.gapCategory === "schools_not_trained" ||
        c.gapCategory === "training_needed",
    ).length,
    /** Back-compat alias for callers still reading the legacy "SIT missing"
     *  signal — now means "training is the recommended next activity". */
    clusterSitMissing:         clusterGaps.filter(
      (c) =>
        c.gapCategory === "weak_ssa_intervention" ||
        c.gapCategory === "ssa_performance_drop" ||
        c.gapCategory === "schools_not_trained" ||
        c.gapCategory === "training_needed",
    ).length,
  };
}

// Cluster-first: an unclustered school is the most "not-ready" — clustering
// is the required setup step after upload, so it leads the gap order.
export const GAP_SORT_ORDER: SchoolGapCategory[] = [
  "no_cluster",
  "no_ssa",
  "no_training",
  "no_visit",
];
