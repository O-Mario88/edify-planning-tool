// New schools joined through a cluster — acquisition-source tracking.
//
// A school is "joined through cluster" when it was acquired via cluster
// onboarding / referral / a cluster meeting / SIT. Ownership stays with the
// account owner; if a partner facilitated the cluster, the school is
// partner-INFLUENCED, not partner-owned.

import { intakeSchools } from "@/lib/intake/intake-mock";
import { clusterById } from "./cluster-core";

export type ClusterJoinSourceType =
  | "cluster_onboarding"
  | "cluster_referral"
  | "cluster_meeting"
  | "sit";

export const JOIN_SOURCE_LABEL: Record<ClusterJoinSourceType, string> = {
  cluster_onboarding: "Cluster onboarding",
  cluster_referral: "Cluster referral",
  cluster_meeting: "Cluster meeting",
  sit: "SIT",
};

export type ClusterSchoolJoinSource = {
  id: string;
  schoolId: string;
  clusterId: string;
  sourceType: ClusterJoinSourceType;
  partnerInfluenced: boolean;
  joinedAt: string;
  addedBy: string;
};

export const clusterJoinSources: ClusterSchoolJoinSource[] = [];
let seq = 0;

export function markJoinedThroughCluster(
  schoolId: string,
  clusterId: string,
  sourceType: ClusterJoinSourceType,
  actor: { name: string; role: string },
): ClusterSchoolJoinSource | { error: string } {
  const cluster = clusterById(clusterId);
  if (!cluster) return { error: "Cluster not found." };
  // Supersede any prior source record for this school.
  for (let i = clusterJoinSources.length - 1; i >= 0; i--) {
    if (clusterJoinSources[i].schoolId === schoolId) clusterJoinSources.splice(i, 1);
  }
  seq += 1;
  const rec: ClusterSchoolJoinSource = {
    id: `CJS-${String(seq).padStart(4, "0")}`,
    schoolId,
    clusterId,
    sourceType,
    partnerInfluenced: !!cluster.managedByPartnerId,
    joinedAt: new Date().toISOString(),
    addedBy: actor.name,
  };
  clusterJoinSources.unshift(rec);
  return rec;
}

export function joinSourceFor(schoolId: string): ClusterSchoolJoinSource | undefined {
  return clusterJoinSources.find((j) => j.schoolId === schoolId);
}

export type ClusterAcquisitionMetrics = {
  schoolsJoined: number;
  clientJoined: number;
  coreJoined: number;
  learnersAdded: number;
  partnerInfluenced: number;
};

/** "New schools joined through cluster" roll-up for analytics/reports. */
export function clusterAcquisitionMetrics(): ClusterAcquisitionMetrics {
  let clientJoined = 0, coreJoined = 0, learnersAdded = 0, partnerInfluenced = 0;
  for (const j of clusterJoinSources) {
    const s = intakeSchools.find((x) => x.schoolId === j.schoolId);
    if (!s) continue;
    if (s.schoolType === "Core") coreJoined += 1;
    else if (s.schoolType === "Client") clientJoined += 1;
    learnersAdded += s.enrollment ?? 0;
    if (j.partnerInfluenced) partnerInfluenced += 1;
  }
  return { schoolsJoined: clusterJoinSources.length, clientJoined, coreJoined, learnersAdded, partnerInfluenced };
}
