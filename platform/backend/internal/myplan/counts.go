package myplan

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// PlanRules are what the page counts and lists by (get_frontend_context).
type PlanRules struct {
	ExcludedStatuses         []string      `json:"excluded_statuses"`
	PartnerOnlyStatuses      []string      `json:"partner_only_statuses"`
	OfficerCompletedStatuses []string      `json:"officer_completed_statuses"`
	ReturnedStatuses         []string      `json:"returned_statuses"`
	CompletedWorkStatuses    []string      `json:"completed_work_statuses"`
	NotStartedStatuses       []string      `json:"not_started_statuses"`
	UnderWayStatuses         []string      `json:"under_way_statuses"`
	PlanStates               []string      `json:"plan_states"`
	SubmittedFilterStatuses  []string      `json:"submitted_filter_statuses"`
	ReturnedFilterStatuses   []string      `json:"returned_filter_statuses"`
	VisitTypes               []string      `json:"visit_types"`
	TrainingTypes            []string      `json:"training_types"`
	MeetingTypes             []string      `json:"meeting_types"`
	CountedVisits            CountedVisits `json:"counted_visits"`
	SummaryTrainingTypes     []string      `json:"summary_training_types"`
	SummaryMeetingTypes      []string      `json:"summary_meeting_types"`
	HelperFigureChars        int           `json:"helper_figure_chars"`
}

// CountedVisits are staff_plan.counted_visits' rules
// (country_oversight.rules: planned_q, counted_visit_q, staff_delivery_q).
type CountedVisits struct {
	VisitShapeTypes        []string `json:"visit_shape_types"`
	CompanionPurpose       string   `json:"companion_purpose"`
	OutreachPurposes       []string `json:"outreach_purposes"`
	DataCollectionPurposes []string `json:"data_collection_purposes"`
	DataCollectionTypes    []string `json:"data_collection_types"`
	KindPurposes           []string `json:"kind_purposes"`
	PlannedStates          []string `json:"planned_states"`
	CoreTypes              []string `json:"core_types"`
}

// Filters are the page's other filters as sent: district, staff member,
// activity type, status and the search.
type Filters struct {
	District, Staff, ActivityType, Status, Search string
}

// ReadFilters reads them from the query: the search stripped, the rest as
// sent ("all" and "All" are no choice).
func ReadFilters(query Query) Filters {
	get := func(key string) string {
		for i, k := range query.keys {
			if k == key {
				return query.values[i]
			}
		}
		return ""
	}
	return Filters{District: get("district"), Staff: get("staff"), ActivityType: get("activity_type"),
		Status: get("status"), Search: closedschools.PyStrip(get("q"))}
}

func chosen(value string) bool { return value != "" && value != "all" && value != "All" }

// sqlb numbers a statement's parameters.
type sqlb struct{ args []any }

func (b *sqlb) arg(v any) string {
	b.args = append(b.args, v)
	return "$" + strconv.Itoa(len(b.args))
}

// localDay is a timestamp's day where the platform works (TIME_ZONE,
// Africa/Nairobi: Django's __date).
const localDay = `(a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date`

// inRange is _scheduled_in_range: the planned date, else the scheduled day.
func inRange(b *sqlb, start, end time.Time) string {
	s, e := b.arg(start.Format(time.DateOnly)), b.arg(end.Format(time.DateOnly))
	return fmt.Sprintf(`(a.planned_date BETWEEN %[1]s::date AND %[2]s::date OR (a.planned_date IS NULL AND %[3]s BETWEEN %[1]s::date AND %[2]s::date))`,
		s, e, localDay)
}

// datePassed is _date_passed_q, NULL-safe so that it can be negated as
// Django negates it.
func datePassed(b *sqlb, today string) string {
	t := b.arg(today)
	return fmt.Sprintf(`(COALESCE(a.planned_date < %[1]s::date, false) OR COALESCE(a.planned_date IS NULL AND %[2]s < %[1]s::date, false))`, t, localDay)
}

// statusIn is status__in; notStatusIn its exclude(), which keeps a blank status.
func statusIn(b *sqlb, statuses []string) string {
	return "a.status = ANY(" + b.arg(statuses) + ")"
}

func notStatusIn(b *sqlb, statuses []string) string {
	return "NOT COALESCE(a.status = ANY(" + b.arg(statuses) + "), false)"
}

// weekRange is get_week_date_range: the week of the month, the fifth to its end.
func weekRange(year, month, week int) (time.Time, time.Time) {
	last := daysIn(year, month)
	end := min(last, week*7)
	if week == 5 {
		end = last
	}
	return time.Date(year, time.Month(month), (week-1)*7+1, 0, 0, 0, 0, time.UTC),
		time.Date(year, time.Month(month), end, 0, 0, 0, 0, time.UTC)
}

// quarterOf is core.fy.get_quarter_for_date.
func quarterOf(month time.Month) string {
	switch {
	case month >= time.October:
		return "Q1"
	case month <= time.March:
		return "Q2"
	case month <= time.June:
		return "Q3"
	}
	return "Q4"
}

// planWhere is the reader's own plan (my_plan_activities, staff_my_plan_q)
// narrowed by the page's filters (_narrow): which states it leaves out is
// the caller's.
func planWhere(b *sqlb, owners []string, fy string, f Filters, today string) string {
	return planWhereOf(b, PlanOf{Owners: owners}, fy, f, today)
}

// PlanOf is whose My Plan a read is (my_plan_activities): a delivery
// partner's is the work assigned to its organisation, anyone else's the
// work they own and deliver.
type PlanOf struct {
	Owners, Partners []string
}

func planWhereOf(b *sqlb, plan PlanOf, fy string, f Filters, today string) string {
	r := rules.Plan
	parts := []string{"a.deleted_at IS NULL", "a.fy = " + b.arg(fy)}
	if len(plan.Partners) > 0 {
		parts = append(parts, "a.assigned_partner_id = ANY("+b.arg(plan.Partners)+")")
	} else {
		parts = append(parts, "a.responsible_staff_id = ANY("+b.arg(plan.Owners)+")",
			"a.delivery_type IS DISTINCT FROM 'partner'", notStatusIn(b, r.PartnerOnlyStatuses))
	}
	if f.Search != "" {
		like := b.arg("%" + likeEscape(f.Search) + "%")
		parts = append(parts, fmt.Sprintf(`(UPPER(s.name::text) LIKE UPPER(%[1]s) OR UPPER(s.school_id::text) LIKE UPPER(%[1]s)
  OR UPPER(c.name::text) LIKE UPPER(%[1]s) OR UPPER(sd.name::text) LIKE UPPER(%[1]s)
  OR UPPER(a.activity_purpose_text::text) LIKE UPPER(%[1]s))`, like))
	}
	if chosen(f.District) {
		d := b.arg(f.District)
		parts = append(parts, "(s.district_id = "+d+" OR c.district_id = "+d+")")
	}
	if chosen(f.Staff) {
		parts = append(parts, "a.responsible_staff_id = "+b.arg(f.Staff))
	}
	if chosen(f.ActivityType) {
		parts = append(parts, "a.activity_type = "+b.arg(f.ActivityType))
	}
	if chosen(f.Status) {
		switch {
		case f.Status == "submitted":
			parts = append(parts, statusIn(b, r.SubmittedFilterStatuses))
		case f.Status == "returned_for_correction":
			parts = append(parts, statusIn(b, r.ReturnedFilterStatuses))
		case f.Status == "upcoming":
			parts = append(parts, statusIn(b, r.NotStartedStatuses), "NOT "+datePassed(b, today))
		case f.Status == "under_way":
			parts = append(parts, statusIn(b, r.UnderWayStatuses))
		case f.Status == "overdue":
			parts = append(parts, statusIn(b, r.NotStartedStatuses), datePassed(b, today))
		default:
			parts = append(parts, "a.status = "+b.arg(f.Status))
		}
	}
	return strings.Join(parts, " AND ")
}

// likeEscape is Django's escaping of a LIKE pattern's own wildcards.
func likeEscape(text string) string {
	return strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(text)
}

const planFrom = `FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
LEFT JOIN district sd ON sd.id = s.district_id`

// Plan is what My Plan counts of the reader's plan, and how much of it the
// tables list.
type Plan struct {
	Counts  PlanCounts
	PastDue int
	// Listed is how many activities the tables would list.
	Listed int
	// Outreach is the period's donor, story, social and invitation visits.
	Outreach int
}

// ReadPlan counts the plan of the people owners for the period p and the
// filters f on the day today, as get_frontend_context counts it for a
// member of staff.
func ReadPlan(ctx context.Context, db schooldirectory.Querier, owners []string, p Period, f Filters, today time.Time) (Plan, error) {
	r := rules.Plan
	today = today.In(kampala)
	day := today.Format(time.DateOnly)
	excludedAsked := in(r.ExcludedStatuses, f.Status)
	open := []string{}
	for _, s := range r.ExcludedStatuses {
		if s != "closed" {
			open = append(open, s)
		}
	}
	periodQ := func(b *sqlb) string { return periodWhere(b, p, today) }
	// The plan the tiles count: closed work included, unless a left-out state
	// was asked for, when nothing is left out.
	plan := func(b *sqlb) string {
		where := planWhere(b, owners, p.FY, f, day)
		if !excludedAsked {
			where += " AND " + notStatusIn(b, open)
		}
		return where
	}
	var out Plan
	// The year's tiles (over the whole plan, whatever the period shown).
	b := &sqlb{}
	where := plan(b)
	wStart, wEnd := weekRange(today.Year(), int(today.Month()), min(5, (today.Day()-1)/7+1))
	mStart := time.Date(today.Year(), today.Month(), 1, 0, 0, 0, 0, time.UTC)
	mEnd := time.Date(today.Year(), today.Month(), daysIn(today.Year(), int(today.Month())), 0, 0, 0, 0, time.UTC)
	week, month := inRange(b, wStart, wEnd), inRange(b, mStart, mEnd)
	quarter := "a.quarter = " + b.arg(quarterOf(today.Month()))
	if err := db.QueryRow(ctx, `SELECT count(*) FILTER (WHERE `+week+`), count(*) FILTER (WHERE `+month+`),
  count(*) FILTER (WHERE `+quarter+`), count(*) `+planFrom+` WHERE `+where, b.args...).
		Scan(&out.Counts.Week, &out.Counts.Month, &out.Counts.Quarter, &out.Counts.FY); err != nil {
		return out, fmt.Errorf("myplan: counting the year's plan: %w", err)
	}
	// The period's tiles.
	b = &sqlb{}
	where = plan(b) + " AND " + periodQ(b)
	trainings, meetings := b.arg(r.TrainingTypes), b.arg(r.MeetingTypes)
	completed := b.arg(r.CompletedWorkStatuses)
	pastDue := fmt.Sprintf("NOT COALESCE(a.status = ANY(%s), false) AND NOT COALESCE(a.status = ANY(%s), false) AND %s",
		b.arg(r.OfficerCompletedStatuses), b.arg(r.ReturnedStatuses), datePassed(b, day))
	if err := db.QueryRow(ctx, `SELECT count(*) FILTER (WHERE a.activity_type = ANY(`+trainings+`)),
  count(*) FILTER (WHERE a.activity_type = ANY(`+meetings+`)), count(*),
  count(*) FILTER (WHERE a.status = ANY(`+completed+`)), count(*) FILTER (WHERE `+pastDue+`) `+planFrom+` WHERE `+where, b.args...).
		Scan(&out.Counts.Trainings, &out.Counts.Meetings, &out.Counts.Total, &out.Counts.Completed, &out.PastDue); err != nil {
		return out, fmt.Errorf("myplan: counting the period's plan: %w", err)
	}
	// Its counted visits, at Core schools and at the others.
	outside, err := visitgate.ProjectsOutsideSSA(ctx, db, schoolprofile.GateRules())
	if err != nil {
		return out, err
	}
	if outside == nil {
		outside = []string{}
	}
	b = &sqlb{}
	where = plan(b) + " AND " + periodQ(b) + " AND " + countedVisit(b, outside)
	core := b.arg(r.CountedVisits.CoreTypes)
	if err := db.QueryRow(ctx, `SELECT count(*) FILTER (WHERE s.school_type = ANY(`+core+`)),
  count(*) FILTER (WHERE NOT COALESCE(s.school_type = ANY(`+core+`), false)) `+planFrom+` WHERE `+where, b.args...).
		Scan(&out.Counts.CoreVisits, &out.Counts.ClientVisits); err != nil {
		return out, fmt.Errorf("myplan: counting the period's visits: %w", err)
	}
	out.Counts.Visits = out.Counts.CoreVisits + out.Counts.ClientVisits
	// Its outreach visits, named beside a visit target (outreach_visit_q:
	// the staff plan holds no partner's SSA Support).
	b = &sqlb{}
	t := rules.Tables
	where = plan(b) + " AND " + periodQ(b) + fmt.Sprintf(` AND a.school_id IS NOT NULL AND a.cluster_id IS NULL
  AND (a.activity_type = ANY(%s) OR (a.activity_type = ANY(%s) AND a.purpose_type = ANY(%s)))`,
		b.arg(t.OutreachTypes), b.arg(t.VisitShapeTypes), b.arg(t.OutreachPurposes))
	if err := db.QueryRow(ctx, `SELECT count(*) `+planFrom+` WHERE `+where, b.args...).Scan(&out.Outreach); err != nil {
		return out, fmt.Errorf("myplan: counting the period's outreach visits: %w", err)
	}
	// What the tables list: still ahead, delivered or sent back, unless a
	// left-out state, work under way or overdue work was asked for.
	b = &sqlb{}
	where = listedWhere(b, owners, p, f, today)
	if err := db.QueryRow(ctx, `SELECT count(*) `+planFrom+` WHERE `+where, b.args...).Scan(&out.Listed); err != nil {
		return out, fmt.Errorf("myplan: counting the listed plan: %w", err)
	}
	return out, nil
}

// periodWhere is the slice the tables show (period): the week of the
// month, the month, the quarter chosen or today's, or the whole year.
func periodWhere(b *sqlb, p Period, today time.Time) string {
	fy, _ := closedschools.PyInt(p.FY)
	month := int(today.Month())
	if p.HasMonth {
		month = p.Month
	}
	year := fy
	if month >= 10 {
		year = fy - 1
	}
	switch p.Kind {
	case "week":
		start, end := weekRange(year, month, p.Week)
		return inRange(b, start, end)
	case "month":
		return inRange(b, time.Date(year, time.Month(month), 1, 0, 0, 0, 0, time.UTC),
			time.Date(year, time.Month(month), daysIn(year, month), 0, 0, 0, 0, time.UTC))
	case "quarter":
		quarter := p.Quarter
		if quarter == "" {
			quarter = quarterOf(today.Month())
		}
		return "a.quarter = " + b.arg(quarter)
	}
	return "true"
}

// listedWhere is what the tables list of the plan of owners for the period
// p and the filters f: still ahead, undated, delivered or sent back, unless
// a left-out state, work under way or overdue work was asked for.
func listedWhere(b *sqlb, owners []string, p Period, f Filters, today time.Time) string {
	r := rules.Plan
	day := today.In(kampala).Format(time.DateOnly)
	where := planWhere(b, owners, p.FY, f, day) + " AND " + periodWhere(b, p, today.In(kampala))
	if in(r.ExcludedStatuses, f.Status) {
		return where
	}
	where += " AND " + notStatusIn(b, r.ExcludedStatuses)
	if f.Status != "under_way" && f.Status != "overdue" {
		t := b.arg(day)
		where += fmt.Sprintf(` AND (a.planned_date >= %[1]s::date OR (a.planned_date IS NULL AND %[2]s >= %[1]s::date)
  OR (a.planned_date IS NULL AND a.scheduled_date IS NULL) OR a.status = ANY(%[3]s) OR a.status = ANY(%[4]s))`,
			t, localDay, b.arg(r.OfficerCompletedStatuses), b.arg(r.ReturnedStatuses))
	}
	return where
}

// countedVisit is staff_plan.counted_visits: planned and dated, a visit at a
// school that is not a companion, an outreach visit or a project's work no
// SSA intervention measures; SSA Support only when staff deliver it; and
// never a partner's (the same statement internal/planningpage counts by).
func countedVisit(b *sqlb, outside []string) string {
	cv := rules.Plan.CountedVisits
	return fmt.Sprintf(`a.status = ANY(%s) AND (a.planned_date IS NOT NULL OR a.scheduled_date IS NOT NULL)
  AND a.activity_type = ANY(%s) AND a.school_id IS NOT NULL AND a.cluster_id IS NULL
  AND a.purpose_type IS DISTINCT FROM %s AND NOT COALESCE(a.purpose_type = ANY(%s), false)
  AND NOT COALESCE(a.project_id = ANY(%s), false)
  AND (NOT (COALESCE(a.purpose_type = ANY(%s), false)
        OR (a.activity_type = ANY(%s) AND NOT COALESCE(a.purpose_type = ANY(%s), false)))
       OR a.delivery_type IS DISTINCT FROM 'partner')
  AND a.delivery_type IS DISTINCT FROM 'partner'`,
		b.arg(cv.PlannedStates), b.arg(cv.VisitShapeTypes), b.arg(cv.CompanionPurpose), b.arg(cv.OutreachPurposes),
		b.arg(outside), b.arg(cv.DataCollectionPurposes), b.arg(cv.DataCollectionTypes), b.arg(cv.KindPurposes))
}

// share is the completed share of the period's plan as the registry writes
// a percentage: round(n / d * 100, 1) with no trailing ".0", "No data" for
// nothing planned.
func share(completed, total int) string {
	if total == 0 {
		return rules.Strip.NoData
	}
	v := schooldirectory.PyRound1(float64(completed) / float64(total) * 100)
	return strconv.FormatFloat(v, 'f', -1, 64) + "%"
}
