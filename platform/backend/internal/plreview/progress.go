package plreview

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// noSalesforceRecord is the record type that legitimately carries no ID
// (apps.activities.salesforce.NO_SALESFORCE_RECORD_TYPES).
const noSalesforceRecord = "NONE"

// creditRule is one active MilestoneActivityRule on the work's catalogue item.
type creditRule struct {
	ID, Milestone, Weight                                            string
	Project, Executor, Method, SchoolType, SchoolLevel, Intervention string
}

// creditFacts is what apps.hr.milestone_progress._rule_matches reads of the work.
type creditFacts struct {
	Project, Delivery, Method, SchoolType, Intervention string
	HasSchool                                           bool
}

// matches is _rule_matches for approved work on the rule's catalogue item.
// A rule naming a school level never matches: no school record carries one.
func (r creditRule) matches(work creditFacts) bool {
	switch {
	case r.Project != "" && r.Project != work.Project:
		return false
	case r.Executor != "" && r.Executor != work.Delivery:
		return false
	case r.Method != "" && r.Method != work.Method:
		return false
	case r.SchoolLevel != "":
		return false
	case r.Intervention != "" && r.Intervention != work.Intervention:
		return false
	}
	if r.SchoolType == "" {
		return true
	}
	family, ok := rules.SchoolTypeFamilies[r.SchoolType]
	if !ok {
		family = []string{r.SchoolType}
	}
	return work.HasSchool && slices.Contains(family, work.SchoolType)
}

// plannedCredits is the rules that earn a credit: one per milestone, none for
// a milestone already credited. Two matching rules on one milestone are left
// to the existing application, whose unordered query picks between them.
func plannedCredits(all []creditRule, work creditFacts, credited map[string]bool) ([]creditRule, bool) {
	planned := []creditRule{}
	taken := map[string]bool{}
	for _, rule := range all {
		if !rule.matches(work) || credited[rule.Milestone] {
			continue
		}
		if taken[rule.Milestone] {
			return nil, true
		}
		taken[rule.Milestone] = true
		planned = append(planned, rule)
	}
	return planned, false
}

// salesforceSatisfied is _salesforce_reference_satisfied.
func salesforceSatisfied(recordType, id string) bool {
	return recordType == noSalesforceRecord || strings.TrimSpace(id) != ""
}

// progressPlan is the credits an approval earns and what each one records.
type progressPlan struct {
	credits  []creditRule
	snapshot map[string]any
}

// planProgress reads what record_activity_progress would credit. It is read
// before the approval is written, so a choice Go cannot make hands the whole
// decision on.
func planProgress(ctx context.Context, q schooldirectory.Querier, r Review) (progressPlan, bool, error) {
	if r.CatalogueItemID == "" {
		return progressPlan{}, false, nil
	}
	var work creditFacts
	var recordType, salesforceID string
	var version *int32
	var intervention, project *string
	err := q.QueryRow(ctx, `
SELECT COALESCE(a.salesforce_record_type_snapshot, ''), COALESCE(a.salesforce_activity_id, ''), a.catalogue_version,
       a.focus_intervention, a.project_id, COALESCE(a.delivery_type, ''), COALESCE(a.delivery_method_snapshot, ''),
       a.school_id IS NOT NULL, COALESCE(s.school_type, '')
  FROM activity a LEFT JOIN school s ON s.id = a.school_id WHERE a.id = $1`, r.ID).Scan(
		&recordType, &salesforceID, &version, &intervention, &project,
		&work.Delivery, &work.Method, &work.HasSchool, &work.SchoolType)
	if err != nil {
		return progressPlan{}, false, fmt.Errorf("plreview: reading the work's credit facts: %w", err)
	}
	if !salesforceSatisfied(recordType, salesforceID) {
		return progressPlan{}, false, nil
	}
	if project != nil {
		work.Project = *project
	}
	if intervention != nil {
		work.Intervention = *intervention
	}
	rows, err := q.Query(ctx, `
SELECT r.id, r.milestone_id, COALESCE(NULLIF(r.weight, 0), 1)::text, COALESCE(r.project_id, ''),
       COALESCE(r.required_executor_type, ''), COALESCE(r.required_delivery_method, ''), COALESCE(r.school_type, ''),
       COALESCE(r.school_level, ''), COALESCE(r.target_intervention, '')
  FROM hr_milestone_activity_rule r JOIN hr_priority_milestone m ON m.id = r.milestone_id
 WHERE r.active AND r.catalogue_item_id = $1 AND m.active AND NOT m.requires_definition`, r.CatalogueItemID)
	if err != nil {
		return progressPlan{}, false, fmt.Errorf("plreview: reading the milestone rules: %w", err)
	}
	all, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (creditRule, error) {
		var c creditRule
		err := row.Scan(&c.ID, &c.Milestone, &c.Weight, &c.Project, &c.Executor, &c.Method, &c.SchoolType, &c.SchoolLevel, &c.Intervention)
		return c, err
	})
	if err != nil {
		return progressPlan{}, false, fmt.Errorf("plreview: reading a milestone rule: %w", err)
	}
	creditedRows, err := q.Query(ctx, `
SELECT DISTINCT x.milestone_id FROM hr_milestone_progress_credit c JOIN hr_milestone_activity_rule x ON x.id = c.rule_id
 WHERE c.activity_id = $1 AND c.reversed_at IS NULL`, r.ID)
	if err != nil {
		return progressPlan{}, false, fmt.Errorf("plreview: reading the work's credits: %w", err)
	}
	milestones, err := pgx.CollectRows(creditedRows, pgx.RowTo[string])
	if err != nil {
		return progressPlan{}, false, fmt.Errorf("plreview: reading a credit: %w", err)
	}
	credited := make(map[string]bool, len(milestones))
	for _, milestone := range milestones {
		credited[milestone] = true
	}
	planned, ambiguous := plannedCredits(all, work, credited)
	if ambiguous {
		return progressPlan{}, true, nil
	}
	var catalogueVersion any
	if version != nil {
		catalogueVersion = *version
	}
	return progressPlan{credits: planned, snapshot: map[string]any{
		"activityId": r.ID, "catalogueItemId": r.CatalogueItemID, "catalogueVersion": catalogueVersion,
		"intervention": textOrNil(intervention), "projectId": textOrNil(project),
		"executorType": work.Delivery, "status": statusVerified,
	}}, false, nil
}

func textOrNil(value *string) any {
	if value == nil {
		return nil
	}
	return *value
}

// recordProgress writes the planned credits once the approval has committed,
// where record_activity_progress runs.
func (s *ReviewService) recordProgress(ctx context.Context, activityID string, plan progressPlan, now time.Time) error {
	if len(plan.credits) == 0 {
		return nil
	}
	snapshot, err := json.Marshal(plan.snapshot)
	if err != nil {
		return fmt.Errorf("encoding the credit's snapshot: %w", err)
	}
	return s.inTransaction(ctx, func(tx pgx.Tx) error {
		for _, credit := range plan.credits {
			if _, err := tx.Exec(ctx, `SELECT gateway_pl_review.record_credit($1, $2, $3, $4::numeric, $5::jsonb, $6)`,
				cuid.New(), credit.ID, activityID, credit.Weight, string(snapshot), now); err != nil {
				return fmt.Errorf("recording the credit on rule %s: %w", credit.ID, err)
			}
		}
		return nil
	})
}
