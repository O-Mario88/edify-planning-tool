package trainingsummary

import (
	"context"
	"slices"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// cell is training_summary.Cell: one staff member's schools for one row.
type cell struct {
	staffID   string
	schools   int
	limit     *int
	ceilingID string
}

// state is Cell.state.
func (c cell) state() string {
	switch {
	case c.limit == nil:
		return "unset"
	case c.schools > *c.limit:
		return "above"
	case c.schools == *c.limit:
		return "reached"
	}
	return "below"
}

func (c cell) blank() bool { return c.limit == nil && c.schools == 0 }

// row is training_summary.Row.
type row struct {
	project                   bool
	name, mode                string
	trainingID, projectID     string
	countryCeiling            *int
	countryCeilingID          string
	planned, staffPlanned     int
	partner, partnerScheduled int
	cells                     []cell
}

func (r row) awaitingPartner() int { return max(r.partner-r.partnerScheduled, 0) }

func (r row) remaining() *int {
	if r.countryCeiling == nil {
		return nil
	}
	left := max(*r.countryCeiling-r.planned, 0)
	return &left
}

func (r row) countryState() string {
	switch {
	case r.countryCeiling == nil:
		return "unset"
	case r.planned > *r.countryCeiling:
		return "above"
	case r.planned == *r.countryCeiling:
		return "reached"
	}
	return "below"
}

// summary is training_summary.Summary.
type summary struct {
	fy                    string
	staff                 []profile
	rows                  []row
	maySet, maySetCountry bool
	leads                 [][2]string
	lead                  string
	leadIDs               []string
	countryLinks          bool
}

// routes are the schools committed to one training, by route: the sets
// scheduled_schools and country_scheduled read.
type routes struct{ group, inSchool, partner, partnerScheduled map[string]bool }

func newRoutes() *routes {
	return &routes{map[string]bool{}, map[string]bool{}, map[string]bool{}, map[string]bool{}}
}

func (r *routes) covered() int {
	all := map[string]bool{}
	for _, set := range []map[string]bool{r.group, r.inSchool, r.partner} {
		for school := range set {
			all[school] = true
		}
	}
	return len(all)
}

// commitments reads every route for these owners in the year, keyed by
// key(owner, course).
func commitments(ctx context.Context, q schooldirectory.Querier, owners []string, fy string, now time.Time,
	key func(owner, course string) (string, bool)) (map[string]*routes, error) {
	out := map[string]*routes{}
	get := func(owner, course string) *routes {
		k, ok := key(owner, course)
		if !ok {
			return nil
		}
		if out[k] == nil {
			out[k] = newRoutes()
		}
		return out[k]
	}
	group, err := groupRows(ctx, q, owners, fy)
	if err != nil {
		return nil, err
	}
	for _, c := range group {
		if r := get(c.owner, c.course); r != nil {
			r.group[c.school] = true
		}
	}
	inSchool, err := inSchoolRows(ctx, q, owners, fy)
	if err != nil {
		return nil, err
	}
	for _, c := range inSchool {
		if r := get(c.owner, c.course); r != nil {
			r.inSchool[c.school] = true
		}
	}
	partner, err := partnerRows(ctx, q, owners, fy)
	if err != nil {
		return nil, err
	}
	for _, c := range partner {
		if r := get(c.owner, c.course); r != nil {
			r.partner[c.school] = true
			if c.dated {
				r.partnerScheduled[c.school] = true
			}
		}
	}
	handovers, err := handoverRows(ctx, q, owners, fy, now)
	if err != nil {
		return nil, err
	}
	for _, c := range handovers {
		if r := get(c.owner, c.course); r != nil {
			r.partner[c.school] = true
		}
	}
	return out, nil
}

// figure is training_ceilings.SummaryRow, as the summary reads it.
type figure struct {
	total, ceilingValue int
	hasCeiling          bool
	ceilingID           string
}

func pairKey(staff, course string) string { return staff + "\x00" + course }

// staffFigures is training_ceilings.summary_for_staff for the columns:
// {(staff id, training id): figure}.
func staffFigures(ctx context.Context, q schooldirectory.Querier, staff []profile, fy string, now time.Time) (map[string]figure, error) {
	if len(staff) == 0 {
		return map[string]figure{}, nil
	}
	byIdentity := map[string]string{}
	ids := []string{}
	for _, p := range staff {
		for _, identity := range []string{p.id, p.userID} {
			if identity != "" {
				if _, seen := byIdentity[identity]; !seen {
					ids = append(ids, identity)
				}
				byIdentity[identity] = p.id
			}
		}
	}
	found, err := commitments(ctx, q, ids, fy, now, func(owner, course string) (string, bool) {
		staffID, ok := byIdentity[owner]
		return pairKey(staffID, course), ok
	})
	if err != nil {
		return nil, err
	}
	staffIDs := make([]string, 0, len(staff))
	for _, p := range staff {
		staffIDs = append(staffIDs, p.id)
	}
	ceilings, err := staffCeilings(ctx, q, staffIDs, fy)
	if err != nil {
		return nil, err
	}
	out := map[string]figure{}
	for k, r := range found {
		out[k] = figure{total: r.covered()}
	}
	// A project's training holds no ceiling here: its courses never come
	// back from the routes, and its ceilings are dropped (projects_own).
	projectOwn, err := projectTrainingIDs(ctx, q)
	if err != nil {
		return nil, err
	}
	for k, c := range ceilings {
		if in(projectOwn, k[1]) {
			continue
		}
		f := out[pairKey(k[0], k[1])]
		f.hasCeiling, f.ceilingValue, f.ceilingID = true, c.value, c.id
		out[pairKey(k[0], k[1])] = f
	}
	return out, nil
}

func projectTrainingIDs(ctx context.Context, q schooldirectory.Querier) ([]string, error) {
	maps, err := projectMappings(ctx, q)
	if err != nil {
		return nil, err
	}
	out := []string{}
	for _, m := range maps {
		out = append(out, m.training.id)
	}
	return out, nil
}

// trainingRows is training_summary._training_rows.
func trainingRows(ctx context.Context, q schooldirectory.Querier, staff []profile, fy, country string, now time.Time) ([]row, error) {
	owners, err := countryIdentities(ctx, q, country)
	if err != nil {
		return nil, err
	}
	planned, err := commitments(ctx, q, owners, fy, now, func(_, course string) (string, bool) { return course, true })
	if err != nil || len(planned) == 0 {
		return nil, err
	}
	ceilings, err := countryCeilings(ctx, q, fy, country)
	if err != nil {
		return nil, err
	}
	figures, err := staffFigures(ctx, q, staff, fy, now)
	if err != nil {
		return nil, err
	}
	courses := make([]string, 0, len(planned))
	for course := range planned {
		courses = append(courses, course)
	}
	slices.Sort(courses)
	items, err := catalogueItems(ctx, q, courses)
	if err != nil {
		return nil, err
	}
	out := make([]row, 0, len(items))
	for _, it := range items {
		r := row{name: it.name, trainingID: it.id}
		for _, p := range staff {
			c := cell{staffID: p.id}
			if f, ok := figures[pairKey(p.id, it.id)]; ok {
				c.schools, c.ceilingID = f.total, f.ceilingID
				if f.hasCeiling {
					limit := f.ceilingValue
					c.limit = &limit
				}
			}
			r.cells = append(r.cells, c)
		}
		country := planned[it.id]
		modes := []string{}
		for _, m := range []struct {
			label   string
			schools int
		}{{rules.ModeGroup, len(country.group)}, {rules.ModeInSchool, len(country.inSchool)}, {rules.ModePartnerInSchool, len(country.partner)}} {
			if m.schools > 0 {
				modes = append(modes, m.label)
			}
		}
		r.mode = strings.Join(modes, " · ")
		if c, ok := ceilings[it.id]; ok {
			value := c.value
			r.countryCeiling, r.countryCeilingID = &value, c.id
		}
		r.planned = country.covered()
		r.staffPlanned = len(country.inSchool)
		r.partner = len(country.partner)
		r.partnerScheduled = len(country.partnerScheduled)
		out = append(out, r)
	}
	return out, nil
}

// projectRows is training_summary._project_rows.
func projectRows(ctx context.Context, q schooldirectory.Querier, staff []profile) ([]row, error) {
	maps, err := projectMappings(ctx, q)
	if err != nil || len(maps) == 0 {
		return nil, err
	}
	projects := []string{}
	for _, m := range maps {
		if !in(projects, m.projectID) {
			projects = append(projects, m.projectID)
		}
	}
	f, err := readProjectFigures(ctx, q, projects, staff)
	if err != nil {
		return nil, err
	}
	out := []row{}
	for _, m := range maps {
		r := row{
			project:    true,
			name:       m.training.name + " (" + m.projectName + ")",
			mode:       catalogueMode(m.training.method),
			trainingID: m.training.id,
			projectID:  m.projectID,
			planned:    f.onProject[m.projectID],
		}
		for _, p := range staff {
			k := [2]string{m.projectID, p.id}
			c := cell{staffID: p.id, schools: f.added[k]}
			if f.hasCapacity[k] {
				limit := f.capacity[k]
				c.limit = &limit
			}
			r.cells = append(r.cells, c)
		}
		if r.planned > 0 {
			out = append(out, r)
		}
	}
	return out, nil
}

// catalogueMode is _CATALOGUE_MODES, else the delivery method's label, else
// the stored value.
func catalogueMode(method string) string {
	if label, ok := rules.CatalogueModes[method]; ok {
		return label
	}
	return method
}

// buildRows is training_summary.build.
func buildRows(ctx context.Context, q schooldirectory.Querier, staff []profile, fy, country string, now time.Time) ([]row, error) {
	trainings, err := trainingRows(ctx, q, staff, fy, country, now)
	if err != nil {
		return nil, err
	}
	projects, err := projectRows(ctx, q, staff)
	if err != nil {
		return nil, err
	}
	return append(trainings, projects...), nil
}

func byFoldedName(key func(profile) string) func(a, b profile) int {
	return func(a, b profile) int { return strings.Compare(strings.ToLower(key(a)), strings.ToLower(key(b))) }
}

// leadsOf is training_summary._leads_of: {officer: lead} and the Leads by
// name.
func leadsOf(ctx context.Context, q schooldirectory.Querier, officers []profile) (map[string]string, [][2]string, error) {
	ids := make([]string, 0, len(officers))
	for _, p := range officers {
		ids = append(ids, p.id)
	}
	links, err := leadLinks(ctx, q, ids)
	if err != nil {
		return nil, nil, err
	}
	names := [][2]string{}
	named := func(id string) bool {
		return slices.ContainsFunc(names, func(pair [2]string) bool { return pair[0] == id })
	}
	for _, p := range officers {
		if p.holds(rules.ProgramLeadRole) {
			name := p.display()
			if name == "" {
				name = "Programme Lead"
			}
			names = append(names, [2]string{p.id, name})
		}
	}
	leadOf := map[string]string{}
	for _, l := range links {
		if l.officer == l.lead || named(l.officer) {
			continue
		}
		if _, ok := leadOf[l.officer]; !ok {
			leadOf[l.officer] = l.lead
		}
		if !named(l.lead) {
			name := l.name
			if name == "" {
				name = "Programme Lead"
			}
			names = append(names, [2]string{l.lead, name})
		}
	}
	slices.SortStableFunc(names, func(a, b [2]string) int { return strings.Compare(strings.ToLower(a[1]), strings.ToLower(b[1])) })
	return leadOf, names, nil
}

// teamsInOrder is training_summary._teams_in_order.
func teamsInOrder(officers []profile, leadOf map[string]string, leadIDs []string) []profile {
	ordered, placed := []profile{}, map[string]bool{}
	byID := map[string]profile{}
	for _, p := range officers {
		byID[p.id] = p
	}
	for _, lead := range leadIDs {
		team := []string{}
		if _, ok := byID[lead]; ok {
			team = append(team, lead)
		}
		for _, p := range officers {
			if leadOf[p.id] == lead {
				team = append(team, p.id)
			}
		}
		for _, id := range team {
			if !placed[id] {
				placed[id] = true
				ordered = append(ordered, byID[id])
			}
		}
	}
	for _, p := range officers {
		if !placed[p.id] {
			ordered = append(ordered, p)
		}
	}
	return ordered
}

// forReader is training_summary.for_reader for a Programme Lead or a reader
// of the country.
func forReader(ctx context.Context, q schooldirectory.Querier, role, userID, staffProfileID, fy, lead string, doors Doors, now time.Time, withRows bool) (summary, error) {
	country, err := readerCountry(ctx, q, userID)
	if err != nil {
		return summary{}, err
	}
	s := summary{fy: fy}
	if role == rules.ProgramLeadRole {
		own, err := ownProfile(ctx, q, staffProfileID)
		if err != nil {
			return s, err
		}
		team, err := teamMembers(ctx, q, staffProfileID, now)
		if err != nil {
			return s, err
		}
		officers := []profile{}
		for _, p := range team {
			if own == nil || p.id != own.id {
				officers = append(officers, p)
			}
		}
		slices.SortStableFunc(officers, byFoldedName(func(p profile) string { return p.name }))
		if own != nil {
			officers = append([]profile{*own}, officers...)
		}
		s.staff, s.maySet = officers, len(officers) > 0
		if staffProfileID != "" {
			s.leadIDs = []string{staffProfileID}
		}
	} else {
		officers, err := countryOfficers(ctx, q, country)
		if err != nil {
			return s, err
		}
		slices.SortStableFunc(officers, byFoldedName(profile.display))
		leadOf, leads, err := leadsOf(ctx, q, officers)
		if err != nil {
			return s, err
		}
		if !slices.ContainsFunc(leads, func(pair [2]string) bool { return pair[0] == lead }) {
			lead = ""
		}
		if lead != "" {
			team := []profile{}
			for _, p := range officers {
				if p.id == lead || leadOf[p.id] == lead {
					team = append(team, p)
				}
			}
			officers = team
		}
		for _, pair := range leads {
			s.leadIDs = append(s.leadIDs, pair[0])
		}
		s.staff = teamsInOrder(officers, leadOf, s.leadIDs)
		s.maySetCountry, s.leads, s.lead, s.countryLinks = doors.SetsCountryCeiling, leads, lead, true
	}
	if !withRows {
		// with_rows=False: the readers and columns alone, for a tab that
		// draws another table of the same people.
		return s, nil
	}
	s.rows, err = buildRows(ctx, q, s.staff, fy, country, now)
	return s, err
}
