package schoolprofile

import (
	"context"
	"fmt"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// The records behind a figure of a profile of many schools
// (profile_records.records, drawn by partials/profiles/_records.html): each
// table paged fifty at a time, so the list reconciles with the number that
// opened it.

// workRecordFilter is profile_records._work_kinds' filter for what, as a
// condition on "a" with its arguments appended to args.
func workRecordFilter(what string, today time.Time, args *[]any) (string, bool) {
	arg := func(v any) string {
		*args = append(*args, v)
		return fmt.Sprintf("$%d", len(*args))
	}
	of := func(types []string) string { return "a.activity_type = ANY(" + arg(types) + ")" }
	done := func() string { return "a.status = ANY(" + arg(rules.Engine.CompletedWorkStatuses) + ")" }
	waiting := func() string { return "a.status = ANY(" + arg(rules.Engine.NotStartedStatuses) + ")" }
	past := func() string {
		d := arg(today)
		return `(a.planned_date < ` + d + `::date OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date < ` + d + `::date))`
	}
	// Django's negation of the past keeps work with no day at all.
	notPast := func() string {
		d := arg(today)
		return `NOT ((a.planned_date < ` + d + `::date AND a.planned_date IS NOT NULL)
    OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date < ` + d + `::date AND a.scheduled_date IS NOT NULL))`
	}
	const (
		inSchool  = "a.school_id IS NOT NULL"
		group     = "a.school_id IS NULL"
		online    = "a.programme_delivery_mode = 'online'"
		notOnline = "a.programme_delivery_mode IS DISTINCT FROM 'online'"
		partner   = "a.delivery_type = 'partner'"
	)
	e := rules.Engine
	and := func(parts ...string) string { return strings.Join(parts, " AND ") }
	switch what {
	case "visits":
		return of(e.VisitTypes), true
	case "visits_done":
		return and(of(e.VisitTypes), done()), true
	case "visits_overdue":
		return and(of(e.VisitTypes), waiting(), past()), true
	case "trainings":
		return of(e.TrainingTypes), true
	case "trainings_done":
		return and(of(e.TrainingTypes), done()), true
	case "trainings_overdue":
		return and(of(e.TrainingTypes), waiting(), past()), true
	case "project_overdue":
		return and("a.project_id IS NOT NULL", waiting(), past()), true
	case "trainings_in_school":
		return and(of(e.TrainingTypes), inSchool, notOnline), true
	case "trainings_in_school_done":
		return and(of(e.TrainingTypes), inSchool, notOnline, done()), true
	case "trainings_partner":
		return and(of(e.TrainingTypes), inSchool, notOnline, partner), true
	case "trainings_group":
		return and(of(e.TrainingTypes), group, notOnline), true
	case "trainings_group_done":
		return and(of(e.TrainingTypes), group, notOnline, done()), true
	case "trainings_online":
		return and(of(e.TrainingTypes), online), true
	case "trainings_online_done":
		return and(of(e.TrainingTypes), online, done()), true
	case "meetings":
		return of(e.MeetingTypes), true
	case "meetings_done":
		return and(of(e.MeetingTypes), done()), true
	case "meetings_upcoming":
		return and(of(e.MeetingTypes), waiting(), notPast()), true
	case "meetings_overdue":
		return and(of(e.MeetingTypes), waiting(), past()), true
	}
	return "", false
}

// workRecord is one activity as a work record reads it.
type workRecord struct {
	id, kind, mode, status, schoolID, schoolName, schoolCode, clusterID, clusterName string
	staff, partner, course                                                           string
	planned, actual                                                                  *time.Time
	scheduled                                                                        *time.Time
}

// workRecords is profile_records._work_table: the scope's work (with its
// live clusters' sessions) that what counts, newest first.
func (s *Service) workRecords(ctx context.Context, pr *scopeProfile, l lens, what string, today time.Time) ([]workRecord, bool, error) {
	args := []any{}
	live := make([]string, 0, len(pr.clusters))
	for id := range pr.clusters {
		live = append(live, id)
	}
	where := scopeWork(idsOf(pr.schools), live, l.fy, l.window, &args)
	filter, ok := workRecordFilter(what, today, &args)
	if !ok {
		return nil, false, nil
	}
	out, err := s.workRecordsWhere(ctx, where+" AND "+filter, args)
	return out, true, err
}

// workRecordsWhere reads the work where picks, newest first.
func (s *Service) workRecordsWhere(ctx context.Context, where string, args []any) ([]workRecord, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(a.programme_delivery_mode, ''), COALESCE(a.status, ''),
  COALESCE(a.school_id, ''), COALESCE(sc.name, ''), COALESCE(sc.school_id, ''), COALESCE(a.cluster_id, ''), COALESCE(cl.name, ''),
  COALESCE(a.responsible_staff_id, ''), COALESCE(a.assigned_partner_id, ''), COALESCE(tc.display_name, ''),
  a.planned_date, a.actual_delivery_date, a.scheduled_date
FROM activity a
LEFT JOIN school sc ON sc.id = a.school_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id
LEFT JOIN activity_catalogue_item tc ON tc.id = a.training_course_id
WHERE `+where+`
ORDER BY a.planned_date DESC, a.scheduled_date DESC, a.id`, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the profile's work records: %w", err)
	}
	out := []workRecord{}
	for rows.Next() {
		var r workRecord
		if err := rows.Scan(&r.id, &r.kind, &r.mode, &r.status, &r.schoolID, &r.schoolName, &r.schoolCode, &r.clusterID,
			&r.clusterName, &r.staff, &r.partner, &r.course, &r.planned, &r.actual, &r.scheduled); err != nil {
			rows.Close()
			return nil, err
		}
		out = append(out, r)
	}
	rows.Close()
	return out, rows.Err()
}

// peopleNames is profile_records._people_names for a page of work: each
// staff member by staff or user id, and each partner.
func (s *Service) peopleNames(ctx context.Context, page []workRecord) (map[string]string, error) {
	staff, partners := []string{}, []string{}
	for _, r := range page {
		if r.staff != "" {
			staff = append(staff, r.staff)
		}
		if r.partner != "" {
			partners = append(partners, r.partner)
		}
	}
	names := map[string]string{}
	if len(staff) > 0 {
		rows, err := s.db.Query(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), u.email, '')
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.id = ANY($1) OR sp.user_id = ANY($1)`, staff)
		if err != nil {
			return nil, fmt.Errorf("schoolprofile: reading staff names: %w", err)
		}
		for rows.Next() {
			var id, user, name string
			if err := rows.Scan(&id, &user, &name); err != nil {
				rows.Close()
				return nil, err
			}
			names[id] = name
			if user != "" {
				names[user] = name
			}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	if len(partners) > 0 {
		rows, err := s.db.Query(ctx, `SELECT id, name FROM partner WHERE id = ANY($1)`, partners)
		if err != nil {
			return nil, fmt.Errorf("schoolprofile: reading partner names: %w", err)
		}
		for rows.Next() {
			var id, name string
			if err := rows.Scan(&id, &name); err != nil {
				rows.Close()
				return nil, err
			}
			names[id] = name
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, err
		}
	}
	return names, nil
}

// recordStatus is profile_records._status: words, the first capital.
func recordStatus(value string) string {
	v := strings.ReplaceAll(value, "_", " ")
	if v == "" {
		return ""
	}
	return strings.ToUpper(v[:1]) + strings.ToLower(v[1:])
}

// workRecordTable is the table of one work record, fifty a page.
func (s *Service) workRecordTable(ctx context.Context, l lens, what string, records []workRecord) (*screensv1.PageBlock, error) {
	return s.workTable(ctx, l, what, rules.Engine.Scope.Records[what][1], records)
}

// workTable is profile_records._work_table: the work, fifty a page under
// the page parameter "rec_" and key.
func (s *Service) workTable(ctx context.Context, l lens, key, title string, records []workRecord) (*screensv1.PageBlock, error) {
	subtitle := intcomma(len(records)) + " record" + plural(len(records)) + " · " + fyLabel(l.fy)
	if l.window.label != "" {
		subtitle += " · " + l.window.label
	}
	t := &screensv1.PageTable{Title: title, Subtitle: subtitle}
	if len(records) == 0 {
		t.EmptyMessage = "No record yet: the figure is 0."
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}, nil
	}
	t.Columns = []*screensv1.PageColumn{{Label: "Date"}, {Label: "Activity"}, {Label: "School ID"}, {Label: "School / Cluster"},
		{Label: "Delivered By"}, {Label: "Status"}}
	page := tablepager.Paginate(len(records), tablePageSize, l.query, "rec_"+key)
	shown := records[page.Start:page.End]
	names, err := s.peopleNames(ctx, shown)
	if err != nil {
		return nil, err
	}
	for _, r := range shown {
		var day *time.Time
		switch {
		case r.actual != nil:
			day = r.actual
		case r.planned != nil:
			day = r.planned
		case r.scheduled != nil:
			d := r.scheduled.UTC()
			d = time.Date(d.Year(), d.Month(), d.Day(), 0, 0, 0, 0, time.UTC)
			day = &d
		}
		date := "—"
		if day != nil {
			date = jMY(*day)
		}
		label := r.course
		if label == "" {
			label = rules.Engine.Scope.ActivityTypeLabels[r.kind]
			if label == "" {
				label = recordStatus(r.kind)
			}
		}
		if r.mode == rules.Engine.Scope.OnlineMode {
			label += " (online)"
		}
		by := names[r.partner]
		if by == "" {
			by = names[r.staff]
		}
		place := &screensv1.PageCell{Text: "—"}
		switch {
		case r.schoolID != "":
			place = &screensv1.PageCell{Text: orDash(r.schoolName), Href: "/schools/" + r.schoolID}
		case r.clusterID != "":
			place = &screensv1.PageCell{Text: orDash(r.clusterName), Href: "/clusters/" + r.clusterID}
		}
		status := &screensv1.PageCell{Text: orDash(recordStatus(r.status))}
		if contains(rules.Engine.CompletedWorkStatuses, r.status) {
			status.Tone = "success"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: date}, {Text: orDash(label), Href: "/activities/" + r.id}, {Text: orDash(r.schoolCode)}, place,
			{Text: orDash(by)}, status,
		}})
	}
	if page.Pager != nil {
		t.Pager, t.Footnote = page.Pager, page.Pager.Summary
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}, nil
}

// recordsInGo are the records beside the work's that Go draws.
var recordsInGo = map[string]bool{"enrolment": true, "enrolment_growth": true, "learning": true, "ssa": true, "intervention": true,
	"stories": true, "stories_approved": true, "handovers": true, "handovers_awaiting": true, "handovers_dated": true,
	"handovers_completed": true, "partners": true, "teachers_trained": true, "leaders_trained": true, "at_meetings": true,
	"cases": true, "loans": true}

// recordBlocks is profile_records.records for what: its tables, or the
// note that none is open to the reader.
func (s *Service) recordBlocks(ctx context.Context, r btReader, pr *scopeProfile, l lens, what, key string, today time.Time) ([]*screensv1.PageBlock, error) {
	d := r.doors
	none := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Empty{Empty: "These records are not open to your role."}}}
	var t scopeRecordTable
	var err error
	switch what {
	case "enrolment", "enrolment_growth":
		t, err = s.enrolmentTable(ctx, pr, l, what == "enrolment_growth")
	case "learning":
		t, err = s.learningTable(ctx, pr, l)
	case "ssa":
		t, err = s.ssaTable(ctx, pr, l)
	case "intervention":
		tables, work, _, err := s.interventionTables(ctx, pr, l, key, today)
		if err != nil || tables == nil {
			return none, err
		}
		return []*screensv1.PageBlock{tables[0].block(l), work}, nil
	case "stories", "stories_approved":
		t, err = s.storyTable(ctx, pr, l, what == "stories_approved")
	case "handovers", "handovers_awaiting", "handovers_dated", "handovers_completed":
		stage := strings.TrimPrefix(strings.TrimPrefix(what, "handovers"), "_")
		t, err = s.handoverTable(ctx, pr, stage)
	case "partners":
		t, err = s.partnerTable(ctx, pr)
	case "teachers_trained", "leaders_trained", "at_meetings":
		types, title := rules.Engine.TrainingTypes, rules.Engine.Scope.Records[what][1]
		if what == "at_meetings" {
			types, title = rules.Engine.MeetingTypes, "At cluster meetings"
		}
		tables, err := s.trainedTables(ctx, pr, l, what, title, types)
		if err != nil {
			return nil, err
		}
		blocks := []*screensv1.PageBlock{}
		for _, t := range tables {
			blocks = append(blocks, t.block(l))
		}
		return blocks, nil
	case "cases":
		// Read by those who may open the loan register.
		if !d.Loans {
			return none, nil
		}
		t, err = s.caseTable(ctx, pr)
	case "loans":
		if !d.Loans {
			return none, nil
		}
		t, err = s.loanTable(ctx, r, pr)
	default:
		records, _, err := s.workRecords(ctx, pr, l, what, today)
		if err != nil {
			return nil, err
		}
		table, err := s.workRecordTable(ctx, l, what, records)
		return []*screensv1.PageBlock{table}, err
	}
	if err != nil {
		return nil, err
	}
	return []*screensv1.PageBlock{t.block(l)}, nil
}
