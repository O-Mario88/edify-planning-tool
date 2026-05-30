// Per-category context options + role-aware category lists.
//
// The composer reads from here twice:
//   1. To populate the Category dropdown — filtered by sender role
//      (Partner sees 5 categories; HR sees 10 HR-specific; RVP sees
//      10 RVP-specific; staff see the full pool).
//   2. To populate the Context picker — filtered by the picked
//      category (Field Debrief → Today's debrief / School / Cluster /
//      Activity / Operational issue; Payment Update → Partner payment
//      / Staff advance / Reimbursement / Accountability / …).

import type { EdifyRole } from "@/lib/auth-public";
import type { MessageCategory, MessageContextType } from "./types";

// ────────── Context option (one entry the user can pick) ──────────

export type ContextOption = {
  type:  MessageContextType;
  /** Stable id when the option points at a real record, e.g.
   *  "school:hope-primary". For generic categories like "Operational
   *  Issue" we use a deterministic sentinel so search can group. */
  id:    string;
  label: string;
};

export type ContextRecord = ContextOption & {
  district?:          string;
  region?:            string;
  assignedCceoId?:    string;
  assignedPlId?:      string;
  assignedPartnerId?: string;
  /** Snapshot status — feeds the category-specific "Schools Not
   *  Scheduled / Evidence Returned" groupings the picker can pivot on. */
  status?:            string;
};

// A small curated set of demo records. Phase 4 swaps this for live
// joins. Each record carries district/region + assigned CCEO/PL/Partner
// so the suggestion engine can reason about location + ownership
// without re-querying.
export const CONTEXT_RECORDS: ContextRecord[] = [
  // ─── Schools (Mukono cluster: monitored by Sarah Nanyongo, Bright Future partner) ───
  { type: "school", id: "school:hope-primary",   label: "Hope Primary School · Mukono",   district: "Mukono",   region: "Central",  assignedCceoId: "STF-SN-101", assignedPlId: "STF-DM-001", assignedPartnerId: "PSF-SK-001", status: "Awaiting partner planning" },
  { type: "school", id: "school:grace-primary",  label: "Grace Primary School · Mukono",  district: "Mukono",   region: "Central",  assignedCceoId: "STF-SN-101", assignedPlId: "STF-DM-001", assignedPartnerId: "PSF-SK-001", status: "Awaiting partner planning" },
  { type: "school", id: "school:kireka-primary", label: "Kireka Primary School · Mukono", district: "Mukono",   region: "Central",  assignedCceoId: "STF-PC-001", assignedPlId: "STF-DM-001", assignedPartnerId: "PSF-AO-002", status: "Active" },
  { type: "school", id: "school:namilyango",     label: "Namilyango Primary · Mukono",    district: "Mukono",   region: "Central",  assignedCceoId: "STF-PC-001", assignedPlId: "STF-DM-001", assignedPartnerId: "PSF-AO-002", status: "Awaiting partner planning" },
  // ─── Schools (Kayunga: monitored by Irene Mutebi) ───
  { type: "school", id: "school:maple-grove",    label: "Maple Grove Primary · Kayunga",  district: "Kayunga",  region: "Central",  assignedCceoId: "STF-IM-005", assignedPlId: "STF-DM-001", assignedPartnerId: "PSF-SK-001", status: "Awaiting partner planning" },
  { type: "school", id: "school:st-marys",       label: "St. Mary's Primary · Kayunga",   district: "Kayunga",  region: "Central",  assignedCceoId: "STF-IM-005", assignedPlId: "STF-DM-001", assignedPartnerId: "PSF-AO-002", status: "Active" },
  // ─── Clusters ───
  { type: "cluster", id: "cluster:bbaale",         label: "Bbaale cluster · Kayunga",  district: "Kayunga", region: "Central", assignedCceoId: "STF-IM-005", assignedPlId: "STF-DM-001", assignedPartnerId: "PSF-SK-001" },
  { type: "cluster", id: "cluster:mukono-central", label: "Mukono Central cluster",    district: "Mukono",  region: "Central", assignedCceoId: "STF-SN-101", assignedPlId: "STF-DM-001", assignedPartnerId: "PSF-AO-002" },
  // ─── Partner activities ───
  { type: "partner_activity", id: "pa:kireka-training", label: "Partner training · Kireka · May 12",     district: "Mukono",  region: "Central", assignedCceoId: "STF-PC-001", assignedPartnerId: "PSF-AO-002", status: "Scheduled" },
  { type: "partner_activity", id: "pa:maple-coaching",  label: "Partner coaching · Maple Grove · May 18", district: "Kayunga", region: "Central", assignedCceoId: "STF-IM-005", assignedPartnerId: "PSF-SK-001", status: "Awaiting partner planning" },
  // ─── Trainings ───
  { type: "training", id: "training:literacy-q3",   label: "Q3 literacy training · 14 schools",   region: "Central", assignedPlId: "STF-DM-001" },
  { type: "training", id: "training:leadership-q3", label: "Q3 leadership training · 8 schools", region: "Central", assignedPlId: "STF-DM-001" },
  // ─── SSA ───
  { type: "ssa", id: "ssa:hope-q2",  label: "SSA · Hope Primary · Q2 baseline",  district: "Mukono", region: "Central", assignedCceoId: "STF-SN-101" },
  { type: "ssa", id: "ssa:grace-q2", label: "SSA · Grace Primary · Q2 baseline", district: "Mukono", region: "Central", assignedCceoId: "STF-SN-101" },
  // ─── Evidence ───
  { type: "evidence", id: "evidence:kireka-attendance", label: "Evidence · Kireka attendance sheet", district: "Mukono", region: "Central", assignedCceoId: "STF-SN-101", assignedPartnerId: "PSF-AO-002", status: "Returned for correction" },
  { type: "evidence", id: "evidence:namilyango-photos", label: "Evidence · Namilyango activity photos", district: "Mukono", region: "Central", assignedCceoId: "STF-PC-001", assignedPartnerId: "PSF-AO-002", status: "Verified" },
  // ─── Payments ───
  { type: "payment", id: "payment:apr-batch",      label: "Payment · April batch · UGX 5.6M",          region: "Central", assignedPartnerId: "PSF-SK-001", status: "Cleared" },
  { type: "payment", id: "payment:maple-followup", label: "Payment · Maple Grove follow-up · UGX 40K", district: "Kayunga", region: "Central", assignedCceoId: "STF-IM-005", assignedPartnerId: "PSF-SK-001", status: "Awaiting CCEO confirmation" },
  // ─── Planning ───
  { type: "planning_item", id: "plan:q3-cceo-cycle",  label: "Plan · Q3 CCEO cycle",                  region: "Central", assignedPlId: "STF-DM-001" },
  { type: "planning_item", id: "plan:partner-bbaale", label: "Plan · Partner assignment · Bbaale",    district: "Kayunga", region: "Central", assignedPlId: "STF-DM-001", assignedPartnerId: "PSF-SK-001" },
  // ─── Field debriefs ───
  { type: "field_debrief", id: "fd:today",  label: "Today's field debrief",  assignedPlId: "STF-DM-001" },
  { type: "field_debrief", id: "fd:weekly", label: "Weekly field reflection", assignedPlId: "STF-DM-001" },
  // ─── Partner debriefs ───
  { type: "partner_debrief", id: "pd:bbaale-may", label: "Partner debrief · Bbaale · May", district: "Kayunga", region: "Central", assignedPartnerId: "PSF-SK-001" },
  // ─── HR ───
  { type: "hr_case", id: "hr:purity-fairness", label: "HR case · Purity Muthoni · fairness review" },
  { type: "hr_case", id: "hr:workload-q2",     label: "HR theme · Q2 workload concerns" },
  // ─── Leadership ───
  { type: "leadership_decision", id: "ld:q3-direction", label: "Leadership decision · Q3 direction" },
  // ─── Regional ───
  { type: "regional_oversight", id: "ro:uganda-q2", label: "Regional review · Uganda · FY27 Q2", region: "East Africa" },
  // ─── General internal ───
  { type: "general_internal", id: "general-internal", label: "General internal matter" },
];

export function contextRecordById(id: string): ContextRecord | undefined {
  return CONTEXT_RECORDS.find((r) => r.id === id);
}

export function searchContextRecords(types: MessageContextType[], query: string): ContextOption[] {
  const q = query.trim().toLowerCase();
  const typeSet = new Set(types);
  return CONTEXT_RECORDS.filter((o) => typeSet.has(o.type)).filter((o) =>
    q.length === 0 ? true : o.label.toLowerCase().includes(q),
  );
}

// ────────── Per-category context-type rules ──────────
//
// The spec's section 8: when the user picks a category, only certain
// context TYPES are valid for it. The picker filters its records by
// the union of these types.

export const CONTEXT_TYPES_BY_CATEGORY: Partial<Record<MessageCategory, MessageContextType[]>> = {
  "field-debrief":        ["field_debrief", "school", "cluster", "partner_activity", "staff_activity"],
  "partner-debrief":      ["partner_debrief", "school", "cluster", "partner_activity"],
  "evidence-review":      ["evidence", "school", "training", "partner_activity"],
  "correction-request":   ["evidence", "school", "partner_activity"],
  "payment-update":       ["payment", "partner_activity", "training"],
  "planning-assignment":  ["planning_item", "school", "cluster", "partner_activity", "staff_activity"],
  "partner-scheduling":   ["partner_activity", "school", "cluster", "training"],
  "school-followup":      ["school", "ssa", "training", "evidence", "partner_debrief"],
  "cluster-update":       ["cluster", "school", "training"],
  "ssa-update":           ["ssa", "school", "cluster"],
  "finance":              ["payment", "general_internal"],
  "hr-support":           ["hr_case", "staff_activity", "general_internal"],
  "leadership-decision":  ["leadership_decision", "regional_oversight", "general_internal"],
  "system-notification":  ["general_internal", "school", "payment", "evidence"],
  "general":              ["general_internal", "school", "cluster"],
};

export function contextTypesForCategory(category: MessageCategory): MessageContextType[] {
  return CONTEXT_TYPES_BY_CATEGORY[category] ?? ["general_internal"];
}

// ────────── Per-role category lists ──────────
//
// Spec's section 6 (role-based category rules). Partners see only 5
// operationally relevant categories. HR sees HR-only categories. RVP
// sees regional/oversight categories. Internal staff (CCEO, PL, CD,
// IA, Accountant, Admin) see the full pool.

const PARTNER_CATEGORIES: MessageCategory[] = [
  "field-debrief",
  "payment-update",
  "planning-assignment",
  "partner-scheduling",
  "school-followup",
];

// HR-flavoured: rather than introduce 10 new categories that don't
// match the rest of the system, we surface the existing categories
// HR actually uses. The "Staff Wellbeing / Workload Concern / …"
// labels from the spec all live as context TYPES inside hr-support.
const HR_CATEGORIES: MessageCategory[] = [
  "hr-support",
  "field-debrief",
  "partner-debrief",
  "leadership-decision",
  "general",
];

const RVP_CATEGORIES: MessageCategory[] = [
  "leadership-decision",
  "finance",
  "field-debrief",
  "partner-debrief",
  "evidence-review",
  "ssa-update",
  "general",
];

const STAFF_CATEGORIES: MessageCategory[] = [
  "general",
  "planning-assignment",
  "partner-scheduling",
  "evidence-review",
  "correction-request",
  "payment-update",
  "field-debrief",
  "partner-debrief",
  "school-followup",
  "cluster-update",
  "ssa-update",
  "finance",
  "hr-support",
  "leadership-decision",
  "system-notification",
];

export function categoriesForRole(role: EdifyRole): MessageCategory[] {
  switch (role) {
    case "PartnerAdmin":
    case "PartnerFieldOfficer":
    case "PartnerViewer":   return PARTNER_CATEGORIES;
    case "HumanResource":   return HR_CATEGORIES;
    case "RVP":             return RVP_CATEGORIES;
    case "CCEO":
    case "CountryProgramLead":
    case "CountryDirector":
    case "ProgramAccountant":
    case "ImpactAssessment":
    case "Admin":           return STAFF_CATEGORIES;
  }
}
