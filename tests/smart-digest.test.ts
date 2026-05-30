import { describe, it, expect } from "vitest";
import {
  buildDigest,
  classifyDigestTier,
  isWithinQuietHours,
  DEFAULT_DIGEST_PREFERENCES,
} from "@/lib/digest/smart-digest";
import type { ActionItem } from "@/lib/actions/action-types";

// Smart Digest converts a noisy stream of ActionItems into a calm,
// classified, grouped digest that respects quiet hours. The product
// principle: notifications should be Critical/Important/Informational,
// not a firehose. These tests pin the classification + quietness +
// grouping rules.

function item(over: Partial<ActionItem> = {}): ActionItem {
  return {
    id: "x",
    role: "CCEO",
    priority: 3,
    category: "FieldVisit",
    title: "Visit Bright Future PS",
    description: "Today's first stop.",
    affectedEntity: { kind: "School", id: "S-1", label: "Bright Future PS" },
    riskLevel: "Medium",
    status: "Pending",
    approvalSafety: "SafeToApprove",
    primaryAction: { label: "Open", intent: "open", href: "/route" },
    sourceModule: "planning",
    inboxTab: "NeedsFollowUp",
    ...over,
  };
}

const NOW = new Date("2026-05-15T10:00:00Z");

// ──────────────── classifyDigestTier ────────────────

describe("classifyDigestTier", () => {
  it("Critical when risk level is Critical (regardless of date)", () => {
    expect(classifyDigestTier(item({ riskLevel: "Critical" }), NOW)).toBe("Critical");
  });

  it("Critical when due today", () => {
    expect(classifyDigestTier(item({ dueDate: NOW.toISOString() }), NOW)).toBe("Critical");
  });

  it("Critical when due in <= 24 hours", () => {
    const in12h = new Date(NOW.getTime() + 12 * 60 * 60 * 1000).toISOString();
    expect(classifyDigestTier(item({ dueDate: in12h }), NOW)).toBe("Critical");
  });

  it("Important when due within the week", () => {
    const in3d = new Date(NOW.getTime() + 3 * 24 * 60 * 60 * 1000).toISOString();
    expect(classifyDigestTier(item({ dueDate: in3d }), NOW)).toBe("Important");
  });

  it("Important when High risk without a date", () => {
    expect(classifyDigestTier(item({ riskLevel: "High" }), NOW)).toBe("Important");
  });

  it("Informational when Completed (no need to interrupt anyone)", () => {
    expect(classifyDigestTier(item({ status: "Completed", riskLevel: "Low" }), NOW)).toBe("Informational");
  });

  it("Informational when AwaitingOther (can't act anyway)", () => {
    expect(classifyDigestTier(item({ status: "AwaitingOther", riskLevel: "Low" }), NOW)).toBe("Informational");
  });

  it("default safety net: Informational", () => {
    expect(classifyDigestTier(item({ riskLevel: "Low" }), NOW)).toBe("Informational");
  });
});

// ──────────────── isWithinQuietHours ────────────────

describe("isWithinQuietHours", () => {
  function at(h: number): Date {
    const d = new Date("2026-05-15T00:00:00");
    d.setHours(h);
    return d;
  }

  it("returns true at 22:00 with default 20..6 window (spans midnight)", () => {
    expect(isWithinQuietHours(at(22))).toBe(true);
  });

  it("returns true at 03:00 with default 20..6 window", () => {
    expect(isWithinQuietHours(at(3))).toBe(true);
  });

  it("returns false at 14:00", () => {
    expect(isWithinQuietHours(at(14))).toBe(false);
  });

  it("simple (non-midnight-spanning) window works too", () => {
    const prefs = { ...DEFAULT_DIGEST_PREFERENCES, quietHoursStart: 12, quietHoursEnd: 14 };
    expect(isWithinQuietHours(at(13), prefs)).toBe(true);
    expect(isWithinQuietHours(at(11), prefs)).toBe(false);
    expect(isWithinQuietHours(at(14), prefs)).toBe(false);
  });

  it("equal start + end disables the window", () => {
    expect(isWithinQuietHours(at(22), { ...DEFAULT_DIGEST_PREFERENCES, quietHoursStart: 12, quietHoursEnd: 12 })).toBe(false);
  });
});

// ──────────────── buildDigest ────────────────

describe("buildDigest", () => {
  it("classifies and buckets every item into one of three tiers", () => {
    const result = buildDigest([
      item({ id: "a", riskLevel: "Critical" }),
      item({ id: "b", riskLevel: "High",   dueDate: new Date(NOW.getTime() + 2 * 24 * 60 * 60 * 1000).toISOString() }),
      item({ id: "c", riskLevel: "Low",    status: "Completed" }),
    ], NOW, DEFAULT_DIGEST_PREFERENCES);
    expect(result.byTier.Critical.length).toBe(1);
    expect(result.byTier.Important.length).toBe(1);
    expect(result.byTier.Informational.length).toBe(1);
  });

  it("fires Critical items live regardless of quiet hours", () => {
    const lateNight = new Date("2026-05-15T22:30:00");
    const result = buildDigest(
      [item({ id: "crit", riskLevel: "Critical" })],
      lateNight,
      DEFAULT_DIGEST_PREFERENCES,
    );
    expect(result.quietHoursActive).toBe(true);
    expect(result.fireNow.length).toBe(1);
  });

  it("suppresses Important + Informational during quiet hours", () => {
    const lateNight = new Date("2026-05-15T22:30:00");
    const result = buildDigest([
      item({ id: "imp", riskLevel: "High" }),
      item({ id: "info", riskLevel: "Low" }),
    ], lateNight, DEFAULT_DIGEST_PREFERENCES);
    expect(result.fireNow.length).toBe(0);
  });

  it("groups multiple items about the same subject into one entry with a count", () => {
    const result = buildDigest([
      item({ id: "g1", riskLevel: "High",
        affectedEntity: { kind: "Staff", id: "STF-1", label: "Grace Njeri" } }),
      item({ id: "g2", riskLevel: "High",
        affectedEntity: { kind: "Staff", id: "STF-1", label: "Grace Njeri" } }),
      item({ id: "g3", riskLevel: "High",
        affectedEntity: { kind: "Staff", id: "STF-1", label: "Grace Njeri" } }),
    ], NOW, DEFAULT_DIGEST_PREFERENCES);
    expect(result.byTier.Important.length).toBe(1);
    expect(result.byTier.Important[0].count).toBe(3);
    expect(result.byTier.Important[0].headline).toContain("Grace Njeri");
    expect(result.byTier.Important[0].headline).toContain("3 updates");
  });

  it("groupBySubject=false keeps each item separate", () => {
    const result = buildDigest([
      item({ id: "g1", riskLevel: "High",
        affectedEntity: { kind: "Staff", id: "STF-1", label: "Grace Njeri" } }),
      item({ id: "g2", riskLevel: "High",
        affectedEntity: { kind: "Staff", id: "STF-1", label: "Grace Njeri" } }),
    ], NOW, { ...DEFAULT_DIGEST_PREFERENCES, groupBySubject: false });
    expect(result.byTier.Important.length).toBe(2);
  });

  it("Completed items never fire live (digest-only)", () => {
    const result = buildDigest(
      [item({ id: "done", status: "Completed", riskLevel: "Critical" })],
      NOW, DEFAULT_DIGEST_PREFERENCES,
    );
    expect(result.fireNow.length).toBe(0);
  });
});
