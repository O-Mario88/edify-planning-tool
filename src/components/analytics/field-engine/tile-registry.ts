// Drilldown registry for the engine-backed analytics surface.
// Each metric key is a tile-filter id, so clicking a KPI opens the exact
// records behind the number (via ?tileFilter=<key> + ActiveTileFilterHeader).

import type { TileFilterSpec } from "@/components/tile-filter/types";

export const FIELD_ANALYTICS_TILES: TileFilterSpec[] = [
  { id: "schoolsReached",     label: "Schools Reached",       description: "Unique schools with a qualifying completed/verified activity in scope.", entityType: "school" },
  { id: "learnersImpacted",   label: "Learners Impacted",     description: "Latest enrollment summed over unique reached schools.",                  entityType: "school" },
  { id: "teachersTrained",    label: "Teachers Trained",      description: "Unique teachers (dedup by identity) from verified trainings.",          entityType: "training" },
  { id: "schoolLeadersTrained", label: "School Leaders Trained", description: "Unique school leaders from verified trainings.",                     entityType: "training" },
  { id: "districtsCovered",   label: "Districts Covered",     description: "Distinct districts with a reached school.",                              entityType: "school" },
  { id: "clustersCovered",    label: "Clusters Covered",      description: "Distinct clusters with a reached school.",                               entityType: "cluster" },
  { id: "activitiesCompleted", label: "Activities Completed", description: "Activities past the Salesforce completion gate.",                       entityType: "activity" },
  { id: "ssaImproved",        label: "Schools Improved (SSA)", description: "Reached schools whose latest SSA beats the previous.",                  entityType: "ssa" },
  { id: "ssaDeclined",        label: "Schools Declined (SSA)", description: "Reached schools whose latest SSA fell.",                                entityType: "ssa" },
  { id: "examImproved",       label: "Exam — Improved",       description: "Schools whose collected exam score beat last year.",                    entityType: "school" },
  { id: "mscDonorReady",      label: "MSC — Donor-Ready",     description: "Most-Significant-Change stories cleared for donor reporting.",          entityType: "school" },
];
