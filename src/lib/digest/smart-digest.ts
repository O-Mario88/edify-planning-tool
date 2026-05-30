// Smart Digest — turns noisy notification streams into a calm,
// prioritised, healthy delivery cadence.
//
// Replaces the (anti-pattern) "ping for every event" model with:
//
//   • Critical    — action needed today; allowed to interrupt
//   • Important   — action needed this week; delivered in batches
//   • Informational — no action needed; rolls up to a daily digest
//
// Plus:
//   • Quiet hours — Critical still delivers; lower tiers wait
//   • Subject grouping — 5 notifications about Grace Njeri become
//     ONE digest entry "Grace Njeri · 5 updates"
//
// Pure functions throughout. Reads ActionItem[] + a user's digest
// preferences; returns the digest the UI renders + a list of items
// that should fire as live notifications.

import type { ActionItem } from "@/lib/actions/action-types";

// ────────── Tier classification ──────────

export type DigestTier = "Critical" | "Important" | "Informational";

const TIER_LABEL: Record<DigestTier, string> = {
  Critical:      "Critical · action today",
  Important:     "Important · action this week",
  Informational: "Informational · no urgent action",
};
export function digestTierLabel(t: DigestTier): string { return TIER_LABEL[t]; }

// Single source of truth for "what counts as Critical / Important".
// Classifier reads risk, due-date proximity, and approval-safety in
// that order.
export function classifyDigestTier(
  item: ActionItem,
  now: Date = new Date(),
): DigestTier {
  // Critical: red-flag risk OR due today.
  if (item.riskLevel === "Critical") return "Critical";
  if (item.dueDate) {
    const due = Date.parse(item.dueDate);
    if (Number.isFinite(due) && due <= now.getTime()) return "Critical";
    const dueInHours = (due - now.getTime()) / (1000 * 60 * 60);
    if (dueInHours <= 24) return "Critical";
    // Important: due within the week.
    if (dueInHours <= 24 * 7) return "Important";
  }
  // High-risk items without a date — Important.
  if (item.riskLevel === "High") return "Important";
  // Completed work + blocked-on-others = Informational only.
  if (item.status === "Completed" || item.status === "AwaitingOther") return "Informational";
  // Default safety net.
  return "Informational";
}

// ────────── User preferences ──────────
//
// Hours in 0..23 local time. Quiet window can span midnight.
// Defaults match a healthy workday boundary.

export type DigestPreferences = {
  quietHoursStart: number;      // inclusive
  quietHoursEnd:   number;      // exclusive
  /// During quiet hours, only Critical fires. Other tiers wait for
  /// the next allowed slot.
  groupBySubject:  boolean;
};

export const DEFAULT_DIGEST_PREFERENCES: DigestPreferences = {
  quietHoursStart: 20,           // 8pm
  quietHoursEnd:    6,           // 6am
  groupBySubject:  true,
};

export function isWithinQuietHours(now: Date, prefs: DigestPreferences = DEFAULT_DIGEST_PREFERENCES): boolean {
  const h = now.getHours();
  const { quietHoursStart: s, quietHoursEnd: e } = prefs;
  if (s === e) return false;            // disabled
  if (s < e) return h >= s && h < e;    // simple window (e.g. 22..6 won't match this branch)
  // Spans midnight, e.g. 20..6.
  return h >= s || h < e;
}

// ────────── Subject grouping ──────────
//
// When the same school / staff / partner / activity appears multiple
// times, collapse to one digest entry with a count. Prevents the
// "Grace Njeri did three things, I got three notifications" anti-pattern.

export type DigestEntry = {
  /// Stable id derived from tier + subject.
  id: string;
  tier: DigestTier;
  /// Subject the entries are about ("Grace Njeri", "Hope Primary School").
  subject: string;
  /// 1 if a single item, > 1 if grouped.
  count: number;
  /// One-line summary the UI renders.
  headline: string;
  /// All items that rolled up here, in original order.
  items: ActionItem[];
};

export type DigestResult = {
  /// Items that SHOULD fire as live notifications right now
  /// (Critical always; Important + Informational only outside quiet
  /// hours when the user hasn't already seen them).
  fireNow: ActionItem[];
  /// What renders in the in-app digest panel — always all three tiers.
  byTier: Record<DigestTier, DigestEntry[]>;
  /// Whether quiet hours are currently in effect (UI shows a small badge).
  quietHoursActive: boolean;
};

export function buildDigest(
  items: ActionItem[],
  now: Date = new Date(),
  prefs: DigestPreferences = DEFAULT_DIGEST_PREFERENCES,
): DigestResult {
  const quietActive = isWithinQuietHours(now, prefs);

  // Bucket by tier.
  const bucket: Record<DigestTier, ActionItem[]> = {
    Critical: [], Important: [], Informational: [],
  };
  for (const item of items) {
    const tier = classifyDigestTier(item, now);
    bucket[tier].push(item);
  }

  // Group by subject inside each tier when enabled.
  const byTier: Record<DigestTier, DigestEntry[]> = {
    Critical: groupBySubject(bucket.Critical, "Critical", prefs.groupBySubject),
    Important: groupBySubject(bucket.Important, "Important", prefs.groupBySubject),
    Informational: groupBySubject(bucket.Informational, "Informational", prefs.groupBySubject),
  };

  // Decide what fires live:
  //   • Critical always fires.
  //   • Important + Informational suppressed during quiet hours.
  //   • Completed items never fire (digest-only).
  const fireNow: ActionItem[] = [
    ...bucket.Critical.filter((i) => i.status !== "Completed"),
    ...(quietActive ? [] : bucket.Important.filter((i) => i.status !== "Completed")),
  ];

  return { fireNow, byTier, quietHoursActive: quietActive };
}

// ────────── Internal: grouping ──────────

function groupBySubject(items: ActionItem[], tier: DigestTier, enabled: boolean): DigestEntry[] {
  if (!enabled || items.length === 0) {
    return items.map((item) => ({
      id: `${tier}:${item.id}`,
      tier, subject: item.affectedEntity.label,
      count: 1,
      headline: item.title,
      items: [item],
    }));
  }
  // Group on (affectedEntity.kind + label).
  const buckets = new Map<string, ActionItem[]>();
  for (const item of items) {
    const key = `${item.affectedEntity.kind}:${item.affectedEntity.label}`;
    const arr = buckets.get(key) ?? [];
    arr.push(item);
    buckets.set(key, arr);
  }
  const entries: DigestEntry[] = [];
  for (const [key, group] of buckets) {
    const first = group[0];
    entries.push({
      id: `${tier}:${key}`,
      tier,
      subject: first.affectedEntity.label,
      count: group.length,
      headline: group.length === 1
        ? first.title
        : `${first.affectedEntity.label} · ${group.length} update${group.length === 1 ? "" : "s"}`,
      items: group,
    });
  }
  return entries;
}
