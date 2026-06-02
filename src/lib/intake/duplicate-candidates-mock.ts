// Duplicate-candidate store — flagged-but-never-blocked school duplicates.
//
// When a school is uploaded that looks like an existing one, a candidate flag is
// recorded here (both schools remain live). IA resolves each flag in the
// Duplicate Review Queue: "Not a duplicate" (dismiss) or "Confirmed duplicate"
// (acknowledged for follow-up). We never auto-delete or auto-merge — resolution
// is a human decision and the record preserves the audit trail.
//
// Mutable, client-safe in-memory store (Year-1 mock; Year-2 = SchoolDuplicateCandidate table).

import type { DuplicateBand } from "./duplicate-detection";

export type DuplicateStatus = "Open" | "Dismissed" | "Confirmed";

export type SchoolDuplicateCandidate = {
  id: string;
  /** The newly-uploaded school that triggered the flag. */
  schoolId: string;
  schoolName: string;
  /** The existing school it may duplicate. */
  matchSchoolId: string;
  matchSchoolName: string;
  score: number;
  band: DuplicateBand;
  reasons: string[];
  status: DuplicateStatus;
  flaggedAt: string;
  flaggedBy: string;
  resolvedAt?: string;
  resolvedBy?: string;
  resolutionNote?: string;
};

// Seed: school 32815 ("Nakaseke Hills Primary School") was uploaded as a near
// duplicate of 32791 ("Nakaseke Hill Primary") — flagged for IA review.
export const duplicateCandidates: SchoolDuplicateCandidate[] = [
  {
    id: "DUP-0001",
    schoolId: "32815",
    schoolName: "Nakaseke Hills Primary School",
    matchSchoolId: "32791",
    matchSchoolName: "Nakaseke Hill Primary",
    score: 86,
    band: "Strong",
    reasons: [
      'Very similar name to "Nakaseke Hill Primary" (86% match)',
      "Same district (Nakaseke)",
      "Same region",
      "Same sub-county (Nakaseke TC)",
    ],
    status: "Open",
    flaggedAt: "2026-05-29",
    flaggedBy: "Grace Alimo",
  },
];

let seq = duplicateCandidates.length;

export function addDuplicateCandidate(input: {
  schoolId: string;
  schoolName: string;
  matchSchoolId: string;
  matchSchoolName: string;
  score: number;
  band: DuplicateBand;
  reasons: string[];
  flaggedBy: string;
  flaggedAt?: string;
}): SchoolDuplicateCandidate {
  seq += 1;
  const row: SchoolDuplicateCandidate = {
    id: `DUP-${String(seq).padStart(4, "0")}`,
    status: "Open",
    flaggedAt: input.flaggedAt ?? new Date().toISOString().slice(0, 10),
    ...input,
  };
  duplicateCandidates.unshift(row);
  return row;
}

export function resolveDuplicateCandidate(
  id: string,
  status: Extract<DuplicateStatus, "Dismissed" | "Confirmed">,
  resolvedBy: string,
  note?: string,
): SchoolDuplicateCandidate | undefined {
  const row = duplicateCandidates.find((d) => d.id === id);
  if (!row) return undefined;
  row.status = status;
  row.resolvedBy = resolvedBy;
  row.resolvedAt = new Date().toISOString().slice(0, 10);
  row.resolutionNote = note;
  return row;
}

export function openDuplicateCandidates(): SchoolDuplicateCandidate[] {
  return duplicateCandidates.filter((d) => d.status === "Open");
}

/** True when this newly-uploaded school already has an OPEN flag against a match. */
export function hasOpenFlag(schoolId: string, matchSchoolId: string): boolean {
  return duplicateCandidates.some(
    (d) => d.status === "Open" && d.schoolId === schoolId && d.matchSchoolId === matchSchoolId,
  );
}

export function openDuplicateCount(): number {
  return openDuplicateCandidates().length;
}
