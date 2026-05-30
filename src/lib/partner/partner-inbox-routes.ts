// Routing metadata for /partner/inbox/[tab]. Lives in
// its own module so middleware-friendly imports stay slim and the
// sidebar + page both read from one source.

export type InboxRouteKey =
  | "assigned"
  | "due-this-week"
  | "needs-evidence"
  | "needs-report"
  | "returned"
  | "awaiting-verification"
  | "verified"
  | "completed";

export const INBOX_ROUTES: ReadonlyArray<{
  key: InboxRouteKey;
  title: string;
  subtitle: string;
  badgeCount: number;
  tone: "neutral" | "warn" | "danger" | "info" | "success";
}> = [
  { key: "assigned",              title: "Assigned to Us",          subtitle: "Activities Edify has assigned to you that need a partner action.",                badgeCount: 12, tone: "neutral" },
  { key: "due-this-week",         title: "Due This Week",           subtitle: "Activities scheduled for this week — deliver these on time.",                     badgeCount: 8,  tone: "info"    },
  { key: "needs-evidence",        title: "Needs Evidence",          subtitle: "Activities waiting on you to upload evidence before they can move to CCEO.",      badgeCount: 14, tone: "danger"  },
  { key: "needs-report",          title: "Needs Report",            subtitle: "Activities where the partner report has not yet been submitted.",                 badgeCount: 6,  tone: "warn"    },
  { key: "returned",              title: "Returned for Correction", subtitle: "Specific items returned by your CCEO / PL / M&E with what to fix.",               badgeCount: 3,  tone: "warn"    },
  { key: "awaiting-verification", title: "Awaiting Verification",   subtitle: "Activities pending Edify M&E verification before they count in official reports.",badgeCount: 7,  tone: "warn"    },
  { key: "verified",              title: "Verified / Counted",      subtitle: "Activities verified by M&E and counted in Edify's official reporting.",           badgeCount: 16, tone: "success" },
  { key: "completed",             title: "Completed",               subtitle: "Activities fully closed — work delivered, evidence accepted, payment cleared.",   badgeCount: 22, tone: "success" },
];
