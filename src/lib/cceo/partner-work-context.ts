// CCEO partner-work *context* — capacity + cluster gate the dashboard
// card uses to frame partner routing in the right narrative. Server-only
// because both engines read the action store + intake-mock that are
// server-side authoritative.
//
// Keeps `buildPartnerWork` (in partner-work.ts) pure / client-safe so
// the deeper /partners section can render inline without spilling
// server-only modules into the browser bundle.

import "server-only";

import type { EdifyRole } from "@/lib/auth-public";
import {
  computeStaffCapacity,
  type StaffCapacity,
} from "@/lib/planning/assignment-policy";
import { scopedClusterCounts } from "@/lib/cluster/cluster-scope";

export type CceoClusterGate = {
  unclustered: number;
  needsReview: number;
  clustered:   number;
};

export type PartnerWorkContext = {
  capacity:    StaffCapacity | null;
  clusterGate: CceoClusterGate | null;
};

export function buildPartnerWorkContext(user: {
  role:    EdifyRole;
  staffId?: string;
}): PartnerWorkContext {
  const scoped = (user.role === "CCEO" || user.role === "Admin") && !!user.staffId;
  if (!scoped) return { capacity: null, clusterGate: null };
  const capacity = computeStaffCapacity(user.staffId!);
  const c        = scopedClusterCounts(user.staffId!, user.role);
  return {
    capacity,
    clusterGate: { unclustered: c.unclustered, needsReview: c.needsReview, clustered: c.clustered },
  };
}
