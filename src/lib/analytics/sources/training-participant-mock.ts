// Training participants — teachers / school leaders trained.
//
// "Teachers Trained" / "School Leaders Trained" dedup by identityKey across the
// period (same person in two trainings counts once). Tagged FY2026. A few
// identityKey duplicates are included on purpose to prove the dedup. Pure.

export type ParticipantType =
  | "Teacher"
  | "SchoolLeader"
  | "Parent"
  | "Student"
  | "DistrictOfficial"
  | "Other";

export type ParticipantEvidenceStatus = "Captured" | "Uploaded" | "CceoConfirmed" | "MeVerified" | "Rejected";

export type TrainingParticipantRecord = {
  id: string;
  activityId: string;
  schoolId: string;
  fy: string; // "FY2026"
  date: string; // ISO
  participantType: ParticipantType;
  participantName: string;
  /** Canonical dedup key (person identity). Dups across trainings count once. */
  identityKey: string;
  evidenceStatus: ParticipantEvidenceStatus;
};

const V: ParticipantEvidenceStatus = "MeVerified";

export const trainingParticipantMock: TrainingParticipantRecord[] = [
  // GAP-NTR-2 · phonics training (T&L) — teachers
  { id: "TP-001", activityId: "TR-FY26-NTR2-A", schoolId: "GAP-NTR-2", fy: "FY2026", date: "2026-02-12", participantType: "Teacher", participantName: "Aisha Nakato", identityKey: "tch:aisha-nakato:GAP-NTR-2", evidenceStatus: V },
  { id: "TP-002", activityId: "TR-FY26-NTR2-A", schoolId: "GAP-NTR-2", fy: "FY2026", date: "2026-02-12", participantType: "Teacher", participantName: "Brian Okello", identityKey: "tch:brian-okello:GAP-NTR-2", evidenceStatus: V },
  { id: "TP-003", activityId: "TR-FY26-NTR2-A", schoolId: "GAP-NTR-2", fy: "FY2026", date: "2026-02-12", participantType: "SchoolLeader", participantName: "Rose Nakimuli", identityKey: "ldr:rose-nakimuli:GAP-NTR-2", evidenceStatus: V },
  // GAP-NTR-2 · follow-up coaching — Aisha attends AGAIN (dedup target)
  { id: "TP-004", activityId: "TR-FY26-NTR2-B", schoolId: "GAP-NTR-2", fy: "FY2026", date: "2026-05-09", participantType: "Teacher", participantName: "Aisha Nakato", identityKey: "tch:aisha-nakato:GAP-NTR-2", evidenceStatus: V },
  { id: "TP-005", activityId: "TR-FY26-NTR2-B", schoolId: "GAP-NTR-2", fy: "FY2026", date: "2026-05-09", participantType: "Teacher", participantName: "Daniel Mwesigwa", identityKey: "tch:daniel-mwesigwa:GAP-NTR-2", evidenceStatus: V },

  // GAP-NTR-1
  { id: "TP-006", activityId: "TR-FY26-NTR1-A", schoolId: "GAP-NTR-1", fy: "FY2026", date: "2026-03-03", participantType: "Teacher", participantName: "Grace Atim", identityKey: "tch:grace-atim:GAP-NTR-1", evidenceStatus: V },
  { id: "TP-007", activityId: "TR-FY26-NTR1-A", schoolId: "GAP-NTR-1", fy: "FY2026", date: "2026-03-03", participantType: "SchoolLeader", participantName: "John Mubiru", identityKey: "ldr:john-mubiru:GAP-NTR-1", evidenceStatus: "CceoConfirmed" },

  // GAP-NTR-3
  { id: "TP-008", activityId: "TR-FY26-NTR3-A", schoolId: "GAP-NTR-3", fy: "FY2026", date: "2026-04-21", participantType: "Teacher", participantName: "Peter Wamala", identityKey: "tch:peter-wamala:GAP-NTR-3", evidenceStatus: V },
  { id: "TP-009", activityId: "TR-FY26-NTR3-A", schoolId: "GAP-NTR-3", fy: "FY2026", date: "2026-04-21", participantType: "Teacher", participantName: "Mary Auma", identityKey: "tch:mary-auma:GAP-NTR-3", evidenceStatus: V },

  // GAP-NV-3
  { id: "TP-010", activityId: "TR-FY26-NV3-A", schoolId: "GAP-NV-3", fy: "FY2026", date: "2026-01-29", participantType: "Teacher", participantName: "Joseph Otim", identityKey: "tch:joseph-otim:GAP-NV-3", evidenceStatus: V },
  { id: "TP-011", activityId: "TR-FY26-NV3-A", schoolId: "GAP-NV-3", fy: "FY2026", date: "2026-01-29", participantType: "SchoolLeader", participantName: "Florence Nabasa", identityKey: "ldr:florence-nabasa:GAP-NV-3", evidenceStatus: V },

  // GAP-NSSA-1 (Kayunga) — teachers trained even before SSA done
  { id: "TP-012", activityId: "TR-FY26-NSSA1-A", schoolId: "GAP-NSSA-1", fy: "FY2026", date: "2026-02-26", participantType: "Teacher", participantName: "Samuel Lubega", identityKey: "tch:samuel-lubega:GAP-NSSA-1", evidenceStatus: V },
  { id: "TP-013", activityId: "TR-FY26-NSSA1-A", schoolId: "GAP-NSSA-1", fy: "FY2026", date: "2026-02-26", participantType: "Teacher", participantName: "Joyce Achieng", identityKey: "tch:joyce-achieng:GAP-NSSA-1", evidenceStatus: "Uploaded" },

  // GAP-NC-1 (Mukono)
  { id: "TP-014", activityId: "TR-FY26-NC1-A", schoolId: "GAP-NC-1", fy: "FY2026", date: "2026-06-04", participantType: "Teacher", participantName: "Robert Sserwanga", identityKey: "tch:robert-sserwanga:GAP-NC-1", evidenceStatus: V },
  { id: "TP-015", activityId: "TR-FY26-NC1-A", schoolId: "GAP-NC-1", fy: "FY2026", date: "2026-06-04", participantType: "SchoolLeader", participantName: "Beatrice Akello", identityKey: "ldr:beatrice-akello:GAP-NC-1", evidenceStatus: V },
];
