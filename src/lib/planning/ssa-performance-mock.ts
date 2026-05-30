// SSA performance mock — multi-year history per school, indexed by
// SchoolGap.id. Drives the SsaPerformanceDrawer. Pure client-safe
// module (no server-only imports) so the drawer can render without
// crossing the server/client boundary.
//
// Model intentionally mirrors the spec's SsaPerformanceRecord shape so
// the Salesforce migration only has to swap `historyFor()`.

import {
  type SchoolGap,
  type SsaInterventionArea,
} from "@/lib/planning/planning-gaps-mock";

// ────────── Canonical intervention list ──────────

/** Display order for the drawer's bar charts — weakest-first so the
 *  most urgent area sits at the top of the horizontal bar chart. The
 *  list rearranges per record because actual weakness changes school
 *  by school; this is only the default authoring order. */
export const SSA_INTERVENTIONS: readonly SsaInterventionArea[] = [
  "Teaching & Learning",
  "Leadership",
  "Learning Environment",
  "Financial Health",
  "Government Requirements & Compliance",
  "Education Technology",
  "Christlike Behaviour",
  "Exposure to the Word of God",
] as const;

// ────────── Data model ──────────

export type SsaStatus = "Critical" | "Needs Support" | "Good" | "Strong";

export type SsaScore = {
  intervention: SsaInterventionArea;
  score:        number; // 0-10
};

export type SsaCompletedByRole = "CCEO" | "PL" | "IA" | "Partner" | "Admin";

export type SsaPerformanceRecord = {
  id:               string;
  schoolId:         string;
  schoolName:       string;
  operationalCycle: string; // "FY2025" / "FY2026" / "FY2027"
  ssaDate:          string; // ISO
  completedBy:      string;
  completedByRole:  SsaCompletedByRole;
  scores:           SsaScore[];
  averageScore:     number;
  status:           SsaStatus;
};

// ────────── Status + trend classifiers ──────────

export function statusFor(score: number): SsaStatus {
  if (score <= 4) return "Critical";
  if (score <= 6) return "Needs Support";
  if (score <= 8) return "Good";
  return "Strong";
}

export type SsaTrend =
  | "strong_improvement"
  | "small_improvement"
  | "no_change"
  | "decline"
  | "serious_decline";

export function trendFor(change: number): SsaTrend {
  if (change >= 2)  return "strong_improvement";
  if (change === 1) return "small_improvement";
  if (change === 0) return "no_change";
  if (change === -1) return "decline";
  return "serious_decline";
}

export const TREND_LABEL: Record<SsaTrend, string> = {
  strong_improvement: "Strong improvement",
  small_improvement:  "Small improvement",
  no_change:          "No change",
  decline:            "Decline",
  serious_decline:    "Serious decline",
};

// ────────── Comparison + snapshot helpers ──────────

export type SsaComparisonRow = {
  intervention:    SsaInterventionArea;
  currentScore:    number;
  previousScore?:  number;
  threeYearScores?: { year: string; score: number }[];
  change?:         number;
  trend:           SsaTrend;
};

/**
 * Build a per-intervention comparison row vs the previous record. If
 * `previous` is undefined, the row carries only currentScore and trend
 * defaults to `no_change` (single-record case — the drawer still uses
 * it for ranking and color coding).
 */
export function compareSsa(
  current: SsaPerformanceRecord,
  previous?: SsaPerformanceRecord,
): SsaComparisonRow[] {
  const prevByArea = new Map<SsaInterventionArea, number>();
  if (previous) {
    for (const s of previous.scores) prevByArea.set(s.intervention, s.score);
  }
  return current.scores.map((s) => {
    const prev = prevByArea.get(s.intervention);
    const change = prev !== undefined ? s.score - prev : undefined;
    return {
      intervention:  s.intervention,
      currentScore:  s.score,
      previousScore: prev,
      change,
      trend:         change !== undefined ? trendFor(change) : "no_change",
    };
  });
}

/**
 * Build a 3-year comparison row when 3+ records exist. Records must be
 * passed newest-first (history[0] = current FY).
 */
export function compareSsaThreeYear(records: SsaPerformanceRecord[]): SsaComparisonRow[] {
  if (records.length < 3) return [];
  const [curr, prev, prev2] = records;
  const prevByArea  = new Map<SsaInterventionArea, number>();
  const prev2ByArea = new Map<SsaInterventionArea, number>();
  for (const s of prev.scores)  prevByArea.set(s.intervention, s.score);
  for (const s of prev2.scores) prev2ByArea.set(s.intervention, s.score);
  return curr.scores.map((s) => {
    const prevScore  = prevByArea.get(s.intervention);
    const prev2Score = prev2ByArea.get(s.intervention);
    const change     = prevScore !== undefined ? s.score - prevScore : undefined;
    return {
      intervention:    s.intervention,
      currentScore:    s.score,
      previousScore:   prevScore,
      threeYearScores: [
        prev2Score !== undefined ? { year: prev2.operationalCycle, score: prev2Score } : null,
        prevScore  !== undefined ? { year: prev.operationalCycle,  score: prevScore  } : null,
        { year: curr.operationalCycle, score: s.score },
      ].filter(Boolean) as { year: string; score: number }[],
      change,
      trend: change !== undefined ? trendFor(change) : "no_change",
    };
  });
}

export type SsaSnapshot = {
  averageScore:       number;
  status:             SsaStatus;
  weakest:            SsaScore;
  best:               SsaScore;
  /** Bottom-N interventions, sorted ascending. */
  priorityAreas:      SsaScore[];
  /** Top-N interventions, sorted descending. */
  strengthAreas:      SsaScore[];
};

export function snapshotFor(record: SsaPerformanceRecord, topN: number = 4): SsaSnapshot {
  const sorted = [...record.scores].sort((a, b) => a.score - b.score);
  return {
    averageScore:  record.averageScore,
    status:        record.status,
    weakest:       sorted[0],
    best:          sorted[sorted.length - 1],
    priorityAreas: sorted.slice(0, topN),
    strengthAreas: [...sorted].reverse().slice(0, topN),
  };
}

// ────────── Recommendation engine ──────────

export type SsaRecommendation = {
  title:   string;
  reason:  string;
  /** Maps to a SchoolGapAction so the drawer's CTA buttons can plug
   *  back into the existing planning flow. */
  action?: "schedule_ssa" | "schedule_support_visit" | "schedule_training" | "schedule_coaching";
};

/**
 * Build the drawer's "Recommended planning actions" list from the
 * SSA history. When no current SSA exists, returns the SSA-first
 * lockout copy. Otherwise surfaces visit + training picks tied to the
 * weakest area, and a "watch declining area" note when comparison
 * data shows decline.
 */
export function recommendActions(
  school: { ssaCompleted: boolean },
  history: SsaPerformanceRecord[],
): SsaRecommendation[] {
  if (history.length === 0 || !school.ssaCompleted) {
    return [
      {
        title:  "Planning remains locked until current-cycle SSA is completed.",
        reason: "All intervention-based planning depends on SSA recommendations. Schedule the current-cycle SSA to unlock visits and trainings.",
        action: "schedule_ssa",
      },
    ];
  }
  const current   = history[0];
  const previous  = history[1];
  const snap      = snapshotFor(current);
  const recs: SsaRecommendation[] = [
    {
      title:  `Schedule support visit focused on ${snap.weakest.intervention}.`,
      reason: `It is the lowest-scoring intervention at ${snap.weakest.score}/10.`,
      action: "schedule_support_visit",
    },
  ];
  // Second priority — a training on the second-weakest area.
  if (snap.priorityAreas.length > 1) {
    const second = snap.priorityAreas[1];
    recs.push({
      title:  `Schedule School Improvement Training on ${second.intervention}.`,
      reason: `${second.intervention} scored ${second.score}/10 — adjacent to the weakest area, ideal for cluster-shared training.`,
      action: "schedule_training",
    });
  }
  // If we have last-year comparison and any decline ≥1, surface it.
  if (previous) {
    const rows = compareSsa(current, previous);
    const biggestDecline = rows
      .filter((r) => (r.change ?? 0) < 0)
      .sort((a, b) => (a.change ?? 0) - (b.change ?? 0))[0];
    if (biggestDecline) {
      recs.push({
        title:  `Watch ${biggestDecline.intervention} — declining trend.`,
        reason: `Score dropped from ${biggestDecline.previousScore}/10 last cycle to ${biggestDecline.currentScore}/10 this cycle. Add a coaching follow-up before the next SSA.`,
        action: "schedule_coaching",
      });
    }
  }
  return recs;
}

// ────────── Convenience accessors ──────────

/** Records sorted newest-first. */
export function historyFor(schoolId: string): SsaPerformanceRecord[] {
  return (SSA_HISTORY_BY_SCHOOL[schoolId] ?? []).slice().sort(
    (a, b) => b.ssaDate.localeCompare(a.ssaDate),
  );
}

/** Most recent completed SSA (newest), undefined when none. */
export function latestSsaFor(schoolId: string): SsaPerformanceRecord | undefined {
  return historyFor(schoolId)[0];
}

// ────────── Mock data ──────────
//
// Hand-tuned per school to cover every drawer state:
//   • 0 SSAs        — GAP-NSSA-1, GAP-NSSA-2 (locked schools)
//   • 1 SSA only    — GAP-NTR-1
//   • 2 SSAs        — GAP-NTR-2, GAP-NTR-3
//   • 3+ SSAs       — GAP-NTR-4, GAP-NV-1, GAP-NV-2, GAP-NV-3
//   • historical-only (no current FY) — GAP-NSSA-3
//
// Score weakness biased toward Teaching & Learning + Leadership so the
// drawer's priority sections actually surface meaningful ranks.

function rec(
  partial: Omit<SsaPerformanceRecord, "averageScore" | "status">,
): SsaPerformanceRecord {
  const avg = partial.scores.reduce((a, b) => a + b.score, 0) / partial.scores.length;
  return { ...partial, averageScore: Math.round(avg * 10) / 10, status: statusFor(avg) };
}

/** Helper to build a full 8-score record from a partial map. */
function scoresFromMap(map: Partial<Record<SsaInterventionArea, number>>, defaultScore: number): SsaScore[] {
  return SSA_INTERVENTIONS.map((area) => ({
    intervention: area,
    score:        map[area] ?? defaultScore,
  }));
}

const SSA_HISTORY_BY_SCHOOL: Record<string, SsaPerformanceRecord[]> = {
  // ─── No SSAs (locked schools — drawer shows "Schedule SSA" empty state) ───
  "GAP-NSSA-1": [],
  "GAP-NSSA-2": [],

  // ─── Historical only (FY2026 done; FY2027 missing — drawer shows
  // "Complete Current SSA" empty state with read-only previous result) ───
  "GAP-NSSA-3": [
    rec({
      id: "SSA-NSSA3-2026", schoolId: "GAP-NSSA-3", schoolName: "Holy Family PS",
      operationalCycle: "FY2026", ssaDate: "2026-04-22",
      completedBy: "PL Mary Aciro", completedByRole: "PL",
      scores: scoresFromMap({
        "Teaching & Learning": 4, "Leadership": 5, "Learning Environment": 5,
        "Financial Health": 6, "Government Requirements & Compliance": 6,
        "Education Technology": 4, "Christlike Behaviour": 7, "Exposure to the Word of God": 7,
      }, 5),
    }),
  ],

  // ─── 1 SSA only (single horizontal bar chart) ───
  "GAP-NTR-1": [
    rec({
      id: "SSA-NTR1-2027", schoolId: "GAP-NTR-1", schoolName: "Acholi Beach PS",
      operationalCycle: "FY2027", ssaDate: "2027-06-12",
      completedBy: "CCEO Sarah Lamunu", completedByRole: "CCEO",
      scores: scoresFromMap({
        "Teaching & Learning": 4, "Leadership": 5, "Learning Environment": 5,
        "Financial Health": 6, "Government Requirements & Compliance": 7,
        "Education Technology": 7, "Christlike Behaviour": 8, "Exposure to the Word of God": 8,
      }, 6),
    }),
  ],

  // ─── 2 SSAs (last FY vs current FY grouped bars) ───
  "GAP-NTR-2": [
    rec({
      id: "SSA-NTR2-2027", schoolId: "GAP-NTR-2", schoolName: "Hope Primary School",
      operationalCycle: "FY2027", ssaDate: "2027-06-08",
      completedBy: "CCEO Sarah Lamunu", completedByRole: "CCEO",
      scores: scoresFromMap({
        "Teaching & Learning": 6, "Leadership": 6, "Learning Environment": 5,
        "Financial Health": 5, "Government Requirements & Compliance": 7,
        "Education Technology": 6, "Christlike Behaviour": 8, "Exposure to the Word of God": 8,
      }, 6),
    }),
    rec({
      id: "SSA-NTR2-2026", schoolId: "GAP-NTR-2", schoolName: "Hope Primary School",
      operationalCycle: "FY2026", ssaDate: "2026-05-18",
      completedBy: "IA James Otto", completedByRole: "IA",
      scores: scoresFromMap({
        "Teaching & Learning": 4, "Leadership": 5, "Learning Environment": 5,
        "Financial Health": 6, "Government Requirements & Compliance": 6,
        "Education Technology": 5, "Christlike Behaviour": 7, "Exposure to the Word of God": 7,
      }, 5),
    }),
  ],

  "GAP-NTR-3": [
    rec({
      id: "SSA-NTR3-2027", schoolId: "GAP-NTR-3", schoolName: "St. Mary's Memorial PS",
      operationalCycle: "FY2027", ssaDate: "2027-05-30",
      completedBy: "PL Mary Aciro", completedByRole: "PL",
      scores: scoresFromMap({
        "Teaching & Learning": 5, "Leadership": 4, "Learning Environment": 6,
        "Financial Health": 5, "Government Requirements & Compliance": 6,
        "Education Technology": 5, "Christlike Behaviour": 7, "Exposure to the Word of God": 8,
      }, 5),
    }),
    rec({
      id: "SSA-NTR3-2026", schoolId: "GAP-NTR-3", schoolName: "St. Mary's Memorial PS",
      operationalCycle: "FY2026", ssaDate: "2026-04-12",
      completedBy: "PL Mary Aciro", completedByRole: "PL",
      scores: scoresFromMap({
        "Teaching & Learning": 6, "Leadership": 5, "Learning Environment": 5,
        "Financial Health": 6, "Government Requirements & Compliance": 6,
        "Education Technology": 4, "Christlike Behaviour": 7, "Exposure to the Word of God": 8,
      }, 5),
    }),
  ],

  // ─── 3 SSAs (three-year trend) ───
  "GAP-NTR-4": [
    rec({
      id: "SSA-NTR4-2027", schoolId: "GAP-NTR-4", schoolName: "St. Joseph PS Kitgum",
      operationalCycle: "FY2027", ssaDate: "2027-06-02",
      completedBy: "CCEO Sarah Lamunu", completedByRole: "CCEO",
      scores: scoresFromMap({
        "Teaching & Learning": 6, "Leadership": 6, "Learning Environment": 7,
        "Financial Health": 5, "Government Requirements & Compliance": 7,
        "Education Technology": 6, "Christlike Behaviour": 8, "Exposure to the Word of God": 9,
      }, 6),
    }),
    rec({
      id: "SSA-NTR4-2026", schoolId: "GAP-NTR-4", schoolName: "St. Joseph PS Kitgum",
      operationalCycle: "FY2026", ssaDate: "2026-05-22",
      completedBy: "IA James Otto", completedByRole: "IA",
      scores: scoresFromMap({
        "Teaching & Learning": 4, "Leadership": 5, "Learning Environment": 5,
        "Financial Health": 6, "Government Requirements & Compliance": 6,
        "Education Technology": 5, "Christlike Behaviour": 7, "Exposure to the Word of God": 8,
      }, 5),
    }),
    rec({
      id: "SSA-NTR4-2025", schoolId: "GAP-NTR-4", schoolName: "St. Joseph PS Kitgum",
      operationalCycle: "FY2025", ssaDate: "2025-04-15",
      completedBy: "PL Mary Aciro", completedByRole: "PL",
      scores: scoresFromMap({
        "Teaching & Learning": 3, "Leadership": 4, "Learning Environment": 5,
        "Financial Health": 6, "Government Requirements & Compliance": 5,
        "Education Technology": 4, "Christlike Behaviour": 6, "Exposure to the Word of God": 7,
      }, 5),
    }),
  ],

  "GAP-NV-1": [
    rec({
      id: "SSA-NV1-2027", schoolId: "GAP-NV-1", schoolName: "Pakwach Town PS",
      operationalCycle: "FY2027", ssaDate: "2027-05-10",
      completedBy: "CCEO Sarah Lamunu", completedByRole: "CCEO",
      scores: scoresFromMap({
        "Teaching & Learning": 7, "Leadership": 7, "Learning Environment": 8,
        "Financial Health": 6, "Government Requirements & Compliance": 8,
        "Education Technology": 7, "Christlike Behaviour": 9, "Exposure to the Word of God": 9,
      }, 7),
    }),
    rec({
      id: "SSA-NV1-2026", schoolId: "GAP-NV-1", schoolName: "Pakwach Town PS",
      operationalCycle: "FY2026", ssaDate: "2026-04-12",
      completedBy: "IA James Otto", completedByRole: "IA",
      scores: scoresFromMap({
        "Teaching & Learning": 6, "Leadership": 6, "Learning Environment": 7,
        "Financial Health": 6, "Government Requirements & Compliance": 7,
        "Education Technology": 6, "Christlike Behaviour": 8, "Exposure to the Word of God": 8,
      }, 6),
    }),
    rec({
      id: "SSA-NV1-2025", schoolId: "GAP-NV-1", schoolName: "Pakwach Town PS",
      operationalCycle: "FY2025", ssaDate: "2025-03-22",
      completedBy: "PL Mary Aciro", completedByRole: "PL",
      scores: scoresFromMap({
        "Teaching & Learning": 5, "Leadership": 5, "Learning Environment": 6,
        "Financial Health": 6, "Government Requirements & Compliance": 6,
        "Education Technology": 5, "Christlike Behaviour": 7, "Exposure to the Word of God": 7,
      }, 6),
    }),
  ],

  "GAP-NV-2": [
    rec({
      id: "SSA-NV2-2027", schoolId: "GAP-NV-2", schoolName: "Bbaale Central PS",
      operationalCycle: "FY2027", ssaDate: "2027-04-28",
      completedBy: "PL Mary Aciro", completedByRole: "PL",
      scores: scoresFromMap({
        "Teaching & Learning": 5, "Leadership": 5, "Learning Environment": 6,
        "Financial Health": 4, "Government Requirements & Compliance": 6,
        "Education Technology": 5, "Christlike Behaviour": 7, "Exposure to the Word of God": 7,
      }, 5),
    }),
    rec({
      id: "SSA-NV2-2026", schoolId: "GAP-NV-2", schoolName: "Bbaale Central PS",
      operationalCycle: "FY2026", ssaDate: "2026-04-08",
      completedBy: "PL Mary Aciro", completedByRole: "PL",
      scores: scoresFromMap({
        "Teaching & Learning": 5, "Leadership": 5, "Learning Environment": 6,
        "Financial Health": 5, "Government Requirements & Compliance": 6,
        "Education Technology": 4, "Christlike Behaviour": 7, "Exposure to the Word of God": 8,
      }, 5),
    }),
    rec({
      id: "SSA-NV2-2025", schoolId: "GAP-NV-2", schoolName: "Bbaale Central PS",
      operationalCycle: "FY2025", ssaDate: "2025-03-15",
      completedBy: "IA James Otto", completedByRole: "IA",
      scores: scoresFromMap({
        "Teaching & Learning": 4, "Leadership": 4, "Learning Environment": 5,
        "Financial Health": 6, "Government Requirements & Compliance": 5,
        "Education Technology": 4, "Christlike Behaviour": 6, "Exposure to the Word of God": 7,
      }, 5),
    }),
  ],

  "GAP-NV-3": [
    rec({
      id: "SSA-NV3-2027", schoolId: "GAP-NV-3", schoolName: "Dokolo Central PS",
      operationalCycle: "FY2027", ssaDate: "2027-05-04",
      completedBy: "CCEO Sarah Lamunu", completedByRole: "CCEO",
      scores: scoresFromMap({
        "Teaching & Learning": 8, "Leadership": 7, "Learning Environment": 8,
        "Financial Health": 7, "Government Requirements & Compliance": 8,
        "Education Technology": 7, "Christlike Behaviour": 9, "Exposure to the Word of God": 9,
      }, 7),
    }),
    rec({
      id: "SSA-NV3-2026", schoolId: "GAP-NV-3", schoolName: "Dokolo Central PS",
      operationalCycle: "FY2026", ssaDate: "2026-04-20",
      completedBy: "CCEO Sarah Lamunu", completedByRole: "CCEO",
      scores: scoresFromMap({
        "Teaching & Learning": 7, "Leadership": 7, "Learning Environment": 7,
        "Financial Health": 7, "Government Requirements & Compliance": 7,
        "Education Technology": 6, "Christlike Behaviour": 8, "Exposure to the Word of God": 8,
      }, 7),
    }),
    rec({
      id: "SSA-NV3-2025", schoolId: "GAP-NV-3", schoolName: "Dokolo Central PS",
      operationalCycle: "FY2025", ssaDate: "2025-03-30",
      completedBy: "PL Mary Aciro", completedByRole: "PL",
      scores: scoresFromMap({
        "Teaching & Learning": 6, "Leadership": 6, "Learning Environment": 6,
        "Financial Health": 6, "Government Requirements & Compliance": 7,
        "Education Technology": 5, "Christlike Behaviour": 8, "Exposure to the Word of God": 7,
      }, 6),
    }),
  ],
};

/**
 * Build a SchoolGap-compatible school context shim for the drawer
 * header. Lifted from the gap mock without forcing the drawer to
 * accept the entire SchoolGap (so the drawer can be opened from
 * surfaces that don't have the full gap object — e.g. Core School
 * cards).
 */
export function schoolContextFromGap(s: SchoolGap): {
  schoolId:    string;
  schoolName:  string;
  district:    string;
  subCounty?:  string;
  parish?:     string;
  ssaCompleted: boolean;
} {
  return {
    schoolId:     s.id,
    schoolName:   s.schoolName,
    district:     s.district,
    subCounty:    s.subCounty,
    parish:       s.parish,
    ssaCompleted: s.ssaCompleted,
  };
}
