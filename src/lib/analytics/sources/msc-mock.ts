// Most Significant Change (MSC) stories.
//
// Workflow: Submitted → PLReviewed → Verified → DonorReady. Some stories link
// to a real SSA or exam improvement so the engine can cross-check. Tagged
// FY2026, with a district carried for geography scope. Pure.

export type MscWorkflowStatus = "Submitted" | "PLReviewed" | "Verified" | "DonorReady";

export type MscStory = {
  id: string;
  schoolId: string;
  district: string;
  intervention: string; // one of the 8 SSA areas
  title: string;
  summary: string;
  status: MscWorkflowStatus;
  submittedBy: string;
  submittedAt: string; // ISO
  fy: string; // "FY2026"
  linkedSsaImprovement?: { area: string; from: number; to: number };
  linkedExamImprovement?: { from: number; to: number };
};

export const mscMock: MscStory[] = [
  { id: "MSC-1", schoolId: "GAP-NTR-2", district: "Mukono", intervention: "Teaching & Learning", title: "P3 readers double in a term", summary: "After phonics coaching, the number of P3 pupils reading at grade level rose sharply.", status: "DonorReady", submittedBy: "CCEO Sarah Nanyongo", submittedAt: "2026-05-20", fy: "FY2026", linkedSsaImprovement: { area: "Teaching & Learning", from: 5, to: 7 }, linkedExamImprovement: { from: 61, to: 68 } },
  { id: "MSC-2", schoolId: "GAP-NTR-1", district: "Mukono", intervention: "Leadership", title: "Head teacher turns around morning routines", summary: "Leadership coaching led to consistent morning briefings and better staff punctuality.", status: "Verified", submittedBy: "CCEO Sarah Nanyongo", submittedAt: "2026-04-12", fy: "FY2026", linkedSsaImprovement: { area: "Leadership", from: 4, to: 6 } },
  { id: "MSC-3", schoolId: "GAP-NTR-4", district: "Kayunga", intervention: "Learning Environment", title: "Community rebuilds the classroom block", summary: "Parents mobilised to repair classrooms after a school-improvement plan.", status: "PLReviewed", submittedBy: "CCEO Sarah Nanyongo", submittedAt: "2026-05-02", fy: "FY2026" },
  { id: "MSC-4", schoolId: "GAP-NV-3", district: "Mukono", intervention: "Education Technology", title: "Tablet library opens", summary: "A donated tablet set is now used for numeracy practice twice a week.", status: "Submitted", submittedBy: "Partner · Numeracy First", submittedAt: "2026-03-30", fy: "FY2026" },
  { id: "MSC-5", schoolId: "GAP-NSSA-1", district: "Kayunga", intervention: "Christlike Behaviour", title: "Peer-mentoring reduces absenteeism", summary: "A pupil mentoring scheme cut chronic absenteeism over two terms.", status: "PLReviewed", submittedBy: "CCEO Sarah Nanyongo", submittedAt: "2026-06-01", fy: "FY2026" },
  { id: "MSC-6", schoolId: "GAP-NTR-3", district: "Mukono", intervention: "Financial Health", title: "Transparent fees rebuild parent trust", summary: "Publishing a simple fees ledger improved collections and parent confidence.", status: "Verified", submittedBy: "PL Mary Aciro", submittedAt: "2026-04-28", fy: "FY2026" },
  { id: "MSC-7", schoolId: "GAP-NC-1", district: "Mukono", intervention: "Government Requirements & Compliance", title: "School finally registers", summary: "Compliance support helped the school complete its registration paperwork.", status: "DonorReady", submittedBy: "CCEO Sarah Nanyongo", submittedAt: "2026-06-10", fy: "FY2026" },
];
