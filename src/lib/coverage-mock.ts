// Client School Coverage & Partner Assignment Engine.
//
// Contract:
//   • Each CCEO must visit at least 560 client schools per FY.
//   • Each Program Lead must visit at least 280 client schools per FY
//     (supervisory / quality assurance / coaching visits).
//   • Minimum 5 client school visits per CCEO per day.
//   • Maximum 1 group training per staff/partner per day.
//   • Schools not covered by staff capacity are assigned to certified
//     partners — never left unassigned.
//   • Partner assignment is ranked by SSA risk: weakest SSA scores get
//     earlier partner support.
//   • Only VERIFIED visits count toward coverage completion. Planned,
//     draft, rejected, unverified work does NOT count.
//   • Non-certified partner visits do NOT count where certification is
//     required.

import "server-only";
import { activeFinancialYear } from "@/lib/fy-engine";
import { CCEO_ANNUAL_TARGET, PL_ANNUAL_TARGET } from "@/lib/targets/role-targets";

// ────────── Constants ──────────

// Per-role FY targets come from the client-safe single source (imported at top
// for local use); re-exported so existing importers of coverage-mock keep working.
export { CCEO_ANNUAL_TARGET, PL_ANNUAL_TARGET };
export const MIN_DAILY_VISITS      = 5;   // CCEO minimum per planning day
export const MAX_DAILY_GROUP_TRAININGS = 1;

// ────────── Coverage status ──────────

export type CoverageStatus =
  | "Not Assigned"
  | "Assigned to CCEO"
  | "Assigned to Program Lead"
  | "Assigned to Partner"
  | "Scheduled"
  | "Completed"
  | "Submitted for Verification"
  | "Verified"
  | "Closed"
  | "At Risk"
  | "Overdue";

export type CovPaceStatus = "Ahead" | "On Track" | "Behind" | "High Risk" | "Critical";

// ────────── CCEO coverage ──────────

export type CceoCoverageRow = {
  staffId:           string;
  staffName:         string;
  district:          string;
  cluster?:          string;
  region:            string;
  assignedSchools:   number;       // schools the CCEO owns this FY
  annualTarget:      number;       // = CCEO_ANNUAL_TARGET unless overridden
  completedVisits:   number;       // verified visits to date
  remainingVisits:   number;
  monthlyPacePct:    number;       // % of expected month pace
  dailyAvgLast14:    number;       // average client visits/day in the last 14 working days
  dailyCompliancePct:number;       // % of recent planning days that hit MIN_DAILY_VISITS
  status:            CovPaceStatus;
};

// Realistic Uganda demo: 8 CCEOs with varied pacing.
export const cceoCoverageRows: CceoCoverageRow[] = [
  buildCceo({ staffId: "STF-DM-014", staffName: "Daniel Mwangi",  district: "Kitgum",  cluster: "Kitgum North", region: "North",  assigned: 562, completed: 437, dailyAvg: 5.8, compliance: 94 }),
  buildCceo({ staffId: "STF-GN-007", staffName: "Grace Njeri",    district: "Gulu",    cluster: "Gulu Mun",     region: "North",  assigned: 560, completed: 412, dailyAvg: 5.4, compliance: 92 }),
  buildCceo({ staffId: "STF-PO-008", staffName: "Peter Ochieng",  district: "Pader",   cluster: "Pader Central",region: "North",  assigned: 558, completed: 318, dailyAvg: 4.6, compliance: 68 }),
  buildCceo({ staffId: "STF-SN-009", staffName: "Sarah Namutebi", district: "Lamwo",   cluster: "Lamwo East",   region: "North",  assigned: 560, completed: 369, dailyAvg: 5.0, compliance: 81 }),
  buildCceo({ staffId: "STF-BO-005", staffName: "Brian Okello",   district: "Agago",   cluster: "Agago Hub",    region: "North",  assigned: 565, completed: 224, dailyAvg: 3.4, compliance: 52 }),
  buildCceo({ staffId: "STF-AD-021", staffName: "Aisha Dar",      district: "Kampala", cluster: "Kampala Central", region: "Central", assigned: 561, completed: 458, dailyAvg: 6.1, compliance: 96 }),
  buildCceo({ staffId: "STF-PM-031", staffName: "Purity Muthoni", district: "Wakiso",  cluster: "Wakiso West",  region: "Central",   assigned: 564, completed: 398, dailyAvg: 5.2, compliance: 88 }),
  buildCceo({ staffId: "STF-EN-012", staffName: "Esther Naluwu",  district: "Mukono",  cluster: "Mukono Hub",   region: "Central",   assigned: 560, completed: 287, dailyAvg: 4.2, compliance: 64 }),
];

function buildCceo({
  staffId, staffName, district, cluster, region,
  assigned, completed, dailyAvg, compliance,
}: {
  staffId: string; staffName: string; district: string; cluster?: string; region: string;
  assigned: number; completed: number; dailyAvg: number; compliance: number;
}): CceoCoverageRow {
  // ENGINE_TODAY anchors at FY month ~2 (November). Expected pace = (current FY month / 12) * target.
  // For demo we set "expected" at month 8 (~mid-year) so percentages spread realistically.
  const expectedPace = Math.round((8 / 12) * CCEO_ANNUAL_TARGET); // ≈ 373
  const monthlyPacePct = Math.round((completed / expectedPace) * 100);
  return {
    staffId, staffName, district, cluster, region,
    assignedSchools:   assigned,
    annualTarget:      CCEO_ANNUAL_TARGET,
    completedVisits:   completed,
    remainingVisits:   Math.max(0, assigned - completed),
    monthlyPacePct,
    dailyAvgLast14:    dailyAvg,
    dailyCompliancePct:compliance,
    status:            pacingStatus(monthlyPacePct),
  };
}

function pacingStatus(pct: number): CovPaceStatus {
  if (pct >= 105) return "Ahead";
  if (pct >= 95)  return "On Track";
  if (pct >= 80)  return "Behind";
  if (pct >= 60)  return "High Risk";
  return "Critical";
}

// ────────── Program Lead coverage ──────────

export type PlCoverageRow = {
  staffId:          string;
  staffName:        string;
  team:             string;
  region:           string;
  annualTarget:     number;       // = PL_ANNUAL_TARGET
  completedVisits:  number;       // verified supervisory visits
  remainingVisits:  number;
  coveragePct:      number;       // completed / target
  schoolsVisited:   number;       // unique schools touched
  districtCoverage: number;       // # districts where at least one school was visited
  status:           CovPaceStatus;
};

export const plCoverageRows: PlCoverageRow[] = [
  buildPl({ staffId: "PL-001", staffName: "Daniel Mwangi",  team: "Northern A",  region: "North",  completed: 184, uniqueSchools: 168, districts: 4 }),
  buildPl({ staffId: "PL-002", staffName: "Aisha Dar",      team: "Central",     region: "Central",   completed: 207, uniqueSchools: 192, districts: 3 }),
  buildPl({ staffId: "PL-003", staffName: "Brian Okello",   team: "Northern B",  team_alt: "Northern B", region: "North", completed: 142, uniqueSchools: 128, districts: 4 }),
  buildPl({ staffId: "PL-004", staffName: "Esther Wanjiru", team: "East",        region: "East",   completed: 156, uniqueSchools: 140, districts: 3 }),
  buildPl({ staffId: "PL-005", staffName: "Fatima Noor",    team: "West",        region: "West",   completed: 118, uniqueSchools: 102, districts: 3 }),
];

function buildPl({
  staffId, staffName, team, region, completed, uniqueSchools, districts,
}: {
  staffId: string; staffName: string; team: string; team_alt?: string; region: string;
  completed: number; uniqueSchools: number; districts: number;
}): PlCoverageRow {
  const coveragePct = Math.round((completed / PL_ANNUAL_TARGET) * 100);
  return {
    staffId, staffName, team, region,
    annualTarget:     PL_ANNUAL_TARGET,
    completedVisits:  completed,
    remainingVisits:  Math.max(0, PL_ANNUAL_TARGET - completed),
    coveragePct,
    schoolsVisited:   uniqueSchools,
    districtCoverage: districts,
    status:           pacingStatus(coveragePct * (12 / 8)), // same expected pace logic
  };
}

// ────────── Partner coverage ──────────

export type PartnerCertification = "Certified" | "Probationary" | "Suspended";
export type PartnerSpecialization =
  | "Leadership Best Practice"
  | "Teaching Environment"
  | "Fees / Budget / Accounts"
  | "Government Requirements"
  | "Learning Environment"
  | "Discipleship";

export type PartnerCoverageRow = {
  partnerId:           string;
  partnerName:         string;
  certification:       PartnerCertification;
  region:              string;
  districts:           string[];
  specialization:      PartnerSpecialization;
  capacityPct:         number;       // % of capacity remaining this FY
  assignedSchools:     number;
  highRiskAssignments: number;       // # of assigned schools at SSA < 5 or no FY SSA
  completedVisits:     number;       // verified
  verifiedVisits:      number;
  remainingVisits:     number;
  verificationPassRate:number;       // % of submitted visits that passed verification
  salesforceCompliancePct: number;
  status:              CovPaceStatus;
};

export const partnerCoverageRows: PartnerCoverageRow[] = [
  buildPartner({ id: "PRT-001", name: "Sunrise Education Partner",   cert: "Certified",   region: "North", districts: ["Kitgum", "Pader", "Lamwo"], spec: "Teaching Environment",      capacity: 68, assigned: 42, highRisk: 18, completed: 28, verified: 26, passRate: 92, sf: 95 }),
  buildPartner({ id: "PRT-002", name: "Hope Africa",                 cert: "Certified",   region: "Central",  districts: ["Kampala", "Wakiso"],         spec: "Leadership Best Practice",  capacity: 54, assigned: 38, highRisk: 12, completed: 24, verified: 22, passRate: 88, sf: 91 }),
  buildPartner({ id: "PRT-003", name: "Olive Children's School",     cert: "Certified",   region: "Central",  districts: ["Mukono", "Buikwe"],          spec: "Discipleship",              capacity: 72, assigned: 28, highRisk: 6,  completed: 16, verified: 16, passRate: 100, sf: 87 }),
  buildPartner({ id: "PRT-004", name: "Western Light Initiative",    cert: "Certified",   region: "West",  districts: ["Hoima", "Mbarara"],          spec: "Fees / Budget / Accounts",  capacity: 45, assigned: 22, highRisk: 9,  completed: 14, verified: 13, passRate: 93, sf: 84 }),
  buildPartner({ id: "PRT-005", name: "Northern Education Trust",    cert: "Certified",   region: "North", districts: ["Gulu", "Omoro", "Agago"],    spec: "Learning Environment",      capacity: 58, assigned: 34, highRisk: 14, completed: 19, verified: 17, passRate: 85, sf: 82 }),
  buildPartner({ id: "PRT-006", name: "Central Schools Network",     cert: "Probationary",region: "Central",  districts: ["Kampala", "Mukono"],         spec: "Government Requirements",   capacity: 80, assigned: 12, highRisk: 4,  completed: 5,  verified: 4,  passRate: 80, sf: 70 }),
  buildPartner({ id: "PRT-007", name: "Maryhill Cluster Partner",    cert: "Certified",   region: "North", districts: ["Kitgum"],                    spec: "Teaching Environment",      capacity: 42, assigned: 16, highRisk: 7,  completed: 11, verified: 11, passRate: 100, sf: 96 }),
  buildPartner({ id: "PRT-008", name: "Apollo Education Foundation", cert: "Certified",   region: "Central",  districts: ["Wakiso"],                    spec: "Leadership Best Practice",  capacity: 38, assigned: 20, highRisk: 8,  completed: 12, verified: 12, passRate: 100, sf: 92 }),
];

function buildPartner({
  id, name, cert, region, districts, spec,
  capacity, assigned, highRisk, completed, verified, passRate, sf,
}: {
  id: string; name: string; cert: PartnerCertification; region: string; districts: string[];
  spec: PartnerSpecialization;
  capacity: number; assigned: number; highRisk: number; completed: number; verified: number;
  passRate: number; sf: number;
}): PartnerCoverageRow {
  const completionPct = assigned === 0 ? 0 : Math.round((verified / assigned) * 100);
  return {
    partnerId: id, partnerName: name, certification: cert, region, districts,
    specialization: spec,
    capacityPct: capacity,
    assignedSchools: assigned,
    highRiskAssignments: highRisk,
    completedVisits: completed,
    verifiedVisits: verified,
    remainingVisits: Math.max(0, assigned - verified),
    verificationPassRate: passRate,
    salesforceCompliancePct: sf,
    status: pacingStatus(completionPct * (12 / 8)),
  };
}

// ────────── Coverage rollup ──────────

export type CoverageKpis = {
  totalClientSchools:     number;
  assignedToCceos:        number;
  assignedToPls:          number;
  assignedToPartners:     number;
  unassigned:             number;
  cceoCoveragePct:        number;
  partnerCoveragePct:     number;
  highRiskCovered:        number;
  schoolsBelowSsaThreshold:number;
};

const FY = activeFinancialYear();

export function coverageKpis(): CoverageKpis {
  const assignedToCceos = cceoCoverageRows.reduce((a, c) => a + c.assignedSchools, 0);
  const assignedToPls   = plCoverageRows.reduce((a, p) => a + p.annualTarget, 0);
  const assignedToPartners = partnerCoverageRows.reduce((a, p) => a + p.assignedSchools, 0);
  // Realistic Uganda Edify total (matches Impact dashboard's Client Schools count + some).
  const totalClientSchools = 4_512;
  const unassigned = Math.max(0, totalClientSchools - assignedToCceos - assignedToPartners);
  const highRiskCovered = partnerCoverageRows.reduce((a, p) => a + p.highRiskAssignments, 0);
  return {
    totalClientSchools,
    assignedToCceos,
    assignedToPls,
    assignedToPartners,
    unassigned,
    cceoCoveragePct:    Math.round((assignedToCceos / totalClientSchools) * 100),
    partnerCoveragePct: Math.round((assignedToPartners / totalClientSchools) * 100),
    highRiskCovered,
    schoolsBelowSsaThreshold: 318, // schools with current FY SSA < 5
  };
}

// ────────── Partner assignment recommendations ──────────

export type PartnerAssignmentRecommendation = {
  id:                  string;
  schoolBatch:         string;       // "42 schools in Kitgum Cluster"
  schoolCount:         number;
  cluster:             string;
  district:            string;
  weakestIntervention: string;
  reason:              string;
  recommendedPartner:  PartnerCoverageRow;
  alternativePartners: PartnerCoverageRow[];
};

// Match weakest-intervention schools to partners whose specialization aligns,
// have capacity, are certified, and have the right district coverage.
export function generatePartnerAssignmentRecommendations(): PartnerAssignmentRecommendation[] {
  return [
    {
      id: "rec-1",
      schoolBatch: "42 low-performing schools in Kitgum Cluster",
      schoolCount: 42,
      cluster: "Kitgum North",
      district: "Kitgum",
      weakestIntervention: "Teaching Environment",
      reason: "Cluster SSA average is 5.2 — below threshold. 42 schools have no current-FY SSA verified visit. Sunrise has 68% capacity remaining, is certified, covers Kitgum, and has prior experience with weak Teaching Environment scores.",
      recommendedPartner: partnerCoverageRows[0],
      alternativePartners: [partnerCoverageRows[4], partnerCoverageRows[6]],
    },
    {
      id: "rec-2",
      schoolBatch: "18 high-risk schools in Pader Central",
      schoolCount: 18,
      cluster: "Pader Central",
      district: "Pader",
      weakestIntervention: "Government Requirements",
      reason: "12 schools have SSA Overdue + 6 with SSA < 5. Northern Education Trust covers Pader, is certified, has 58% capacity, and specializes in school operations/compliance support.",
      recommendedPartner: partnerCoverageRows[4],
      alternativePartners: [partnerCoverageRows[0]],
    },
    {
      id: "rec-3",
      schoolBatch: "24 schools in Wakiso West needing Leadership coaching",
      schoolCount: 24,
      cluster: "Wakiso West",
      district: "Wakiso",
      weakestIntervention: "Leadership Best Practice",
      reason: "Cluster Leadership intervention score dropped from 7.2 to 6.3. Hope Africa is certified, covers Wakiso, specializes in Leadership Best Practice, with 88% verification pass rate.",
      recommendedPartner: partnerCoverageRows[1],
      alternativePartners: [partnerCoverageRows[7]],
    },
    {
      id: "rec-4",
      schoolBatch: "16 schools in Mukono Hub with weak finance",
      schoolCount: 16,
      cluster: "Mukono Hub",
      district: "Mukono",
      weakestIntervention: "Fees / Budget / Accounts",
      reason: "Mukono cluster Fees/Budget intervention is the weakest at 5.6 (down 0.4 vs prev FY). Western Light Initiative specializes in this area and covers neighbouring districts.",
      recommendedPartner: partnerCoverageRows[3],
      alternativePartners: [partnerCoverageRows[1]],
    },
    {
      id: "rec-5",
      schoolBatch: "11 schools in Gulu Municipality needing follow-up",
      schoolCount: 11,
      cluster: "Gulu Municipality",
      district: "Gulu",
      weakestIntervention: "Enrollment",
      reason: "Enrollment dropping in 11 schools (avg -4% term-over-term). Northern Education Trust covers Gulu and has the partner experience.",
      recommendedPartner: partnerCoverageRows[4],
      alternativePartners: [partnerCoverageRows[6]],
    },
  ];
}

// ────────── Daily planning validation ──────────

export type DailyValidationResult = {
  date:              string;
  schoolVisitCount:  number;
  groupTrainingCount:number;
  warnings:          Array<{ kind: "Daily Visit Minimum Not Met" | "Group Training Conflict"; message: string }>;
};

export function validateDailyPlan(
  date: string,
  schoolVisits: number,
  groupTrainings: number,
): DailyValidationResult {
  const warnings: DailyValidationResult["warnings"] = [];
  if (schoolVisits < MIN_DAILY_VISITS) {
    warnings.push({
      kind: "Daily Visit Minimum Not Met",
      message: `This day has only ${schoolVisits} school visit${schoolVisits === 1 ? "" : "s"} planned. The minimum expected daily visit load is ${MIN_DAILY_VISITS}. Add ${MIN_DAILY_VISITS - schoolVisits} nearby school${MIN_DAILY_VISITS - schoolVisits === 1 ? "" : "s"} or provide a valid planning reason.`,
    });
  }
  if (groupTrainings > MAX_DAILY_GROUP_TRAININGS) {
    warnings.push({
      kind: "Group Training Conflict",
      message: `You planned ${groupTrainings} group trainings on the same day. Group training is limited to ${MAX_DAILY_GROUP_TRAININGS} per day because of preparation, facilitation, travel, participant management, and quality assurance.`,
    });
  }
  return { date, schoolVisitCount: schoolVisits, groupTrainingCount: groupTrainings, warnings };
}

// ────────── FY scope ──────────

export const COVERAGE_FY = FY;
