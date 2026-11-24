package activities

// What My Plan's Complete drawer (my_plan_views.complete_drawer_view,
// partials/my_plan/complete_drawer.html) shows for the work Go completes with
// the existing application absent: an officer's own staff School Visit
// (183.1's case) and their own staff cluster meeting. The existing drawer
// starts work not yet started as it opens; Go's draws it and writes nothing,
// and the completion starts it in its own transaction, as the view does.
// Every other drawer is handed on (ErrHandOn).

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// plainSchoolVisit is the one visit type whose drawer asks no purpose: the
// donor, story-gathering, invitation and social visits are offered the
// completion purposes (completion_purpose_options).
const plainSchoolVisit = "school_visit"

// CompleteFacts are what the drawer is drawn from.
type CompleteFacts struct {
	ActivityID, ActivityType, SchoolName string
	Delivered, Today                     string // ISO days
	SalesforceKind                       string // "visit" or "training"
	Attendance                           bool   // the head counts are asked
	Teachers, Leaders                    string
	Cluster                              bool // the register is asked
	Register                             []RegisterSchool
	Outcome, Observations, FollowUp      string
}

// RegisterSchool is one of the cluster's schools on the register.
type RegisterSchool struct {
	ID, Name, Code string
	Ticked         bool
}

// CompleteDrawer reads the drawer's facts, or ErrHandOn.
func (s *Service) CompleteDrawer(ctx context.Context, p auth.Principal, id string) (CompleteFacts, error) {
	id = strings.TrimSpace(id)
	m, err := s.meetingInCase(ctx, p, id)
	if err != nil {
		return CompleteFacts{}, err
	}
	if m != nil {
		return s.meetingFacts(ctx, m)
	}
	if err := s.visitDrawerInCase(ctx, p, id); err != nil {
		return CompleteFacts{}, err
	}
	return s.visitFacts(ctx, id)
}

// visitDrawerInCase is the completion's case for a School Visit, started or
// still to be started, whose drawer asks for no accountability.
func (s *Service) visitDrawerInCase(ctx context.Context, p auth.Principal, id string) error {
	if p.InActingAppointment || p.StaffProfileID == "" || p.ActiveRole != officerRole || slices.Contains(p.Roles, programmeLeadRole) {
		return handOn("not an officer completing their own visit")
	}
	a, err := readCompletedVisit(ctx, s.db, id)
	if err != nil {
		return err
	}
	if a == nil || a.activityType != plainSchoolVisit {
		return handOn("not a staff School Visit with a school and a day")
	}
	if why := a.outOfCase(p, true); why != "" {
		return handOn(why)
	}
	if err := s.ownVisitSchool(ctx, p, a.schoolID, s.now()); err != nil {
		return err
	}
	ownerUID, err := fundingOwner(ctx, s.db, a.responsible, p.UserID)
	if err != nil {
		return err
	}
	if why, err := moveNotices(ctx, s.db, a.id, ownerUID); err != nil || why != "" {
		if err != nil {
			return err
		}
		return handOn(why)
	}
	var accountable bool
	if err := s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM advance_request r
  WHERE (r.activity_id = $1 OR r.budget_line_id IN (SELECT c.id FROM activity_schedule_cost_line c WHERE c.activity_id = $1))
    AND r.status = 'disbursed' AND COALESCE(r.accountability_netsuite_id, '') = '')`, id).Scan(&accountable); err != nil {
		return fmt.Errorf("activities: reading the visit's advances: %w", err)
	}
	if accountable {
		return handOn("a disbursed advance the drawer asks to account for")
	}
	return nil
}

// workFacts reads what every drawer shows of the work.
func (s *Service) workFacts(ctx context.Context, id string) (CompleteFacts, *int, *int, []string, error) {
	f := CompleteFacts{ActivityID: id}
	var delivered *time.Time
	var school, outcome, observations, followUp *string
	var teachers, leaders *int
	var attended []string
	err := s.db.QueryRow(ctx, `
SELECT a.activity_type, s.name, a.actual_delivery_date, a.actual_outcome, a.actual_observations, a.follow_up_note,
       a.teachers_attended, a.leaders_attended, COALESCE(a.attended_school_ids, '{}')
FROM activity a LEFT JOIN school s ON s.id = a.school_id WHERE a.id = $1`, id).Scan(
		&f.ActivityType, &school, &delivered, &outcome, &observations, &followUp, &teachers, &leaders, &attended)
	if errors.Is(err, pgx.ErrNoRows) {
		return f, nil, nil, nil, handOn("no such activity")
	}
	if err != nil {
		return f, nil, nil, nil, fmt.Errorf("activities: reading the work to complete: %w", err)
	}
	now := s.now().In(s.kampala)
	f.Today = time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC).Format(time.DateOnly)
	f.Delivered = f.Today
	if delivered != nil {
		f.Delivered = delivered.Format(time.DateOnly)
	}
	f.SchoolName, f.Outcome, f.Observations, f.FollowUp = text(school), text(outcome), text(observations), text(followUp)
	return f, teachers, leaders, attended, nil
}

func (s *Service) visitFacts(ctx context.Context, id string) (CompleteFacts, error) {
	f, _, _, _, err := s.workFacts(ctx, id)
	f.SalesforceKind = "visit"
	return f, err
}

// meetingFacts adds the head counts and the register: the cluster's
// operating schools by name, ticked as the drawer opens them — the
// attendance recorded at an earlier submission, else who was invited, else
// every member.
func (s *Service) meetingFacts(ctx context.Context, m *completedMeeting) (CompleteFacts, error) {
	f, teachers, leaders, attended, err := s.workFacts(ctx, m.id)
	if err != nil {
		return f, err
	}
	f.SalesforceKind, f.Attendance, f.Cluster = "training", true, true
	f.Teachers, f.Leaders = countValue(teachers), countValue(leaders)
	rows, err := s.db.Query(ctx, `
SELECT s.id, s.name, COALESCE(s.school_id, ''), x.invited, x.attended
FROM school s
LEFT JOIN cluster_activity_attendance x ON x.activity_id = $1 AND x.school_id = s.id
WHERE s.cluster_id = $2 AND s.deleted_at IS NULL AND s.operational_status = ANY($3)
ORDER BY s.name`, m.id, m.clusterID, rules.OperatingStatuses)
	if err != nil {
		return f, fmt.Errorf("activities: reading the register: %w", err)
	}
	defer rows.Close()
	type member struct {
		school            RegisterSchool
		invited, attended *bool
	}
	var members []member
	for rows.Next() {
		var mb member
		if err := rows.Scan(&mb.school.ID, &mb.school.Name, &mb.school.Code, &mb.invited, &mb.attended); err != nil {
			return f, err
		}
		members = append(members, mb)
	}
	if err := rows.Err(); err != nil {
		return f, err
	}
	var anyRow, anyAttended bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cluster_activity_attendance WHERE activity_id = $1),
  EXISTS (SELECT 1 FROM cluster_activity_attendance WHERE activity_id = $1 AND attended)`, m.id).Scan(&anyRow, &anyAttended); err != nil {
		return f, fmt.Errorf("activities: reading the attendance rows: %w", err)
	}
	recorded := teachers != nil || len(attended) > 0 || anyAttended
	for _, mb := range members {
		switch {
		case recorded:
			mb.school.Ticked = (mb.attended != nil && *mb.attended) || in(attended, mb.school.ID)
		case anyRow:
			mb.school.Ticked = mb.invited != nil && *mb.invited
		default:
			mb.school.Ticked = true
		}
		f.Register = append(f.Register, mb.school)
	}
	return f, nil
}

// countValue is `{{ n|default:0 }}`.
func countValue(n *int) string {
	if n == nil || *n == 0 {
		return "0"
	}
	return strconv.Itoa(*n)
}
