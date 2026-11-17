package programmerollout

import (
	"context"
	"fmt"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trainingsummary"
)

// member is one row owner: an officer on the team, or the lead's own
// portfolio.
type member struct {
	staffID, userID, name string
	isLead                bool
	schools               map[string]bool
}

func (m *member) ids() []string {
	out := []string{}
	for _, id := range []string{m.staffID, m.userID} {
		if id != "" {
			out = append(out, id)
		}
	}
	return out
}

// school is a portfolio school.
type school struct{ name, code, district, cluster string }

// scope is resolve_rollout_scope for a Programme Lead in their own seat.
type scope struct {
	leadStaffID, leadUserID, leadName string
	officers                          []*member
	lead                              *member
	schools                           map[string]school
	ownerByID                         map[string]string
	ownersBySchool                    map[string][]string
}

func (s *scope) everyone() []*member {
	out := append([]*member{}, s.officers...)
	if s.lead != nil {
		out = append(out, s.lead)
	}
	return out
}

func (s *scope) staffIDs() []string {
	out := []string{}
	for _, m := range s.everyone() {
		if m.staffID != "" {
			out = append(out, m.staffID)
		}
	}
	return out
}

func (s *scope) member(staffID string) *member {
	for _, m := range s.everyone() {
		if m.staffID == staffID {
			return m
		}
	}
	return nil
}

// rows is the officers, then the lead's own portfolio when it holds schools
// or any of the work counted.
func (s *scope) rows(attributed map[string]bool) []*member {
	out := append([]*member{}, s.officers...)
	if s.lead != nil && (len(s.lead.schools) > 0 || attributed[s.lead.staffID]) {
		out = append(out, s.lead)
	}
	return out
}

// attribute is RolloutScope.attribute: the officer responsible, else the one
// monitoring, else the first holder of the school.
func (s *scope) attribute(responsible, monitor, schoolID string) string {
	for _, id := range []string{responsible, monitor} {
		if owner, ok := s.ownerByID[id]; ok && id != "" {
			return owner
		}
	}
	if owners := s.ownersBySchool[schoolID]; len(owners) > 0 {
		return owners[0]
	}
	return ""
}

// readScope reads the lead's team, their portfolio and the clusters' names.
func readScope(ctx context.Context, db schooldirectory.Querier, staffID, userID string, now time.Time) (*scope, error) {
	team, err := trainingsummary.TeamMembers(ctx, db, staffID, now)
	if err != nil {
		return nil, err
	}
	people := []string{userID}
	for _, t := range team {
		people = append(people, t.UserID)
	}
	named := map[string]string{}
	rows, err := db.Query(ctx, `SELECT id, COALESCE(NULLIF(name, ''), email) FROM "user" WHERE id = ANY($1)`, people)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the team's names: %w", err)
	}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			rows.Close()
			return nil, fmt.Errorf("programmerollout: reading a name: %w", err)
		}
		named[id] = name
	}
	rows.Close()
	s := &scope{leadStaffID: staffID, leadUserID: userID, leadName: named[userID], schools: map[string]school{},
		ownerByID: map[string]string{}, ownersBySchool: map[string][]string{}}
	for _, t := range team {
		s.officers = append(s.officers, &member{staffID: t.StaffID, userID: t.UserID, name: named[t.UserID], schools: map[string]bool{}})
	}
	if staffID != "" {
		s.lead = &member{staffID: staffID, userID: userID, name: s.leadName, isLead: true, schools: map[string]bool{}}
	}
	type assignment struct{ staff, school string }
	var assigned []assignment
	rows, err = db.Query(ctx, `SELECT staff_id, school_id FROM staff_school_assignment WHERE staff_id = ANY($1)`, s.staffIDs())
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the portfolio: %w", err)
	}
	ids := []string{}
	for rows.Next() {
		var a assignment
		if err := rows.Scan(&a.staff, &a.school); err != nil {
			rows.Close()
			return nil, fmt.Errorf("programmerollout: reading an assignment: %w", err)
		}
		assigned = append(assigned, a)
		ids = append(ids, a.school)
	}
	rows.Close()
	rows, err = db.Query(ctx, `SELECT s.id, s.name, COALESCE(s.school_id, ''), COALESCE(d.name, ''), COALESCE(s.cluster_id, '')
FROM school s LEFT JOIN district d ON d.id = s.district_id
WHERE s.id = ANY($1) AND s.deleted_at IS NULL AND s.operational_status = ANY($2)`, ids, rules.OperatingStatuses)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the portfolio's schools: %w", err)
	}
	for rows.Next() {
		var id string
		var sc school
		if err := rows.Scan(&id, &sc.name, &sc.code, &sc.district, &sc.cluster); err != nil {
			rows.Close()
			return nil, fmt.Errorf("programmerollout: reading a school: %w", err)
		}
		s.schools[id] = sc
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("programmerollout: reading the portfolio's schools: %w", err)
	}
	for _, a := range assigned {
		if _, ok := s.schools[a.school]; !ok {
			continue
		}
		if m := s.member(a.staff); m != nil {
			m.schools[a.school] = true
		}
	}
	for _, m := range s.everyone() {
		for _, id := range m.ids() {
			if _, ok := s.ownerByID[id]; !ok {
				s.ownerByID[id] = m.staffID
			}
		}
	}
	for _, m := range s.everyone() {
		for id := range m.schools {
			s.ownersBySchool[id] = append(s.ownersBySchool[id], m.staffID)
		}
	}
	return s, nil
}

// activityFilter is RolloutScope.activity_filter over activity `a`, its
// arguments appended: owned or monitored by anyone on the team, or held at
// a portfolio school.
func (s *scope) activityFilter(args []any) (string, []any) {
	ids := []string{}
	for id := range s.ownerByID {
		ids = append(ids, id)
	}
	args = append(args, ids)
	n := len(args)
	clause := fmt.Sprintf("(a.responsible_staff_id = ANY($%d) OR a.monitored_by_staff_id = ANY($%d)", n, n)
	if len(s.schools) > 0 {
		args = append(args, s.staffIDs(), rules.OperatingStatuses)
		clause += fmt.Sprintf(` OR a.school_id IN (SELECT sc.id FROM school sc WHERE sc.id IN (
  SELECT school_id FROM staff_school_assignment WHERE staff_id = ANY($%d)) AND sc.deleted_at IS NULL AND sc.operational_status = ANY($%d))`,
			len(args)-1, len(args))
	}
	return clause + ")", args
}
