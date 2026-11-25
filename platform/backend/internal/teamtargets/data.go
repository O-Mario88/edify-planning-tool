package teamtargets

import (
	"context"
	"sort"
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
	if d.groupByLead {
		if err := d.groupRows(ctx, db); err != nil {
			return nil, err
		}
	}
	if d.ranked {
		d.rankRows()
	}
	return d, nil
}

// noLead is owner_groups.NO_LEAD.
const noLead = "No Program Lead"

// groupRows files each member under their Programme Lead, for a reader of
// many teams: the Leads by name, those with none last, then the member.
func (d *data) groupRows(ctx context.Context, db schooldirectory.Querier) error {
	ids := d.t.staffIDs()
	leads, err := schooldirectory.OwnerLeads(ctx, db, ids)
	if err != nil {
		return err
	}
	for _, r := range d.t.rows {
		r.leadName = leads[r.member.StaffID]
		if r.leadName == "" {
			r.leadName = noLead
		}
	}
	sort.SliceStable(d.t.rows, func(i, j int) bool {
		a, b := d.t.rows[i], d.t.rows[j]
		if (a.leadName == noLead) != (b.leadName == noLead) {
			return b.leadName == noLead
		}
		if a.leadName != b.leadName {
			return a.leadName < b.leadName
		}
		return a.member.Name < b.member.Name
	})
	return nil
}

// rankRows is _rank: the members by their weighted full-year achievement,
// the strongest first and numbered; those with no target for the year last
// by name, without a place.
func (d *data) rankRows() {
	year := func(r *row) targets.Cell { return r.Cells[len(r.Cells)-1] }
	pct := func(r *row) int {
		if p := year(r).Pct; p != nil {
			return *p
		}
		return 0
	}
	sort.SliceStable(d.t.rows, func(i, j int) bool {
		a, b := d.t.rows[i], d.t.rows[j]
		ua, ub := year(a).Target == 0, year(b).Target == 0
		if ua != ub {
			return ub
		}
		if pa, pb := pct(a), pct(b); pa != pb {
			return pa > pb
		}
		return strings.ToLower(a.member.Name) < strings.ToLower(b.member.Name)
	})
	place := 0
	for _, r := range d.t.rows {
		r.rank = nil
		if year(r).Target != 0 {
			place++
			v := place
			r.rank = &v
		}
	}
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
