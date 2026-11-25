package teamtargets

import (
	"context"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// data is get_page's figures before they are drawn.
type data struct {
	period
	q                       query
	all                     []Member
	t                       team
	roster                  *targets.Roster
	port                    portfolio
	category, categoryLabel string
	district, member        string
	ranked, groupByLead     bool
}

// read is get_page up to the members: the team, the agreed areas, the
// filters it validates and each member's row.
func read(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q query, today time.Time,
	operationalFY string) (*data, error) {
	scope, err := schooldirectory.ResolveScope(ctx, db, p, today)
	if err != nil {
		return nil, err
	}
	d := &data{period: periodOf(q, today, operationalFY), q: q}
	if d.all, err = supervisedUsers(ctx, db, p, scope); err != nil {
		return nil, err
	}
	people := make([]targets.Person, len(d.all))
	staffIDs := []string{}
	for i, m := range d.all {
		people[i] = targets.Person{UserID: m.UserID, StaffID: m.StaffID}
		if m.StaffID != "" {
			staffIDs = append(staffIDs, m.StaffID)
		}
	}
	if d.roster, err = targets.Prepare(ctx, db, people, d.fy, nil); err != nil {
		return nil, err
	}
	d.t.areas = d.roster.AgreedAreas(people)
	d.category, d.categoryLabel = "overall", "Overall weighted performance"
	d.t.metricAreas = d.t.areas
	for _, a := range d.t.areas {
		if a.Key == q.category {
			d.category, d.categoryLabel = a.Key, a.Label
			d.t.metricAreas = []targets.Area{a}
		}
	}
	if d.port, err = readPortfolio(ctx, db, staffIDs); err != nil {
		return nil, err
	}
	for _, opt := range d.port.districts {
		if opt == q.district {
			d.district = opt
		}
	}
	for _, m := range d.all {
		if m.UserID == q.member {
			d.member = m.UserID
		}
	}
	d.ranked = q.order == rules.OrderRanked
	d.groupByLead = p.ActiveRole == "RegionalProgramLead" && !d.ranked
	for i, m := range d.all {
		if d.member != "" && m.UserID != d.member {
			continue
		}
		if d.district != "" && !hasDistrict(d.port.of[m.StaffID], d.district) {
			continue
		}
		var metric []targets.Area
		if d.category != "overall" {
			metric = []targets.Area{}
			for _, a := range d.roster.Areas(people[i]) {
				if a.Key == d.category {
					metric = append(metric, a)
				}
			}
		}
		r := &row{TeamMember: d.roster.TeamMember(people[i], d.month, d.current, today, metric), member: m,
			initials: initials(m.Name), schools: d.port.of[m.StaffID]}
		r.districts = d.port.districtsOf(m.StaffID)
		r.districtLabel = strings.Join(first(r.districts, 2), ", ")
		if r.districtLabel == "" {
			r.districtLabel = "—"
		}
		d.t.rows = append(d.t.rows, r)
	}
	return d, nil
}

func hasDistrict(schools []school, district string) bool {
	for _, s := range schools {
		if s.district == district {
			return true
		}
	}
	return false
}

// initials is (name or "??")[:2].upper().
func initials(name string) string {
	if name == "" {
		name = "??"
	}
	r := []rune(name)
	if len(r) > 2 {
		r = r[:2]
	}
	return strings.ToUpper(string(r))
}

func first(s []string, n int) []string {
	if len(s) > n {
		return s[:n]
	}
	return s
}
