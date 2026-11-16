package weeklyrequest

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// readMission is _mission_status_for_cceo: for a CCEO, the week's
// vendor-paid lines (fundable.vendor_direct_filter: a one-day school
// activity's transport, and accommodation Finance booked) as days and
// nights, and whether every mission day's transport provider is paid.
func (s *Service) readMission(ctx context.Context, v *view, p auth.Principal, _ schooldirectory.Scope) error {
	if p.ActiveRole != "CCEO" {
		return nil
	}
	var days, nights, lines int
	err := s.db.QueryRow(ctx, `
SELECT count(DISTINCT l.planned_date) FILTER (WHERE l.line_item_type = 'transport'),
  COALESCE(SUM(l.quantity) FILTER (WHERE l.line_item_type = 'accommodation'), 0)::int, count(*)
FROM activity_schedule_cost_line l JOIN activity a ON a.id = l.activity_id
WHERE l.responsible_user = $1 AND l.week_start_date = $2 AND a.deleted_at IS NULL
  AND ((l.line_item_type = 'transport' AND a.school_id IS NOT NULL
        AND (a.end_date IS NULL OR a.planned_date IS NULL OR a.end_date <= a.planned_date))
    OR (l.line_item_type = 'accommodation' AND l.vendor_paid))`, p.UserID, v.weekStart).Scan(&days, &nights, &lines)
	if err != nil {
		return fmt.Errorf("weeklyrequest: reading the mission's vendor lines: %w", err)
	}
	if lines == 0 {
		return nil
	}
	var payments, paid int
	if err := s.db.QueryRow(ctx, `
SELECT count(*), count(*) FILTER (WHERE t.status = 'paid') FROM transport_payment t
JOIN daily_visit_batch b ON b.id = t.batch_id
WHERE b.responsible_user = $1 AND b.visit_date >= $2 AND b.visit_date <= $3`, p.UserID, v.weekStart, v.weekEnd).Scan(&payments, &paid); err != nil {
		return fmt.Errorf("weeklyrequest: reading the mission's transport payments: %w", err)
	}
	v.mission = &mission{transportDays: days, nights: nights, confirmed: payments > 0 && payments == paid}
	return nil
}

// The activity types a source activity is titled as a school visit.
var visitTypes = []string{"school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "core_visit"}

// readSources is the week's source activities: titled by kind, placed by
// district, dated on the local day, with their purpose.
func (s *Service) readSources(ctx context.Context, v *view, _ auth.Principal, _ schooldirectory.Scope) error {
	q := args{}
	where := v.base.activities(v.a, &q)
	rows, err := s.db.Query(ctx, `
SELECT a.activity_type, a.status, COALESCE(a.planning_source, ''), COALESCE(a.activity_name_snapshot, ''),
  COALESCE(ed.name, ''), COALESCE(a.venue, ''), COALESCE(s.name, ''), COALESCE(sd.name, ''),
  COALESCE(c.name, ''), COALESCE(cd.name, ''), a.scheduled_date, COALESCE(a.activity_purpose_text, ''),
  COALESCE(a.purpose_intervention, '')
FROM activity a
LEFT JOIN school s ON s.id = a.school_id LEFT JOIN district sd ON sd.id = s.district_id
LEFT JOIN cluster c ON c.id = a.cluster_id LEFT JOIN district cd ON cd.id = c.district_id
LEFT JOIN district ed ON ed.id = a.event_district_id
WHERE `+where+` AND (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date BETWEEN `+q.add(v.weekStart)+` AND `+q.add(v.weekEnd)+`
ORDER BY a.created_at DESC`, q...)
	if err != nil {
		return fmt.Errorf("weeklyrequest: reading the week's activities: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (source, error) {
		var kind, status, planning, snapshot, eventDistrict, venue, school, schoolDistrict, cluster, clusterDistrict, text, purpose string
		var at *time.Time
		err := row.Scan(&kind, &status, &planning, &snapshot, &eventDistrict, &venue, &school, &schoolDistrict,
			&cluster, &clusterDistrict, &at, &text, &purpose)
		src := source{kind: kind, status: status, date: "Unscheduled"}
		if at != nil {
			src.date = at.In(kampala).Format("Jan 02, 2006")
		}
		district := func(name string) string {
			if name == "" {
				return "Unknown District"
			}
			return name + " District"
		}
		switch {
		case planning == "manual_work_plan" && snapshot != "":
			src.title = snapshot
			switch {
			case eventDistrict != "":
				src.location = eventDistrict + " District"
			case venue != "":
				src.location = venue
			default:
				src.location = "Programme activity"
			}
		case in(visitTypes, kind):
			src.title = "School Visit"
			if school != "" {
				src.title = school + " Visit"
			}
			src.location = district(schoolDistrict)
			if school == "" {
				src.location = "Unknown District"
			}
		case kind == "cluster_meeting":
			src.title = "Cluster Meeting"
			if cluster != "" {
				src.title = cluster + " Meeting"
			}
			src.location = district(clusterDistrict)
			if cluster == "" {
				src.location = "Unknown District"
			}
		default:
			src.title = "Cluster Training"
			if cluster != "" {
				src.title = cluster + " Training"
			}
			src.location = district(clusterDistrict)
			if cluster == "" {
				src.location = "Unknown District"
			}
		}
		src.purpose = text
		if src.purpose == "" {
			src.purpose = rules.PurposeInterventions[purpose]
			if src.purpose == "" {
				src.purpose = purpose
			}
		}
		if src.purpose == "" {
			src.purpose = "Operational Support"
		}
		return src, err
	})
	if err != nil {
		return fmt.Errorf("weeklyrequest: reading the week's activities: %w", err)
	}
	v.sources = list
	return nil
}

// readInsights is the insights panel's counts, the monthly submission's due
// date and the recommended next action.
func (s *Service) readInsights(ctx context.Context, v *view, p auth.Principal, sc schooldirectory.Scope) error {
	ins := &v.insights
	q := args{}
	week, err := s.tally(ctx, v.base.requests(v.a, &q)+" AND w.week_start_date = "+q.add(v.weekStart), q)
	if err != nil {
		return err
	}
	ins.week = week
	q = args{}
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM weekly_fund_request w WHERE `+v.base.requests(v.a, &q)+
		` AND w.week_start_date = `+q.add(v.weekStart)+` AND w.status IN ('pending_responsible_confirmation', 'not_requested')`, q...).Scan(&ins.attention); err != nil {
		return fmt.Errorf("weeklyrequest: counting the requests awaiting confirmation: %w", err)
	}
	selfFunded := `SELECT count(*) FROM advance_request r WHERE r.status = 'self_funded_pending_reimbursement'
AND (r.planned_date AT TIME ZONE 'Africa/Kampala')::date BETWEEN $1 AND $2`
	sfArgs := []any{v.weekStart, v.weekEnd}
	if !sc.CountryScope {
		selfFunded += ` AND r.responsible_user_id = ANY($3)`
		sfArgs = append(sfArgs, append([]string{p.UserID}, v.base.supervised...))
	}
	if err := s.db.QueryRow(ctx, selfFunded, sfArgs...).Scan(&ins.selfFunded); err != nil {
		return fmt.Errorf("weeklyrequest: counting self-funded work: %w", err)
	}
	q = args{}
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM activity a WHERE `+v.base.activities(v.a, &q)+
		fmt.Sprintf(` AND EXTRACT(MONTH FROM a.scheduled_date AT TIME ZONE 'Africa/Kampala') = %d AND a.cost_missing`, v.month), q...).Scan(&ins.missingCosted); err != nil {
		return fmt.Errorf("weeklyrequest: counting uncosted work: %w", err)
	}
	due := time.Date(v.year, time.Month(v.month), 25, 0, 0, 0, 0, time.UTC)
	days := int(due.Sub(v.today).Hours() / 24)
	ins.dueDate = due.Format("Jan 02, 2006")
	switch {
	case days > 0:
		ins.dueHeading, ins.dueTiming = "Upcoming Monthly Submission", fmt.Sprintf("%d days remaining", days)
	case days == 0:
		ins.dueHeading, ins.dueTiming = "Monthly Submission Due Today", "Due today"
	default:
		over := -days
		plural := "s"
		if over == 1 {
			plural = ""
		}
		ins.dueHeading, ins.dueTiming = "Monthly Submission Overdue", fmt.Sprintf("%d day%s overdue", over, plural)
	}
	switch {
	case v.active != nil && v.owner && in(set4, v.active.status):
		ins.action = "Submit this week's advance request"
		ins.actionDesc = "Check the weekly plan and any correction notes, then submit for supervisor approval."
		ins.takeAction = true
	case v.active != nil:
		ins.action = "No immediate action pending"
		ins.actionDesc = "The current workflow status and available actions are shown on the weekly request."
	default:
		q := args{}
		var scheduled bool
		if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity_schedule_cost_line l
LEFT JOIN activity a ON a.id = l.activity_id WHERE `+v.base.lines(v.a, &q)+`
  AND l.planned_date >= `+q.add(v.weekStart)+` AND l.planned_date <= `+q.add(v.weekEnd)+`
  AND (a.id IS NULL OR NOT (a.status = ANY(`+q.add(rules.NonFundableStatuses)+`))))`, q...).Scan(&scheduled); err != nil {
			return fmt.Errorf("weeklyrequest: reading the week's scheduled costs: %w", err)
		}
		if scheduled {
			ins.action = "This week's request could not be prepared"
			ins.actionDesc = "Activities are scheduled but no advance request exists for them. The platform normally creates it automatically; if this persists, report it from Help."
		} else {
			ins.action = "No immediate action pending"
			ins.actionDesc = "No activities scheduled for this week yet."
		}
	}
	return nil
}

// set4 is the statuses an owner submits from.
var set4 = []string{"pending_responsible_confirmation", "returned_by_pl", "returned_by_cd", "returned_by_accountant"}

// readOptions is the district and staff selects and the manager's team tabs.
func (s *Service) readOptions(ctx context.Context, v *view, p auth.Principal, sc schooldirectory.Scope) error {
	pairs := func(sql string, a ...any) ([][2]string, error) {
		rows, err := s.db.Query(ctx, sql, a...)
		if err != nil {
			return nil, fmt.Errorf("weeklyrequest: reading the options: %w", err)
		}
		return pgx.CollectRows(rows, func(row pgx.CollectableRow) ([2]string, error) {
			var o [2]string
			err := row.Scan(&o[0], &o[1])
			return o, err
		})
	}
	var err error
	if v.showTeamFilters {
		if v.districts, err = pairs(`SELECT id, name FROM district ORDER BY name`); err != nil {
			return err
		}
		staff := `SELECT sp.user_id, COALESCE(u.name, '') FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL`
		sargs := []any{}
		if !sc.CountryScope {
			staff += ` AND sp.user_id = ANY($1)`
			sargs = append(sargs, append([]string{p.UserID}, v.base.supervised...))
		}
		if v.staffOptions, err = pairs(staff+` ORDER BY u.name`, sargs...); err != nil {
			return err
		}
	}
	if len(v.base.supervised) > 0 {
		members, err := pairs(`SELECT id, COALESCE(name, '') FROM "user" WHERE id = ANY($1) ORDER BY name`,
			append([]string{p.UserID}, v.base.supervised...))
		if err != nil {
			return err
		}
		for _, m := range members {
			active := ""
			if m[0] == v.base.staff {
				active = "1"
			}
			v.teamTabs = append(v.teamTabs, [3]string{m[0], m[1], active})
		}
	}
	return nil
}
