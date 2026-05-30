// Per-role hero data for the unified dashboard hero.
//
// Each role's dashboard renders the same header + greeting hero
// structure (title strip · mountain gradient · greeting · chips · CTAs)
// so the experience feels coherent across roles. The numbers and
// language change per role to reflect what that user is accountable
// for — a Country Director leads with regions and approvals, a CCEO
// with schools and SSA scores.
//
// Greeting text + first name resolve from the signed-in session at
// render time (not stored here), so the welcome is always personalised.

export type HeroChipTone = "good" | "info" | "warn";

export type HeroChip = {
  key:     string;
  tone:    HeroChipTone;
  label:   string;
  caption: string;
};

export type HeroCta = {
  label: string;
  href:  string;
};

export type DashboardHeroContent = {
  title:     string;
  pillLabel: string;
  filters: {
    month:          string;
    monthCaption:   string;
    compare:        string;
    compareCaption: string;
    region:         string;
    regionCaption:  string;
  };
  quote:        string;
  subtext:      string;
  chips:        HeroChip[];
  primaryCta:   HeroCta;
  secondaryCta: HeroCta;
};

// ────────── CCEO — Field Operating View ──────────

export const cceoHeroContent: DashboardHeroContent = {
  title:     "Main Dashboard",
  pillLabel: "CCEO",
  filters: {
    month:          "May 2025",
    monthCaption:   "This Month",
    compare:        "Compare: Apr 2025",
    compareCaption: "Compare to",
    region:         "Kigun District",
    regionCaption:  "All Clusters",
  },
  quote:   "Lead boldly. Serve deeply. Change lives.",
  subtext: "Every school you reach becomes a community that thrives.",
  chips: [
    { key: "ssa",      tone: "good", label: "+0.3 SSA",         caption: "vs Apr"           },
    { key: "champion", tone: "info", label: "4 Champion-ready", caption: "ready to promote" },
    { key: "critical", tone: "warn", label: "5 Critical",       caption: "below 6.0"        },
  ],
  primaryCta:   { label: "Review This Week", href: "/planning" },
  secondaryCta: { label: "Open Route Plan",  href: "/route"    },
};

// ────────── Country Director — Executive ──────────

export const directorHeroContent: DashboardHeroContent = {
  title:     "Country Director Dashboard",
  pillLabel: "Executive View",
  filters: {
    month:          "May 2025",
    monthCaption:   "This Month",
    compare:        "Compare: Apr 2025",
    compareCaption: "Compare to",
    region:         "Uganda",
    regionCaption:  "Country",
  },
  quote:   "Steward the mission. Steady the field. Sharpen the wins.",
  subtext: "Every region you raise raises the country with it.",
  chips: [
    { key: "target",   tone: "good", label: "+5 pp Target", caption: "vs Apr"          },
    { key: "approvals",tone: "info", label: "154 Approvals", caption: "awaiting review" },
    { key: "behind",   tone: "warn", label: "1 Region Behind", caption: "North 58%" },
  ],
  primaryCta:   { label: "Review Approvals",   href: "/approvals" },
  secondaryCta: { label: "Open Country Report", href: "/reports"   },
};

// ────────── Country Program Lead ──────────

export const cplHeroContent: DashboardHeroContent = {
  title:     "Country Program Lead Dashboard",
  pillLabel: "Field View",
  filters: {
    month:          "May 2025",
    monthCaption:   "This Month",
    compare:        "Compare: Apr 2025",
    compareCaption: "Compare to",
    region:         "Central",
    regionCaption:  "All Districts",
  },
  quote:   "Coach the field. Close the gaps. Multiply the wins.",
  subtext: "Strong CCEOs build strong schools build a stronger country.",
  chips: [
    { key: "ssa",     tone: "good", label: "+0.4 SSA",      caption: "region trend"      },
    { key: "cceos",   tone: "info", label: "12 CCEOs",      caption: "on track"          },
    { key: "behind",  tone: "warn", label: "3 CCEOs Behind", caption: "need a debrief"   },
  ],
  primaryCta:   { label: "Plan This Week",    href: "/planning"    },
  secondaryCta: { label: "Open Approvals",    href: "/approvals"   },
};

// ────────── RVP — Regional VP ──────────

export const rvpHeroContent: DashboardHeroContent = {
  title:     "Regional VP Dashboard",
  pillLabel: "Regional View",
  filters: {
    month:          "May 2025",
    monthCaption:   "This Month",
    compare:        "Compare: Apr 2025",
    compareCaption: "Compare to",
    region:         "East & Central Africa",
    regionCaption:  "All Countries",
  },
  quote:   "Set the standard. Spread what works. Multiply the leaders.",
  subtext: "Every country you raise raises the region with it.",
  chips: [
    { key: "target",     tone: "good", label: "+3 pp Region", caption: "vs Apr"            },
    { key: "countries",  tone: "info", label: "5 Countries",  caption: "above target"      },
    { key: "watch",      tone: "warn", label: "1 Country Watch", caption: "needs attention" },
  ],
  primaryCta:   { label: "Review Countries", href: "/dashboards/rvp" },
  secondaryCta: { label: "Open Region Report", href: "/reports"      },
};

// ────────── Program Accountant — Finance ──────────

export const accountantHeroContent: DashboardHeroContent = {
  title:     "Finance Dashboard",
  pillLabel: "Finance View",
  filters: {
    month:          "May 2025",
    monthCaption:   "This Month",
    compare:        "Compare: Apr 2025",
    compareCaption: "Compare to",
    region:         "All Funds",
    regionCaption:  "Scope",
  },
  quote:   "Steward every shilling. Fuel every visit.",
  subtext: "Finance keeps the field moving — clarity here, momentum there.",
  chips: [
    { key: "utilization", tone: "good", label: "64% Utilized",     caption: "of FY budget"      },
    { key: "pending",     tone: "info", label: "154 Pending",      caption: "fund requests"     },
    { key: "overdue",     tone: "warn", label: "782 Overdue",      caption: "activities"        },
  ],
  primaryCta:   { label: "Review Fund Requests", href: "/fund-requests" },
  secondaryCta: { label: "Open Budget Report",   href: "/budget"        },
};

// ────────── Impact Assessment — M&E ──────────

export const impactHeroContent: DashboardHeroContent = {
  title:     "Impact & M&E Dashboard",
  pillLabel: "Impact View",
  filters: {
    month:          "May 2025",
    monthCaption:   "This Month",
    compare:        "Compare: Apr 2025",
    compareCaption: "Compare to",
    region:         "All Programs",
    regionCaption:  "Scope",
  },
  quote:   "Measure what matters. Verify what's claimed. Tell the truth.",
  subtext: "Strong evidence builds the case for the next decade of impact.",
  chips: [
    { key: "rate",     tone: "good", label: "92% Verified",   caption: "of submissions" },
    { key: "queue",    tone: "info", label: "7,842 IDs",       caption: "in review queue" },
    { key: "flagged",  tone: "warn", label: "1,126 Flagged",   caption: "returned"        },
  ],
  primaryCta:   { label: "Open Review Queue",  href: "/queue"     },
  secondaryCta: { label: "Open Impact Report", href: "/analytics" },
};

// ────────── HR — People & Performance ──────────

export const hrHeroContent: DashboardHeroContent = {
  title:     "People & Performance Dashboard",
  pillLabel: "HR View",
  filters: {
    month:          "May 2025",
    monthCaption:   "This Month",
    compare:        "Compare: Apr 2025",
    compareCaption: "Compare to",
    region:         "All Staff",
    regionCaption:  "Scope",
  },
  quote:   "Grow the team. Guard their well-being. Celebrate the wins.",
  subtext: "Strong leaders build strong teams build a stronger mission.",
  chips: [
    { key: "engagement", tone: "good", label: "84% Engaged",      caption: "active this month" },
    { key: "leave",      tone: "info", label: "214 On Leave",      caption: "or conflicts"      },
    { key: "review",     tone: "warn", label: "6 Performance",     caption: "reviews due"       },
  ],
  primaryCta:   { label: "Open Leaderboard", href: "/leaderboard" },
  secondaryCta: { label: "Review Leave",     href: "/leave"       },
};

// ────────── Resolver helper ──────────
//
// Map an EdifyRole string to the right hero content. Falls back to
// CCEO if a role we don't yet support comes through (e.g., Admin —
// admins land on the director dashboard, so the resolver routes them
// there explicitly).

export type HeroRole =
  | "CCEO"
  | "CountryProgramLead"
  | "CountryDirector"
  | "RVP"
  | "ProgramAccountant"
  | "ImpactAssessment"
  | "HumanResource"
  | "Admin";

export function heroContentForRole(role: HeroRole): DashboardHeroContent {
  switch (role) {
    case "CCEO":               return cceoHeroContent;
    case "CountryProgramLead": return cplHeroContent;
    case "CountryDirector":    return directorHeroContent;
    case "Admin":              return directorHeroContent;
    case "RVP":                return rvpHeroContent;
    case "ProgramAccountant":  return accountantHeroContent;
    case "ImpactAssessment":   return impactHeroContent;
    case "HumanResource":      return hrHeroContent;
  }
}
