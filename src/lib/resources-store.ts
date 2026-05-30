// Resources store — uploads + role-gated permissions.
//
// Seed resources live in /resources page as static rows; this store
// adds an uploaded layer keyed by category. Country Directors own
// the policy/field-guide canon; training material is broader (CCEO,
// IA, PL, and CD all contribute). Anyone can READ.
//
// Storage is localStorage so demos persist across reloads without a
// backend. Shape mirrors a future server `resources` table 1:1 so a
// real backend swap touches only this file.

"use client";

import type { EdifyRole } from "@/lib/auth-public";

export type ResourceCategory = "Field Guides" | "Policies" | "Training Material";

export const RESOURCE_CATEGORIES: ResourceCategory[] = [
  "Field Guides",
  "Policies",
  "Training Material",
];

export type UploadedResource = {
  id:               string;
  title:            string;
  body:             string;
  category:         ResourceCategory;
  fileName:         string;
  fileSize:         number;   // bytes
  fileType:         string;   // mime
  /** Base64 data URL — kept in-memory + localStorage so the file is
   * downloadable even after reload. Capped at ~5 MB per item by the
   * uploader UI to stay within localStorage budgets. */
  dataUrl?:         string;
  uploadedByName:   string;
  uploadedByRole:   EdifyRole;
  uploadedAt:       string;   // ISO timestamp
};

// ────────── Role → category permission map ──────────
//
// Field Guides + Policies are CD-owned: they're the country canon and
// shouldn't drift. Training Material is broader because every front-
// line role produces lesson plans, debrief decks, and how-to videos
// for their team.
const UPLOAD_PERMISSIONS: Record<ResourceCategory, EdifyRole[]> = {
  "Field Guides":      ["CountryDirector"],
  "Policies":          ["CountryDirector"],
  "Training Material": ["CCEO", "ImpactAssessment", "CountryProgramLead", "CountryDirector"],
};

export function canUploadCategory(role: EdifyRole, category: ResourceCategory): boolean {
  return UPLOAD_PERMISSIONS[category].includes(role);
}

export function uploadableCategoriesFor(role: EdifyRole): ResourceCategory[] {
  return RESOURCE_CATEGORIES.filter((c) => canUploadCategory(role, c));
}

// ────────── Storage ──────────

const KEY = "edify.resources.v1";

function readAll(): UploadedResource[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as UploadedResource[]) : [];
  } catch {
    return [];
  }
}

function writeAll(rows: UploadedResource[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(rows));
    window.dispatchEvent(new CustomEvent("edify:resources:changed"));
  } catch {
    // localStorage may be unavailable (private mode / quota). The UI
    // shows an error toast where the caller invoked addResource.
  }
}

export function listResources(category?: ResourceCategory): UploadedResource[] {
  const all = readAll().sort((a, b) => b.uploadedAt.localeCompare(a.uploadedAt));
  return category ? all.filter((r) => r.category === category) : all;
}

export function addResource(input: Omit<UploadedResource, "id" | "uploadedAt">): UploadedResource {
  const row: UploadedResource = {
    ...input,
    id: `up-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
    uploadedAt: new Date().toISOString(),
  };
  writeAll([row, ...readAll()]);
  return row;
}

export function removeResource(id: string) {
  writeAll(readAll().filter((r) => r.id !== id));
}

// ────────── Reactivity helper ──────────
//
// Components subscribe via subscribeResources(cb) and re-fetch on
// every storage/custom event. Works across tabs (storage event) and
// in the same tab (custom event dispatched by writeAll).
export function subscribeResources(cb: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const onStorage = (e: StorageEvent) => { if (e.key === KEY || e.key === null) cb(); };
  const onCustom  = () => cb();
  window.addEventListener("storage", onStorage);
  window.addEventListener("edify:resources:changed", onCustom);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener("edify:resources:changed", onCustom);
  };
}

// ────────── Display helpers ──────────

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

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
