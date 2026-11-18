package partneroversight

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The group trainings and cluster meetings a Partner facilitates
// (partner_oversight_service.FacilitatedTraining, facilitated_trainings):
// the officer's own work, read under the Partner that facilitates it.

// training is one facilitated training.
type training struct {
	activityID, activityType, status string
	partnerID, partnerName           string
	place, district                  string
	name, intervention               string
	day                              *time.Time
	fee                              int64
	cceoID, cceoName, plID           string
	// The completion columns.
	salesforceID              string
	isComplete, showsComplete bool
	completionGap             string
}

var returnedStatuses = []string{"returned", "returned_by_pl", "returned_by_ia"}

func (t *training) awaitsReview() bool { return t.status == "submitted_to_pl" }
func (t *training) withIA() bool       { return t.status == "awaiting_ia_verification" }
func (t *training) isReturned() bool   { return in(returnedStatuses, t.status) }

func (t *training) isOverdue(today time.Time) bool {
	return !t.isComplete && t.completionGap == "" && !t.isReturned() && t.day != nil && t.day.Before(today)
}

// statusLabel is Upcoming until the officer completes it, Completed once
// its Salesforce ID is in, Verified once confirmed; Returned, Overdue, or
// what a done status is missing.
func (t *training) statusLabel(today time.Time) string {
	switch {
	case t.isReturned():
		return "Returned"
	case t.showsComplete:
		return "Verified"
	case t.isComplete:
		return "Completed"
	case t.completionGap != "":
		return t.completionGap
	case t.isOverdue(today):
		return "Overdue"
	}
	return "Upcoming"
}

// deliveryPhase is the page's status filter keys.
func (t *training) deliveryPhase() string {
	switch {
	case t.isReturned():
		return "returned"
	case in(rules.Work.Completion.CompletedWork, t.status):
		return "completed"
	case t.awaitsReview(), t.withIA():
		return "verification"
	case t.status == "in_progress", t.status == "completion_started":
		return "in_progress"
	}
	return "scheduled"
}

// readTrainings is facilitated_trainings over the years read: a team's
// (staff), a region's (regions) or the country's (both nil).
func readTrainings(ctx context.Context, db schooldirectory.Querier, staff, regions, years []string) ([]*training, error) {
	acts, err := readActivities(ctx, db, `a.deleted_at IS NULL AND COALESCE(a.facilitating_partner_id, '') <> ''
  AND a.status <> ALL($1) AND a.fy = ANY($2)
  AND ($3::text[] IS NULL OR a.responsible_staff_id = ANY($3) OR c.responsible_staff_id = ANY($3))
  AND ($4::text[] IS NULL OR c.region_id = ANY($4) OR s.region_id = ANY($4))
ORDER BY a.created_at DESC, a.id`, []string{"cancelled", "rejected", "deferred"}, years, staff, regions)
	if err != nil || len(acts) == 0 {
		return nil, err
	}
	ids := make([]string, 0, len(acts))
	for _, a := range acts {
		ids = append(ids, a.id)
	}
	rows, err := db.Query(ctx, `
SELECT a.id, COALESCE(a.facilitating_partner_id, ''), COALESCE(p.name, ''),
  COALESCE(c.name, s.name, ''), COALESCE(CASE WHEN c.id IS NOT NULL THEN cd.name ELSE sd.name END, ''),
  COALESCE((SELECT SUM(l.amount) FROM activity_schedule_cost_line l WHERE l.activity_id = a.id AND l.line_item_type = 'facilitation'), 0)::bigint
FROM activity a
LEFT JOIN partner p ON p.id = a.facilitating_partner_id
LEFT JOIN cluster c ON c.id = a.cluster_id LEFT JOIN district cd ON cd.id = c.district_id
LEFT JOIN school s ON s.id = a.school_id LEFT JOIN district sd ON sd.id = s.district_id
WHERE a.id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("partneroversight: reading the facilitated trainings: %w", err)
	}
	type more struct {
		partnerID, partnerName, place, district string
		fee                                     int64
	}
	extra := map[string]more{}
	for rows.Next() {
		var id string
		var m more
		if err := rows.Scan(&id, &m.partnerID, &m.partnerName, &m.place, &m.district, &m.fee); err != nil {
			rows.Close()
			return nil, fmt.Errorf("partneroversight: reading the facilitated trainings: %w", err)
		}
		extra[id] = m
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	staffIDs := []string{}
	for _, a := range acts {
		staffIDs = append(staffIDs, a.responsible, a.clusterOwner)
	}
	dir, err := readDirectory(ctx, db, nonEmpty(staffIDs))
	if err != nil {
		return nil, err
	}
	// The completion columns, over stand-in items (staff work: complete
	// with its Salesforce ID alone).
	stand := make([]*item, 0, len(acts))
	out := make([]*training, 0, len(acts))
	for _, a := range acts {
		m := extra[a.id]
		owner := first(a.responsible, a.clusterOwner)
		t := &training{activityID: a.id, activityType: a.activityType, status: a.status,
			partnerID: m.partnerID, partnerName: m.partnerName, place: m.place, district: m.district,
			day: a.day(), fee: m.fee, cceoName: dir.names[owner]}
		t.cceoID = owner
		if c, ok := dir.canonical[owner]; ok {
			t.cceoID = c
		}
		if s, ok := dir.supervisor[t.cceoID]; ok {
			t.plID = s[0]
		}
		name, _, intervention := describe(work{act: a})
		if name == "" {
			name = a.snapshot
		}
		if name == "" {
			name = choiceLabel(a.activityType, rules.Work.ActivityTypeLabels)
		}
		t.name, t.intervention = name, intervention
		out = append(out, t)
		stand = append(stand, &item{act: a, activityStatus: a.status})
	}
	if err := annotate(ctx, db, stand, time.Time{}); err != nil {
		return nil, err
	}
	for k, t := range out {
		s := stand[k]
		t.salesforceID, t.isComplete, t.completionGap, t.showsComplete = s.salesforceID, s.isComplete, s.completionGap, s.showsComplete()
	}
	// Open work by its training date, undated last among it; complete work
	// at the bottom (sort_completed_last).
	sort.SliceStable(out, func(x, y int) bool {
		a, b := out[x], out[y]
		if a.isComplete != b.isComplete {
			return !a.isComplete
		}
		if (a.day == nil) != (b.day == nil) {
			return a.day != nil
		}
		return a.day != nil && a.day.Before(*b.day)
	})
	return out, nil
}

// trainingsBlocks is partner_trainings_table.html under the Clusters tab:
// its heading and its table.
func (v *workView) trainingsBlocks(list []*training) []*screensv1.PageBlock {
	table := &screensv1.PageTable{}
	for _, l := range []string{"Cluster Name", "District", "Training Name", "SSA Intervention", "Training Date",
		"Salesforce ID", "Status", "Cost", "Action"} {
		table.Columns = append(table.Columns, &screensv1.PageColumn{Label: l, Numeric: l == "Cost"})
	}
	for _, t := range list {
		sf := t.salesforceID
		if sf == "" {
			sf = "Not in SF"
		}
		dated := jMY(t.day)
		if dated == "" {
			dated = "Not dated"
		}
		// The record-action mark sits on the button's wrapper, not the
		// cell, so the feed reads the lone link as the cell's text.
		action := &screensv1.PageCell{Text: "View activity", Href: "/activities/" + t.activityID}
		if t.withIA() {
			action = &screensv1.PageCell{Text: "With Impact Assessment"}
		}
		row := &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: orDash(t.place)}, {Text: orDash(t.district)}, {Text: orDefault(t.name, "Group training")},
			{Text: orDash(t.intervention)}, {Text: dated}, {Text: sf}, {Text: t.statusLabel(v.today)},
			{Text: "UGX " + intcomma(t.fee)}, action,
		}}
		if t.isOverdue(v.today) {
			row.Tone = "overdue"
		}
		table.Rows = append(table.Rows, row)
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Section{Section: "Trainings and meetings facilitated (" + strconv.Itoa(len(list)) + ")"}},
		{Kind: &screensv1.PageBlock_Table{Table: table}},
	}
}
