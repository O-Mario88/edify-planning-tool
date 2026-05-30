// Partner fraud + duplication detection.
//
// Implements the 10 detection rules from the spec. Every rule is a
// pure function that takes the candidate activity + a small amount of
// context (recent activities for the same partner / school) and
// returns whether the flag fires.
//
// IMPORTANT: per the spec, fraud flags NEVER auto-reject. They mark
// the record as "Needs Review" so a human (typically M&E) decides.
// This file produces flags; downstream code (verification engine,
// UI badges) consumes them.

import type {
  FraudFlag,
  PartnerActivity,
  PartnerScope,
} from "./partner-types";
import { canPartnerAct } from "./partner-scope";

// Context passed to the detector — everything it needs to make a call.
// Designed so the caller can prepare it once per partner submission
// and run all detectors against it.

export type FraudContext = {
  /// Activities by the same partner in the last 30 days, including
  /// the candidate itself (the detectors filter it out by id).
  recentPartnerActivities: PartnerActivity[];
  /// The scope this candidate is being submitted under.
  scope: PartnerScope;
  /// The school's district + cluster — needed for scope checks.
  schoolDistrictId: string;
  schoolClusterId?: string;
  /// Optional GPS reading from the submitting device.
  submittedGpsLat?: number;
  submittedGpsLng?: number;
  /// The school's official GPS coordinates, if known.
  schoolGpsLat?: number;
  schoolGpsLng?: number;
  /// Hash of the attendance-sheet file the partner uploaded, if any.
  /// Production reads this from PartnerEvidence.fileHash.
  attendanceSheetHash?: string;
  /// Hashes of all attendance sheets the partner has previously
  /// uploaded (so we can detect re-use).
  partnerAttendanceSheetHashes: string[];
  /// Hashes of photos attached + photos previously uploaded.
  photoHashes: string[];
  partnerHistoricalPhotoHashes: string[];
  /// Hash of the submission attempting an edit (engine pre-checks).
  isEditingVerifiedRecord?: boolean;
};

// ────────── Public API ──────────

export function detectFraudFlags(candidate: PartnerActivity, ctx: FraudContext): FraudFlag[] {
  const flags: FraudFlag[] = [];

  if (rule_outsideScope(candidate, ctx))                 flags.push("OutsideScope");
  if (rule_missingSchoolAssignment(candidate))           flags.push("MissingSchoolAssignment");
  if (rule_afterContractEnd(candidate, ctx))             flags.push("AfterContractEnd");
  if (rule_editAfterVerified(ctx))                       flags.push("EditAfterVerified");
  if (rule_duplicateSchoolDateActivity(candidate, ctx))  flags.push("DuplicateSchoolDateActivity");
  if (rule_duplicateAttendanceSheet(ctx))                flags.push("DuplicateAttendanceSheet");
  if (rule_reusedPhoto(ctx))                             flags.push("ReusedPhoto");
  if (rule_gpsMismatch(ctx))                             flags.push("GPSMismatch");
  if (rule_unrealisticParticipantCount(candidate))       flags.push("UnrealisticParticipantCount");
  if (rule_followUpBeforeOriginal(candidate, ctx))       flags.push("FollowUpBeforeOriginal");

  return flags;
}

// ────────── Rule implementations ──────────

function rule_outsideScope(c: PartnerActivity, ctx: FraudContext): boolean {
  const r = canPartnerAct({
    scope: ctx.scope,
    schoolId: c.schoolId,
    schoolDistrictId: ctx.schoolDistrictId,
    schoolClusterId: ctx.schoolClusterId,
    activityKind: c.kind,
    intervention: c.intervention,
    scheduledDate: c.scheduledDate,
  });
  return r.ok === false;
}

function rule_missingSchoolAssignment(c: PartnerActivity): boolean {
  return !c.schoolId || c.schoolId.trim() === "";
}

function rule_afterContractEnd(c: PartnerActivity, ctx: FraudContext): boolean {
  return Date.parse(c.scheduledDate) > Date.parse(ctx.scope.endDate);
}

function rule_editAfterVerified(ctx: FraudContext): boolean {
  return ctx.isEditingVerifiedRecord === true;
}

function rule_duplicateSchoolDateActivity(c: PartnerActivity, ctx: FraudContext): boolean {
  const candDate = c.scheduledDate.slice(0, 10); // YYYY-MM-DD
  return ctx.recentPartnerActivities.some(
    (other) =>
      other.id !== c.id &&
      other.schoolId === c.schoolId &&
      other.kind === c.kind &&
      other.scheduledDate.slice(0, 10) === candDate,
  );
}

function rule_duplicateAttendanceSheet(ctx: FraudContext): boolean {
  if (!ctx.attendanceSheetHash) return false;
  return ctx.partnerAttendanceSheetHashes.includes(ctx.attendanceSheetHash);
}

function rule_reusedPhoto(ctx: FraudContext): boolean {
  if (ctx.photoHashes.length === 0) return false;
  return ctx.photoHashes.some((h) => ctx.partnerHistoricalPhotoHashes.includes(h));
}

function rule_gpsMismatch(ctx: FraudContext): boolean {
  if (
    ctx.submittedGpsLat == null ||
    ctx.submittedGpsLng == null ||
    ctx.schoolGpsLat == null ||
    ctx.schoolGpsLng == null
  ) {
    return false; // no signal, no flag
  }
  // Haversine — flag when submitted location is >2km from the school.
  const distKm = haversineKm(
    ctx.submittedGpsLat, ctx.submittedGpsLng,
    ctx.schoolGpsLat, ctx.schoolGpsLng,
  );
  return distKm > 2;
}

function rule_unrealisticParticipantCount(c: PartnerActivity): boolean {
  const teachers = c.participants?.teachers ?? 0;
  const learners = c.participants?.learners ?? 0;
  // Heuristic thresholds — outside-the-band signals manipulation,
  // either inflated or accidentally zero on a delivered activity.
  if (teachers > 200) return true;       // a single training rarely exceeds 200
  if (learners > 2000) return true;
  if (c.status === "Completed" && teachers === 0 && learners === 0 && (c.kind === "TeacherTraining" || c.kind === "InSchoolTraining")) {
    return true;                          // completed training with zero participants is suspect
  }
  return false;
}

function rule_followUpBeforeOriginal(c: PartnerActivity, ctx: FraudContext): boolean {
  if (c.kind !== "FollowUpVisit") return false;
  // A follow-up requires a prior training at the same school. If
  // every prior partner activity at this school is later than this
  // one, the follow-up is being reported before the original.
  const sameSchoolEarlier = ctx.recentPartnerActivities.filter(
    (a) =>
      a.id !== c.id &&
      a.schoolId === c.schoolId &&
      (a.kind === "TeacherTraining" || a.kind === "InSchoolTraining" || a.kind === "CoachingSession") &&
      Date.parse(a.scheduledDate) <= Date.parse(c.scheduledDate),
  );
  return sameSchoolEarlier.length === 0;
}

// ────────── Helpers ──────────

function haversineKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371; // km
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

function toRad(deg: number): number { return (deg * Math.PI) / 180; }
