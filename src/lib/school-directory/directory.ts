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
import type { PlanningSignal } from "@/lib/schools-mock";

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

/** One metric for the compact MetricStrip (dense alternative to the tile grid).
 *  Counts carry their proportion as a caption so no info is lost vs the donuts. */
export type DirectoryMetric = {
  key: string;
  label: string;
  value: number;
  caption?: string;
  tone?: "default" | "alert" | "good";
};

export function directoryMetrics(schools: IntakeSchool[]): DirectoryMetric[] {
  const total = schools.length;
  const denom = Math.max(total, 1);
  const pct = (n: number) => `${Math.round((n / denom) * 1000) / 10}%`;
  const withPartner = schoolIdsWithActivePartner();
  const client = schools.filter((s) => s.schoolType === "Client").length;
  const core = schools.filter((s) => s.schoolType === "Core").length;
  const clustered = schools.filter((s) => clusterStatusOf(s) === "clustered").length;
  const unclustered = total - clustered;
  const owned = schools.filter((s) => resolveOwner(s.assignedCceo).status === "matched").length;
  const partners = schools.filter((s) => withPartner.has(s.schoolId)).length;
  const ssaDone = schools.filter((s) => s.ssaStatus === "SSA Done").length;
  const ssaMiss = total - ssaDone;

  return [
    { key: "total",       label: "Total Schools",     value: total },
    { key: "client",      label: "Client",            value: client,      caption: pct(client) },
    { key: "core",        label: "Core",              value: core,        caption: pct(core) },
    { key: "clustered",   label: "Clustered",         value: clustered,   caption: pct(clustered), tone: clustered ? "good" : "default" },
    { key: "unclustered", label: "Unclustered",       value: unclustered, caption: pct(unclustered), tone: unclustered ? "alert" : "default" },
    { key: "ssa_done",    label: "SSA Complete",      value: ssaDone,     caption: pct(ssaDone), tone: ssaDone ? "good" : "default" },
    { key: "ssa_miss",    label: "SSA Pending",       value: ssaMiss,     caption: pct(ssaMiss), tone: ssaMiss ? "alert" : "default" },
    { key: "staff",       label: "Owned by Staff",    value: owned,       caption: pct(owned) },
    { key: "partners",    label: "Partner-Supported", value: partners,    caption: pct(partners) },
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
