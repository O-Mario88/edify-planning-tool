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

export type ClusterGapCategory =
  | "no_first_meeting"
  | "no_second_meeting"
  | "no_third_meeting"
  | "no_sit";

export type ClusterGap = {
  id: string;
  clusterName: string;
  district: string;
  schoolsCount: number;
  schoolsWithSsa: number;
  assignedCceo: string;
  partnerFacilitator?: string;
  firstMeeting: ClusterMeetingStatus;
  secondMeeting: ClusterMeetingStatus;
  thirdMeeting: ClusterMeetingStatus;
  schoolImprovementTraining: ClusterMeetingStatus;
  gapCategory: ClusterGapCategory;
  // ─ Scheduled-date provision ─
  // Each meeting slot carries an optional date (current scheduled
  // date) + the cluster leader who proposed it + the reschedule
  // history. When the date is interfered with — exam week, weather,
  // leader unavailable — the planning UI opens a reschedule modal
  // that captures the new date + reason + appends a history entry.
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
  first:  "1st Cluster Meeting",
  second: "2nd Cluster Meeting",
  third:  "3rd Cluster Meeting",
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

export type ClusterRecommendedAction = {
  headline: string;
  purpose: string;
  primaryAction: "schedule_first" | "schedule_second" | "schedule_third" | "schedule_sit" | "add_schools" | "view";
  primaryLabel: string;
  /// School Improvement Training is gated on SSA completion within
  /// the cluster. UI uses this to disable + explain.
  sitDisabledReason?: string;
};

/**
 * Optional per-slot overlay that the caller can pass to reflect work
 * the user just did in-session — without having to mutate the
 * underlying ClusterGap. Any slot present in the overlay is treated
 * as effectively "Scheduled" for the purpose of picking the primary
 * CTA. This is what flips the cluster's primary action from
 * "Schedule First Meeting" to the next gap (or to the on-track view
 * recommendation) as soon as the user lands a date on the calendar.
 */
export type ClusterScheduleOverlay = Partial<
  Record<ClusterMeetingSlot, { date?: string } | undefined>
>;

export function recommendForCluster(
  c: ClusterGap,
  overlay: ClusterScheduleOverlay = {},
): ClusterRecommendedAction {
  // Effective per-slot status. Slots present in the overlay are
  // treated as Scheduled so the recommendation engine advances past
  // them — the chip already shows the chosen date, the underlying
  // ClusterGap stays untouched.
  const eff = (slot: ClusterMeetingSlot, base: ClusterMeetingStatus): ClusterMeetingStatus =>
    overlay[slot] ? "Scheduled" : base;

  const effSit    = eff("sit",    c.schoolImprovementTraining);
  const effFirst  = eff("first",  c.firstMeeting);
  const effSecond = eff("second", c.secondMeeting);
  const effThird  = eff("third",  c.thirdMeeting);

  // SIT is the FIRST activity in the cluster training cycle. If it's
  // missing, recommend it before any of the 3 meetings — gated only by
  // SSA coverage (the only thing that can actually block training).
  if (effSit === "Missing") {
    const noSsaCount = c.schoolsCount - c.schoolsWithSsa;
    if (noSsaCount === c.schoolsCount) {
      return {
        headline: `School Improvement Training blocked for ${c.clusterName}`,
        purpose:
          "None of the schools in this cluster have completed SSA. Complete SSA for at least one client school before scheduling intervention-based training.",
        primaryAction: "schedule_sit",
        primaryLabel: "School Improvement Training",
        sitDisabledReason: "Complete SSA for at least one client school first.",
      };
    }
    if (noSsaCount > 0) {
      return {
        headline: `Schedule School Improvement Training for ${c.clusterName}`,
        purpose:
          `${noSsaCount} of ${c.schoolsCount} schools in this cluster have no SSA. ` +
          `Training can be planned for the ${c.schoolsWithSsa} schools with completed SSA, ` +
          `or you can schedule the missing SSAs first.`,
        primaryAction: "schedule_sit",
        primaryLabel: "Schedule SIT (SSA-completed only)",
      };
    }
    return {
      headline: `Schedule School Improvement Training for ${c.clusterName}`,
      purpose:
        "All schools have current SSAs — schedule the SIT and pull the topic from the weakest cluster intervention area.",
      primaryAction: "schedule_sit",
      primaryLabel: "Schedule SIT",
    };
  }

  // Once SIT is done (or scheduled this session), fall through to the
  // 3 meetings in order. Overlay-aware: a meeting freshly scheduled
  // in-session reads as Scheduled, advancing the rec to the next gap.
  if (effFirst === "Missing") {
    return {
      headline: `Schedule first cluster meeting for ${c.clusterName}`,
      purpose:
        "Introduce cluster structure, confirm participating schools, and agree on school improvement priorities.",
      primaryAction: "schedule_first",
      primaryLabel: "Schedule First Meeting",
    };
  }
  if (effSecond === "Missing") {
    return {
      headline: `Schedule second cluster meeting for ${c.clusterName}`,
      purpose:
        "Review school progress, follow up on action points, and address common school improvement gaps.",
      primaryAction: "schedule_second",
      primaryLabel: "Schedule Second Meeting",
    };
  }
  if (effThird === "Missing") {
    return {
      headline: `Schedule third cluster meeting for ${c.clusterName}`,
      purpose:
        "Review implementation progress, share learning, and prepare next support actions.",
      primaryAction: "schedule_third",
      primaryLabel: "Schedule Third Meeting",
    };
  }

  // Nothing missing — fall through to a benign "view" recommendation
  // so callers always get a well-formed action object. When the last
  // gap was just closed in this session (any overlay slot present),
  // the wording switches to "Scheduled — view detail" so the planner
  // gets immediate feedback that the action landed.
  const justScheduled = !!(overlay.sit || overlay.first || overlay.second || overlay.third);
  if (justScheduled) {
    return {
      headline: `${c.clusterName} — scheduled. View detail.`,
      purpose:
        "Recent in-session schedule landed on the calendar. Open the cluster to confirm participants, venue, and projected cost.",
      primaryAction: "view",
      primaryLabel: "Scheduled — view detail",
    };
  }
  return {
    headline: `Cluster ${c.clusterName} is on track`,
    purpose: "SIT and all three cluster meetings are accounted for.",
    primaryAction: "view",
    primaryLabel: "View cluster",
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

export const clusterGaps: ClusterGap[] = [
  // No first meeting
  {
    id: "CG-1",
    clusterName: "Galiraaya Cluster", district: "Kayunga",
    schoolsCount: 7, schoolsWithSsa: 4,
    assignedCceo: "Sarah Nanyongo",
    firstMeeting: "Missing",
    secondMeeting: "Not Yet Due",
    thirdMeeting: "Not Yet Due",
    schoolImprovementTraining: "Missing",
    gapCategory: "no_first_meeting",
  },
  // No second meeting — 1st meeting completed, 2nd needs scheduling
  // by the cluster leader. SIT scheduled but already rescheduled
  // once after the cluster leader flagged exam week conflict.
  {
    id: "CG-2",
    clusterName: "Ntenjeru Cluster", district: "Mukono",
    schoolsCount: 6, schoolsWithSsa: 6,
    assignedCceo: "Sarah Nanyongo",
    partnerFacilitator: "Bright Future Education Partners",
    firstMeeting: "Completed",
    secondMeeting: "Missing",
    thirdMeeting: "Not Yet Due",
    schoolImprovementTraining: "Completed",
    gapCategory: "no_second_meeting",
    firstMeetingDate: "Apr 24, 2026", firstMeetingProposedBy: "Esther Naluwu (Ntenjeru CL)",
  },
  // Cluster with a scheduled 2nd meeting that's been rescheduled twice.
  // Shows the audit-trail story end-to-end in the demo.
  {
    id: "CG-3",
    clusterName: "Kayunga Cluster", district: "Kayunga",
    schoolsCount: 5, schoolsWithSsa: 4,
    assignedCceo: "Sarah Nanyongo",
    partnerFacilitator: "Bright Future Education Partners",
    firstMeeting: "Completed",
    secondMeeting: "Rescheduled",
    thirdMeeting: "Not Yet Due",
    schoolImprovementTraining: "Missing",
    gapCategory: "no_second_meeting",
    firstMeetingDate:    "Apr 18, 2026", firstMeetingProposedBy:  "John Mubiru (Kayunga CL)",
    secondMeetingDate:   "Jun 20, 2026", secondMeetingProposedBy: "John Mubiru (Kayunga CL)",
    secondMeetingReschedules: [
      { from: "May 22, 2026", to: "Jun 5, 2026",  reason: "Exam week — schools unavailable",       movedBy: "John Mubiru (Kayunga CL)", movedAt: "May 12, 2026 09:14" },
      { from: "Jun 5, 2026",  to: "Jun 20, 2026", reason: "Cluster leader unavailable (funeral)",  movedBy: "Sarah Nanyongo (CCEO)",    movedAt: "Jun 1, 2026 14:22" },
    ],
  },
  // No third meeting — 1st + 2nd done, 3rd has a confirmed scheduled
  // date from the cluster leader.
  {
    id: "CG-4",
    clusterName: "Mukono Central Cluster", district: "Mukono",
    schoolsCount: 5, schoolsWithSsa: 5,
    assignedCceo: "Sarah Nanyongo",
    firstMeeting: "Completed",
    secondMeeting: "Completed",
    thirdMeeting: "Scheduled",
    schoolImprovementTraining: "Completed",
    gapCategory: "no_third_meeting",
    firstMeetingDate:  "Apr 10, 2026", firstMeetingProposedBy:  "Peter Wamala (Mukono CL)",
    secondMeetingDate: "May 14, 2026", secondMeetingProposedBy: "Peter Wamala (Mukono CL)",
    thirdMeetingDate:  "Jul 8, 2026",  thirdMeetingProposedBy:  "Peter Wamala (Mukono CL)",
  },
  // No SIT — meetings 1 + 2 done, 3rd not yet due, SIT outstanding.
  {
    id: "CG-5",
    clusterName: "Bbaale Cluster", district: "Kayunga",
    schoolsCount: 6, schoolsWithSsa: 3,
    assignedCceo: "Sarah Nanyongo",
    firstMeeting: "Completed",
    secondMeeting: "Completed",
    thirdMeeting: "Not Yet Due",
    schoolImprovementTraining: "Missing",
    gapCategory: "no_sit",
    firstMeetingDate:  "Apr 22, 2026", firstMeetingProposedBy:  "Grace Atim (Bbaale CL)",
    secondMeetingDate: "May 27, 2026", secondMeetingProposedBy: "Grace Atim (Bbaale CL)",
  },
  // SIT scheduled and once-rescheduled — shows the SIT slot also
  // supports the rescheduling provision.
  {
    id: "CG-6",
    clusterName: "Kireka Cluster", district: "Mukono",
    schoolsCount: 4, schoolsWithSsa: 4,
    assignedCceo: "Sarah Nanyongo",
    partnerFacilitator: "Bright Future Education Partners",
    firstMeeting: "Completed",
    secondMeeting: "Completed",
    thirdMeeting: "Not Yet Due",
    schoolImprovementTraining: "Rescheduled",
    gapCategory: "no_sit",
    firstMeetingDate:  "Apr 15, 2026", firstMeetingProposedBy: "Daniel Mwangi (Kireka CL)",
    secondMeetingDate: "May 20, 2026", secondMeetingProposedBy: "Daniel Mwangi (Kireka CL)",
    sitDate:           "Jul 15, 2026", sitProposedBy:           "Daniel Mwangi (Kireka CL)",
    sitReschedules: [
      { from: "Jun 24, 2026", to: "Jul 15, 2026", reason: "Weather / road impassable", movedBy: "Daniel Mwangi (Kireka CL)", movedAt: "Jun 18, 2026 16:40" },
    ],
  },
];

// ────────── Aggregates ──────────

export function planningSummary() {
  return {
    noSsa:                     schoolGaps.filter((s) => s.gapCategory === "no_ssa").length,
    noVisit:                   schoolGaps.filter((s) => s.gapCategory === "no_visit").length,
    noTraining:                schoolGaps.filter((s) => s.gapCategory === "no_training").length,
    noCluster:                 schoolGaps.filter((s) => s.gapCategory === "no_cluster").length,
    clusterMeetingsMissing:    clusterGaps.filter((c) => c.gapCategory !== "no_sit").length,
    clusterSitMissing:         clusterGaps.filter((c) => c.gapCategory === "no_sit" || c.schoolImprovementTraining === "Missing").length,
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
