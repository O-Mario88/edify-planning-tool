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

// creditRule is one MilestoneActivityRule as _rule_matches reads it.
type creditRule struct {
	ID, Milestone, Catalogue, Weight                                 string
	Project, Executor, Method, SchoolType, SchoolLevel, Intervention string
}

// creditFacts is what apps.hr.milestone_progress._rule_matches reads of the work.
type creditFacts struct {
	Catalogue, Project, Delivery, Method, SchoolType, Intervention string
	HasSchool                                                      bool
}

// reversedCredit is a credit an earlier return took back.
type reversedCredit struct {
	ID   string
	Rule creditRule
}

// matches is _rule_matches for approved work. A rule naming a school level
// never matches: no school record carries one.
func (r creditRule) matches(work creditFacts) bool {
	switch {
	case r.Catalogue != work.Catalogue:
		return false
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
// a milestone already credited. Rules are taken oldest first, the order the
// existing unordered query returns them in.
func plannedCredits(all []creditRule, work creditFacts, credited map[string]bool) []creditRule {
	planned := []creditRule{}
	taken := map[string]bool{}
	for _, rule := range all {
		if !rule.matches(work) || credited[rule.Milestone] || taken[rule.Milestone] {
			continue
		}
		taken[rule.Milestone] = true
		planned = append(planned, rule)
	}
	return planned
}

// revivedCredits is the reversed credits whose rule still matches the work,
// and their milestones. The same row counts again rather than a second one.
func revivedCredits(reversed []reversedCredit, work creditFacts) ([]string, []string) {
	ids, milestones := []string{}, []string{}
	for _, credit := range reversed {
		if !credit.Rule.matches(work) {
			continue
		}
		ids = append(ids, credit.ID)
		if !slices.Contains(milestones, credit.Rule.Milestone) {
			milestones = append(milestones, credit.Rule.Milestone)
		}
	}
	return ids, milestones
}

// salesforceSatisfied is _salesforce_reference_satisfied.
func salesforceSatisfied(recordType, id string) bool {
	return recordType == noSalesforceRecord || strings.TrimSpace(id) != ""
}

// progressPlan is what an approval does to milestone progress.
type progressPlan struct {
	credits  []creditRule
	revive   []string
	refresh  []string
	snapshot map[string]any
}

const creditRuleColumns = `r.id, r.milestone_id, r.catalogue_item_id, COALESCE(NULLIF(r.weight, 0), 1)::text,
       COALESCE(r.project_id, ''), COALESCE(r.required_executor_type, ''), COALESCE(r.required_delivery_method, ''),
       COALESCE(r.school_type, ''), COALESCE(r.school_level, ''), COALESCE(r.target_intervention, '')`

func scanCreditRule(row pgx.Row, extra ...any) (creditRule, error) {
	var c creditRule
	err := row.Scan(append(extra, &c.ID, &c.Milestone, &c.Catalogue, &c.Weight, &c.Project, &c.Executor,
		&c.Method, &c.SchoolType, &c.SchoolLevel, &c.Intervention)...)
	return c, err
}

// planProgress reads what record_activity_progress will do, before the
// approval is written.
func planProgress(ctx context.Context, q schooldirectory.Querier, r Review) (progressPlan, error) {
	if r.CatalogueItemID == "" {
		return progressPlan{}, nil
	}
	work := creditFacts{Catalogue: r.CatalogueItemID}
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
		return progressPlan{}, fmt.Errorf("plreview: reading the work's credit facts: %w", err)
	}
	if !salesforceSatisfied(recordType, salesforceID) {
		return progressPlan{}, nil
	}
	if project != nil {
		work.Project = *project
	}
	if intervention != nil {
		work.Intervention = *intervention
	}
	reversed, err := readReversedCredits(ctx, q, r.ID)
	if err != nil {
		return progressPlan{}, err
	}
	revive, refresh := revivedCredits(reversed, work)
	active, err := readActiveRules(ctx, q, r.CatalogueItemID)
	if err != nil {
		return progressPlan{}, err
	}
	credited, err := readCreditedMilestones(ctx, q, r.ID)
	if err != nil {
		return progressPlan{}, err
	}
	for _, milestone := range refresh {
		credited[milestone] = true
	}
	planned := plannedCredits(active, work, credited)
	for _, rule := range planned {
		if !slices.Contains(refresh, rule.Milestone) {
			refresh = append(refresh, rule.Milestone)
		}
	}
	var catalogueVersion any
	if version != nil {
		catalogueVersion = *version
	}
	return progressPlan{credits: planned, revive: revive, refresh: refresh, snapshot: map[string]any{
		"activityId": r.ID, "catalogueItemId": r.CatalogueItemID, "catalogueVersion": catalogueVersion,
		"intervention": textOrNil(intervention), "projectId": textOrNil(project),
		"executorType": work.Delivery, "status": statusVerified,
	}}, nil
}

func readReversedCredits(ctx context.Context, q schooldirectory.Querier, activityID string) ([]reversedCredit, error) {
	rows, err := q.Query(ctx, `SELECT c.id, `+creditRuleColumns+`
  FROM hr_milestone_progress_credit c JOIN hr_milestone_activity_rule r ON r.id = c.rule_id
 WHERE c.activity_id = $1 AND c.reversed_at IS NOT NULL ORDER BY c.created_at, c.id`, activityID)
	if err != nil {
		return nil, fmt.Errorf("plreview: reading the reversed credits: %w", err)
	}
	reversed, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (reversedCredit, error) {
		var credit reversedCredit
		rule, err := scanCreditRule(row, &credit.ID)
		credit.Rule = rule
		return credit, err
	})
	if err != nil {
		return nil, fmt.Errorf("plreview: reading a reversed credit: %w", err)
	}
	return reversed, nil
}

func readActiveRules(ctx context.Context, q schooldirectory.Querier, catalogueItem string) ([]creditRule, error) {
	rows, err := q.Query(ctx, `SELECT `+creditRuleColumns+`
  FROM hr_milestone_activity_rule r JOIN hr_priority_milestone m ON m.id = r.milestone_id
 WHERE r.active AND r.catalogue_item_id = $1 AND m.active AND NOT m.requires_definition
 ORDER BY r.created_at, r.id`, catalogueItem)
	if err != nil {
		return nil, fmt.Errorf("plreview: reading the milestone rules: %w", err)
	}
	active, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (creditRule, error) {
		return scanCreditRule(row)
	})
	if err != nil {
		return nil, fmt.Errorf("plreview: reading a milestone rule: %w", err)
	}
	return active, nil
}

func readCreditedMilestones(ctx context.Context, q schooldirectory.Querier, activityID string) (map[string]bool, error) {
	rows, err := q.Query(ctx, `
SELECT DISTINCT x.milestone_id FROM hr_milestone_progress_credit c JOIN hr_milestone_activity_rule x ON x.id = c.rule_id
 WHERE c.activity_id = $1 AND c.reversed_at IS NULL`, activityID)
	if err != nil {
		return nil, fmt.Errorf("plreview: reading the work's credits: %w", err)
	}
	milestones, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("plreview: reading a credit: %w", err)
	}
	credited := make(map[string]bool, len(milestones))
	for _, milestone := range milestones {
		credited[milestone] = true
	}
	return credited, nil
}

func textOrNil(value *string) any {
	if value == nil {
		return nil
	}
	return *value
}

// recordProgress is record_activity_progress, run once the approval has
// committed: credits brought back, credits earned, and each moved milestone's
// period figures recomputed.
func (s *ReviewService) recordProgress(ctx context.Context, activityID string, plan progressPlan, now time.Time) error {
	if len(plan.credits) == 0 && len(plan.revive) == 0 {
		return nil
	}
	snapshot, err := json.Marshal(plan.snapshot)
	if err != nil {
		return fmt.Errorf("encoding the credit's snapshot: %w", err)
	}
	return s.inTransaction(ctx, func(tx pgx.Tx) error {
		if len(plan.revive) > 0 {
			if _, err := tx.Exec(ctx, `SELECT gateway_pl_review.revive_credits($1)`, plan.revive); err != nil {
				return fmt.Errorf("bringing back the reversed credits: %w", err)
			}
		}
		for _, credit := range plan.credits {
			if _, err := tx.Exec(ctx, `SELECT gateway_pl_review.record_credit($1, $2, $3, $4::numeric, $5::jsonb, $6)`,
				cuid.New(), credit.ID, activityID, credit.Weight, string(snapshot), now); err != nil {
				return fmt.Errorf("recording the credit on rule %s: %w", credit.ID, err)
			}
		}
		for _, milestone := range plan.refresh {
			if err := refreshPeriodTargets(ctx, tx, milestone, now); err != nil {
				return err
			}
		}
		return nil
	})
}
