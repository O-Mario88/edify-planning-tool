-- Extra Assigned Work saved through Go, with Django absent (apps.hr.extra_work:
-- create_assignment, acknowledge, start, submit, return_work, verify, cancel).
-- internal/extrawork is the table's listed writer in dbguard; nothing is
-- deleted. Applied by apply-roles.sh and the integration TestMain. Idempotent.

GRANT SELECT (id, fy, title, assigner_id, assignee_id, reviewer_id, supervising_pl_id, status, evidence_required,
              due_date, complexity, urgency, return_count, started_at, start_date, contribution_points, instruction,
              expected_output, assigner_role, return_reason)
  ON hr_extra_assignment TO edify_activities_rw;
GRANT INSERT (id, created_at, updated_at, fy, title, instruction, reason, category, linked_priority_id,
              linked_milestone_id, linked_activity_id, assigner_id, assigner_role, assignee_id, assignee_role,
              supervising_pl_id, country, due_date, expected_output, output_unit, evidence_required, reviewer_id,
              complexity, urgency, status, outcome, evidence_note, evidence_uri, return_reason, return_count,
              verified_by, cancel_reason)
  ON hr_extra_assignment TO edify_activities_rw;
GRANT UPDATE (status, acknowledged_at, started_at, start_date, outcome, evidence_note, evidence_uri, submitted_at,
              return_reason, return_count, verified_at, verified_by, completion_date, contribution_points,
              scoring_policy_id, cancelled_at, cancel_reason, updated_at)
  ON hr_extra_assignment TO edify_activities_rw;
GRANT SELECT (id, fy, status, complexity_weights, overdue_multiplier, max_contribution_points)
  ON hr_extra_work_scoring_policy TO edify_activities_rw;
