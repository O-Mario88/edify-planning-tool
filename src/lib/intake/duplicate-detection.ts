// School duplicate detection — FLAG, never block.
//
// The real duplicate problem is the same school uploaded twice under DIFFERENT
// School IDs (exact-ID collisions are already rejected at validation). This
// module scores a candidate school against the existing roster and explains WHY
// it might be a duplicate. It never blocks an upload, never auto-merges, and
// never auto-deletes — it only produces a flag for the IA Duplicate Review
// Queue, where a human decides.
//
// Scoring band (per spec): 85+ = Strong, 60–84 = Potential, <60 = ignored.
//
// Pure & client-safe (no store, no IO) so both the upload preview and the
// server action can score with identical logic.

export type DuplicateBand = "Strong" | "Potential" | "None";

export const DUPLICATE_THRESHOLDS = { strong: 85, potential: 60 } as const;

export type DuplicateScoreInput = {
  schoolId: string;
  schoolName: string;
  district?: string;
  region?: string;
  subCounty?: string;
  phone?: string;
  shippingAddress?: string;
};

export type DuplicateMatch = {
  /** The existing school this candidate may duplicate. */
  matchSchoolId: string;
  matchSchoolName: string;
  score: number;
  band: DuplicateBand;
  reasons: string[];
};

// ── Text similarity helpers ────────────────────────────────────────

function normalize(s: string | undefined): string {
  return (s ?? "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
}

function tokenSet(s: string): Set<string> {
  return new Set(normalize(s).split(" ").filter(Boolean));
}

/** Jaccard overlap of word tokens (order-independent). */
function tokenJaccard(a: string, b: string): number {
  const A = tokenSet(a), B = tokenSet(b);
  if (A.size === 0 || B.size === 0) return 0;
  let inter = 0;
  for (const t of A) if (B.has(t)) inter += 1;
  return inter / (A.size + B.size - inter);
}

/** Levenshtein-ratio similarity on the normalized full strings (0..1). */
function editRatio(a: string, b: string): number {
  const x = normalize(a), y = normalize(b);
  if (!x && !y) return 1;
  if (!x || !y) return 0;
  const m = x.length, n = y.length;
  const dp = new Array(n + 1);
  for (let j = 0; j <= n; j++) dp[j] = j;
  for (let i = 1; i <= m; i++) {
    let prev = dp[0];
    dp[0] = i;
    for (let j = 1; j <= n; j++) {
      const tmp = dp[j];
      dp[j] = Math.min(
        dp[j] + 1,
        dp[j - 1] + 1,
        prev + (x[i - 1] === y[j - 1] ? 0 : 1),
      );
      prev = tmp;
    }
  }
  const dist = dp[n];
  return 1 - dist / Math.max(m, n);
}

/** Blended name similarity (0..1): best of token-overlap and edit-distance. */
export function nameSimilarity(a: string, b: string): number {
  return Math.max(tokenJaccard(a, b), editRatio(a, b));
}

// ── Scoring ────────────────────────────────────────────────────────

export function bandFor(score: number): DuplicateBand {
  if (score >= DUPLICATE_THRESHOLDS.strong) return "Strong";
  if (score >= DUPLICATE_THRESHOLDS.potential) return "Potential";
  return "None";
}

/**
 * Score a candidate against ONE existing school. Returns 0 with no reasons when
 * they share the same id (that's a hard collision handled at validation, not a
 * fuzzy duplicate) or when nothing meaningful matches.
 */
export function scorePair(candidate: DuplicateScoreInput, existing: DuplicateScoreInput): { score: number; reasons: string[] } {
  if (candidate.schoolId && candidate.schoolId === existing.schoolId) return { score: 0, reasons: [] };

  const reasons: string[] = [];
  let score = 0;

  const sim = nameSimilarity(candidate.schoolName, existing.schoolName);
  if (sim >= 0.5) {
    const pts = Math.round(sim * 60);
    score += pts;
    if (sim >= 0.95) reasons.push(`Identical school name ("${existing.schoolName}")`);
    else reasons.push(`Very similar name to "${existing.schoolName}" (${Math.round(sim * 100)}% match)`);
  }

  const sameDistrict = candidate.district && existing.district &&
    normalize(candidate.district) === normalize(existing.district);
  if (sameDistrict) { score += 25; reasons.push(`Same district (${existing.district})`); }

  if (candidate.region && existing.region && normalize(candidate.region) === normalize(existing.region)) {
    score += 8; reasons.push("Same region");
  }

  if (candidate.subCounty && existing.subCounty && normalize(candidate.subCounty) === normalize(existing.subCounty)) {
    score += 10; reasons.push(`Same sub-county (${existing.subCounty})`);
  }

  if (candidate.phone && existing.phone && normalize(candidate.phone) === normalize(existing.phone)) {
    score += 15; reasons.push("Same phone number");
  }

  if (candidate.shippingAddress && existing.shippingAddress &&
      normalize(candidate.shippingAddress) === normalize(existing.shippingAddress)) {
    score += 10; reasons.push("Same shipping address");
  }

  // A name match alone, in a different district, isn't enough to flag.
  if (sim < 0.5) return { score: 0, reasons: [] };

  return { score: Math.min(100, score), reasons };
}

/**
 * Find all existing schools the candidate may duplicate (band Potential or
 * Strong), strongest first.
 */
export function findDuplicateCandidates(
  candidate: DuplicateScoreInput,
  existing: DuplicateScoreInput[],
): DuplicateMatch[] {
  const out: DuplicateMatch[] = [];
  for (const e of existing) {
    const { score, reasons } = scorePair(candidate, e);
    const band = bandFor(score);
    if (band === "None") continue;
    out.push({ matchSchoolId: e.schoolId, matchSchoolName: e.schoolName, score, band, reasons });
  }
  return out.sort((a, b) => b.score - a.score);
}
