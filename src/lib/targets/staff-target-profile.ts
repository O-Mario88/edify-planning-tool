// Per-staff target profiles. Phase 6 fleshes this out (assign + PL approval);
// for now it's the minimal contract the activation engine needs so the
// "target profile assigned" gate resolves. Pure & client-safe.

import type { EdifyRole } from "@/lib/auth";
import { fyTargetForRole } from "./role-targets";

export type StaffTargetProfile = {
  staffId: string;
  role: EdifyRole;
  fy: string;
  visitTarget: number;
  trainingTarget?: number;
  ssaTarget?: number;
  clusterMeetingTarget?: number;
  partnerMonitoringTarget?: number;
  approvedBy?: string;
  isActive: boolean;
};

// Runtime store of assigned profiles (empty until Phase 6 wires assignment).
const profiles: StaffTargetProfile[] = [];

export function addStaffTargetProfile(p: StaffTargetProfile): StaffTargetProfile {
  profiles.unshift(p);
  return p;
}

export function targetProfileFor(staffId: string): StaffTargetProfile | undefined {
  return profiles.find((p) => p.staffId === staffId && p.isActive);
}

/** True when a staff member has an active target profile (the final activation gate). */
export function hasTargetProfile(staffId: string): boolean {
  return !!targetProfileFor(staffId);
}

/** Role-default target profile (CCEO 560 / PL 280 FY visit target) — the
 *  starting point a Program Lead reviews + approves at onboarding. */
export function defaultTargetProfileFor(staffId: string, role: EdifyRole, fy: string): StaffTargetProfile {
  const visit = fyTargetForRole(role);
  return {
    staffId,
    role,
    fy,
    visitTarget: visit,
    trainingTarget: Math.round(visit * 0.15),
    ssaTarget: Math.round(visit * 0.5),
    clusterMeetingTarget: role === "CCEO" ? 12 : 8,
    partnerMonitoringTarget: role === "CCEO" ? 24 : 12,
    isActive: false,
  };
}
