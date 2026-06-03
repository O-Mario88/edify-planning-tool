// Canonical School Directory accessor — the SINGLE source of truth.
//
// The uploaded schools (`intakeSchools`) are the master record; this module is
// the one place the directory's scoped list + headline numbers are derived, so
// /schools (and anything else) reads the same truth as clustering, SSA, and
// planning. Replaces the legacy schoolsMock-derived KPIs on the directory page.

import type { EdifyRole } from "@/lib/auth";
import { intakeSchools, type IntakeSchool } from "@/lib/intake/intake-mock";
import { resolveOwner } from "@/lib/portfolio/portfolio";
import { visibleStaffIds } from "@/lib/org/supervision";
import { schoolIdsWithActivePartner } from "@/lib/portfolio/partner-assignments";
import { clusterStatusOf } from "@/lib/cluster/cluster-core";
import { schoolWorkflowState } from "./school-state";
import { openDuplicateCandidates } from "@/lib/intake/duplicate-candidates-mock";
import type { SchoolKpi, StatusSnapshotTile, PlanningSignal } from "@/lib/schools-mock";

const SEES_ALL: ReadonlySet<string> = new Set(["Admin", "CountryDirector", "RVP", "ImpactAssessment"]);

/** The viewer's directory — uploaded schools scoped to their supervision chain. */
export function directoryRecords(staffId: string, role: EdifyRole): IntakeSchool[] {
  if (SEES_ALL.has(role)) return intakeSchools;
  const scope = visibleStaffIds(staffId, role);
  return intakeSchools.filter((s) => {
    const r = resolveOwner(s.assignedCceo);
    return r.status === "matched" ? scope.has(r.staffId) : true; // never hide unplaceable
  });
}

const FLAT = { pct: "—", tone: "up" as const };

/** Headline KPIs computed from the master (same shape the KPI row renders). */
export function directoryKpis(schools: IntakeSchool[]): SchoolKpi[] {
  const withPartner = schoolIdsWithActivePartner();
  const total = schools.length;
  const client = schools.filter((s) => s.schoolType === "Client").length;
  const core = schools.filter((s) => s.schoolType === "Core").length;
  const owned = schools.filter((s) => resolveOwner(s.assignedCceo).status === "matched").length;
  const partners = schools.filter((s) => withPartner.has(s.schoolId)).length;
  const clustered = schools.filter((s) => clusterStatusOf(s) === "clustered").length;
  const unclustered = total - clustered;
  const ssaDone = schools.filter((s) => s.ssaStatus === "SSA Done").length;
  const ssaMiss = total - ssaDone;

  return [
    { key: "total",     label: "Total Schools",       value: total,       delta: FLAT, icon: "school",      iconTone: "edify",   spark: { seed: 21, trend: "up" } },
    { key: "client",    label: "Client Schools",      value: client,      delta: FLAT, icon: "briefcase",   iconTone: "blue",    spark: { seed: 23, trend: "up" } },
    { key: "core",      label: "Core Schools",        value: core,        delta: FLAT, icon: "shield",      iconTone: "violet",  spark: { seed: 24, trend: "up" } },
    { key: "clustered", label: "Clustered",           value: clustered,   delta: FLAT, icon: "checkCircle", iconTone: "emerald", spark: { seed: 30, trend: "up" } },
    { key: "unclustered", label: "Unclustered",       value: unclustered, delta: { pct: "—", tone: "down" }, icon: "schoolOff", iconTone: "rose", spark: { seed: 31, trend: "down" } },
    { key: "staff",     label: "Owned by Staff",      value: owned,       delta: FLAT, icon: "userPlus",    iconTone: "amber",   spark: { seed: 26, trend: "up" } },
    { key: "partners",  label: "Partner-Supported",   value: partners,    delta: FLAT, icon: "handshake",   iconTone: "edify",   spark: { seed: 27, trend: "up" } },
    { key: "ssa_done",  label: "SSA Complete",        value: ssaDone,     delta: FLAT, icon: "checkCircle", iconTone: "emerald", spark: { seed: 28, trend: "up" } },
    { key: "ssa_miss",  label: "SSA Pending",         value: ssaMiss,     delta: { pct: "—", tone: "down" }, icon: "xCircle", iconTone: "red", spark: { seed: 29, trend: "down" } },
  ];
}

/** Status snapshot tiles from the master. */
export function directoryStatusSnapshot(schools: IntakeSchool[]): StatusSnapshotTile[] {
  const total = Math.max(schools.length, 1);
  const pct = (n: number) => Math.round((n / total) * 1000) / 10;
  const withPartner = schoolIdsWithActivePartner();
  const client = schools.filter((s) => s.schoolType === "Client").length;
  const core = schools.filter((s) => s.schoolType === "Core").length;
  const clustered = schools.filter((s) => clusterStatusOf(s) === "clustered").length;
  const unclustered = schools.length - clustered;
  const ssaDone = schools.filter((s) => s.ssaStatus === "SSA Done").length;
  const ssaMiss = schools.length - ssaDone;
  const owned = schools.filter((s) => resolveOwner(s.assignedCceo).status === "matched").length;
  const partners = schools.filter((s) => withPartner.has(s.schoolId)).length;
  return [
    { key: "active",   label: "Clustered",       value: clustered,   pct: pct(clustered),   icon: "checkCircle", tone: "emerald" },
    { key: "inactive", label: "Unclustered",     value: unclustered, pct: pct(unclustered), icon: "schoolOff",   tone: "rose"    },
    { key: "client",   label: "Client Schools",  value: client,      pct: pct(client),      icon: "briefcase",   tone: "blue"    },
    { key: "core",     label: "Core Schools",    value: core,        pct: pct(core),        icon: "shield",      tone: "violet"  },
    { key: "ssa_done", label: "SSA Complete",    value: ssaDone,     pct: pct(ssaDone),     icon: "checkCircle", tone: "emerald" },
    { key: "ssa_miss", label: "SSA Pending",     value: ssaMiss,     pct: pct(ssaMiss),     icon: "xCircle",     tone: "red"     },
    { key: "staff",    label: "Owned by Staff",  value: owned,       pct: pct(owned),       icon: "userPlus",    tone: "amber"   },
    { key: "partners", label: "Partner-Supported", value: partners,  pct: pct(partners),    icon: "handshake",   tone: "edify"   },
  ];
}

/** Planning-readiness signals from the master (the canonical workflow stages). */
export function directoryPlanningSignals(schools: IntakeSchool[]): PlanningSignal[] {
  let needsOwner = 0, unclustered = 0, ssaRequired = 0, planningReady = 0;
  for (const s of schools) {
    const stage = schoolWorkflowState(s).stage;
    if (stage === "needs_owner") needsOwner += 1;
    else if (stage === "unclustered") unclustered += 1;
    else if (stage === "ssa_required") ssaRequired += 1;
    else planningReady += 1;
  }
  const dupes = openDuplicateCandidates().filter((d) => schools.some((s) => s.schoolId === d.schoolId)).length;
  return [
    { key: "needs_owner",    label: "Needs Account Owner", value: needsOwner,   icon: "phone",         tone: "red"    },
    { key: "unclustered",    label: "Unclustered",         value: unclustered,  icon: "mapPin",        tone: "edify"  },
    { key: "ssa_required",   label: "SSA Required",        value: ssaRequired,  icon: "shieldOff",     tone: "amber"  },
    { key: "planning_ready", label: "Planning Ready",      value: planningReady, icon: "gauge",        tone: "violet" },
    { key: "duplicate",      label: "Duplicate Review",    value: dupes,        icon: "schoolOff",     tone: "rose"   },
  ];
}
