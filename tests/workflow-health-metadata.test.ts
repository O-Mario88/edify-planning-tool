// Metadata coverage test for the Workflow Health Monitor.
//
// Catches the common drift bug: a new WorkflowCheckId is added to the union
// type but its CHECK_META entry or its HREF mapping is forgotten — which
// would crash the System Health page at render time.

import { describe, expect, it } from "vitest";
import { WORKFLOW_CHECK_META, WORKFLOW_CHECK_HREF } from "@/lib/health/workflow-health";

describe("workflow-health metadata", () => {
  it("every check id has metadata (label + description + severity)", () => {
    for (const [id, meta] of Object.entries(WORKFLOW_CHECK_META)) {
      expect(meta.label, `missing label for ${id}`).toBeTruthy();
      expect(meta.description, `missing description for ${id}`).toBeTruthy();
      expect(["critical", "warning", "info"], `bad severity for ${id}`).toContain(meta.severity);
    }
  });

  it("every check id has an href", () => {
    for (const id of Object.keys(WORKFLOW_CHECK_META)) {
      expect(WORKFLOW_CHECK_HREF[id as keyof typeof WORKFLOW_CHECK_HREF], `missing href for ${id}`).toBeTruthy();
    }
  });

  it("includes the eleven budget integrity checks", () => {
    const budgetChecks = [
      "activity_missing_budget_line",
      "budget_line_no_catalogue_version",
      "partner_activity_no_partner_rate",
      "training_no_participant_cost",
      "weekly_request_missing_activity",
      "monthly_budget_missing_activity",
      "duplicate_activity_in_request",
      "rescheduled_activity_in_old_period",
      "approved_request_has_cost_blockers",
      "fund_request_total_mismatch",
      "staff_no_primary_district",
    ] as const;
    for (const id of budgetChecks) {
      expect(WORKFLOW_CHECK_META[id]).toBeDefined();
      expect(WORKFLOW_CHECK_HREF[id]).toBeDefined();
    }
  });

  it("includes the fourteen upload + evidence integrity checks", () => {
    const uploadChecks = [
      "school_upload_failed_rows",
      "school_missing_geography",
      "ssa_record_missing_school",
      "school_ssa_without_scores",
      "evidence_missing_storage_object",
      "storage_object_missing_evidence_row",
      "docx_conversion_failed",
      "evidence_view_url_invalid",
      "completed_without_evidence",
      "submitted_to_ia_without_evidence",
      "submitted_to_ia_without_activity_code",
      "ia_verified_without_evidence",
      "evidence_uploaded_by_unauthorized_user",
      "evidence_view_attempted_by_unauthorized_user",
    ] as const;
    for (const id of uploadChecks) {
      expect(WORKFLOW_CHECK_META[id]).toBeDefined();
      expect(WORKFLOW_CHECK_HREF[id]).toBeDefined();
    }
  });
});
