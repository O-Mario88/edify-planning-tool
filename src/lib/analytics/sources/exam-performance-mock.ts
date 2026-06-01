// Exam performance records — collection + improvement.
//
// The engine recomputes improved/declined from score vs prevScore (the `trend`
// field is kept only so a future cached snapshot matches). Two schools are
// `collected: false` to exercise the collection-rate / missing-data path.
// Tagged FY2026. Pure.

export type ExamLevel = "Below" | "Approaching" | "Meeting" | "Exceeding";
export type ExamTrend = "improved" | "declined" | "flat" | "baseline";

export type ExamPerformanceRecord = {
  id: string;
  schoolId: string;
  fy: string; // "FY2026"
  examDate: string; // ISO
  score: number; // 0–100
  level: ExamLevel;
  prevScore?: number;
  trend: ExamTrend;
  collected: boolean;
};

export const examPerformanceMock: ExamPerformanceRecord[] = [
  { id: "EX-1",  schoolId: "GAP-NTR-2", fy: "FY2026", examDate: "2026-03-20", score: 68, level: "Meeting",     prevScore: 61, trend: "improved", collected: true },
  { id: "EX-2",  schoolId: "GAP-NTR-1", fy: "FY2026", examDate: "2026-03-20", score: 57, level: "Approaching", prevScore: 52, trend: "improved", collected: true },
  { id: "EX-3",  schoolId: "GAP-NTR-3", fy: "FY2026", examDate: "2026-03-20", score: 49, level: "Approaching", prevScore: 55, trend: "declined", collected: true },
  { id: "EX-4",  schoolId: "GAP-NTR-4", fy: "FY2026", examDate: "2026-03-21", score: 72, level: "Meeting",     prevScore: 64, trend: "improved", collected: true },
  { id: "EX-5",  schoolId: "GAP-NV-1",  fy: "FY2026", examDate: "2026-03-21", score: 44, level: "Below",       prevScore: 47, trend: "declined", collected: true },
  { id: "EX-6",  schoolId: "GAP-NV-3",  fy: "FY2026", examDate: "2026-03-22", score: 63, level: "Meeting",     prevScore: 63, trend: "flat",     collected: true },
  { id: "EX-7",  schoolId: "GAP-NSSA-1",fy: "FY2026", examDate: "2026-03-22", score: 51, level: "Approaching", prevScore: undefined, trend: "baseline", collected: true },
  { id: "EX-8",  schoolId: "GAP-NC-1",  fy: "FY2026", examDate: "2026-03-23", score: 0,  level: "Below",       collected: false, trend: "baseline" },
  { id: "EX-9",  schoolId: "GAP-NV-2",  fy: "FY2026", examDate: "2026-03-23", score: 0,  level: "Below",       collected: false, trend: "baseline" },
];
