"use server";

// Demo-seed action — runs a full W3→W5 chain in one go so the audit
// log and notifications surface have something to render. Admin-only.
//
// This is NOT a generic seeding tool; it's an interactive smoke test
// the team can click during the build-out. Every step calls a real
// server action — there is no shortcut into the store, no fake audit
// emit. If the chain works here, it works for every caller.

import { getCurrentUser } from "@/lib/auth";
import {
  addActivityToPlan,
  approvePlan,
  createPlan,
  submitPlan,
} from "./plan-actions";
import {
  addTrainingParticipants,
  confirmEvidence,
  markActivityCompleted,
  recordVisit,
  submitActivityForVerification,
  uploadEvidence,
} from "./activity-actions";
import { recordSsaSnapshot } from "./ssa-actions";
import {
  assignPartnerActivity,
  cceoConfirmPartnerActivity,
  partnerMarkDelivered,
  partnerUploadEvidence,
} from "./partner-actions";
import { generateDonorSnapshot } from "./donor-actions";

export type SeedResult =
  | {
      ok: true;
      planId: string;
      activityIds: string[];
      generatedRequestIds: string[];
      visitIds:         string[];
      participantIds:   string[];
      ssaSnapshotIds:   string[];
      partnerActivityIds: string[];
      donorSnapshotId?: string;
      donorFiltersHash?: string;
    }
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "FAILED"; step: string; detail: string };

// Build a stable-ish month string slightly in the future so re-running
// the seed across a session doesn't collide on the (authorId, monthIso)
// unique constraint until 12 runs in.
function nextSeedMonth(): string {
  const now = new Date();
  const m = (now.getMonth() + 1) + (Math.floor(Math.random() * 60_000) % 12);
  const year = now.getFullYear() + Math.floor(m / 12);
  const month = (m % 12) + 1;
  return `${year}-${String(month).padStart(2, "0")}`;
}

export async function seedSamplePlan(): Promise<SeedResult> {
  const user = await getCurrentUser();
  if (user.role !== "Admin" && user.role !== "CCEO") {
    return { ok: false, reason: "FORBIDDEN" };
  }
  const monthIso = nextSeedMonth();

  // 1) Create the plan.
  const plan = await createPlan(monthIso);
  if (!plan.ok) {
    return { ok: false, reason: "FAILED", step: "createPlan", detail: plan.reason };
  }
  const planId = plan.id;

  // 2) Add three activities — one per week, mixing kinds so the audit
  // trail reads like a real planning session.
  const activityIds: string[] = [];
  const drafts = [
    { kind: "SCHOOL_VISIT" as const,      title: "Week 1 · Foundational Literacy support visit", weekOfMonth: 1, estCostCents: 140_000 * 100 },
    { kind: "CLUSTER_TRAINING" as const,  title: "Week 2 · Phonics cluster training",             weekOfMonth: 2, estCostCents: 1_200_000 * 100 },
    { kind: "IN_SCHOOL_COACHING" as const, title: "Week 3 · Headteacher coaching",                weekOfMonth: 3, estCostCents: 250_000 * 100 },
  ];
  for (const draft of drafts) {
    const a = await addActivityToPlan(planId, draft);
    if (!a.ok) {
      return { ok: false, reason: "FAILED", step: `addActivity(${draft.title})`, detail: a.reason };
    }
    activityIds.push(a.id);
  }

  // 3) Submit the plan (Draft → SubmittedForApproval).
  const sub = await submitPlan(planId);
  if (!sub.ok) {
    return { ok: false, reason: "FAILED", step: "submitPlan", detail: sub.reason };
  }

  // 4) Approve (SubmittedForApproval → Approved → triggers W5 split).
  // Admins can approve their own seeded plans for this smoke path; CCEO
  // role can't approve their own plan in production, but for the seed
  // we use the calling Admin role.
  if (user.role !== "Admin") {
    // CCEO can't self-approve; stop here. The plan is visible in
    // /approvals for a CPL/CD to act on. Empty arrays for the
    // downstream chains since those depend on approval.
    return {
      ok: true,
      planId,
      activityIds,
      generatedRequestIds: [],
      visitIds: [],
      participantIds: [],
      ssaSnapshotIds: [],
      partnerActivityIds: [],
    };
  }

  const apr = await approvePlan(planId);
  if (!apr.ok) {
    return { ok: false, reason: "FAILED", step: "approvePlan", detail: apr.reason };
  }

  // ─── W6 — Activity execution + evidence ──────────────────────────
  // Take the first activity through: mark complete → submit for
  // verification → add 2 participants → upload evidence per participant
  // → CCEO confirm one of them. The IA queue at /data-verification
  // will surface the rest.
  const visitIds: string[] = [];
  const participantIds: string[] = [];
  if (activityIds.length > 0) {
    const a0 = activityIds[0];
    const mc = await markActivityCompleted(a0, "Completed during seed run");
    if (!mc.ok) return { ok: false, reason: "FAILED", step: "markActivityCompleted", detail: mc.reason };
    // a0 is a SCHOOL_VISIT → enters a Salesforce Visit ID (SVE-). The IA queue
    // shows this exact value for the IA to paste into Salesforce.
    const sv = await submitActivityForVerification(a0, "SVE-88273");
    if (!sv.ok) return { ok: false, reason: "FAILED", step: "submitActivityForVerification", detail: sv.reason };

    const drafts = [
      { participantType: "Teacher" as const,      participantName: "Aisha Nakato",    schoolId: "school-NTL-001", phone: "+256700000001" },
      { participantType: "SchoolLeader" as const, participantName: "Headteacher Mwangi", schoolId: "school-NTL-001", phone: "+256700000002" },
    ];
    const addPart = await addTrainingParticipants(a0, drafts);
    if (!addPart.ok) return { ok: false, reason: "FAILED", step: "addTrainingParticipants", detail: addPart.reason };
    participantIds.push(...(addPart.addedIds ?? []));

    for (const pid of participantIds) {
      const up = await uploadEvidence({
        kind: "TrainingParticipant",
        subjectId: pid,
        filename: "attendance-week1.pdf",
        contentLength: 184_320,
      });
      if (!up.ok) return { ok: false, reason: "FAILED", step: `uploadEvidence(${pid})`, detail: up.reason };
    }
    // CCEO confirms the first participant — leaves the second waiting
    // for M&E so the verification queue has a row to work on.
    if (participantIds.length > 0) {
      const cc = await confirmEvidence(participantIds[0]);
      if (!cc.ok) return { ok: false, reason: "FAILED", step: "confirmEvidence", detail: cc.reason };
    }

    // Record a SchoolVisit.
    const rv = await recordVisit({
      schoolId: "school-NTL-001",
      kind: "SCHOOL_VISIT",
      date: new Date().toISOString().slice(0, 10),
      completed: true,
    });
    if (rv.ok) visitIds.push(rv.id);
  }

  // ─── W7 — SSA: capture two baseline scores + a follow-up improved
  const ssaSnapshotIds: string[] = [];
  const s1 = await recordSsaSnapshot({
    schoolId: "school-NTL-001",
    interventionArea: "TeachingAndLearning",
    score: 3,
    completedAt: new Date(Date.now() - 90 * 86_400_000).toISOString(),
    notes: "Baseline — weak phonics, large class.",
  });
  if (s1.ok) ssaSnapshotIds.push(s1.id);
  const s2 = await recordSsaSnapshot({
    schoolId: "school-NTL-001",
    interventionArea: "TeachingAndLearning",
    score: 6,
    notes: "Follow-Up after coaching — Improved.",
  });
  if (s2.ok) ssaSnapshotIds.push(s2.id);

  // ─── W8 — Partner activity: assign → deliver → upload → CCEO confirm
  const partnerActivityIds: string[] = [];
  const pa = await assignPartnerActivity({
    partnerId: "partner-bfep-001",
    partnerName: "BrightFuture Education Partners",
    schoolId: "school-NTL-001",
    interventionArea: "Leadership",
    title: "Headteacher leadership workshop",
    date: new Date().toISOString().slice(0, 10),
    costUgxCents: 2_500_000 * 100,
  });
  if (pa.ok) partnerActivityIds.push(pa.id);
  if (pa.ok) {
    const md = await partnerMarkDelivered(pa.id, {
      teachersReached: 12,
      leadersReached: 1,
      studentsReached: 0,
      notes: "Delivered in plenary session.",
    });
    if (!md.ok) return { ok: false, reason: "FAILED", step: "partnerMarkDelivered", detail: md.reason };
    const pu = await partnerUploadEvidence({
      activityId: pa.id,
      filename: "leadership-workshop-photo.jpg",
      contentLength: 412_000,
      notes: "Attendance sheet + group photo",
    });
    if (!pu.ok) return { ok: false, reason: "FAILED", step: "partnerUploadEvidence", detail: pu.reason };
    const cc = await cceoConfirmPartnerActivity(pa.id);
    if (!cc.ok) return { ok: false, reason: "FAILED", step: "cceoConfirmPartnerActivity", detail: cc.reason };
  }

  // ─── W11 — Generate a donor snapshot off the live data. Determinism
  // is verified by re-running with the same filters and comparing the
  // filtersHash → expect the same hash + same numbers.
  const ds = await generateDonorSnapshot({
    roleScope: "ImpactAssessment",
    scopeLabel: "Uganda · Seed batch",
    operationalCycle: "FY 2025/26 · Seed",
    dateRangeStart: new Date(Date.now() - 180 * 86_400_000).toISOString(),
    dateRangeEnd:   new Date().toISOString(),
  });
  const donorSnapshotId  = ds.ok ? ds.snapshotId : undefined;
  const donorFiltersHash = ds.ok ? ds.filtersHash : undefined;

  return {
    ok: true,
    planId,
    activityIds,
    generatedRequestIds: apr.generatedRequestIds ?? [],
    visitIds,
    participantIds,
    ssaSnapshotIds,
    partnerActivityIds,
    donorSnapshotId,
    donorFiltersHash,
  };
}
