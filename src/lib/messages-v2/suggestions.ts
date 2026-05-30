// Intelligent receiver suggestions.
//
// Given a sender + chosen category + a list of selected contexts,
// produce three buckets:
//
//   • PRIMARY   — pre-checked, the people who clearly should see it
//                 (e.g. partner assigned to the selected schools).
//   • OPTIONAL  — unchecked checkboxes, the user can opt in
//                 (e.g. CD escalation for a routine partner-scheduling
//                 message).
//   • REASONS   — per-userId list of human reasons ("Partner assigned
//                 to 8 of 12 selected schools", "PL under program
//                 scope", "M&E linked to evidence/SSA").
//
// Role gates run on top: HR + RVP never see partners; partners
// never see internal HR/CD-only people. The directory's
// recipientsForSender(role) filters the final result so the picker
// can't suggest someone the sender wouldn't otherwise be allowed to
// message.

import type { EdifyRole } from "@/lib/auth-public";
import { DIRECTORY, recipientsForSender, type DirectoryUser } from "./directory";
import { contextRecordById, type ContextRecord } from "./contexts";
import type { MessageCategory, MessageContext } from "./types";

export type Suggestion = {
  user:    DirectoryUser;
  reasons: string[];
};

export type SuggestionResult = {
  primary:  Suggestion[];
  optional: Suggestion[];
};

// Resolve the chosen contexts back into their enriched ContextRecord
// rows so we can read assignedCceoId / district / status. Contexts
// whose record isn't in the directory still pass through (e.g. the
// generic "Today's field debrief") — those just contribute no
// attribution to the suggestions.
function enrichContexts(contexts: MessageContext[]): ContextRecord[] {
  const out: ContextRecord[] = [];
  for (const c of contexts) {
    const rec = contextRecordById(c.id);
    if (rec) out.push(rec);
    else out.push({ type: c.type, id: c.id, label: c.label });
  }
  return out;
}

// ─── Build helpers ───────────────────────────────────────────────

type Counter = Map<string, { user: DirectoryUser; reasons: string[]; weight: number }>;

function add(c: Counter, userId: string | undefined, reason: string, weight = 1): void {
  if (!userId) return;
  const u = DIRECTORY.find((d) => d.userId === userId);
  if (!u) return;
  const existing = c.get(userId);
  if (existing) {
    if (!existing.reasons.includes(reason)) existing.reasons.push(reason);
    existing.weight += weight;
  } else {
    c.set(userId, { user: u, reasons: [reason], weight });
  }
}

function addAll(c: Counter, users: DirectoryUser[], reason: string, weight = 1): void {
  for (const u of users) add(c, u.userId, reason, weight);
}

// Per-category attribution rules — what to seed the counter with.
function seedCategoryDefaults(c: Counter, category: MessageCategory): void {
  switch (category) {
    case "payment-update":
    case "finance":
      addAll(c, DIRECTORY.filter((d) => d.role === "ProgramAccountant"), "Accountant handles payment flow");
      break;
    case "evidence-review":
    case "correction-request":
      addAll(c, DIRECTORY.filter((d) => d.role === "ImpactAssessment"), "M&E owns evidence verification");
      break;
    case "hr-support":
      addAll(c, DIRECTORY.filter((d) => d.role === "HumanResource"), "HR owns staff support cases");
      break;
    case "leadership-decision":
      addAll(c, DIRECTORY.filter((d) => d.role === "CountryDirector"), "CD makes leadership decisions");
      break;
    default:
      break;
  }
}

// ─── Entry point ─────────────────────────────────────────────────

export function suggestedReceivers(
  contexts:   MessageContext[],
  category:   MessageCategory,
  senderRole: EdifyRole,
): SuggestionResult {
  const enriched = enrichContexts(contexts);

  // The directory tells us which roles the sender is allowed to
  // message AT ALL. This is the upper bound — every suggestion below
  // is filtered through it. (HR/RVP never get partners because the
  // directory excludes them upstream.)
  const allowedUsers = recipientsForSender(senderRole);
  const allowedIds = new Set(allowedUsers.map((u) => u.userId));

  const primary: Counter = new Map();
  const optional: Counter = new Map();

  seedCategoryDefaults(primary, category);

  // Per-record attribution. The same person can pick up multiple
  // reasons + weight as more contexts pile in.
  for (const r of enriched) {
    if (r.assignedCceoId) {
      add(primary, r.assignedCceoId, `Assigned CCEO for ${r.label}`);
    }
    if (r.assignedPlId) {
      add(primary, r.assignedPlId, `PL under scope for ${r.label}`);
    }
    if (r.assignedPartnerId) {
      // Partners are only "primary" on partner-facing categories.
      const partnerFacing = category === "partner-scheduling"
        || category === "partner-debrief"
        || category === "payment-update"
        || category === "correction-request"
        || category === "evidence-review"
        || category === "school-followup";
      if (partnerFacing) {
        add(primary, r.assignedPartnerId, `Partner assigned to ${r.label}`);
      } else {
        add(optional, r.assignedPartnerId, `Partner working in scope of ${r.label}`);
      }
    }
  }

  // Category-specific optional escalations. CD always gets an
  // "optional" slot on urgent operational categories.
  if (category === "field-debrief" || category === "partner-debrief"
      || category === "school-followup" || category === "evidence-review") {
    addAll(optional, DIRECTORY.filter((d) => d.role === "CountryDirector"),
      "Country Director — for escalation");
    addAll(optional, DIRECTORY.filter((d) => d.role === "ImpactAssessment"),
      "M&E — if evidence/SSA issue surfaces");
  }
  if (category === "payment-update" || category === "finance") {
    addAll(optional, DIRECTORY.filter((d) => d.role === "CountryDirector"),
      "Country Director — for finance escalation");
  }

  // Remove anyone the sender isn't allowed to message at all.
  function filterAndSort(c: Counter): Suggestion[] {
    return [...c.values()]
      .filter((v) => allowedIds.has(v.user.userId))
      .sort((a, b) => b.weight - a.weight)
      .map((v) => ({ user: v.user, reasons: v.reasons }));
  }

  // Anyone who landed in BOTH buckets should only stay in primary.
  const primaryIds = new Set([...primary.keys()]);
  for (const id of primaryIds) optional.delete(id);

  return {
    primary:  filterAndSort(primary),
    optional: filterAndSort(optional),
  };
}
