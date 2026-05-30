// FWI mock layer.
//
// Seeds Portfolio Complexity inputs for the five staff defined in
// team-targets-mock.ts. In production these numbers come from joins
// on PortfolioComplexity (computed at FY-month boundaries by the
// cron in src/lib/performance/fwi-engine.ts). Here we hand-tune them
// to demonstrate every band on the Fair Matrix without needing live
// data.
//
// The mock is designed so the dashboard tells a real story:
//   • Grace Njeri   — heavy load, hitting 81% → True Top Performer
//   • James Otieno  — medium load, 62% pace   → Concern (output gap)
//   • Purity Muthoni — high load, 46% pace    → Overloaded (support)
//   • Abdi Hassan   — very high load, 33%     → Overloaded + early-warning
//   • Peter Mutua   — low load, 35% pace      → Concern (real coaching)
//
// Plus a sixth staff (Mary Auma) seeded as Hidden Leader: medium pace,
// high team-support score from coaching newer CCEOs.

import type {
  FairMatrixInput,
  RebalanceInput,
} from "./fwi-engine";
import { staffTargetPerformance } from "@/lib/team-targets-mock";

// ────────── Portfolio inputs by staffId ──────────
//
// Hand-tuned so the spread across the team produces distinct bands —
// makes the dashboard demonstrable without a database.

type Extra = {
  schoolCount: number;
  partnerSchoolCount: number;
  districtCount: number;
  secondaryDistrictCount: number;
  highRiskSchoolCount: number;
  avgSsaWeakness: number;
  avgDistanceKm: number;
  hotelTripsCount: number;
  totalTravelKm: number;
  partnersManaged: number;
  specialProjectsActive: number;
  /// 0-100 — coaching / mentoring contribution. Drives HiddenLeader.
  teamSupportScore: number;
  /// 0-100 — school-improvement signal. Drives BusyLowImpact.
  impactScore: number;
  /// True for first-90-days staff (treated as Establishing).
  isProbationary?: boolean;
  /// School roster (just enough to drive rebalance recommendations).
  schools: Array<{
    schoolId: string;
    schoolName: string;
    currentOwnerDistanceKm: number;
    distanceFromCandidates: Record<string, number>;
  }>;
};

const STAFF_EXTRA: Record<string, Extra> = {
  "STF-GN-007": {
    schoolCount: 38, partnerSchoolCount: 9, districtCount: 5,
    secondaryDistrictCount: 3, highRiskSchoolCount: 6,
    avgSsaWeakness: 5.5, avgDistanceKm: 78, hotelTripsCount: 4,
    totalTravelKm: 1240, partnersManaged: 3, specialProjectsActive: 1,
    teamSupportScore: 65, impactScore: 78,
    schools: [
      { schoolId: "S-GN-1", schoolName: "Bright Future PS",   currentOwnerDistanceKm: 80, distanceFromCandidates: { "STF-PM-052": 18 } },
      { schoolId: "S-GN-2", schoolName: "Hope Academy",       currentOwnerDistanceKm: 90, distanceFromCandidates: { "STF-PM-052": 22 } },
      { schoolId: "S-GN-3", schoolName: "Sunrise School",     currentOwnerDistanceKm: 60, distanceFromCandidates: { "STF-PM-052": 70 } },
      { schoolId: "S-GN-4", schoolName: "Kapchorwa Comm. PS", currentOwnerDistanceKm: 110, distanceFromCandidates: { "STF-PM-052": 35 } },
    ],
  },
  "STF-JO-022": {
    schoolCount: 24, partnerSchoolCount: 4, districtCount: 3,
    secondaryDistrictCount: 1, highRiskSchoolCount: 3,
    avgSsaWeakness: 4.5, avgDistanceKm: 38, hotelTripsCount: 1,
    totalTravelKm: 620, partnersManaged: 1, specialProjectsActive: 0,
    teamSupportScore: 35, impactScore: 55,
    schools: [
      { schoolId: "S-JO-1", schoolName: "Mukono Central PS",  currentOwnerDistanceKm: 30, distanceFromCandidates: { "STF-PM-052": 55 } },
      { schoolId: "S-JO-2", schoolName: "Mpigi Community PS", currentOwnerDistanceKm: 42, distanceFromCandidates: { "STF-PM-052": 60 } },
    ],
  },
  "STF-PM-031": {
    schoolCount: 41, partnerSchoolCount: 8, districtCount: 4,
    secondaryDistrictCount: 2, highRiskSchoolCount: 7,
    avgSsaWeakness: 6.5, avgDistanceKm: 92, hotelTripsCount: 5,
    totalTravelKm: 1480, partnersManaged: 2, specialProjectsActive: 1,
    teamSupportScore: 30, impactScore: 50,
    schools: [
      { schoolId: "S-PM-1", schoolName: "Fort Portal Central",  currentOwnerDistanceKm: 95, distanceFromCandidates: { "STF-PM-052": 88 } },
      { schoolId: "S-PM-2", schoolName: "Kasese Trading PS",    currentOwnerDistanceKm: 110, distanceFromCandidates: { "STF-PM-052": 102 } },
    ],
  },
  "STF-AH-044": {
    schoolCount: 47, partnerSchoolCount: 11, districtCount: 6,
    secondaryDistrictCount: 4, highRiskSchoolCount: 9,
    avgSsaWeakness: 7.5, avgDistanceKm: 145, hotelTripsCount: 8,
    totalTravelKm: 2240, partnersManaged: 4, specialProjectsActive: 2,
    teamSupportScore: 40, impactScore: 45,
    schools: [
      { schoolId: "S-AH-1", schoolName: "Kitgum Boarding PS",   currentOwnerDistanceKm: 160, distanceFromCandidates: { "STF-PM-052": 220 } },
      { schoolId: "S-AH-2", schoolName: "Gulu North Mixed PS",  currentOwnerDistanceKm: 145, distanceFromCandidates: { "STF-PM-052": 210 } },
    ],
  },
  "STF-PM-052": {
    schoolCount: 12, partnerSchoolCount: 1, districtCount: 1,
    secondaryDistrictCount: 0, highRiskSchoolCount: 1,
    avgSsaWeakness: 3.5, avgDistanceKm: 18, hotelTripsCount: 0,
    totalTravelKm: 180, partnersManaged: 0, specialProjectsActive: 0,
    teamSupportScore: 20, impactScore: 40,
    schools: [
      { schoolId: "S-PT-1", schoolName: "Mbale Central PS",     currentOwnerDistanceKm: 14, distanceFromCandidates: {} },
      { schoolId: "S-PT-2", schoolName: "Mbale Riverside PS",   currentOwnerDistanceKm: 22, distanceFromCandidates: {} },
    ],
  },
};

// ────────── Synthetic "Hidden Leader" staff ──────────
//
// Not in team-targets-mock yet — added here to demonstrate the band
// renders correctly. Production will join the real staff list.

const HIDDEN_LEADER_INPUT: FairMatrixInput = {
  staffId: "STF-MA-018",
  staffName: "Mary Auma",
  initials: "MA",
  rawPacePct: 82,
  complexityInputs: {
    staffId: "STF-MA-018",
    staffName: "Mary Auma",
    periodIso: "2026-05",
    schoolCount: 26, partnerSchoolCount: 5, districtCount: 3,
    secondaryDistrictCount: 1, highRiskSchoolCount: 4,
    avgSsaWeakness: 5.0, avgDistanceKm: 46, hotelTripsCount: 2,
    totalTravelKm: 740, partnersManaged: 1, specialProjectsActive: 1,
  },
  teamSupportScore: 88, // strong coaching contribution
  impactScore: 80,
};

// Demo CCEO — Paul Chinyama is the demo login for the CCEO role, so
// his /my-targets page needs an FWI entry for the workload callout
// to render. Tuned to "Carrying Heavy Load" so the demo shows the
// fairness adjustment in action (raw pace below 80, but heavy load
// boosts the adjusted pace and lands him in the Overloaded band).
const DEMO_CCEO_INPUT: FairMatrixInput = {
  staffId: "STF-PC-001",
  staffName: "Paul Chinyama",
  initials: "PC",
  rawPacePct: 78,
  complexityInputs: {
    staffId: "STF-PC-001",
    staffName: "Paul Chinyama",
    periodIso: "2026-05",
    schoolCount: 44, partnerSchoolCount: 10, districtCount: 5,
    secondaryDistrictCount: 3, highRiskSchoolCount: 8,
    avgSsaWeakness: 6.5, avgDistanceKm: 88, hotelTripsCount: 6,
    totalTravelKm: 1680, partnersManaged: 3, specialProjectsActive: 1,
  },
  teamSupportScore: 55,
  impactScore: 70,
};

// ────────── Adapter — StaffTargetRow → FairMatrixInput ──────────

export function fairMatrixInputsForTeam(): FairMatrixInput[] {
  const rows: FairMatrixInput[] = staffTargetPerformance.map((s) => {
    const extra = STAFF_EXTRA[s.staffId];
    if (!extra) {
      // Unknown staff — synthesize neutral inputs so the matrix
      // doesn't break in the demo. Production rejects missing
      // PortfolioComplexity rows instead.
      return {
        staffId: s.staffId,
        staffName: s.staffName,
        initials: s.initials,
        rawPacePct: s.achievementPercent,
        complexityInputs: {
          staffId: s.staffId,
          staffName: s.staffName,
          periodIso: "2026-05",
          schoolCount: 20, partnerSchoolCount: 0, districtCount: 2,
          secondaryDistrictCount: 0, highRiskSchoolCount: 1,
          avgSsaWeakness: 4, avgDistanceKm: 30, hotelTripsCount: 0,
          totalTravelKm: 0, partnersManaged: 0, specialProjectsActive: 0,
        },
      };
    }
    return {
      staffId: s.staffId,
      staffName: s.staffName,
      initials: s.initials,
      rawPacePct: s.achievementPercent,
      complexityInputs: {
        staffId: s.staffId,
        staffName: s.staffName,
        periodIso: "2026-05",
        schoolCount: extra.schoolCount,
        partnerSchoolCount: extra.partnerSchoolCount,
        districtCount: extra.districtCount,
        secondaryDistrictCount: extra.secondaryDistrictCount,
        highRiskSchoolCount: extra.highRiskSchoolCount,
        avgSsaWeakness: extra.avgSsaWeakness,
        avgDistanceKm: extra.avgDistanceKm,
        hotelTripsCount: extra.hotelTripsCount,
        totalTravelKm: extra.totalTravelKm,
        partnersManaged: extra.partnersManaged,
        specialProjectsActive: extra.specialProjectsActive,
      },
      teamSupportScore: extra.teamSupportScore,
      impactScore: extra.impactScore,
      isProbationary: extra.isProbationary,
    };
  });
  return [...rows, HIDDEN_LEADER_INPUT, DEMO_CCEO_INPUT];
}

// ────────── Rebalance inputs ──────────
//
// Maps the same staff into the shape the rebalance engine expects —
// complexityScore comes from buildFairMatrix at compute time, NOT
// from this seed.

export function rebalanceInputsForTeam(
  complexityScoresByStaffId: Record<string, number>,
): RebalanceInput[] {
  return Object.keys(STAFF_EXTRA).map((staffId) => {
    const extra = STAFF_EXTRA[staffId];
    const staff = staffTargetPerformance.find((s) => s.staffId === staffId);
    return {
      staffId,
      staffName: staff?.staffName ?? staffId,
      complexityScore: complexityScoresByStaffId[staffId] ?? 0,
      schools: extra.schools,
    };
  });
}

// ────────── Staff portfolio breakdown (for the profile card) ──────────
//
// Returns the by-factor breakdown the WorkloadContextCallout renders.
// Pure data lookup — no engine call.

export function portfolioContextForStaff(staffId: string): Extra | null {
  return STAFF_EXTRA[staffId] ?? null;
}
