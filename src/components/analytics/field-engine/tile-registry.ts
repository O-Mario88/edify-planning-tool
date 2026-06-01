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
  { id: "coreSchoolsReached", label: "Core Schools Reached",  description: "Reached schools on the Core track.",                                    entityType: "school" },
  { id: "activitiesCompleted", label: "Activities Completed", description: "Activities past the Salesforce completion gate.",                       entityType: "activity" },
  { id: "ssaImproved",        label: "Schools Improved (SSA)", description: "Reached schools whose latest SSA beats the previous.",                  entityType: "ssa" },
  { id: "ssaDeclined",        label: "Schools Declined (SSA)", description: "Reached schools whose latest SSA fell.",                                entityType: "ssa" },
  { id: "examImproved",       label: "Exam — Improved",       description: "Schools whose collected exam score beat last year.",                    entityType: "school" },
  { id: "mscDonorReady",      label: "MSC — Donor-Ready",     description: "Most-Significant-Change stories cleared for donor reporting.",          entityType: "school" },
  // Verification & evidence
  { id: "evidenceUploaded",   label: "Evidence Uploaded",     description: "Activities with evidence uploaded.",                                    entityType: "evidence" },
  { id: "evidenceAccepted",   label: "Evidence Accepted",     description: "Activities whose evidence is complete or verified.",                    entityType: "evidence" },
  { id: "evidenceReturned",   label: "Evidence Returned",     description: "Activities whose evidence was returned for correction.",                entityType: "evidence" },
  { id: "evidenceMissing",    label: "Evidence Missing",      description: "Activities with no evidence uploaded.",                                 entityType: "evidence" },
  { id: "sfEntered",          label: "Salesforce IDs Entered", description: "Activities with a Salesforce ID entered.",                             entityType: "activity" },
  { id: "iaVerified",         label: "IA Verified",           description: "Activities verified by Impact Assessment.",                             entityType: "activity" },
  { id: "sfMissing",          label: "Missing Salesforce ID", description: "Activities blocked at the Salesforce completion gate.",                 entityType: "activity" },
  { id: "selfVerification",   label: "Self-Verification (10%)", description: "Staff self-verified Client schools — 10% portfolio quota.",            entityType: "school" },
  // Payment
  { id: "paymentsAwaitingPl", label: "Awaiting PL Approval",  description: "Payments waiting on Program Lead approval.",                            entityType: "payment" },
  { id: "paymentsSentToAccountant", label: "Sent to Accountant", description: "Payments routed to the accountant.",                                entityType: "payment" },
  { id: "paymentsPaid",       label: "Payments Cleared",      description: "Payments paid and cleared.",                                            entityType: "payment" },
  { id: "paymentsBlocked",    label: "Payments Blocked",      description: "Payments blocked by the Salesforce completion gate.",                   entityType: "payment" },
  // Exam + MSC
  { id: "examResultsCollected", label: "Exam Results Collected", description: "Schools with collected exam results this FY.",                       entityType: "school" },
  { id: "examMissing",        label: "Exam Results Missing",  description: "Schools with no exam results collected.",                               entityType: "school" },
  { id: "examCollectionRate", label: "Exam Collection Rate",  description: "Percent of in-scope schools with collected exam results.",              entityType: "school" },
  { id: "mscSubmitted",       label: "MSC Stories Submitted", description: "Most-Significant-Change stories submitted in scope.",                   entityType: "school" },
  { id: "mscPendingReview",   label: "MSC Pending Review",    description: "MSC stories awaiting PL review.",                                       entityType: "school" },
];
