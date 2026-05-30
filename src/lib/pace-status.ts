// Single source of truth for pace status. Apply across My Targets,
// Team Targets, Coverage, Leaderboard so the same staff member always
// shows the same pace status.

export type PaceStatus = "On Track" | "Needs Attention" | "Critical";

export function getPaceStatus(args: {
  completed: number;
  target: number;
  expectedByNow: number;        // expected verified count given elapsed FY
  // Optional context fields. When provided, the helper de-prioritizes
  // raw shortfalls that are explained by approved leave / holidays.
  leaveDays?: number;
  publicHolidays?: number;
  blockedDays?: number;
}): PaceStatus {
  const expected = Math.max(1, args.expectedByNow);
  const ratio = args.completed / expected;
  // Adjust for protected non-working days. Each protected day allows
  // up to 5 visits not happening before degrading status.
  const protectedDays =
    (args.leaveDays ?? 0) + (args.publicHolidays ?? 0) + (args.blockedDays ?? 0);
  const protectedTolerance = protectedDays * 5 / Math.max(1, args.target);
  const adjustedRatio = Math.min(1.5, ratio + protectedTolerance);

  if (adjustedRatio >= 0.95) return "On Track";
  if (adjustedRatio >= 0.80) return "Needs Attention";
  return "Critical";
}
