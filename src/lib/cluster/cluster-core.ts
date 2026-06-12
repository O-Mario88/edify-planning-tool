// Cluster engine — the truth layer behind "every school belongs to a cluster".
//
// Core product rule (the second spine of the workflow, after ownership):
//   School Upload creates portfolio ownership.
//   CLUSTER ASSIGNMENT creates planning structure.
//   SSA creates support intelligence.
//   Planning creates execution.
//
// After a school is uploaded and mapped to an account owner, the next required
// setup action is assigning it to a cluster. Until then the school is
// `unclustered` and full support planning is blocked (cluster-first gate):
// clusters drive SIT, SSA, cluster meetings, travel, partner assignment, and
// donor/district reporting, so nothing downstream is meaningful without one.
//
// Mutable in-memory store (mock mode persists for the running server session;
// Year-2 swaps for Prisma writes). Pure & client-safe so the Cluster Assignment
// Workspace, the Unclustered Schools queue, dashboards, and analytics all
// compute from the same numbers.

import {
  intakeSchools,
  ssaUploads,
  type IntakeSchool,
} from "@/lib/intake/intake-mock";
import { SSA_INTERVENTION_AREAS } from "@/lib/intake/intake-core";
import {
  districtByName,
  regionIdFor,
  regionForDistrict,
  subCountiesOf,
} from "@/lib/geography";

// ── Types ──────────────────────────────────────────────────────────

export type ClusterStatus = NonNullable<IntakeSchool["clusterStatus"]>;
export type AssignmentSource =
  | "upload"
  | "staff_assignment"
  | "ia_correction"
  | "reassignment";

export type ClusterRecord = {
  id: string;
  name: string;
  /** Canonical region id (via geography). */
  regionId?: string;
  /** Display region name as entered. */
  region?: string;
  /** Canonical district id (UG-D-*). */
  districtId?: string;
  /** Display district name (the operational key). */
  district: string;
  /** Primary sub-county (= subCounties[0]) — kept for matching/recommendation. */
  subCounty?: string;
  /** All sub-counties this cluster covers (a cluster may span several). */
  subCounties: string[];
  parish?: string;
  /** Cluster leader — a school leader from one of the cluster's schools. */
  clusterLeaderName?: string;
  clusterLeaderPhone?: string;
  /** School the cluster leader leads (for traceability). */
  clusterLeaderSchoolId?: string;
  /** Partner this cluster is delegated to manage (staff stays the owner). */
  managedByPartnerId?: string;
  managedByPartnerName?: string;
  meetingLocation?: string;
  notes?: string;
  expectedSchools?: number;
  createdBy: string;
  createdByRole: string;
  createdAt: string;
  isActive: boolean;
};

export type SchoolClusterAssignment = {
  id: string;
  schoolId: string;
  clusterId: string;
  assignedBy: string;
  assignedByRole: string;
  assignmentSource: AssignmentSource;
  assignedAt: string;
  isActive: boolean;
  endedAt?: string;
  reason?: string;
};

export type ClusterAuditAction =
  | "cluster_created"
  | "school_assigned"
  | "school_removed"
  | "school_reassigned"
  | "ia_corrected"
  | "duplicate_assigned"
  | "partner_assigned"
  | "leader_changed"
  | "meeting_scheduled"
  | "cluster_archived";

export type ClusterAuditEntry = {
  id: string;
  action: ClusterAuditAction;
  user: string;
  role: string;
  timestamp: string;
  schoolId?: string;
  oldClusterId?: string;
  newClusterId?: string;
  reason?: string;
  district?: string;
  subCounty?: string;
};

/** Who performed a cluster action — threaded through for the audit trail. */
export type ClusterActor = { name: string; role: string };

// ── Stores ─────────────────────────────────────────────────────────

let clusterSeq = 100;
function nextClusterId(district: string): string {
  clusterSeq += 1;
  const d = districtByName(district);
  const slug = d ? d.slug : district.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return `CLU-${slug}-${clusterSeq}`;
}

let assignmentSeq = 0;
function nextAssignmentId(): string {
  assignmentSeq += 1;
  return `SCA-${String(assignmentSeq).padStart(4, "0")}`;
}

let auditSeq = 0;
function nextAuditId(): string {
  auditSeq += 1;
  return `CAUD-${String(auditSeq).padStart(4, "0")}`;
}

// Seed clusters so the Workspace isn't empty on first load and the demo shows
// both clustered + unclustered states. Seed schools (intake-mock) all start
// unclustered — that is the point: assigning them is the next action.
export const clusters: ClusterRecord[] = [
  {
    id: "CLU-mukono-001",
    name: "Mukono Central Cluster",
    region: "Central Region",
    districtId: districtByName("Mukono")?.id,
    regionId: regionIdFor("Mukono"),
    district: "Mukono",
    subCounty: "Mukono Central",
    subCounties: ["Mukono Central"],
    clusterLeaderName: "Esther Naluwu",
    clusterLeaderPhone: "+256 772 100 200",
    expectedSchools: 6,
    createdBy: "Paul Chinyama",
    createdByRole: "CCEO",
    createdAt: "2026-04-02",
    isActive: true,
  },
  {
    id: "CLU-nakaseke-001",
    name: "Nakaseke TC Cluster",
    region: "Central Region",
    districtId: districtByName("Nakaseke")?.id,
    regionId: regionIdFor("Nakaseke"),
    district: "Nakaseke",
    subCounty: "Nakaseke TC",
    subCounties: ["Nakaseke TC"],
    clusterLeaderName: "John Mubiru",
    clusterLeaderPhone: "+256 701 555 110",
    expectedSchools: 5,
    createdBy: "Paul Chinyama",
    createdByRole: "CCEO",
    createdAt: "2026-04-09",
    isActive: true,
    // Delegated to a partner so the partner dashboard + partner payment path
    // have a live cluster to operate on.
    managedByPartnerId: "P-LIT",
    managedByPartnerName: "Literacy Training Uganda",
  },
];

export const clusterAssignments: SchoolClusterAssignment[] = [];
export const clusterAudit: ClusterAuditEntry[] = [];

// ── Cluster meetings (scheduled by the partner OR by Edify staff) ──
export type ClusterMeetingKind =
  | "first_meeting"
  | "second_meeting"
  | "third_meeting"
  | "follow_up"
  | "sit"
  | "training";

export const CLUSTER_MEETING_LABEL: Record<ClusterMeetingKind, string> = {
  first_meeting: "1st Cluster Meeting",
  second_meeting: "2nd Cluster Meeting",
  third_meeting: "3rd Cluster Meeting",
  follow_up: "Follow-up Cluster Meeting",
  sit: "School Improvement Training",
  training: "Cluster Training",
};

/** The meeting that auto-schedules after this one completes (null = end of cycle). */
export function nextMeetingKind(kind: ClusterMeetingKind): ClusterMeetingKind | null {
  switch (kind) {
    case "first_meeting": return "second_meeting";
    case "second_meeting": return "third_meeting";
    case "third_meeting": return "follow_up";
    case "follow_up": return "follow_up";
    default: return null; // sit / training don't chain
  }
}

/** Who organises the meeting: the delegated partner, or Edify (staff). */
export type ClusterMeetingOrganizer = "partner" | "edify";

/**
 * Cluster-activity lifecycle. A meeting/training only COUNTS once IA has
 * confirmed its Salesforce training record; partner payment only clears after
 * that. Scheduled → Awaiting IA (Salesforce TS- + attendance entered) →
 * IA Confirmed → Paid. Returned is a correction loop.
 */
export type ClusterActivityStatus =
  | "Scheduled"
  | "Awaiting IA"
  | "IA Confirmed"
  | "Paid"      // partner payment cleared
  | "Closed"    // staff Netsuite accountability recorded
  | "Returned";

export type ClusterMeeting = {
  id: string;
  clusterId: string;
  kind: ClusterMeetingKind;
  date: string; // ISO date
  organizer: ClusterMeetingOrganizer;
  scheduledBy: string;
  scheduledByRole: string;
  participants?: number;
  notes?: string;
  createdAt: string;
  // ── Lifecycle ──
  status: ClusterActivityStatus;
  /** Salesforce training record id — must be TS-#####. */
  salesforceTrainingId?: string;
  teachersCount?: number;
  schoolLeadersCount?: number;
  otherCount?: number;
  totalParticipants?: number;
  evidenceUploaded?: boolean;
  iaConfirmedAt?: string;
  iaConfirmedBy?: string;
  accountantPaidAt?: string;
  /** Staff path: Netsuite accountability. */
  netsuiteExpenseId?: string;
  accountabilityClosedAt?: string;
  returnedReason?: string;
  // ── Completion record ──
  actualDate?: string;
  completedBy?: string;
  completedAt?: string;
  attendanceFileName?: string;
  minutesText?: string;
  minutesFileName?: string;
  resolutionsText?: string;
  resolutionsFileName?: string;
  nextMeetingDate?: string;
  nextActivityId?: string;
  linkedPreviousMeetingId?: string;
};

/** Salesforce training ids must be TS-#### (cluster meetings/trainings). */
export function isValidTsId(id: string | undefined | null): boolean {
  return !!id && /^TS-\d{3,}$/i.test(id.trim());
}

// Demo seed — representative cluster activities across the lifecycle so the
// role-gated surfaces (IA confirmation queue, accountant partner payments +
// staff Netsuite accountability, partner dashboard, role-dashboard cluster
// cards) all render real data. Replaced by Salesforce/DB reads in year 2.
export const clusterMeetings: ClusterMeeting[] = [
  {
    // Staff-organised training, completed → awaiting IA confirmation.
    id: "CMT-S001",
    clusterId: "CLU-mukono-001",
    kind: "training",
    date: "2026-05-20",
    organizer: "edify",
    scheduledBy: "Paul Chinyama",
    scheduledByRole: "CCEO",
    participants: 30,
    createdAt: "2026-05-10",
    status: "Awaiting IA",
    salesforceTrainingId: "TS-50121",
    teachersCount: 22,
    schoolLeadersCount: 6,
    otherCount: 2,
    totalParticipants: 30,
    evidenceUploaded: true,
    actualDate: "2026-05-20",
    completedBy: "Paul Chinyama",
    completedAt: "2026-05-20",
    attendanceFileName: "mukono-training-attendance.pdf",
    minutesText:
      "Reviewed term-2 literacy results across the cluster; agreed a shared lesson-observation rubric for all 6 schools.",
    minutesFileName: "mukono-training-minutes.pdf",
    resolutionsText:
      "1) Every school runs weekly paired reading. 2) Next cluster activity hosts a joint School Improvement Training.",
    resolutionsFileName: "mukono-training-resolutions.pdf",
    nextMeetingDate: "2026-06-24",
  },
  {
    // Partner-organised 1st cluster meeting, IA-confirmed → awaiting finance.
    id: "CMT-S002",
    clusterId: "CLU-nakaseke-001",
    kind: "first_meeting",
    date: "2026-05-12",
    organizer: "partner",
    scheduledBy: "Sarah Kanyi",
    scheduledByRole: "PartnerAdmin",
    participants: 28,
    createdAt: "2026-05-02",
    status: "IA Confirmed",
    salesforceTrainingId: "TS-50088",
    teachersCount: 20,
    schoolLeadersCount: 5,
    otherCount: 3,
    totalParticipants: 28,
    evidenceUploaded: true,
    actualDate: "2026-05-12",
    completedBy: "Sarah Kanyi",
    completedAt: "2026-05-12",
    attendanceFileName: "nakaseke-m1-attendance.pdf",
    minutesText:
      "Introduced the cluster, mapped member schools and set the term meeting calendar.",
    minutesFileName: "nakaseke-m1-minutes.pdf",
    resolutionsText:
      "1) Confirm cluster leader contact list. 2) Each school nominates a literacy lead before the 2nd meeting.",
    resolutionsFileName: "nakaseke-m1-resolutions.pdf",
    iaConfirmedAt: "2026-05-15",
    iaConfirmedBy: "Grace Alimo",
    nextMeetingDate: "2026-06-16",
  },
  {
    // Staff-organised 2nd cluster meeting, IA-confirmed → awaiting Netsuite
    // accountability (the staff finance-close path).
    id: "CMT-S003",
    clusterId: "CLU-mukono-001",
    kind: "second_meeting",
    date: "2026-04-28",
    organizer: "edify",
    scheduledBy: "Paul Chinyama",
    scheduledByRole: "CCEO",
    participants: 26,
    createdAt: "2026-04-18",
    status: "IA Confirmed",
    salesforceTrainingId: "TS-49977",
    teachersCount: 18,
    schoolLeadersCount: 6,
    otherCount: 2,
    totalParticipants: 26,
    evidenceUploaded: true,
    actualDate: "2026-04-28",
    completedBy: "Paul Chinyama",
    completedAt: "2026-04-28",
    attendanceFileName: "mukono-m2-attendance.pdf",
    minutesText:
      "Shared classroom-observation findings; agreed remediation focus for struggling readers.",
    minutesFileName: "mukono-m2-minutes.pdf",
    resolutionsText:
      "1) Run a cluster-wide reading assessment. 2) Pair strong and weak schools for peer support.",
    resolutionsFileName: "mukono-m2-resolutions.pdf",
    iaConfirmedAt: "2026-05-02",
    iaConfirmedBy: "Grace Alimo",
    nextMeetingDate: "2026-05-26",
  },
];
let meetingSeq = 0;
function nextMeetingId(): string {
  meetingSeq += 1;
  return `CMT-${String(meetingSeq).padStart(4, "0")}`;
}

function logAudit(entry: Omit<ClusterAuditEntry, "id" | "timestamp">): void {
  clusterAudit.unshift({
    ...entry,
    id: nextAuditId(),
    timestamp: new Date().toISOString(),
  });
}

// ── Lookups ────────────────────────────────────────────────────────

export function clusterById(id: string | undefined | null): ClusterRecord | undefined {
  if (!id) return undefined;
  return clusters.find((c) => c.id === id);
}

export function activeClusters(): ClusterRecord[] {
  return clusters.filter((c) => c.isActive);
}

/** Active clusters in a district, sub-county matches first (assignment UX). */
export function clustersForLocation(district: string, subCounty?: string): ClusterRecord[] {
  const inDistrict = activeClusters().filter(
    (c) => c.district.toLowerCase() === district.trim().toLowerCase(),
  );
  if (!subCounty) return inDistrict;
  const sc = subCounty.trim().toLowerCase();
  const covers = (c: ClusterRecord) => (c.subCounties ?? []).some((s) => s.toLowerCase() === sc);
  return [...inDistrict].sort((a, b) => (covers(a) ? 0 : 1) - (covers(b) ? 0 : 1));
}

export function schoolsInCluster(clusterId: string): IntakeSchool[] {
  return intakeSchools.filter((s) => s.clusterId === clusterId);
}

export function clusterStatusOf(s: IntakeSchool): ClusterStatus {
  if (s.clusterStatus) return s.clusterStatus;
  return s.clusterId ? "clustered" : "unclustered";
}

/**
 * Scheduled (non-terminal) cluster meetings attributed to a staff member by name.
 * Used by My Plan to surface cluster activities alongside school activities.
 */
export function clusterMeetingsForStaff(staffName: string): ClusterMeeting[] {
  const TERMINAL: ClusterActivityStatus[] = ["IA Confirmed", "Paid", "Closed"];
  return clusterMeetings.filter(
    (m) =>
      !TERMINAL.includes(m.status) &&
      (m.scheduledBy === staffName || m.scheduledBy.startsWith(staffName.split(" ")[0])),
  );
}

/** Schools that still need a cluster — the Unclustered Schools queue. */
export function unclusteredSchools(): IntakeSchool[] {
  return intakeSchools.filter((s) => clusterStatusOf(s) === "unclustered");
}

/** Schools an IA flagged as wrongly/inconsistently clustered. */
export function needsReviewSchools(): IntakeSchool[] {
  return intakeSchools.filter((s) => clusterStatusOf(s) === "needs_review");
}

// ── Cluster creation ───────────────────────────────────────────────

export type NewClusterInput = {
  name: string;
  region?: string;
  district: string;
  /** One or more sub-counties the cluster covers (≥1 required). */
  subCounties: string[];
  parish?: string;
  /** Cluster leader — a school leader from one of the cluster's schools. */
  clusterLeaderName?: string;
  clusterLeaderPhone?: string;
  clusterLeaderSchoolId?: string;
  meetingLocation?: string;
  notes?: string;
  expectedSchools?: number;
};

export type ClusterValidation = { ok: boolean; errors: Record<string, string>; warning?: string };

/**
 * Validate a new cluster. Requires a district + at least one sub-county; name
 * must be unique within the district (an exact match is a hard error, which
 * admin/IA may override via `allowDuplicate`).
 */
export function validateNewCluster(
  input: NewClusterInput,
  opts: { allowDuplicate?: boolean } = {},
): ClusterValidation {
  const errors: Record<string, string> = {};
  if (!input.name?.trim()) errors.name = "Cluster name is required.";
  if (!input.district?.trim()) errors.district = "District is required.";
  if (!input.subCounties || input.subCounties.filter((s) => s?.trim()).length === 0) {
    errors.subCounties = "Select at least one sub-county.";
  }

  if (input.name && input.district) {
    const dup = activeClusters().find(
      (c) =>
        c.name.trim().toLowerCase() === input.name.trim().toLowerCase() &&
        c.district.trim().toLowerCase() === input.district.trim().toLowerCase(),
    );
    if (dup && !opts.allowDuplicate) {
      errors.name = "A cluster with this name already exists in this district.";
    }
  }
  return { ok: Object.keys(errors).length === 0, errors };
}

export function createCluster(input: NewClusterInput, actor: ClusterActor): ClusterRecord {
  const district = input.district.trim();
  const subCounties = (input.subCounties ?? []).map((s) => s.trim()).filter(Boolean);
  const rec: ClusterRecord = {
    id: nextClusterId(district),
    name: input.name.trim(),
    region: input.region?.trim() || regionForDistrict(district),
    regionId: regionIdFor(district),
    districtId: districtByName(district)?.id,
    district,
    subCounty: subCounties[0],
    subCounties,
    parish: input.parish?.trim() || undefined,
    clusterLeaderName: input.clusterLeaderName?.trim() || undefined,
    clusterLeaderPhone: input.clusterLeaderPhone?.trim() || undefined,
    clusterLeaderSchoolId: input.clusterLeaderSchoolId || undefined,
    meetingLocation: input.meetingLocation?.trim() || undefined,
    notes: input.notes?.trim() || undefined,
    expectedSchools: input.expectedSchools,
    createdBy: actor.name,
    createdByRole: actor.role,
    createdAt: new Date().toISOString(),
    isActive: true,
  };
  clusters.unshift(rec);
  logAudit({
    action: "cluster_created",
    user: actor.name,
    role: actor.role,
    newClusterId: rec.id,
    district: rec.district,
    subCounty: rec.subCounty,
  });
  return rec;
}

// ── Assignment ─────────────────────────────────────────────────────

export type AssignResult =
  | { ok: true; school: IntakeSchool }
  | { ok: false; reason: string };

/**
 * Assign one school to a cluster. Deactivates any prior active assignment,
 * writes a SchoolClusterAssignment, syncs the school's clusterId / name /
 * status, and logs the audit trail. The school stays in its account owner's
 * portfolio — clustering never changes ownership.
 */
export function assignSchoolToCluster(
  schoolId: string,
  clusterId: string,
  actor: ClusterActor,
  source: AssignmentSource = "staff_assignment",
  reason?: string,
): AssignResult {
  const school = intakeSchools.find((s) => s.schoolId === schoolId);
  if (!school) return { ok: false, reason: "School not found." };
  const cluster = clusterById(clusterId);
  if (!cluster || !cluster.isActive) return { ok: false, reason: "Cluster not found." };

  // Cross-district guard — a cluster is a district/sub-county structure.
  if (cluster.district.toLowerCase() !== school.district.trim().toLowerCase()) {
    return {
      ok: false,
      reason: `${school.schoolName} is in ${school.district}, but ${cluster.name} is a ${cluster.district} cluster.`,
    };
  }

  const prevClusterId = school.clusterId;
  const reassigning = !!prevClusterId && prevClusterId !== clusterId;

  // Close the previous active assignment.
  for (const a of clusterAssignments) {
    if (a.schoolId === schoolId && a.isActive) {
      a.isActive = false;
      a.endedAt = new Date().toISOString();
    }
  }

  clusterAssignments.unshift({
    id: nextAssignmentId(),
    schoolId,
    clusterId,
    assignedBy: actor.name,
    assignedByRole: actor.role,
    assignmentSource: reassigning ? "reassignment" : source,
    assignedAt: new Date().toISOString(),
    isActive: true,
    reason,
  });

  school.clusterId = clusterId;
  school.cluster = cluster.name;
  school.clusterStatus = "clustered";

  logAudit({
    action: source === "ia_correction" ? "ia_corrected" : reassigning ? "school_reassigned" : "school_assigned",
    user: actor.name,
    role: actor.role,
    schoolId,
    oldClusterId: prevClusterId,
    newClusterId: clusterId,
    reason,
    district: school.district,
    subCounty: school.subCounty,
  });
  return { ok: true, school };
}

export type BulkAssignResult = {
  assigned: string[];
  failed: { schoolId: string; reason: string }[];
};

/** Assign many schools to one existing cluster. */
export function bulkAssign(
  schoolIds: string[],
  clusterId: string,
  actor: ClusterActor,
  source: AssignmentSource = "staff_assignment",
): BulkAssignResult {
  const assigned: string[] = [];
  const failed: { schoolId: string; reason: string }[] = [];
  for (const id of schoolIds) {
    const r = assignSchoolToCluster(id, clusterId, actor, source);
    if (r.ok) assigned.push(id);
    else failed.push({ schoolId: id, reason: r.reason });
  }
  return { assigned, failed };
}

export type CreateAndAssignResult =
  | { ok: true; cluster: ClusterRecord; result: BulkAssignResult }
  | { ok: false; reason: string };

/**
 * Create a new cluster and assign the selected schools. Blocks when the
 * selection spans multiple districts (a cluster is single-district);
 * geography is auto-derived from the selection.
 */
export function createClusterAndAssign(
  schoolIds: string[],
  input: Partial<NewClusterInput> & { name: string },
  actor: ClusterActor,
): CreateAndAssignResult {
  const schools = intakeSchools.filter((s) => schoolIds.includes(s.schoolId));
  if (schools.length === 0) return { ok: false, reason: "Select at least one school." };

  const districts = new Set(schools.map((s) => s.district.trim()));
  if (districts.size > 1) {
    return {
      ok: false,
      reason: "Selected schools belong to different districts. Create separate clusters.",
    };
  }
  const district = input.district ?? [...districts][0];
  const region = input.region ?? schools[0].region;
  // Cover every sub-county the selected schools sit in (a cluster may span
  // several), unless the caller passed an explicit set.
  const derivedSubCounties = [...new Set(schools.map((s) => s.subCounty).filter(Boolean) as string[])];
  const subCounties = input.subCounties && input.subCounties.length > 0 ? input.subCounties : derivedSubCounties;

  const cluster = createCluster(
    {
      name: input.name,
      region,
      district,
      subCounties,
      parish: input.parish,
      clusterLeaderName: input.clusterLeaderName,
      clusterLeaderPhone: input.clusterLeaderPhone,
      clusterLeaderSchoolId: input.clusterLeaderSchoolId,
      meetingLocation: input.meetingLocation,
      notes: input.notes,
      expectedSchools: input.expectedSchools ?? schools.length,
    },
    actor,
  );
  const result = bulkAssign(schoolIds, cluster.id, actor);
  return { ok: true, cluster, result };
}

/** Remove a school from its cluster (correction path). */
export function removeFromCluster(
  schoolId: string,
  actor: ClusterActor,
  reason?: string,
): AssignResult {
  const school = intakeSchools.find((s) => s.schoolId === schoolId);
  if (!school) return { ok: false, reason: "School not found." };
  const prev = school.clusterId;
  for (const a of clusterAssignments) {
    if (a.schoolId === schoolId && a.isActive) {
      a.isActive = false;
      a.endedAt = new Date().toISOString();
      a.reason = reason ?? a.reason;
    }
  }
  school.clusterId = undefined;
  school.cluster = undefined;
  school.clusterStatus = "unclustered";
  logAudit({
    action: "school_removed",
    user: actor.name,
    role: actor.role,
    schoolId,
    oldClusterId: prev,
    reason,
    district: school.district,
    subCounty: school.subCounty,
  });
  return { ok: true, school };
}

/** IA: flag a school's cluster as wrong/inconsistent for review. */
export function flagClusterForReview(schoolId: string, actor: ClusterActor, reason?: string): AssignResult {
  const school = intakeSchools.find((s) => s.schoolId === schoolId);
  if (!school) return { ok: false, reason: "School not found." };
  school.clusterStatus = "needs_review";
  logAudit({
    action: "ia_corrected",
    user: actor.name,
    role: actor.role,
    schoolId,
    oldClusterId: school.clusterId,
    reason: reason ?? "Flagged for cluster review",
    district: school.district,
    subCounty: school.subCounty,
  });
  return { ok: true, school };
}

// ── Smart recommendation ───────────────────────────────────────────

export type ClusterRecommendation =
  | { kind: "existing"; cluster: ClusterRecord; reason: string }
  | { kind: "create"; reason: string };

/**
 * Recommend a cluster for an unclustered school from geography + capacity:
 * prefer an existing cluster in the same sub-county, then same district; if
 * none is suitable, recommend creating a new one.
 */
export function recommendClusterFor(school: IntakeSchool): ClusterRecommendation {
  const candidates = clustersForLocation(school.district, school.subCounty);
  const sc = school.subCounty?.trim().toLowerCase();
  const sameSub = candidates.find(
    (c) => sc && (c.subCounties ?? []).some((s) => s.toLowerCase() === sc),
  );
  if (sameSub) {
    const n = schoolsInCluster(sameSub.id).length;
    return {
      kind: "existing",
      cluster: sameSub,
      reason: `${sameSub.name} covers ${school.subCounty}${n ? ` and already has ${n} school${n === 1 ? "" : "s"}` : ""}.`,
    };
  }
  if (candidates.length > 0) {
    const c = candidates[0];
    return {
      kind: "existing",
      cluster: c,
      reason: `${c.name} is in the same district (${school.district}).`,
    };
  }
  return {
    kind: "create",
    reason: `No cluster exists yet for ${school.subCounty ?? school.district}. Create one.`,
  };
}

// ── Grouped recommendations (Schools Directory "Add to Cluster") ───

export type ClusterMatchTier = "strong" | "district" | "region";

export type ClusterMatch = {
  cluster: ClusterRecord;
  schoolCount: number;
  ssaRate: number; // % of cluster schools with SSA done (0 when empty)
  tier: ClusterMatchTier;
};

export type GroupedClusterMatches = {
  /** Same district AND same sub-county — the primary recommendation. */
  strong: ClusterMatch[];
  /** Same district (different/any sub-county). */
  district: ClusterMatch[];
  /** Same region, different district — fallback (override only). */
  region: ClusterMatch[];
};

function toMatch(cluster: ClusterRecord, tier: ClusterMatchTier): ClusterMatch {
  const schools = schoolsInCluster(cluster.id);
  const done = schools.filter((s) => s.ssaStatus === "SSA Done").length;
  return {
    cluster,
    schoolCount: schools.length,
    ssaRate: schools.length ? Math.round((done / schools.length) * 100) : 0,
    tier,
  };
}

/**
 * Geography-ranked cluster matches for a school: strong (same district + sub-
 * county) → district → region fallback. Powers the directory "Add to Cluster"
 * drawer. Never returns clusters outside the school's region.
 */
export function recommendClustersFor(school: IntakeSchool): GroupedClusterMatches {
  const district = school.district.trim().toLowerCase();
  const sc = school.subCounty?.trim().toLowerCase();
  const schoolRegionId = regionIdFor(school.district);

  const strong: ClusterMatch[] = [];
  const district2: ClusterMatch[] = [];
  const region: ClusterMatch[] = [];

  for (const c of activeClusters()) {
    const sameDistrict = c.district.trim().toLowerCase() === district;
    if (sameDistrict) {
      const sameSub = !!sc && (c.subCounties ?? []).some((s) => s.toLowerCase() === sc);
      if (sameSub) strong.push(toMatch(c, "strong"));
      else district2.push(toMatch(c, "district"));
    } else if (schoolRegionId && c.regionId === schoolRegionId) {
      region.push(toMatch(c, "region"));
    }
  }
  return { strong, district: district2, region };
}

// ── Cluster-first planning gate ────────────────────────────────────

export type GateAction =
  | "view_school"
  | "view_duplicate"
  | "edit_geography"
  | "assign_existing_cluster"
  | "create_cluster"
  | "schedule_sit"
  | "complete_ssa"
  | "schedule_visit"
  | "schedule_training"
  | "assign_partner"
  | "add_to_my_plan"
  | "generate_budget";

export type GateDecision = {
  /** Overall readiness state for the school. */
  state: "UNCLUSTERED" | "CLUSTER_REVIEW" | "SSA_REQUIRED" | "PLANNING_READY";
  allowed: GateAction[];
  blocked: GateAction[];
  /** Human-readable reason the gate is limiting planning (when it is). */
  reason?: string;
};

const ALL_ACTIONS: GateAction[] = [
  "view_school",
  "view_duplicate",
  "edit_geography",
  "assign_existing_cluster",
  "create_cluster",
  "schedule_sit",
  "complete_ssa",
  "schedule_visit",
  "schedule_training",
  "assign_partner",
  "add_to_my_plan",
  "generate_budget",
];

/**
 * The mandatory Cluster Assignment Gate (cluster-first rule).
 *
 *   No cluster   → only view / edit-geography / assign-or-create cluster.
 *   Clustered    → SIT + SSA unlock (cluster-based), full planning still
 *                  locked until current-FY SSA is complete.
 *   SSA complete → full planning ready.
 *
 * Clustering never removes a school from its owner's portfolio.
 */
export function clusterGateFor(school: IntakeSchool): GateDecision {
  const status = clusterStatusOf(school);
  const setupActions: GateAction[] = ["view_school", "view_duplicate", "edit_geography"];

  if (status !== "clustered") {
    const allowed: GateAction[] = [...setupActions, "assign_existing_cluster", "create_cluster"];
    return {
      state: status === "needs_review" ? "CLUSTER_REVIEW" : "UNCLUSTERED",
      allowed,
      blocked: ALL_ACTIONS.filter((a) => !allowed.includes(a)),
      reason:
        status === "needs_review"
          ? "IA flagged this cluster assignment for review — resolve it before planning."
          : "No cluster yet. Assign this school to a cluster before planning support.",
    };
  }

  // Clustered — SSA/SIT unlock; everything else waits for current-FY SSA.
  if (school.ssaStatus !== "SSA Done") {
    const allowed: GateAction[] = [...setupActions, "schedule_sit", "complete_ssa"];
    return {
      state: "SSA_REQUIRED",
      allowed,
      blocked: ALL_ACTIONS.filter((a) => !allowed.includes(a)),
      reason: "Clustered. Complete the current-FY SSA (via SIT, partner, or yourself) to unlock full planning.",
    };
  }

  return { state: "PLANNING_READY", allowed: [...ALL_ACTIONS], blocked: [] };
}

// ── Portfolio cluster counts ───────────────────────────────────────

export type ClusterCounts = {
  clustered: number;
  unclustered: number;
  needsReview: number;
};

export function clusterCountsFor(schools: IntakeSchool[]): ClusterCounts {
  let clustered = 0, unclustered = 0, needsReview = 0;
  for (const s of schools) {
    const st = clusterStatusOf(s);
    if (st === "clustered") clustered += 1;
    else if (st === "needs_review") needsReview += 1;
    else unclustered += 1;
  }
  return { clustered, unclustered, needsReview };
}

// ── Analytics ──────────────────────────────────────────────────────

export type ClusterAnalytics = {
  totalClusters: number;
  schoolsClustered: number;
  schoolsUnclustered: number;
  coreClustered: number;
  clientClustered: number;
  avgSchoolsPerCluster: number;
};

export function clusterAnalytics(): ClusterAnalytics {
  const active = activeClusters();
  const counts = clusterCountsFor(intakeSchools);
  let coreClustered = 0, clientClustered = 0;
  for (const s of intakeSchools) {
    if (clusterStatusOf(s) !== "clustered") continue;
    if (s.schoolType === "Core") coreClustered += 1;
    else if (s.schoolType === "Client") clientClustered += 1;
  }
  return {
    totalClusters: active.length,
    schoolsClustered: counts.clustered,
    schoolsUnclustered: counts.unclustered,
    coreClustered,
    clientClustered,
    avgSchoolsPerCluster: active.length
      ? Math.round((counts.clustered / active.length) * 10) / 10
      : 0,
  };
}

// ── Cluster SSA intervention heatmap ───────────────────────────────

export type ClusterSsaHeatmapRow = {
  clusterId: string;
  clusterName: string;
  district: string;
  schoolsWithSsa: number;
  /** Average score per intervention (same order as `interventions`); null if no data. */
  cells: (number | null)[];
};
export type ClusterSsaHeatmap = {
  interventions: string[];
  rows: ClusterSsaHeatmapRow[];
};

function latestSsaUploadFor(schoolId: string) {
  return ssaUploads
    .filter((u) => u.schoolId === schoolId)
    .sort((a, b) => b.ssaDate.localeCompare(a.ssaDate))[0];
}

/** SSA intervention scores averaged per cluster (rows) × intervention (cols). */
export function clusterSsaHeatmap(): ClusterSsaHeatmap {
  const interventions = [...SSA_INTERVENTION_AREAS] as string[];
  const rows: ClusterSsaHeatmapRow[] = activeClusters().map((c) => {
    const schools = schoolsInCluster(c.id);
    const uploads = schools.map((s) => latestSsaUploadFor(s.schoolId)).filter(Boolean);
    const cells = interventions.map((area) => {
      const vals = uploads.map((u) => Number(u!.scores[area])).filter((n) => Number.isFinite(n));
      return vals.length ? Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10 : null;
    });
    return { clusterId: c.id, clusterName: c.name, district: c.district, schoolsWithSsa: uploads.length, cells };
  });
  return { interventions, rows };
}

// ── System health checks ───────────────────────────────────────────

export type ClusterHealthIssue = {
  kind:
    | "school_without_cluster"
    | "core_without_cluster"
    | "cluster_without_schools"
    | "cluster_missing_district"
    | "cross_district_school"
    | "duplicate_cluster_name"
    | "inactive_cluster_with_schools";
  label: string;
  count: number;
  ids: string[];
};

export function clusterHealthChecks(): ClusterHealthIssue[] {
  const issues: ClusterHealthIssue[] = [];

  const unclustered = unclusteredSchools();
  if (unclustered.length) {
    issues.push({
      kind: "school_without_cluster",
      label: "Schools without a cluster",
      count: unclustered.length,
      ids: unclustered.map((s) => s.schoolId),
    });
  }
  const coreUnclustered = unclustered.filter((s) => s.schoolType === "Core");
  if (coreUnclustered.length) {
    issues.push({
      kind: "core_without_cluster",
      label: "Core schools without a cluster",
      count: coreUnclustered.length,
      ids: coreUnclustered.map((s) => s.schoolId),
    });
  }
  const empty = activeClusters().filter((c) => schoolsInCluster(c.id).length === 0);
  if (empty.length) {
    issues.push({
      kind: "cluster_without_schools",
      label: "Clusters with no schools",
      count: empty.length,
      ids: empty.map((c) => c.id),
    });
  }
  const noDistrict = activeClusters().filter((c) => !c.district?.trim());
  if (noDistrict.length) {
    issues.push({
      kind: "cluster_missing_district",
      label: "Clusters missing a district",
      count: noDistrict.length,
      ids: noDistrict.map((c) => c.id),
    });
  }
  const crossDistrict = intakeSchools.filter((s) => {
    const c = clusterById(s.clusterId);
    return c && c.district.toLowerCase() !== s.district.trim().toLowerCase();
  });
  if (crossDistrict.length) {
    issues.push({
      kind: "cross_district_school",
      label: "Schools assigned to a cluster in a different district",
      count: crossDistrict.length,
      ids: crossDistrict.map((s) => s.schoolId),
    });
  }
  const nameKey = (c: ClusterRecord) => `${c.district}|${c.subCounty ?? ""}|${c.name}`.toLowerCase();
  const seen = new Map<string, string[]>();
  for (const c of activeClusters()) {
    const k = nameKey(c);
    seen.set(k, [...(seen.get(k) ?? []), c.id]);
  }
  const dupes = [...seen.values()].filter((ids) => ids.length > 1).flat();
  if (dupes.length) {
    issues.push({
      kind: "duplicate_cluster_name",
      label: "Duplicate cluster names in the same district / sub-county",
      count: dupes.length,
      ids: dupes,
    });
  }
  const inactiveWithSchools = clusters.filter(
    (c) => !c.isActive && schoolsInCluster(c.id).length > 0,
  );
  if (inactiveWithSchools.length) {
    issues.push({
      kind: "inactive_cluster_with_schools",
      label: "Inactive clusters still holding schools",
      count: inactiveWithSchools.length,
      ids: inactiveWithSchools.map((c) => c.id),
    });
  }
  return issues;
}

// ── Partner management (staff delegates a cluster to a partner) ─────

export type ClusterPartnerResult =
  | { ok: true; cluster: ClusterRecord }
  | { ok: false; reason: string };

/**
 * Delegate a cluster to a partner to manage (or clear the delegation when
 * partnerId is empty). Staff stays the owner; the partner becomes the
 * executor — mirrors per-school partner delegation at the cluster level.
 */
export function assignClusterToPartner(
  clusterId: string,
  partnerId: string,
  partnerName: string,
  actor: ClusterActor,
): ClusterPartnerResult {
  const cluster = clusterById(clusterId);
  if (!cluster) return { ok: false, reason: "Cluster not found." };
  if (!partnerId) {
    cluster.managedByPartnerId = undefined;
    cluster.managedByPartnerName = undefined;
  } else {
    cluster.managedByPartnerId = partnerId;
    cluster.managedByPartnerName = partnerName;
  }
  logAudit({
    action: "partner_assigned",
    user: actor.name,
    role: actor.role,
    newClusterId: clusterId,
    reason: partnerId ? `Delegated to ${partnerName}` : "Partner delegation cleared",
    district: cluster.district,
    subCounty: cluster.subCounty,
  });
  return { ok: true, cluster };
}

// ── Edit cluster leader ────────────────────────────────────────────

/**
 * Change a cluster's leader (name + phone, optionally the school they lead) —
 * so staff can update leadership when it changes. Empty name clears the leader.
 */
export function updateClusterLeader(
  clusterId: string,
  leader: { name?: string; phone?: string; schoolId?: string },
  actor: ClusterActor,
): ClusterPartnerResult {
  const cluster = clusterById(clusterId);
  if (!cluster) return { ok: false, reason: "Cluster not found." };
  const name = leader.name?.trim();
  cluster.clusterLeaderName = name || undefined;
  cluster.clusterLeaderPhone = leader.phone?.trim() || undefined;
  cluster.clusterLeaderSchoolId = leader.schoolId || undefined;
  logAudit({
    action: "leader_changed",
    user: actor.name,
    role: actor.role,
    newClusterId: clusterId,
    reason: name ? `Leader set to ${name}` : "Leader cleared",
    district: cluster.district,
    subCounty: cluster.subCounty,
  });
  return { ok: true, cluster };
}

/** Clusters delegated to a given partner to manage. */
export function clustersManagedByPartner(partnerId: string): ClusterRecord[] {
  return activeClusters().filter((c) => c.managedByPartnerId === partnerId);
}

// ── Cluster meetings ───────────────────────────────────────────────

export type ScheduleMeetingResult =
  | { ok: true; meeting: ClusterMeeting }
  | { ok: false; reason: string };

/**
 * Schedule a cluster meeting / training. Used by BOTH the delegated partner
 * (organizer "partner") and Edify staff (organizer "edify") — delegation never
 * blocks staff from running Edify-organised activities on the same cluster.
 */
export function scheduleClusterMeeting(
  clusterId: string,
  input: { kind: ClusterMeetingKind; date: string; participants?: number; notes?: string },
  actor: ClusterActor,
  organizer: ClusterMeetingOrganizer,
): ScheduleMeetingResult {
  const cluster = clusterById(clusterId);
  if (!cluster) return { ok: false, reason: "Cluster not found." };
  if (!input.date) return { ok: false, reason: "Pick a date." };
  const meeting: ClusterMeeting = {
    id: nextMeetingId(),
    clusterId,
    kind: input.kind,
    date: input.date,
    organizer,
    scheduledBy: actor.name,
    scheduledByRole: actor.role,
    participants: input.participants,
    notes: input.notes?.trim() || undefined,
    createdAt: new Date().toISOString(),
    status: "Scheduled",
  };
  clusterMeetings.unshift(meeting);
  logAudit({
    action: "meeting_scheduled",
    user: actor.name,
    role: actor.role,
    newClusterId: clusterId,
    reason: `${organizer === "partner" ? "Partner" : "Edify"} scheduled ${CLUSTER_MEETING_LABEL[input.kind]} on ${input.date}`,
    district: cluster.district,
    subCounty: cluster.subCounty,
  });
  return { ok: true, meeting };
}

/** Scheduled meetings for a cluster, soonest first. */
export function meetingsForCluster(clusterId: string): ClusterMeeting[] {
  return clusterMeetings
    .filter((m) => m.clusterId === clusterId)
    .sort((a, b) => a.date.localeCompare(b.date));
}

export function clusterActivityById(id: string): ClusterMeeting | undefined {
  return clusterMeetings.find((m) => m.id === id);
}

export type ActivityResult =
  | { ok: true; activity: ClusterMeeting }
  | { ok: false; reason: string };

/**
 * Record the Salesforce training id + attendance for a held activity. Validates
 * the TS- id, totals participants, marks evidence uploaded, and moves the
 * activity to "Awaiting IA". Done by the executor (partner or staff).
 */
export function recordClusterActivitySalesforce(
  activityId: string,
  input: { salesforceTrainingId: string; teachersCount: number; schoolLeadersCount: number; otherCount?: number },
  actor: ClusterActor,
): ActivityResult {
  const a = clusterActivityById(activityId);
  if (!a) return { ok: false, reason: "Activity not found." };
  if (!isValidTsId(input.salesforceTrainingId)) {
    return { ok: false, reason: "Salesforce training id must look like TS-01234." };
  }
  const teachers = Math.max(0, Math.floor(input.teachersCount || 0));
  const leaders = Math.max(0, Math.floor(input.schoolLeadersCount || 0));
  const other = Math.max(0, Math.floor(input.otherCount || 0));
  a.salesforceTrainingId = input.salesforceTrainingId.trim().toUpperCase();
  a.teachersCount = teachers;
  a.schoolLeadersCount = leaders;
  a.otherCount = other;
  a.totalParticipants = teachers + leaders + other;
  a.participants = a.totalParticipants;
  a.evidenceUploaded = true;
  a.returnedReason = undefined;
  a.status = "Awaiting IA";
  return { ok: true, activity: a };
}

export type CompleteMeetingInput = {
  salesforceTrainingId: string;
  teachersCount: number;
  schoolLeadersCount: number;
  otherCount?: number;
  attendanceFileName: string;
  minutesText: string;
  minutesFileName?: string;
  resolutionsText?: string;
  resolutionsFileName?: string;
  nextMeetingDate?: string;
  notes?: string;
};

export type CompleteMeetingResult =
  | { ok: true; activity: ClusterMeeting; nextActivity?: ClusterMeeting }
  | { ok: false; reason: string };

/**
 * Complete a cluster meeting — the full gate. A meeting isn't complete until
 * attendance + evidence + typed minutes + resolutions + a valid TS- id are in,
 * and (for early meetings) the next meeting date is set, which auto-schedules
 * the next meeting. Moves the activity to "Awaiting IA".
 */
export function completeClusterMeeting(
  activityId: string,
  input: CompleteMeetingInput,
  actor: ClusterActor,
): CompleteMeetingResult {
  const a = clusterActivityById(activityId);
  if (!a) return { ok: false, reason: "Activity not found." };
  if (!isValidTsId(input.salesforceTrainingId)) return { ok: false, reason: "Salesforce training id must look like TS-01234." };
  if (!input.attendanceFileName?.trim()) return { ok: false, reason: "Attendance evidence is required." };
  if (!input.minutesText?.trim()) return { ok: false, reason: "Meeting minutes are required." };
  if (!input.resolutionsText?.trim() && !input.resolutionsFileName?.trim()) {
    return { ok: false, reason: "Capture at least one resolution (text or upload)." };
  }
  const teachers = Math.max(0, Math.floor(input.teachersCount || 0));
  const leaders = Math.max(0, Math.floor(input.schoolLeadersCount || 0));
  const other = Math.max(0, Math.floor(input.otherCount || 0));
  if (teachers + leaders + other === 0) return { ok: false, reason: "Enter the actual attendance." };

  const next = nextMeetingKind(a.kind);
  const nextRequired = a.kind === "first_meeting" || a.kind === "second_meeting";
  if (nextRequired && !input.nextMeetingDate) return { ok: false, reason: "Confirm the next meeting date." };

  // Write the completion record.
  a.salesforceTrainingId = input.salesforceTrainingId.trim().toUpperCase();
  a.teachersCount = teachers;
  a.schoolLeadersCount = leaders;
  a.otherCount = other;
  a.totalParticipants = teachers + leaders + other;
  a.participants = a.totalParticipants;
  a.attendanceFileName = input.attendanceFileName.trim();
  a.minutesText = input.minutesText.trim();
  a.minutesFileName = input.minutesFileName?.trim() || undefined;
  a.resolutionsText = input.resolutionsText?.trim() || undefined;
  a.resolutionsFileName = input.resolutionsFileName?.trim() || undefined;
  a.nextMeetingDate = input.nextMeetingDate || undefined;
  a.notes = input.notes?.trim() || a.notes;
  a.evidenceUploaded = true;
  a.completedBy = actor.name;
  a.completedAt = new Date().toISOString();
  a.actualDate = new Date().toISOString().slice(0, 10);
  a.returnedReason = undefined;
  a.status = "Awaiting IA";

  // Auto-schedule the next meeting from the confirmed date.
  let nextActivity: ClusterMeeting | undefined;
  if (input.nextMeetingDate && next) {
    nextActivity = {
      id: nextMeetingId(),
      clusterId: a.clusterId,
      kind: next,
      date: input.nextMeetingDate,
      organizer: a.organizer,
      scheduledBy: actor.name,
      scheduledByRole: actor.role,
      createdAt: new Date().toISOString(),
      status: "Scheduled",
      linkedPreviousMeetingId: a.id,
    };
    clusterMeetings.unshift(nextActivity);
    a.nextActivityId = nextActivity.id;
    const cluster = clusterById(a.clusterId);
    logAudit({
      action: "meeting_scheduled",
      user: actor.name,
      role: actor.role,
      newClusterId: a.clusterId,
      reason: `Auto-scheduled ${CLUSTER_MEETING_LABEL[next]} on ${input.nextMeetingDate} from the completed ${CLUSTER_MEETING_LABEL[a.kind]}`,
      district: cluster?.district,
      subCounty: cluster?.subCounty,
    });
  }

  return { ok: true, activity: a, nextActivity };
}

/** IA confirms the Salesforce record — the only thing that makes it "count". */
export function iaConfirmClusterActivity(activityId: string, actor: ClusterActor): ActivityResult {
  const a = clusterActivityById(activityId);
  if (!a) return { ok: false, reason: "Activity not found." };
  if (!isValidTsId(a.salesforceTrainingId)) return { ok: false, reason: "No valid TS- Salesforce id to confirm." };
  if (a.status !== "Awaiting IA") return { ok: false, reason: "Activity is not awaiting IA confirmation." };
  a.status = "IA Confirmed";
  a.iaConfirmedAt = new Date().toISOString();
  a.iaConfirmedBy = actor.name;
  return { ok: true, activity: a };
}

/** Accountant clears partner payment — only after IA confirmation. */
export function accountantPayClusterActivity(activityId: string, actor: ClusterActor): ActivityResult {
  const a = clusterActivityById(activityId);
  if (!a) return { ok: false, reason: "Activity not found." };
  if (a.organizer !== "partner") return { ok: false, reason: "Only partner-managed activities are paid." };
  if (a.status !== "IA Confirmed") return { ok: false, reason: "Payment is blocked until IA confirms the Salesforce record." };
  a.status = "Paid";
  a.accountantPaidAt = new Date().toISOString();
  return { ok: true, activity: a };
}

/** Staff (Edify-managed) cluster activities IA-confirmed, awaiting Netsuite accountability. */
export function staffClusterAccountabilityPending(): ClusterMeeting[] {
  return clusterMeetings.filter((m) => m.organizer === "edify" && m.status === "IA Confirmed");
}

/** Accountant records Netsuite accountability for a staff-managed activity — only after IA confirmation. */
export function recordStaffAccountability(activityId: string, netsuiteExpenseId: string, actor: ClusterActor): ActivityResult {
  const a = clusterActivityById(activityId);
  if (!a) return { ok: false, reason: "Activity not found." };
  if (a.organizer !== "edify") return { ok: false, reason: "Only staff-managed activities use Netsuite accountability." };
  if (a.status !== "IA Confirmed") return { ok: false, reason: "Accountability is blocked until IA confirms the Salesforce record." };
  if (!netsuiteExpenseId.trim()) return { ok: false, reason: "Enter the Netsuite Expense ID." };
  a.netsuiteExpenseId = netsuiteExpenseId.trim();
  a.accountabilityClosedAt = new Date().toISOString();
  a.status = "Closed";
  return { ok: true, activity: a };
}

/** Return an activity for correction (IA or staff). */
export function returnClusterActivity(activityId: string, reason: string, actor: ClusterActor): ActivityResult {
  const a = clusterActivityById(activityId);
  if (!a) return { ok: false, reason: "Activity not found." };
  a.status = "Returned";
  a.returnedReason = reason || "Returned for correction";
  return { ok: true, activity: a };
}

/** Cluster activities awaiting IA Salesforce confirmation (IA queue). */
export function clusterActivitiesAwaitingIa(): ClusterMeeting[] {
  return clusterMeetings.filter((m) => m.status === "Awaiting IA");
}

/** Partner cluster activities IA-confirmed and ready for accountant payment. */
export function partnerClusterPaymentsReady(): ClusterMeeting[] {
  return clusterMeetings.filter((m) => m.organizer === "partner" && m.status === "IA Confirmed");
}

export type ClusterMeetingMetrics = {
  scheduled: number;
  awaitingIa: number;
  confirmed: number; // IA Confirmed or Paid
  attendanceTotal: number;
  teachersReached: number;
  schoolLeadersReached: number;
  partnerPaymentsReady: number;
  nextScheduled: number; // future-dated, still Scheduled
};

/** Roll-up of cluster-meeting lifecycle for dashboards. */
export function clusterMeetingMetrics(): ClusterMeetingMetrics {
  const confirmedList = clusterMeetings.filter((m) => m.status === "IA Confirmed" || m.status === "Paid" || m.status === "Closed");
  return {
    scheduled: clusterMeetings.filter((m) => m.status === "Scheduled").length,
    awaitingIa: clusterMeetings.filter((m) => m.status === "Awaiting IA").length,
    confirmed: confirmedList.length,
    attendanceTotal: confirmedList.reduce((n, m) => n + (m.totalParticipants ?? 0), 0),
    teachersReached: confirmedList.reduce((n, m) => n + (m.teachersCount ?? 0), 0),
    schoolLeadersReached: confirmedList.reduce((n, m) => n + (m.schoolLeadersCount ?? 0), 0),
    partnerPaymentsReady: partnerClusterPaymentsReady().length,
    nextScheduled: clusterMeetings.filter((m) => m.status === "Scheduled").length,
  };
}

// ── Cluster feedback ───────────────────────────────────────────────

export type ClusterFeedbackType = "partner" | "staff" | "ia";
export const CLUSTER_FEEDBACK_LABEL: Record<ClusterFeedbackType, string> = {
  partner: "Partner feedback",
  staff: "Staff feedback",
  ia: "IA verification feedback",
};

export type ClusterFeedback = {
  id: string;
  clusterId: string;
  activityId?: string;
  submittedBy: string;
  submittedByRole: string;
  feedbackType: ClusterFeedbackType;
  whatWentWell?: string;
  challenges?: string;
  recommendations?: string;
  rating?: number; // 1–5
  createdAt: string;
};

export const clusterFeedback: ClusterFeedback[] = [];
let feedbackSeq = 0;

export function addClusterFeedback(
  clusterId: string,
  input: { feedbackType: ClusterFeedbackType; whatWentWell?: string; challenges?: string; recommendations?: string; rating?: number; activityId?: string },
  actor: ClusterActor,
): ClusterFeedback | { error: string } {
  if (!clusterById(clusterId)) return { error: "Cluster not found." };
  if (!input.whatWentWell?.trim() && !input.challenges?.trim() && !input.recommendations?.trim()) {
    return { error: "Add at least one note." };
  }
  feedbackSeq += 1;
  const rec: ClusterFeedback = {
    id: `CFB-${String(feedbackSeq).padStart(4, "0")}`,
    clusterId,
    activityId: input.activityId,
    submittedBy: actor.name,
    submittedByRole: actor.role,
    feedbackType: input.feedbackType,
    whatWentWell: input.whatWentWell?.trim() || undefined,
    challenges: input.challenges?.trim() || undefined,
    recommendations: input.recommendations?.trim() || undefined,
    rating: input.rating,
    createdAt: new Date().toISOString(),
  };
  clusterFeedback.unshift(rec);
  return rec;
}

export function feedbackForCluster(clusterId: string): ClusterFeedback[] {
  return clusterFeedback.filter((f) => f.clusterId === clusterId);
}

// ── Verified cluster impact (donor reporting) ──────────────────────
//
// Only IA-confirmed activities (IA Confirmed / Paid / Closed) count as verified
// donor-ready. Every number traces back to a Salesforce TS- id + cluster.

export type VerifiedActivityRow = {
  id: string;
  clusterId: string;
  clusterName: string;
  district: string;
  label: string;
  date: string;
  organizer: ClusterMeetingOrganizer;
  salesforceTrainingId?: string;
  teachers: number;
  schoolLeaders: number;
  total: number;
  iaConfirmedAt?: string;
};

export type VerifiedClusterImpact = {
  verifiedMeetings: number;
  teachersReached: number;
  schoolLeadersReached: number;
  attendanceTotal: number;
  clustersWithVerified: number;
  schoolsInClusters: number;
  rows: VerifiedActivityRow[];
};

export function verifiedClusterImpact(): VerifiedClusterImpact {
  const verified = clusterMeetings.filter(
    (m) => m.status === "IA Confirmed" || m.status === "Paid" || m.status === "Closed",
  );
  const rows: VerifiedActivityRow[] = verified.map((m) => {
    const c = clusterById(m.clusterId);
    return {
      id: m.id,
      clusterId: m.clusterId,
      clusterName: c?.name ?? "Unknown cluster",
      district: c?.district ?? "—",
      label: CLUSTER_MEETING_LABEL[m.kind],
      date: m.date,
      organizer: m.organizer,
      salesforceTrainingId: m.salesforceTrainingId,
      teachers: m.teachersCount ?? 0,
      schoolLeaders: m.schoolLeadersCount ?? 0,
      total: m.totalParticipants ?? 0,
      iaConfirmedAt: m.iaConfirmedAt,
    };
  }).sort((a, b) => b.date.localeCompare(a.date));

  return {
    verifiedMeetings: verified.length,
    teachersReached: rows.reduce((n, r) => n + r.teachers, 0),
    schoolLeadersReached: rows.reduce((n, r) => n + r.schoolLeaders, 0),
    attendanceTotal: rows.reduce((n, r) => n + r.total, 0),
    clustersWithVerified: new Set(verified.map((m) => m.clusterId)).size,
    schoolsInClusters: intakeSchools.filter((s) => clusterStatusOf(s) === "clustered").length,
    rows,
  };
}

// ── Cluster performance (computed from member schools + activities) ─

export type ClusterProfile = {
  cluster: ClusterRecord;
  managementType: "staff" | "partner" | "mixed";
  schools: IntakeSchool[];
  clientCount: number;
  coreCount: number;
  ssaDone: number;
  ssaMissing: number;
  ssaCompletionRate: number; // %
  activities: ClusterMeeting[];
  meetingsCompleted: number;   // IA-confirmed
  meetingsScheduled: number;
  attendanceTotal: number;
  teachersReached: number;
  schoolLeadersReached: number;
  paymentsReady: number;       // partner, IA-confirmed, unpaid
  paymentsPaid: number;
};

/** Full cluster profile — the cluster's truth is its schools + activities. */
export function clusterProfile(clusterId: string): ClusterProfile | undefined {
  const cluster = clusterById(clusterId);
  if (!cluster) return undefined;
  const schools = schoolsInCluster(clusterId);
  const activities = meetingsForCluster(clusterId);
  const ssaDone = schools.filter((s) => s.ssaStatus === "SSA Done").length;
  const confirmed = activities.filter((a) => a.status === "IA Confirmed" || a.status === "Paid" || a.status === "Closed");
  const teachersReached = confirmed.reduce((n, a) => n + (a.teachersCount ?? 0), 0);
  const schoolLeadersReached = confirmed.reduce((n, a) => n + (a.schoolLeadersCount ?? 0), 0);
  const attendanceTotal = confirmed.reduce((n, a) => n + (a.totalParticipants ?? 0), 0);

  // Management type = derived from who runs the activities + delegation.
  const hasPartner = !!cluster.managedByPartnerId || activities.some((a) => a.organizer === "partner");
  const hasStaff = activities.some((a) => a.organizer === "edify");
  const managementType: ClusterProfile["managementType"] =
    hasPartner && hasStaff ? "mixed" : hasPartner ? "partner" : "staff";

  return {
    cluster,
    managementType,
    schools,
    clientCount: schools.filter((s) => s.schoolType === "Client").length,
    coreCount: schools.filter((s) => s.schoolType === "Core").length,
    ssaDone,
    ssaMissing: schools.length - ssaDone,
    ssaCompletionRate: schools.length ? Math.round((ssaDone / schools.length) * 100) : 0,
    activities,
    meetingsCompleted: confirmed.length,
    meetingsScheduled: activities.length,
    attendanceTotal,
    teachersReached,
    schoolLeadersReached,
    paymentsReady: activities.filter((a) => a.organizer === "partner" && a.status === "IA Confirmed").length,
    paymentsPaid: activities.filter((a) => a.status === "Paid").length,
  };
}

// ── Staff vs partner comparison ────────────────────────────────────

export type ManagementComparisonRow = {
  managementType: "staff" | "partner";
  clusters: number;
  meetingsScheduled: number;
  meetingsConfirmed: number;
  attendanceTotal: number;
  teachersReached: number;
  schoolLeadersReached: number;
  avgSsaCompletion: number; // % across those clusters
};

export function staffVsPartnerClusterComparison(): { staff: ManagementComparisonRow; partner: ManagementComparisonRow } {
  const mk = (type: "staff" | "partner"): ManagementComparisonRow => ({
    managementType: type, clusters: 0, meetingsScheduled: 0, meetingsConfirmed: 0,
    attendanceTotal: 0, teachersReached: 0, schoolLeadersReached: 0, avgSsaCompletion: 0,
  });
  const staff = mk("staff");
  const partner = mk("partner");
  const ssaAcc = { staff: [] as number[], partner: [] as number[] };

  for (const c of activeClusters()) {
    const p = clusterProfile(c.id);
    if (!p) continue;
    const bucket = p.managementType === "partner" ? partner : staff; // mixed counts as staff oversight here
    bucket.clusters += 1;
    bucket.meetingsScheduled += p.meetingsScheduled;
    bucket.meetingsConfirmed += p.meetingsCompleted;
    bucket.attendanceTotal += p.attendanceTotal;
    bucket.teachersReached += p.teachersReached;
    bucket.schoolLeadersReached += p.schoolLeadersReached;
    (p.managementType === "partner" ? ssaAcc.partner : ssaAcc.staff).push(p.ssaCompletionRate);
  }
  const avg = (xs: number[]) => (xs.length ? Math.round(xs.reduce((a, b) => a + b, 0) / xs.length) : 0);
  staff.avgSsaCompletion = avg(ssaAcc.staff);
  partner.avgSsaCompletion = avg(ssaAcc.partner);
  return { staff, partner };
}

// ── Cluster-leader candidates ──────────────────────────────────────

export type ClusterLeaderCandidate = {
  schoolId: string;
  schoolName: string;
  leaderName: string;
  phone?: string;
  subCounty?: string;
};

/**
 * Candidate cluster leaders for the create form — school leaders (a school's
 * primary contact) from schools in the chosen district + sub-counties. The
 * cluster leader should be a school leader from one of the cluster's schools.
 */
export function candidateClusterLeaders(district: string, subCounties: string[] = []): ClusterLeaderCandidate[] {
  const d = district.trim().toLowerCase();
  const subs = subCounties.map((s) => s.trim().toLowerCase()).filter(Boolean);
  return intakeSchools
    .filter((s) => s.district.trim().toLowerCase() === d)
    .filter((s) => subs.length === 0 || (s.subCounty != null && subs.includes(s.subCounty.trim().toLowerCase())))
    .filter((s) => !!s.primaryContact)
    .map((s) => ({
      schoolId: s.schoolId,
      schoolName: s.schoolName,
      leaderName: s.primaryContact as string,
      phone: s.phone,
      subCounty: s.subCounty,
    }));
}

// ── Geography helpers for the Workspace pickers ────────────────────

/** Sub-counties for a district name (proxy to geography, name-keyed). */
export function subCountyOptions(district: string): string[] {
  return subCountiesOf(district).map((s) => s.name);
}
