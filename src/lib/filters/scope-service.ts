// Role-aware analytics filter scope.
//
// `getFilterScope(user)` returns the dropdown contents every analytics
// surface should render. It is the single seam between the bar UI and
// the data layer — today it reads the mock files; later it swaps to
// Prisma without the call sites changing.
//
// Slice 1 contract:
//   • Per-role visibility comes from filters/visibility.ts.
//   • Per-user scope (which regions / districts / clusters / CCEOs /
//     partners the user can see) is derived from schoolsMock + the
//     user's assignment fields. CCEO scope is strict; PL/CD/Admin see
//     everything; Partner roles see their own organisation only.
//   • Dependent narrowing (region → districts → clusters) happens at
//     render time in the hook, NOT here — this returns the full scope.
//   • Package / SSA / Champion are program-defined static option sets.

import "server-only";

import type { DemoUser } from "@/lib/auth";
import { schoolsMock, clustersMock, type SchoolRow } from "@/lib/schools-mock";
import {
  REGIONS,
  DISTRICTS,
  regionLabel,
  regionForDistrict,
  type UgandaRegion,
} from "@/lib/geography";
import { buildFyOptions, buildQuarterOptions } from "./fy-options";
import {
  ALL_SENTINEL,
  type FilterOption,
  type FilterScope,
  type FilterScopeEntry,
} from "./types";
import { visibilityFor } from "./visibility";

// ────────── User → visible schools ──────────
//
// CCEO: strict assignment. Partner roles: their org's partner id.
// Everyone else (PL, CD, RVP, IA, Accountant, HR, Admin): country-wide.
// This mirrors `getVisibleSchools` in schools-mock.ts but inlines a
// minimal copy so the scope service doesn't drag in the dashboard's
// access-control branch (which leans on CurrentUser, not DemoUser).
function visibleSchoolsFor(user: DemoUser): SchoolRow[] {
  if (user.role === "CCEO") {
    return schoolsMock.filter((s) => s.assignedCceoId === user.staffId);
  }
  // Partner roles — slice 1 stub. The partner→user binding lives in
  // partner-types.ts; for now the demo accounts share a placeholder
  // mapping (LTU + BFEP) and we widen to "any school with a partner".
  if (
    user.role === "PartnerAdmin" ||
    user.role === "PartnerFieldOfficer" ||
    user.role === "PartnerViewer"
  ) {
    return schoolsMock.filter((s) => !!s.assignedPartnerId);
  }
  return schoolsMock;
}

// ────────── Helpers — distinct, sorted, prefixed with "All …" ──────────

function withAll(label: string, options: FilterOption[]): FilterOption[] {
  return [{ id: ALL_SENTINEL, label }, ...options];
}

function entry(visible: boolean, options: FilterOption[]): FilterScopeEntry {
  return { visible, options };
}

// ────────── Region / District / Cluster / CCEO / Partner ──────────
//
// Region + district options come from the geography source of truth
// (@/lib/geography), NOT from whatever districts happen to be in the mock
// schools — so every Ugandan region/district is selectable and the
// region→district cascade is complete. School counts are layered on from
// the visible schools where present. `allowed` scopes the list: null =
// country-wide (all 4 regions / 136 districts); a Set = the district names
// a scoped role (CCEO / Partner) may see.

// District names a role is allowed to filter by. null = the whole country.
function scopedDistrictNames(user: DemoUser, schools: SchoolRow[]): Set<string> | null {
  if (
    user.role === "CCEO" ||
    user.role === "PartnerAdmin" ||
    user.role === "PartnerFieldOfficer" ||
    user.role === "PartnerViewer"
  ) {
    return new Set(schools.map((s) => s.district));
  }
  return null; // PL / CD / RVP / IA / Accountant / HR / Admin — country-wide
}

function regionOptions(schools: SchoolRow[], allowed: Set<string> | null): FilterOption[] {
  const counts = new Map<string, number>();
  for (const s of schools) counts.set(s.region, (counts.get(s.region) ?? 0) + 1);

  const keys: UgandaRegion[] =
    allowed === null
      ? REGIONS.map((r) => r.key)
      : Array.from(
          new Set(
            Array.from(allowed)
              .map((d) => regionForDistrict(d))
              .filter((r): r is UgandaRegion => Boolean(r)),
          ),
        );

  const sorted = keys.slice().sort((a, b) => a.localeCompare(b));
  return withAll(
    "All Regions",
    sorted.map((key) => {
      const n = counts.get(key) ?? 0;
      return {
        id: key,
        label: regionLabel(key),
        caption: n ? `${n} ${n === 1 ? "school" : "schools"}` : undefined,
      };
    }),
  );
}

function districtOptions(schools: SchoolRow[], allowed: Set<string> | null): FilterOption[] {
  const counts = new Map<string, number>();
  for (const s of schools) counts.set(s.district, (counts.get(s.district) ?? 0) + 1);

  // Each district belongs to exactly one region now, so parentKey is a single
  // region key and the region→district cascade resolves cleanly.
  const list = allowed === null ? DISTRICTS : DISTRICTS.filter((d) => allowed.has(d.name));
  const sorted = list.slice().sort((a, b) => a.name.localeCompare(b.name));
  return withAll(
    "All Districts",
    sorted.map((d) => {
      const n = counts.get(d.name) ?? 0;
      return {
        id: d.name,
        label: d.name,
        caption: n
          ? `${regionLabel(d.region)} · ${n} ${n === 1 ? "school" : "schools"}`
          : regionLabel(d.region),
        parentKey: d.region,
      };
    }),
  );
}

function clusterOptions(schools: SchoolRow[]): FilterOption[] {
  // Map school assignment to clusters by owner CCEO + region/district —
  // the schools-mock cluster records don't carry direct schoolIds, so we
  // approximate "this cluster is in scope" by intersecting on owner.
  const visibleCceos = new Set(schools.map((s) => s.assignedCceoId));
  const inScope = clustersMock.filter((c) => visibleCceos.has(c.ownerCceoId));
  const sorted = inScope.slice().sort((a, b) => a.name.localeCompare(b.name));
  return withAll(
    "All Clusters",
    sorted.map((c) => ({
      id: c.id,
      label: c.name,
      caption: [c.region, c.district].filter(Boolean).join(" · ") || undefined,
      parentKey: c.district,
    })),
  );
}

function cceoOptions(schools: SchoolRow[], user: DemoUser): FilterOption[] {
  // CCEO sees only themselves.
  if (user.role === "CCEO") {
    return [
      { id: ALL_SENTINEL, label: "My Portfolio" },
      {
        id: user.staffId,
        label: user.name,
        caption: `${user.scope}`,
      },
    ];
  }
  const seen = new Map<string, { name: string; count: number; districts: Set<string> }>();
  for (const s of schools) {
    const cur = seen.get(s.assignedCceoId);
    if (cur) {
      cur.count += 1;
      cur.districts.add(s.district);
    } else {
      seen.set(s.assignedCceoId, {
        name: s.assignedCceoName,
        count: 1,
        districts: new Set([s.district]),
      });
    }
  }
  const sorted = Array.from(seen.entries()).sort((a, b) => a[1].name.localeCompare(b[1].name));
  return withAll(
    "All CCEOs",
    sorted.map(([staffId, { name, count, districts }]) => ({
      id: staffId,
      label: name,
      caption: `${Array.from(districts).join(", ")} · ${count} schools`,
    })),
  );
}

function partnerOptions(schools: SchoolRow[]): FilterOption[] {
  const seen = new Map<string, { name: string; count: number; districts: Set<string> }>();
  for (const s of schools) {
    if (!s.assignedPartnerId) continue;
    const cur = seen.get(s.assignedPartnerId);
    if (cur) {
      cur.count += 1;
      cur.districts.add(s.district);
    } else {
      seen.set(s.assignedPartnerId, {
        name: s.assignedPartnerName ?? s.assignedPartnerId,
        count: 1,
        districts: new Set([s.district]),
      });
    }
  }
  const sorted = Array.from(seen.entries()).sort((a, b) => a[1].name.localeCompare(b[1].name));
  return withAll(
    "All Partners",
    sorted.map(([id, { name, count, districts }]) => ({
      id,
      label: name,
      caption: `${Array.from(districts).join(", ")} · ${count} ${count === 1 ? "school" : "schools"}`,
    })),
  );
}

// ────────── Program-defined static option sets ──────────
//
// Slice 1 uses the spec's Core Package list. Later slices will lift
// these into a `lib/program-packages.ts` config file once the model
// owner confirms the canonical list.

// The official 8 SSA interventions — labels + display order match the canonical
// list. (ids are kept stable so existing filter state keeps resolving.)
const PACKAGE_OPTIONS: FilterOption[] = [
  { id: ALL_SENTINEL,  label: "All Core Packages" },
  { id: "christlike",  label: "Christ-like Behavior" },
  { id: "word",        label: "Exposure to the Word of God" },
  { id: "leadership",  label: "Leadership Best Practice" },
  { id: "teaching",    label: "Teaching Environment" },
  { id: "environment", label: "Learning Environment" },
  { id: "compliance",  label: "Government Requirements" },
  { id: "financial",   label: "Fees / Budget / Accounts" },
  { id: "enrollment",  label: "Enrollment" },
];

const SSA_OPTIONS: FilterOption[] = [
  { id: ALL_SENTINEL, label: "All SSA Status" },
  { id: "complete",   label: "Complete",  caption: "Current FY SSA done" },
  { id: "not_done",   label: "Not Done",  caption: "Current FY SSA missing" },
];

const CHAMPION_OPTIONS: FilterOption[] = [
  { id: ALL_SENTINEL, label: "All Champion Status" },
  { id: "verified",  label: "Verified Champion School" },
  { id: "potential", label: "Potential Champion" },
];

// ────────── Public entry point ──────────

export type GetFilterScopeArgs = {
  user: DemoUser;
  // When the backend is live, a server page can pass the district NAMES the
  // user actually has data for (from /analytics/districts). The geography
  // dropdowns are then built from the LIVE universe — so the bar offers exactly
  // the districts that exist in the data (and the region→district cascade +
  // active-label resolve against real options), instead of the mock portfolio.
  // Omitted → falls back to the mock-derived scope (dev / backend-off).
  liveDistrictNames?: string[];
};

export function getFilterScope({ user, liveDistrictNames }: GetFilterScopeArgs): FilterScope {
  const vis = visibilityFor(user.role);
  const schools = visibleSchoolsFor(user);
  // Live district universe takes precedence. `liveDistrictNames` already comes
  // from the role-scoped /analytics/districts endpoint, so it IS the user's
  // permitted set — trust it directly rather than re-intersecting with the mock
  // portfolio (whose identity can differ from the live backend account).
  const allowed = liveDistrictNames ? new Set(liveDistrictNames) : scopedDistrictNames(user, schools);
  const fyOpts = buildFyOptions();
  const activeFyId = fyOpts[0]?.id ?? "";

  return {
    fy:       entry(vis.fy,       fyOpts),
    quarter:  entry(vis.quarter,  buildQuarterOptions(activeFyId)),
    region:   entry(vis.region,   regionOptions(schools, allowed)),
    district: entry(vis.district, districtOptions(schools, allowed)),
    cluster:  entry(vis.cluster,  clusterOptions(schools)),
    cceo:     entry(vis.cceo,     cceoOptions(schools, user)),
    partner:  entry(vis.partner,  partnerOptions(schools)),
    package:  entry(vis.package,  PACKAGE_OPTIONS),
    ssa:      entry(vis.ssa,      SSA_OPTIONS),
    champion: entry(vis.champion, CHAMPION_OPTIONS),
  };
}
