// Data-quality engine — pure integrity audit over the school + SSA universe.
//
// The Data Intake & Readiness Engine promises "unapproved / malformed data does
// not feed the planning engine". This module is the check that backs that
// promise: it scans normalised school records and flags the issues that would
// poison targets, leaderboards, or donor reports — a school with no region
// (can't roll up), an enrollment of zero (can't size impact), an SSA score
// outside 0–10 (corrupt upload), a school that was never assessed (planning is
// flying blind). Pure & client-safe; the mock layer does the joining.

export type QualitySeverity = "Error" | "Warning";

export type QualityCategory =
  | "Missing region"
  | "Unknown district"
  | "Missing enrollment"
  | "SSA score out of range"
  | "Never assessed"
  | "Unassigned CCEO";

export type QualityIssue = {
  schoolId: string;
  schoolName: string;
  category: QualityCategory;
  severity: QualitySeverity;
  detail: string;
};

export type QualitySchool = {
  schoolId: string;
  schoolName: string;
  district?: string;
  region?: string;
  enrollment?: number;
  assignedCceo?: string;
  /** Latest SSA scores to range-check (0–10). Empty/undefined → not assessed. */
  ssaScores?: number[];
};

const ERROR_CATEGORIES = new Set<QualityCategory>(["Missing region", "Unknown district", "SSA score out of range"]);

function severityFor(cat: QualityCategory): QualitySeverity {
  return ERROR_CATEGORIES.has(cat) ? "Error" : "Warning";
}

function issue(s: QualitySchool, category: QualityCategory, detail: string): QualityIssue {
  return { schoolId: s.schoolId, schoolName: s.schoolName, category, severity: severityFor(category), detail };
}

/** Audit one school. `isKnownDistrict` validates the district against geography. */
export function auditSchool(s: QualitySchool, isKnownDistrict: (d: string) => boolean): QualityIssue[] {
  const out: QualityIssue[] = [];

  if (!s.region || !s.region.trim()) {
    out.push(issue(s, "Missing region", `${s.schoolId} has no region — it can't roll up into regional or donor reports.`));
  }
  if (s.district && !isKnownDistrict(s.district)) {
    out.push(issue(s, "Unknown district", `District "${s.district}" is not in the Uganda district registry.`));
  }
  if (s.enrollment === undefined || s.enrollment <= 0) {
    out.push(issue(s, "Missing enrollment", `${s.schoolId} has no enrollment — impact and cost-per-child can't be computed.`));
  }
  if (!s.assignedCceo || !s.assignedCceo.trim()) {
    out.push(issue(s, "Unassigned CCEO", `${s.schoolId} has no assigned CCEO — it falls outside every portfolio.`));
  }
  const scores = s.ssaScores ?? [];
  if (scores.length === 0) {
    out.push(issue(s, "Never assessed", `${s.schoolId} has no SSA on record — planning for it is unguided.`));
  } else {
    const bad = scores.filter((n) => !Number.isFinite(n) || n < 0 || n > 10);
    if (bad.length > 0) {
      out.push(issue(s, "SSA score out of range", `${s.schoolId} has ${bad.length} SSA score(s) outside 0–10 (${bad.join(", ")}).`));
    }
  }
  return out;
}

export type QualityReport = {
  totalSchools: number;
  cleanSchools: number;
  /** 0–100 — share of schools with no issue at all. */
  qualityScore: number;
  errors: number;
  warnings: number;
  byCategory: Array<{ category: QualityCategory; severity: QualitySeverity; count: number }>;
  issues: QualityIssue[];
};

const CATEGORY_ORDER: QualityCategory[] = [
  "Missing region", "Unknown district", "SSA score out of range",
  "Never assessed", "Missing enrollment", "Unassigned CCEO",
];

/** Audit a whole universe → a roll-up report (errors first, stable order). */
export function auditSchools(schools: QualitySchool[], isKnownDistrict: (d: string) => boolean): QualityReport {
  const issues: QualityIssue[] = [];
  const dirty = new Set<string>();
  for (const s of schools) {
    const found = auditSchool(s, isKnownDistrict);
    for (const i of found) {
      issues.push(i);
      dirty.add(s.schoolId);
    }
  }

  const counts = new Map<QualityCategory, number>();
  for (const i of issues) counts.set(i.category, (counts.get(i.category) ?? 0) + 1);
  const byCategory = CATEGORY_ORDER.filter((c) => counts.has(c)).map((category) => ({
    category,
    severity: severityFor(category),
    count: counts.get(category)!,
  }));

  const total = schools.length;
  const clean = total - dirty.size;
  // Errors before warnings, then by the canonical category order.
  const sevRank = (s: QualitySeverity) => (s === "Error" ? 0 : 1);
  issues.sort(
    (a, b) => sevRank(a.severity) - sevRank(b.severity)
      || CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category)
      || a.schoolId.localeCompare(b.schoolId),
  );

  return {
    totalSchools: total,
    cleanSchools: clean,
    qualityScore: total === 0 ? 100 : Math.round((clean / total) * 100),
    errors: issues.filter((i) => i.severity === "Error").length,
    warnings: issues.filter((i) => i.severity === "Warning").length,
    byCategory,
    issues,
  };
}
