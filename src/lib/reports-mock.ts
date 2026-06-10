// Generated reports + scheduled reports — used by /reports.
//
// Also home to the CCEO auto-generated report catalogue (spec §21):
// seven reports assembled from the records the CCEO already produces
// (plans, completed activities, evidence, SSA uploads, partner work,
// cluster meetings, targets) — no manual report writing.

export type ReportFormat = "PDF" | "XLSX" | "CSV";

export type GeneratedReport = {
  id:         string;
  title:      string;
  period:     string;
  format:     ReportFormat;
  sizeKb:     number;
  generatedBy:string;
  generatedAt:string;
  href:       string; // mock download link
};

export const recentReports: GeneratedReport[] = [
  { id: "r1", title: "Country Performance — Uganda",  period: "Apr 2025",            format: "PDF",  sizeKb: 1280, generatedBy: "Sarah Okello",   generatedAt: "May 02, 2025 · 17:10", href: "#" },
  { id: "r2", title: "Verified Impact Leaderboard",   period: "Q1 FY 24/25",          format: "PDF",  sizeKb:  840, generatedBy: "Esther Wanjiru", generatedAt: "Apr 30, 2025 · 14:22", href: "#" },
  { id: "r3", title: "Funds & Disbursement",          period: "Apr 2025",            format: "XLSX", sizeKb: 2410, generatedBy: "Moses Tindi",    generatedAt: "Apr 28, 2025 · 09:55", href: "#" },
  { id: "r4", title: "SSA Performance — All Regions", period: "Q1 FY 24/25",          format: "PDF",  sizeKb: 1640, generatedBy: "Grace Alimo",    generatedAt: "Apr 22, 2025 · 11:00", href: "#" },
  { id: "r5", title: "Team Targets · Pace Status",    period: "Apr 2025",            format: "CSV",  sizeKb:  120, generatedBy: "Daniel Mwangi",  generatedAt: "Apr 20, 2025 · 16:40", href: "#" },
  { id: "r6", title: "Leave & Holiday Impact",        period: "Apr 2025",            format: "XLSX", sizeKb:  680, generatedBy: "Anne Wairimu",   generatedAt: "Apr 18, 2025 · 10:15", href: "#" },
];

export type ScheduledReport = {
  id:        string;
  title:     string;
  cadence:   "Daily" | "Weekly" | "Monthly" | "Quarterly";
  nextRun:   string;
  recipients:string; // human-friendly list
  status:    "Active" | "Paused";
};

export const scheduledReports: ScheduledReport[] = [
  { id: "s1", title: "Country Performance",      cadence: "Monthly",   nextRun: "Jun 01, 2025 · 06:00", recipients: "Country Directors · RVP",                  status: "Active" },
  { id: "s2", title: "Verified Impact",          cadence: "Quarterly", nextRun: "Jul 01, 2025 · 06:00", recipients: "All Program Leads + Country Directors",    status: "Active" },
  { id: "s3", title: "Funds & Disbursement",     cadence: "Weekly",    nextRun: "May 19, 2025 · 06:00", recipients: "Program Accountants · Country Directors",  status: "Active" },
  { id: "s4", title: "Team Targets",             cadence: "Weekly",    nextRun: "May 19, 2025 · 06:00", recipients: "Country Program Leads",                    status: "Active" },
  { id: "s5", title: "SSA Performance",          cadence: "Monthly",   nextRun: "Jun 01, 2025 · 06:00", recipients: "Impact Assessors · Country Directors",     status: "Paused" },
];

// ─── CCEO auto-generated reports (spec §21) ─────────────────────────

export type CceoAutoReport = {
  id:            string;
  title:         string;
  cadence:       "Weekly" | "Monthly" | "Quarterly" | "Continuous";
  /** One-line purpose of the report. */
  description:   string;
  /** Which workflow records feed it — the "auto-generated from" line. */
  generatedFrom: string[];
  /** When it was last assembled and the window it covers. */
  freshness:     string;
  /** Headline numbers shown on the collapsed card. */
  keyNumbers:    { label: string; value: string }[];
  /** Expanded detail view — simple narrative sections. */
  sections:      { heading: string; lines: string[] }[];
  /** Page where the live underlying data is. */
  liveHref:      string;
  /** Existing print view when one trivially covers this report. */
  printHref?:    string;
};

export const cceoAutoReports: CceoAutoReport[] = [
  {
    id: "weekly-update",
    title: "Weekly Update",
    cadence: "Weekly",
    description: "What you planned vs what happened this week, assembled from your plan and debriefs.",
    generatedFrom: ["My Plan activities", "Daily field debriefs", "Weekly fund request", "Evidence uploads"],
    freshness: "Assembled Mon 06:00 · covers Jun 02 – Jun 08",
    keyNumbers: [
      { label: "Activities completed", value: "11 / 14" },
      { label: "Schools visited", value: "8" },
      { label: "Evidence uploaded", value: "10" },
      { label: "Funds accounted", value: "UGX 1.4M" },
    ],
    sections: [
      { heading: "Completed this week", lines: ["8 school visits across Mukono and Wakiso", "2 trainings (Numeracy Foundations · SLT coaching)", "1 cluster meeting — Kireka cluster, 11 schools attended"] },
      { heading: "Slipped / rescheduled", lines: ["Sunrise Primary training moved to Tue (head teacher away)", "2 visits deferred — public holiday block on Friday"] },
      { heading: "Money", lines: ["Weekly fund request UGX 1.6M disbursed Mon", "UGX 1.4M accounted with receipts · UGX 0.2M pending"] },
    ],
    liveHref: "/my-plan",
  },
  {
    id: "monthly-update",
    title: "Monthly Update",
    cadence: "Monthly",
    description: "Portfolio month in review — reach, completions, verification and payment status.",
    generatedFrom: ["Completed activities (Salesforce-gated)", "IA verification queue", "Payment ledger", "Enrollment records"],
    freshness: "Assembled Jun 01 · covers May 2026",
    keyNumbers: [
      { label: "Schools reached", value: "16 / 18" },
      { label: "Activities completed", value: "42" },
      { label: "IA verified", value: "31" },
      { label: "Learners impacted", value: "6,420" },
    ],
    sections: [
      { heading: "Reach", lines: ["16 of 18 portfolio schools had ≥1 qualifying activity", "2 idle schools flagged: Mukono Hill, Bukoto Junior"] },
      { heading: "Pipeline", lines: ["42 completed → 31 IA-verified → 27 paid", "3 activities blocked at the Salesforce gate (missing IDs)"] },
      { heading: "Quality flags", lines: ["1 evidence return (Hope Primary attendance sheet)", "1 payment query (Kireka cluster refreshments)"] },
    ],
    liveHref: "/analytics",
    printHref: "/donor-reporting/print",
  },
  {
    id: "core-school-report",
    title: "Core School Report",
    cadence: "Quarterly",
    description: "Per-core-school progress against the 4-visit + 4-training package, with SSA movement.",
    generatedFrom: ["Core package slots (4+4)", "Visit & training records", "Follow-up SSA uploads"],
    freshness: "Assembled Jun 01 · FY 2026 to date",
    keyNumbers: [
      { label: "Core schools", value: "5" },
      { label: "Package slots done", value: "26 / 40" },
      { label: "On track", value: "3" },
      { label: "SSA improved", value: "4" },
    ],
    sections: [
      { heading: "On track (3)", lines: ["Grace Academy — 7/8 slots, SSA 6.2 → 7.1", "Living Word School — 6/8 slots, follow-up SSA scheduled", "St. Peter's Junior — 6/8 slots, SSA 5.8 → 6.4"] },
      { heading: "Behind package (2)", lines: ["Hope Primary — 4/8 slots, 2 trainings unplanned", "Seeta Junior — 3/8 slots, partner-delegated work overdue"] },
    ],
    liveHref: "/core-schools",
  },
  {
    id: "partner-work-summary",
    title: "Partner Work Summary",
    cadence: "Monthly",
    description: "Delegated school work by partner — scheduled, completed, evidence and overdue items.",
    generatedFrom: ["Partner delegations", "Partner activity records", "Partner evidence uploads"],
    freshness: "Assembled Jun 08 · covers May 09 – Jun 08",
    keyNumbers: [
      { label: "Schools delegated", value: "6" },
      { label: "Completed", value: "9 / 13" },
      { label: "Evidence in", value: "7" },
      { label: "Overdue", value: "2" },
    ],
    sections: [
      { heading: "Lift Them Up", lines: ["4 schools · 6/8 activities completed", "1 training overdue at Seeta Junior (3 days)", "2 schools with no scheduled activity — follow up"] },
      { heading: "Bright Future", lines: ["2 schools · 3/5 activities completed", "Kireka Primary Q2 evidence uploaded — awaiting your review"] },
    ],
    liveHref: "/partners",
  },
  {
    id: "cluster-fellowship-report",
    title: "Cluster / Parish Fellowship Report",
    cadence: "Monthly",
    description: "Cluster meeting cadence, attendance, and topics across your clusters.",
    generatedFrom: ["Cluster meeting records", "Attendance sheets", "Cluster topics"],
    freshness: "Assembled Jun 08 · covers May–Jun cycle",
    keyNumbers: [
      { label: "Clusters", value: "3" },
      { label: "Meetings held", value: "2 / 3" },
      { label: "Avg attendance", value: "78%" },
      { label: "Schools unclustered", value: "1" },
    ],
    sections: [
      { heading: "Held", lines: ["Kireka cluster — 11/13 schools, topic: learner assessment", "Faleha cluster — 9/12 schools, topic: numeracy foundations"] },
      { heading: "Due", lines: ["Mukono cluster — meeting not yet scheduled this cycle", "St. Jude Primary still unclustered — flagged for assignment"] },
    ],
    liveHref: "/clusters",
  },
  {
    id: "ssa-improvement-summary",
    title: "SSA Improvement Summary",
    cadence: "Quarterly",
    description: "SSA movement per school and the weakest intervention areas across the portfolio.",
    generatedFrom: ["SSA uploads (baseline + follow-up)", "Intervention scores", "Recommendation engine output"],
    freshness: "Assembled Jun 01 · latest SSA per school",
    keyNumbers: [
      { label: "Schools with SSA", value: "15 / 18" },
      { label: "Improved", value: "9" },
      { label: "Declined", value: "2" },
      { label: "Weakest area", value: "Records & Finance" },
    ],
    sections: [
      { heading: "Movement", lines: ["9 schools improved their SSA average since baseline", "2 declined — Living Word School flagged red (2 cycles down)", "3 schools still missing a first SSA — planning locked"] },
      { heading: "Weakest interventions", lines: ["Records & Finance — avg 4.8, lowest across the portfolio", "Teaching & Learning — avg 5.6, improving", "Recommended focus for next quarter's trainings"] },
    ],
    liveHref: "/ssa",
  },
  {
    id: "target-progress-report",
    title: "Target Progress Report",
    cadence: "Continuous",
    description: "Completed activities vs the FY target pace, with the gap and what closes it.",
    generatedFrom: ["Completed activities (Salesforce-gated)", "FY target ledger (560)", "Period-target pace engine"],
    freshness: "Live · recomputed on every completion",
    keyNumbers: [
      { label: "FY target", value: "560" },
      { label: "Completed", value: "214" },
      { label: "Expected by now", value: "226" },
      { label: "Pace", value: "12 behind" },
    ],
    sections: [
      { heading: "Pace", lines: ["214 completed vs 226 expected at this point of FY 2026", "Gap of 12 — roughly one strong field week", "Q3 was above pace; the slip is from the May holiday block"] },
      { heading: "Closing the gap", lines: ["14 activities already planned for next week", "2 idle schools scheduled would add 4 qualifying completions"] },
    ],
    liveHref: "/my-targets",
    printHref: "/donor-reporting/print",
  },
];
