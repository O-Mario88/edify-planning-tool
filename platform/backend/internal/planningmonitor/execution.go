package planningmonitor

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// execution is one person's, one team's or everyone's figures on the
// Execution & Completion tab (apps.planning.execution_monitor
// PersonExecution, TeamExecution).
type execution struct {
	key, name, leadID, leadName, role string
	ids                               []string
	visitsTarget                      int

	visitsPlanned, visitsDelivered                 int
	outreachPlanned, outreachDelivered             int
	trainingsPlanned, trainingsDelivered           int
	meetingsPlanned, meetingsDelivered             int
	planned, due, delivered, deliveredDue          int
	complete, verified, overdue                    int
	missingSalesforce, missingEvidence, awaitingPL int
	returned, partnerScheduled, partnerDelivered   int
	trainingPortfolio, schoolsTrained              int
	remainingVisits, remainingTrain, people        int
}

func (e *execution) isLead() bool { return e.role == rules.RoleCodes[rules.ProgramLeadRole] }

// add sums another's counts in: a team's figures are its people's, and what
// remains is each person's own remainder, summed.
func (e *execution) add(o *execution) {
	for _, pair := range [][2]*int{
		{&e.visitsTarget, &o.visitsTarget}, {&e.visitsPlanned, &o.visitsPlanned}, {&e.visitsDelivered, &o.visitsDelivered},
		{&e.outreachPlanned, &o.outreachPlanned}, {&e.outreachDelivered, &o.outreachDelivered},
		{&e.trainingsPlanned, &o.trainingsPlanned}, {&e.trainingsDelivered, &o.trainingsDelivered},
		{&e.meetingsPlanned, &o.meetingsPlanned}, {&e.meetingsDelivered, &o.meetingsDelivered},
		{&e.planned, &o.planned}, {&e.due, &o.due}, {&e.delivered, &o.delivered}, {&e.deliveredDue, &o.deliveredDue},
		{&e.complete, &o.complete}, {&e.verified, &o.verified}, {&e.overdue, &o.overdue},
		{&e.missingSalesforce, &o.missingSalesforce}, {&e.missingEvidence, &o.missingEvidence}, {&e.awaitingPL, &o.awaitingPL},
		{&e.returned, &o.returned}, {&e.partnerScheduled, &o.partnerScheduled}, {&e.partnerDelivered, &o.partnerDelivered},
		{&e.trainingPortfolio, &o.trainingPortfolio}, {&e.schoolsTrained, &o.schoolsTrained},
		{&e.remainingVisits, &o.remainingVisits}, {&e.remainingTrain, &o.remainingTrain}, {&e.people, &o.people},
	} {
		*pair[0] += *pair[1]
	}
}

// settle is a person's remainders once their counts are in.
func (e *execution) settle() {
	e.remainingVisits = max(0, e.visitsTarget-e.visitsDelivered)
	e.remainingTrain = max(0, e.trainingPortfolio-e.schoolsTrained)
	e.people = 1
}

func (e *execution) listCount(key string) int {
	switch key {
	case "overdue":
		return e.overdue
	case "missing_salesforce":
		return e.missingSalesforce
	case "missing_evidence":
		return e.missingEvidence
	case "awaiting_pl":
		return e.awaitingPL
	case "returned":
		return e.returned
	}
	return 0
}

// executionTeam is a Lead's people on the tab.
type executionTeam struct {
	key, name string
	people    []*execution
	total     execution
}

// executionMonitor is execution_monitor's answer for the reader's roster.
type executionMonitor struct {
	teams  []*executionTeam
	totals execution
}

// readExecution is execution_monitor over the monitor's roster for fy, today
// being the local day: every person's own staff work of the year, their
// partner work, and the schools they hold that take a training.
//
// A region reader's roster is read without the Leads their schools hint at
// (execution_monitor calls monitor_roster with none), so it follows nobody.
func readExecution(ctx context.Context, db schooldirectory.Querier, m *Monitor, fy string, today time.Time, region bool) (*executionMonitor, error) {
	out := &executionMonitor{}
	byKey := map[string]*execution{}
	teams := m.teams
	if region {
		teams = nil
	}
	for _, t := range teams {
		team := &executionTeam{key: t.lead.Key, name: t.lead.Name}
		for _, p := range t.people {
			if _, seen := byKey[p.key]; seen {
				continue
			}
			e := &execution{key: p.key, name: p.name, leadID: team.key, leadName: team.name, role: p.role,
				ids: p.ids, visitsTarget: rules.VisitTargets[p.role]}
			byKey[p.key] = e
			team.people = append(team.people, e)
		}
		if len(team.people) > 0 {
			out.teams = append(out.teams, team)
		}
	}
	if len(byKey) == 0 {
		return out, nil
	}
	byID := map[string]*execution{}
	ids := []string{}
	for _, t := range out.teams {
		for _, e := range t.people {
			for _, id := range e.ids {
				if _, ok := byID[id]; !ok {
					byID[id] = e
					ids = append(ids, id)
				}
			}
		}
	}
	handed, err := handOvers(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	if err := countExecution(ctx, db, m, fy, today, ids, byID, handed); err != nil {
		return nil, err
	}
	// Training is read against every school the person holds that takes
	// one (training_reach).
	for _, o := range m.Officers() {
		for _, s := range o.Schools {
			if !takesTraining(s.Type) {
				continue
			}
			if e := byID[s.OfficerID]; e != nil {
				e.trainingPortfolio++
				if s.TrainingDone {
					e.schoolsTrained++
				}
			}
		}
	}
	for _, t := range out.teams {
		for _, e := range t.people {
			e.settle()
			t.total.add(e)
		}
		out.totals.add(&t.total)
	}
	return out, nil
}

// handOvers is the hand-overs these people made or monitor, by the activity
// each became or carries, the latest first made last.
func handOvers(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string][2]string, error) {
	rows, err := db.Query(ctx, `SELECT COALESCE(scheduled_activity_id, ''), COALESCE(source_activity_id, ''),
  COALESCE(monitoring_staff_id, ''), COALESCE(assigning_staff_id, '')
FROM partner_assignment WHERE (monitoring_staff_id = ANY($1) OR assigning_staff_id = ANY($1))
  AND (scheduled_activity_id IS NOT NULL OR source_activity_id IS NOT NULL) ORDER BY created_at`, ids)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: reading the hand-overs: %w", err)
	}
	defer rows.Close()
	out := map[string][2]string{}
	for rows.Next() {
		var scheduled, source, monitor, assigner string
		if err := rows.Scan(&scheduled, &source, &monitor, &assigner); err != nil {
			return nil, fmt.Errorf("planningmonitor: reading a hand-over: %w", err)
		}
		for _, id := range []string{scheduled, source} {
			if id != "" {
				out[id] = [2]string{monitor, assigner}
			}
		}
	}
	return out, rows.Err()
}

// countExecution folds the year's live activities into each person's row.
func countExecution(ctx context.Context, db schooldirectory.Querier, m *Monitor, fy string, today time.Time,
	ids []string, byID map[string]*execution, handed map[string][2]string) error {
	handedIDs := make([]string, 0, len(handed))
	for id := range handed {
		handedIDs = append(handedIDs, id)
	}
	rows, err := db.Query(ctx, `SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(a.status, ''), a.planned_date,
  COALESCE(a.delivery_type, ''), COALESCE(a.responsible_staff_id, ''), COALESCE(a.monitored_by_staff_id, ''),
  COALESCE(a.school_id, ''), COALESCE(a.purpose_type, ''), COALESCE(a.cluster_id, ''), COALESCE(s.account_owner_id, ''),
  a.scheduled_date IS NOT NULL, COALESCE(TRIM(a.salesforce_activity_id), '')
FROM activity a LEFT JOIN school s ON s.id = a.school_id
WHERE a.deleted_at IS NULL AND a.status = ANY($1) AND a.fy = $2 AND (
  (a.responsible_staff_id = ANY($3) AND a.delivery_type IS DISTINCT FROM 'partner')
  OR (a.delivery_type = 'partner' AND (a.monitored_by_staff_id = ANY($3) OR a.responsible_staff_id = ANY($3)
      OR s.account_owner_id = ANY($3) OR a.id = ANY($4))))`, rules.Execution.LiveStatuses, fy, ids, handedIDs)
	if err != nil {
		return fmt.Errorf("planningmonitor: reading the year's work: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, kind, status, delivery, responsible, monitor, school, purpose, cluster, holder, salesforce string
		var planned *time.Time
		var scheduled bool
		if err := rows.Scan(&id, &kind, &status, &planned, &delivery, &responsible, &monitor, &school, &purpose,
			&cluster, &holder, &scheduled, &salesforce); err != nil {
			return fmt.Errorf("planningmonitor: reading an activity: %w", err)
		}
		delivered := slices.Contains(rules.OfficerCompletedStatuses, status)
		if delivery == "partner" {
			// Dated Partner work only: a hand-over the Partner has not dated
			// is planning still to do.
			if planned == nil && !scheduled {
				continue
			}
			h := handed[id]
			var e *execution
			for _, raw := range []string{h[0], h[1], monitor, responsible, holder} {
				if p, ok := byID[raw]; ok && raw != "" {
					e = p
					break
				}
			}
			if e == nil {
				continue
			}
			e.partnerScheduled++
			if delivered {
				e.partnerDelivered++
			}
			continue
		}
		e := byID[responsible]
		if e == nil {
			continue
		}
		countWork(e, kind, status, purpose, school, cluster, salesforce, planned, delivered, today, m.outside)
	}
	return rows.Err()
}

// countWork is one staff activity on its person's row.
func countWork(e *execution, kind, status, purpose, school, cluster, salesforce string, planned *time.Time, delivered bool,
	today time.Time, outside []string) {
	counted := slices.Contains(rules.DeliveredStatuses, status)
	due := planned != nil && !planned.After(today)
	e.planned++
	atSchool := school != "" && cluster == ""
	switch {
	case atSchool && visitKind(kind, purpose, "", "staff", outside) != "":
		if slices.Contains(rules.PlannedStates, status) {
			e.visitsPlanned++
		}
		e.visitsDelivered += boolInt(counted)
	case atSchool && isUncountedVisit(kind, purpose, "staff", outside):
		e.outreachPlanned++
		e.outreachDelivered += boolInt(delivered)
	}
	switch {
	case slices.Contains(rules.TrainingTypes, kind):
		e.trainingsPlanned++
		e.trainingsDelivered += boolInt(counted)
	case slices.Contains(rules.ClusterMeetingTypes, kind):
		e.meetingsPlanned++
		e.meetingsDelivered += boolInt(counted)
	}
	if due || delivered {
		e.due++
		e.deliveredDue += boolInt(counted)
	}
	switch {
	case slices.Contains(rules.Execution.ReturnedStatuses, status):
		e.returned++
	case due && planned.Before(today) && !delivered:
		e.overdue++
	}
	if !delivered {
		return
	}
	e.delivered++
	// Staff work is complete with its Salesforce ID alone (UPLOAD-OFF).
	if salesforce != "" {
		e.complete++
	} else {
		e.missingSalesforce++
	}
	e.verified += boolInt(counted)
	if slices.Contains(rules.Execution.AwaitingPLStatuses, status) {
		e.awaitingPL++
	}
}
