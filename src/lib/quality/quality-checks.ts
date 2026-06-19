// Quality-check runs — a small in-memory log of data-quality scans.
//
// "Running a quality check" recomputes the open-issue picture: it takes the
// seeded mock baseline (rich enough to populate the page) and folds in a LIVE
// scan of the activity store (e.g. submitted/completed activities still
// missing a Salesforce ID) so each run genuinely reflects current state and
// the "scanned / last run" stamp moves.
//
// Persistence mirrors the rest of the app: a globalThis-backed array, shaped
// like a future Prisma `QualityCheckRun` row. The production swap replaces the
// array push with a real Prisma create on the QualityCheckRun model; call
// sites don't change.

import "server-only";
import { activities } from "@/lib/actions/store";
import {
  qualityCheckSeverity,
  topQualityIssues,
  type DataQualityIssue,
} from "@/lib/impact-mock";

export type QualitySeverityCount = { key: string; label: string; value: number; color: string };

export type QualityCheckRun = {
  id: string;
  ranAt: string; // ISO
  ranById: string;
  ranByName: string;
  scannedActivities: number;
  liveSalesforceGaps: number; // submitted/completed activities with no Salesforce ID
  totalIssues: number;
  bySeverity: QualitySeverityCount[];
  topIssues: DataQualityIssue[];
};

type QualityStore = { runs: QualityCheckRun[] };
const STORE_KEY = "__edify_quality_store__";
type GlobalWithStore = typeof globalThis & { [STORE_KEY]?: QualityStore };

function getStore(): QualityStore {
  const g = globalThis as GlobalWithStore;
  if (!g[STORE_KEY]) g[STORE_KEY] = { runs: [] };
  return g[STORE_KEY]!;
}

/** Latest completed run, or undefined if a check has never been run this session. */
export function latestQualityRun(): QualityCheckRun | undefined {
  return getStore().runs[0];
}

export function qualityRunHistory(limit = 10): QualityCheckRun[] {
  return getStore().runs.slice(0, limit);
}

// Pure-ish: reads the live activity store and the mock baseline, returns a
// fresh findings snapshot. Does NOT persist — the action layer pushes it.
export function computeQualityFindings(ranById: string, ranByName: string): QualityCheckRun {
  const acts = activities();
  const scanned = acts.length;
  // A real, store-derived signal: anything awaiting verification (or already
  // marked completed) that has no Salesforce Activity ID is an open data-quality
  // gap — the IA can't confirm it and it can't be counted for donors.
  const liveSalesforceGaps = acts.filter(
    (a) => (a.status === "SubmittedForVerification" || a.status === "Completed") && !a.salesforceId,
  ).length;

  // Baseline severity tiers from the seeded picture, with the live Salesforce
  // gaps added to the Critical tier (they block program counting).
  const bySeverity: QualitySeverityCount[] = qualityCheckSeverity.map((s) => ({
    key: s.key,
    label: s.label,
    color: s.color,
    value: s.key === "critical" ? s.value + liveSalesforceGaps : s.value,
  }));

  // Top issues: baseline + a live "Missing Salesforce ID" row when there are any.
  const topIssues: DataQualityIssue[] = [...topQualityIssues];
  if (liveSalesforceGaps > 0) {
    topIssues.unshift({
      key: "missing-salesforce-id",
      label: "Missing Salesforce ID (live)",
      count: liveSalesforceGaps,
      tone: "rose",
      href: "/quality-checks?issue=missing-salesforce-id",
    });
  }

  const totalIssues = bySeverity.reduce((sum, s) => sum + s.value, 0);

  return {
    id: `qc_${Date.now().toString(36)}`,
    ranAt: new Date().toISOString(),
    ranById,
    ranByName,
    scannedActivities: scanned,
    liveSalesforceGaps,
    totalIssues,
    bySeverity,
    topIssues,
  };
}

export function recordQualityRun(ranById: string, ranByName: string): QualityCheckRun {
  const run = computeQualityFindings(ranById, ranByName);
  getStore().runs.unshift(run);
  return run;
}

export function __resetQualityStore() {
  const g = globalThis as GlobalWithStore;
  g[STORE_KEY] = { runs: [] };
}
