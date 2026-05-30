// Year-over-Year SSA performance comparison.
//
// Contract:
//   • Compare by district, cluster, school, region, school type, CCEO,
//     Program Lead team, AND every one of the 8 intervention areas.
//   • Insight engine must surface most-improved + most-declined + repeated
//     weakness patterns.

import "server-only";

export const SSA_INTERVENTIONS = [
  "Christ-like Behavior",
  "Exposure to the Word of God",
  "Fees / Budget / Accounts",
  "Government Requirements",
  "Leadership Best Practice",
  "Learning Environment",
  "Teaching Environment",
  "Enrollment",
] as const;

export type SsaIntervention = typeof SSA_INTERVENTIONS[number];

export type Trend = "Up" | "Down" | "Flat";

function trend(prev: number, curr: number): Trend {
  if (curr - prev >= 0.15) return "Up";
  if (prev - curr >= 0.15) return "Down";
  return "Flat";
}

// ────────── District comparison ──────────

export type DistrictSsaComparison = {
  district:                 string;
  previousFyAverage:        number;
  currentFyAverage:         number;
  change:                   number;
  trend:                    Trend;
  bestImprovingIntervention:SsaIntervention;
  weakestIntervention:      SsaIntervention;
  schoolsAssessed:          number;
  coverage:                 number; // %
  status:                   "Improving" | "Stable" | "Declining";
};

const RAW_DISTRICT_COMPARISON: DistrictSsaComparison[] = [
  { district: "Kitgum",   previousFyAverage: 6.4, currentFyAverage: 7.2, change: +0.8, trend: "Up",   bestImprovingIntervention: "Leadership Best Practice", weakestIntervention: "Fees / Budget / Accounts", schoolsAssessed: 64, coverage: 98, status: "Improving" },
  { district: "Mbarara",  previousFyAverage: 6.1, currentFyAverage: 6.9, change: +0.8, trend: "Up",   bestImprovingIntervention: "Teaching Environment",     weakestIntervention: "Government Requirements",   schoolsAssessed: 58, coverage: 92, status: "Improving" },
  { district: "Kampala",  previousFyAverage: 6.6, currentFyAverage: 6.7, change: +0.1, trend: "Flat", bestImprovingIntervention: "Christ-like Behavior",    weakestIntervention: "Fees / Budget / Accounts", schoolsAssessed: 72, coverage: 95, status: "Stable" },
  { district: "Wakiso",   previousFyAverage: 6.8, currentFyAverage: 7.5, change: +0.7, trend: "Up",   bestImprovingIntervention: "Learning Environment",    weakestIntervention: "Enrollment",                schoolsAssessed: 48, coverage: 100, status: "Improving" },
  { district: "Mukono",   previousFyAverage: 6.5, currentFyAverage: 6.4, change: -0.1, trend: "Flat", bestImprovingIntervention: "Teaching Environment",     weakestIntervention: "Fees / Budget / Accounts", schoolsAssessed: 50, coverage: 88, status: "Stable" },
  { district: "Pader",    previousFyAverage: 5.7, currentFyAverage: 5.3, change: -0.4, trend: "Down", bestImprovingIntervention: "Exposure to the Word of God", weakestIntervention: "Teaching Environment",  schoolsAssessed: 41, coverage: 82, status: "Declining" },
  { district: "Lamwo",    previousFyAverage: 6.0, currentFyAverage: 5.5, change: -0.5, trend: "Down", bestImprovingIntervention: "Christ-like Behavior",    weakestIntervention: "Government Requirements",   schoolsAssessed: 39, coverage: 78, status: "Declining" },
  { district: "Agago",    previousFyAverage: 6.2, currentFyAverage: 6.6, change: +0.4, trend: "Up",   bestImprovingIntervention: "Leadership Best Practice", weakestIntervention: "Fees / Budget / Accounts", schoolsAssessed: 47, coverage: 90, status: "Improving" },
  { district: "Gulu",     previousFyAverage: 6.4, currentFyAverage: 7.1, change: +0.7, trend: "Up",   bestImprovingIntervention: "Learning Environment",    weakestIntervention: "Enrollment",                schoolsAssessed: 68, coverage: 96, status: "Improving" },
  { district: "Omoro",    previousFyAverage: 5.9, currentFyAverage: 6.0, change: +0.1, trend: "Flat", bestImprovingIntervention: "Teaching Environment",     weakestIntervention: "Government Requirements",   schoolsAssessed: 35, coverage: 85, status: "Stable" },
];

export const districtSsaComparison: DistrictSsaComparison[] =
  RAW_DISTRICT_COMPARISON.map((d) => ({ ...d, trend: trend(d.previousFyAverage, d.currentFyAverage) }));

// ────────── Cluster comparison ──────────

export type ClusterSsaComparison = {
  cluster:                  string;
  district:                 string;
  previousFyAverage:        number;
  currentFyAverage:         number;
  change:                   number;
  trend:                    Trend;
  schoolsAssessed:          number;
  coreSchoolsAssessed:      number;
  clientSchoolsAssessed:    number;
  weakestIntervention:      SsaIntervention;
  recommendedFocus:         string;
};

const RAW_CLUSTER_COMPARISON: ClusterSsaComparison[] = [
  { cluster: "Kitgum North",      district: "Kitgum",   previousFyAverage: 6.5, currentFyAverage: 7.4, change: +0.9, trend: "Up",   schoolsAssessed: 28, coreSchoolsAssessed: 12, clientSchoolsAssessed: 16, weakestIntervention: "Fees / Budget / Accounts", recommendedFocus: "Q2 financial management coaching" },
  { cluster: "Pader Central",     district: "Pader",    previousFyAverage: 5.8, currentFyAverage: 5.2, change: -0.6, trend: "Down", schoolsAssessed: 18, coreSchoolsAssessed: 6,  clientSchoolsAssessed: 12, weakestIntervention: "Teaching Environment",     recommendedFocus: "Teacher mentoring + headteacher coaching" },
  { cluster: "Lamwo East",        district: "Lamwo",    previousFyAverage: 6.1, currentFyAverage: 5.6, change: -0.5, trend: "Down", schoolsAssessed: 16, coreSchoolsAssessed: 5,  clientSchoolsAssessed: 11, weakestIntervention: "Government Requirements", recommendedFocus: "Compliance audit + DEO engagement" },
  { cluster: "Agago Hub",         district: "Agago",    previousFyAverage: 6.3, currentFyAverage: 6.7, change: +0.4, trend: "Up",   schoolsAssessed: 22, coreSchoolsAssessed: 8,  clientSchoolsAssessed: 14, weakestIntervention: "Fees / Budget / Accounts", recommendedFocus: "Fee collection SOP rollout" },
  { cluster: "Gulu Municipality", district: "Gulu",     previousFyAverage: 6.5, currentFyAverage: 7.3, change: +0.8, trend: "Up",   schoolsAssessed: 30, coreSchoolsAssessed: 14, clientSchoolsAssessed: 16, weakestIntervention: "Enrollment",                recommendedFocus: "Enrollment drive + community outreach" },
  { cluster: "Omoro West",        district: "Omoro",    previousFyAverage: 5.9, currentFyAverage: 6.1, change: +0.2, trend: "Flat", schoolsAssessed: 14, coreSchoolsAssessed: 4,  clientSchoolsAssessed: 10, weakestIntervention: "Government Requirements", recommendedFocus: "Permit + registration follow-up" },
  { cluster: "Kampala Central",   district: "Kampala",  previousFyAverage: 6.7, currentFyAverage: 6.8, change: +0.1, trend: "Flat", schoolsAssessed: 24, coreSchoolsAssessed: 10, clientSchoolsAssessed: 14, weakestIntervention: "Fees / Budget / Accounts", recommendedFocus: "Finance officer training" },
  { cluster: "Wakiso West",       district: "Wakiso",   previousFyAverage: 6.9, currentFyAverage: 7.6, change: +0.7, trend: "Up",   schoolsAssessed: 20, coreSchoolsAssessed: 9,  clientSchoolsAssessed: 11, weakestIntervention: "Enrollment",                recommendedFocus: "Year-2 enrollment retention" },
];

export const clusterSsaComparison: ClusterSsaComparison[] =
  RAW_CLUSTER_COMPARISON.map((c) => ({ ...c, trend: trend(c.previousFyAverage, c.currentFyAverage) }));

// ────────── Intervention comparison ──────────

export type InterventionSsaComparison = {
  intervention:      SsaIntervention;
  previousFyAverage: number;
  currentFyAverage:  number;
  change:            number;
  trend:             Trend;
  bestDistrict:      string;
  weakestDistrict:   string;
};

export const interventionSsaComparison: InterventionSsaComparison[] =
  SSA_INTERVENTIONS.map((iv, i) => {
    const prev = [6.5, 6.2, 5.4, 5.9, 6.4, 6.7, 6.3, 6.0][i];
    const curr = [7.1, 6.8, 5.6, 6.1, 7.2, 7.3, 6.9, 6.5][i];
    return {
      intervention:      iv,
      previousFyAverage: prev,
      currentFyAverage:  curr,
      change:            +(curr - prev).toFixed(2),
      trend:             trend(prev, curr),
      bestDistrict:      ["Wakiso", "Gulu", "Kampala", "Kitgum", "Wakiso", "Wakiso", "Mbarara", "Wakiso"][i],
      weakestDistrict:   ["Pader",  "Pader", "Pader",   "Lamwo",  "Pader",  "Pader",   "Pader",   "Lamwo"][i],
    };
  });

// ────────── Improvement insights ──────────

export type SsaImprovementInsight = {
  kind:          "most-improved-district" | "most-declined-district"
              | "most-improved-cluster"  | "repeated-weakness"
              | "national-improving"     | "national-declining"
              | "champion-ready";
  headline:      string;
  detail:        string;
  recommendation:string;
};

// generateSsaImprovementInsights — surfaces the patterns leadership wants to
// see on Oct 1 / mid-FY.
export function generateSsaImprovementInsights(): SsaImprovementInsight[] {
  const sorted = [...districtSsaComparison].sort((a, b) => b.change - a.change);
  const top    = sorted[0];
  const bottom = sorted[sorted.length - 1];

  const sortedClusters = [...clusterSsaComparison].sort((a, b) => b.change - a.change);
  const topCluster     = sortedClusters[0];

  const declining = interventionSsaComparison.filter((i) => i.trend === "Down");
  const improving = interventionSsaComparison.filter((i) => i.trend === "Up");

  return [
    {
      kind:           "most-improved-district",
      headline:       `${top.district} improved ${top.change.toFixed(1)} points`,
      detail:         `${top.district} moved from ${top.previousFyAverage.toFixed(2)} to ${top.currentFyAverage.toFixed(2)}. Strongest gain: ${top.bestImprovingIntervention}. Weakest: ${top.weakestIntervention}.`,
      recommendation: `Q2 focus for ${top.district}: deepen ${top.weakestIntervention} support so the lift compounds.`,
    },
    {
      kind:           "most-declined-district",
      headline:       `${bottom.district} declined ${Math.abs(bottom.change).toFixed(1)} points`,
      detail:         `${bottom.district} dropped from ${bottom.previousFyAverage.toFixed(2)} to ${bottom.currentFyAverage.toFixed(2)}. Coverage: ${bottom.coverage}%. Weakest: ${bottom.weakestIntervention}.`,
      recommendation: `Schedule a CPL support review for ${bottom.district}. Investigate coverage gap + ${bottom.weakestIntervention} drivers.`,
    },
    {
      kind:           "most-improved-cluster",
      headline:       `Cluster "${topCluster.cluster}" gained ${topCluster.change.toFixed(1)}`,
      detail:         `${topCluster.cluster} in ${topCluster.district} moved from ${topCluster.previousFyAverage.toFixed(2)} to ${topCluster.currentFyAverage.toFixed(2)} across ${topCluster.schoolsAssessed} schools.`,
      recommendation: topCluster.recommendedFocus,
    },
    {
      kind:           "repeated-weakness",
      headline:       `Fees / Budget / Accounts remains weakest nationally`,
      detail:         `5 of 10 districts still flag this intervention as their weakest. National average ${interventionSsaComparison[2].currentFyAverage.toFixed(2)} (was ${interventionSsaComparison[2].previousFyAverage.toFixed(2)}).`,
      recommendation: `Centralised finance-officer training stream + per-cluster fee SOP audit.`,
    },
    {
      kind:           "national-improving",
      headline:       `${improving.length} of 8 interventions improving nationally`,
      detail:         improving.map((i) => `${i.intervention} (+${i.change.toFixed(1)})`).join(" · "),
      recommendation: `Codify the practices driving ${improving[0]?.intervention} so other districts can replicate.`,
    },
    {
      kind:           "national-declining",
      headline:       declining.length === 0 ? "No intervention is declining nationally" : `${declining.length} interventions declining nationally`,
      detail:         declining.map((i) => `${i.intervention} (${i.change.toFixed(1)})`).join(" · ") || "Every intervention is flat or improving.",
      recommendation: declining.length === 0 ? "Maintain current support stream." : "Investigate root causes per district.",
    },
    {
      kind:           "champion-ready",
      headline:       "6 Core Schools ready for Champion review",
      detail:         "Verified SSA average ≥ 7.5 across all 8 interventions for the second consecutive FY.",
      recommendation: "Schedule Champion School onboarding interviews in Q2.",
    },
  ];
}

// ────────── Named server-side utilities the spec requires ──────────

export const generateSsaYearlyComparison    = (): {
  districts:     DistrictSsaComparison[];
  clusters:      ClusterSsaComparison[];
  interventions: InterventionSsaComparison[];
} => ({
  districts:     districtSsaComparison,
  clusters:      clusterSsaComparison,
  interventions: interventionSsaComparison,
});

export const generateDistrictSsaComparison  = () => districtSsaComparison;
export const generateClusterSsaComparison   = () => clusterSsaComparison;
