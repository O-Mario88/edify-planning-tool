// Partners store — add/edit + role permissions.
//
// Delivery partners are operational records: who trains the schools,
// on what curriculum, in which region. They're owned by the people
// who actually source + onboard them — Impact Assessment (M&E sets
// up the partner agreements), the Country Director (signs off on the
// canon), and Admin (system fallback). Everyone else can READ.
//
// localStorage-backed for the demo; future server swap touches only
// this file, since the page reads through `listPartners()` and writes
// through `addPartner()` / `removePartner()`.

"use client";

import type { EdifyRole } from "@/lib/auth-public";

/** Partner lifecycle — partners are assignable ONLY after CD activation. */
export type PartnerLifecycleStatus = "Pending Activation" | "Active" | "Inactive";
export type PartnerCertStatus = "Certified" | "Pending" | "Not Certified";
export type PartnerContractStatus = "Draft" | "Signed" | "Expired";

export type PartnerStatusEvent = {
  status: PartnerLifecycleStatus;
  byName: string;
  byRole: EdifyRole;
  at:     string; // ISO timestamp
};

export type AddedPartner = {
  id:            string;
  name:          string;
  region:        string;
  /** Curriculum / topics this partner is certified to train on. Free
   * text — store as a single string with bullet separators so the
   * form stays simple. */
  trainsOn:      string[];
  notes:         string;
  addedByName:   string;
  addedByRole:   EdifyRole;
  addedAt:       string; // ISO timestamp
  // ── Onboarding profile (CD-owned) ──
  contactPerson?: string;
  email?:         string;
  phone?:         string;
  /** District coverage — assignments outside these districts fail the
   *  coverage check. Empty = whole region. */
  districts?:     string[];
  subCounties?:   string[];
  certificationStatus?: PartnerCertStatus;
  contractStatus?:      PartnerContractStatus;
  startDate?:     string; // ISO date
  // ── Lifecycle (only the CD activates; pending = NOT assignable) ──
  status?:        PartnerLifecycleStatus;
  statusHistory?: PartnerStatusEvent[];
};

// ────────── Role gating ──────────

const PARTNER_ADD_ROLES: EdifyRole[] = [
  "ImpactAssessment",
  "CountryDirector",
  "Admin",
];

// Activation is narrower than add: the CD owns the partner canon — IA
// can prepare the record, but only the CD switches it live (or off).
const PARTNER_ACTIVATE_ROLES: EdifyRole[] = ["CountryDirector", "Admin"];

export function canAddPartner(role: EdifyRole): boolean {
  return PARTNER_ADD_ROLES.includes(role);
}

export function canActivatePartner(role: EdifyRole): boolean {
  return PARTNER_ACTIVATE_ROLES.includes(role);
}

export function partnerEditorRolesLabel(): string {
  return "Impact Assessment, Country Director, or Admin";
}

/** Lifecycle status of a partner row — legacy rows (saved before the
 *  lifecycle existed) read as Pending Activation, never silently Active. */
export function partnerStatusOf(p: AddedPartner): PartnerLifecycleStatus {
  return p.status ?? "Pending Activation";
}

// ────────── Storage ──────────

const KEY = "edify.partners.v1";

function readAll(): AddedPartner[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as AddedPartner[]) : [];
  } catch {
    return [];
  }
}

function writeAll(rows: AddedPartner[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(rows));
    window.dispatchEvent(new CustomEvent("edify:partners:changed"));
  } catch {
    // localStorage may be unavailable. The caller surfaces a toast.
  }
}

export function listPartners(): AddedPartner[] {
  return readAll().sort((a, b) => b.addedAt.localeCompare(a.addedAt));
}

export function addPartner(input: Omit<AddedPartner, "id" | "addedAt">): AddedPartner {
  const row: AddedPartner = {
    ...input,
    id:      `pt-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
    addedAt: new Date().toISOString(),
  };
  writeAll([row, ...readAll()]);
  return row;
}

export function removePartner(id: string) {
  writeAll(readAll().filter((r) => r.id !== id));
}

/**
 * Activate / deactivate a partner. CD (or Admin) only — callers must
 * gate on `canActivatePartner(role)`; this also enforces it so a stray
 * caller can't flip a partner live. Every change is appended to the
 * row's status history (the audit trail the backend will mirror).
 */
export function setPartnerStatus(
  id: string,
  status: PartnerLifecycleStatus,
  byName: string,
  byRole: EdifyRole,
): AddedPartner | undefined {
  if (!canActivatePartner(byRole)) return undefined;
  const rows = readAll();
  const row = rows.find((r) => r.id === id);
  if (!row) return undefined;
  row.status = status;
  row.statusHistory = [
    ...(row.statusHistory ?? []),
    { status, byName, byRole, at: new Date().toISOString() },
  ];
  writeAll(rows);
  return row;
}

/** Partners eligible for work assignment — Active only. Assignment
 *  pickers must read THIS, not listPartners(): a partner that the CD
 *  has not activated (or has deactivated) is never assignable. */
export function assignablePartners(): AddedPartner[] {
  return listPartners().filter((p) => partnerStatusOf(p) === "Active");
}

// ────────── Reactivity ──────────

export function subscribePartners(cb: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const onStorage = (e: StorageEvent) => { if (e.key === KEY || e.key === null) cb(); };
  const onCustom  = () => cb();
  window.addEventListener("storage", onStorage);
  window.addEventListener("edify:partners:changed", onCustom);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener("edify:partners:changed", onCustom);
  };
}

// ────────── Display helpers ──────────

export function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const now  = Date.now();
  const sec  = Math.max(0, Math.round((now - then) / 1000));
  if (sec < 60) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.round(hr / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

/** Default training topics for the seed partners (read-only) so the
 *  page always communicates "what they train on" even before anyone
 *  has added a partner through the form. */
export const SEED_PARTNER_TRAINS_ON: Record<string, string[]> = {
  "PRT-AHA":  ["Adolescent Health & Wellness", "WASH"],
  "PRT-WV":   ["Christ-like Behavior", "Child Protection"],
  "PRT-PI":   ["Inclusive Education", "Gender Equity"],
  "PRT-STC":  ["Early Grade Reading", "Teacher Coaching"],
  "PRT-CARE": ["Leadership Best Practice", "Numeracy Foundations"],
};
