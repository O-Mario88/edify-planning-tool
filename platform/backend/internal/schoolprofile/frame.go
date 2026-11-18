package schoolprofile

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// lens is what an engine tab is read for: the year, the part of it, and
// where the profile's links start (profile_views.profile_context).
type lens struct {
	tab, fy, period, running string
	window                   window
	// base is the profile's own address, /schools/<record id>.
	base string
	// query is the page's query, which a table's pager reads its page
	// from and carries on.
	query url.Values
}

// href is profile_context's "href": every link of the profile starts here.
func (l lens) href() string {
	h := l.base + "?"
	if l.period != "" {
		h += "period=" + l.period + "&"
	}
	return h
}

// records is where a figure's records open: the address up to the
// figure's name.
func (l lens) records() string { return l.href() + "fy=" + l.fy + "&what=" }

func lensOf(sc school, tab, fy, period, running string) lens {
	if !slices.Contains(fyChoices(running), fy) {
		fy = running
	}
	if !knownPeriod(period) {
		period = ""
	}
	return lens{tab: tab, fy: fy, period: period, running: running, window: periodWindow(fy, period), base: "/schools/" + sc.ID}
}

// frame is what every engine tab draws above its section: what the
// numbers cover, the profile's facts, and the year and period filters.
func (s *Service) frame(ctx context.Context, d doors, sc school, l lens) ([]*screensv1.PageBlock, error) {
	scopeLine := "Single school, " + fyLabel(l.fy)
	if l.window.label != "" {
		scopeLine += " · work in " + l.window.label
	}
	facts, err := s.identity(ctx, d, sc, l)
	if err != nil {
		return nil, err
	}
	fyOptions := []*screensv1.PageFilterOption{}
	for _, year := range fyChoices(l.running) {
		fyOptions = append(fyOptions, &screensv1.PageFilterOption{Value: year, Label: fyLabel(year)})
	}
	periods := []*screensv1.PageFilterOption{}
	for _, o := range periodOptions() {
		periods = append(periods, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_ScopeLine{ScopeLine: scopeLine}},
		{Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: facts}}},
		{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
			Filters: []*screensv1.PageFilter{
				{Name: "fy", Label: "Fiscal year", Value: l.fy, Options: fyOptions},
				{Name: "period", Label: "Period", Value: l.period, Options: periods},
			},
			Hidden: map[string]string{"tab": l.tab},
		}}},
	}, nil
}

// identity is profile_records.identity for a school: its ID, type, cohort,
// where it sits, its cluster, who holds it and their lead, the partners
// holding work there, its status and the year.
func (s *Service) identity(ctx context.Context, d doors, sc school, l lens) ([]*screensv1.PageFact, error) {
	facts := []*screensv1.PageFact{}
	add := func(label, value, href string) {
		if value != "" {
			facts = append(facts, &screensv1.PageFact{Label: label, Value: value, Href: href})
		}
	}
	add("School ID", sc.SchoolID, "")
	add("Type", rules.SchoolTypes[sc.Type], "")
	if sc.CohortYear != nil && sc.CohortNumber != nil {
		add("Cohort", fmt.Sprintf("Cohort %d · %d", *sc.CohortNumber, *sc.CohortYear), "")
	}
	var subRegionID, subRegionName, clusterName string
	err := s.db.QueryRow(ctx, `
SELECT COALESCE(d.sub_region_id, ''), COALESCE(sr.name, ''),
  COALESCE((SELECT c.name FROM cluster c WHERE c.id = $2 AND c.deleted_at IS NULL), '')
FROM (SELECT 1) one
LEFT JOIN district d ON d.id = $1
LEFT JOIN sub_region sr ON sr.id = d.sub_region_id`, sc.DistrictID, sc.ClusterID).Scan(&subRegionID, &subRegionName, &clusterName)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the school's place: %w", err)
	}
	if sc.HasDistrict {
		add("District", sc.DistrictName, "/districts/"+sc.DistrictID)
		if subRegionID != "" {
			add("Sub-region", subRegionName, "/sub-regions/"+subRegionID)
		}
	}
	if sc.SubCountyID != "" {
		add("Sub-county", sc.SubCountyName, "")
	}
	if sc.ClusterID != "" && clusterName != "" {
		add("Cluster", clusterName, "/clusters/"+sc.ClusterID)
	}
	staff, leads, err := s.holders(ctx, sc.OwnerID)
	if err != nil {
		return nil, err
	}
	facts = append(facts, peopleFact("CCEO", staff, d.OpenStaff, "/staff/"), peopleFact("Programme Lead", leads, d.OpenStaff, "/staff/"))
	partners, err := s.partnersHolding(ctx, sc.ID)
	if err != nil {
		return nil, err
	}
	if len(partners) > 0 {
		fact := peopleFact("Partner", partners, true, "/partners/")
		facts = append(facts, fact)
	}
	status := "Operating"
	if sc.closed() {
		status = "Closed"
	}
	add("Status", status, "")
	add("Fiscal Year", fyLabel(l.fy), "")
	return facts, nil
}

// person is someone a fact names: the id their profile's address takes.
type person struct{ id, name string }

// peopleFact is profile_records._people_fact as the header draws it: up to
// three names, then "and N more"; "Not assigned" for nobody. The first
// name's link is the fact's.
func peopleFact(label string, people []person, link bool, prefix string) *screensv1.PageFact {
	if len(people) != 1 {
		label += "s"
	}
	if len(people) == 0 {
		return &screensv1.PageFact{Label: label, Value: "Not assigned"}
	}
	shown := people[:min(3, len(people))]
	names := []string{}
	for _, p := range shown {
		names = append(names, p.name)
	}
	value := strings.Join(names, ", ")
	if more := len(people) - len(shown); more > 0 {
		value += fmt.Sprintf(" and %d more", more)
	}
	href := ""
	if link {
		href = prefix + shown[0].id
	}
	return &screensv1.PageFact{Label: label, Value: value, Href: href}
}

// holders is profile_records._holders: the staff holding the school (its
// owner, by staff or user id) and the leads they report to, by name.
func (s *Service) holders(ctx context.Context, ownerID string) (staff, leads []person, err error) {
	if ownerID == "" {
		return nil, nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT sp.id, sp.user_id, COALESCE(NULLIF(u.name, ''), NULLIF(u.email, ''), 'Unnamed')
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = $1 OR sp.user_id = $1)`, ownerID)
	if err != nil {
		return nil, nil, fmt.Errorf("schoolprofile: reading the school's holder: %w", err)
	}
	staffIDs := []string{}
	staff, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (person, error) {
		var staffID string
		var p person
		err := row.Scan(&staffID, &p.id, &p.name)
		staffIDs = append(staffIDs, staffID)
		return p, err
	})
	if err != nil {
		return nil, nil, err
	}
	rows, err = s.db.Query(ctx, `
SELECT DISTINCT sup.user_id, COALESCE(NULLIF(u.name, ''), NULLIF(u.email, ''), 'Unnamed')
FROM staff_supervisor_assignment a
JOIN staff_profile sup ON sup.id = a.supervisor_id JOIN "user" u ON u.id = sup.user_id
WHERE a.supervisee_id = ANY($1)`, staffIDs)
	if err != nil {
		return nil, nil, fmt.Errorf("schoolprofile: reading the school's lead: %w", err)
	}
	leads, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (person, error) {
		var p person
		return p, row.Scan(&p.id, &p.name)
	})
	if err != nil {
		return nil, nil, err
	}
	byName := func(a, b person) int { return strings.Compare(strings.ToLower(a.name), strings.ToLower(b.name)) }
	slices.SortStableFunc(staff, byName)
	slices.SortStableFunc(leads, byName)
	return staff, leads, nil
}

// partnersHolding are the partners holding work at the school (hand-overs
// not taken back), by name.
func (s *Service) partnersHolding(ctx context.Context, schoolID string) ([]person, error) {
	rows, err := s.db.Query(ctx, `
SELECT DISTINCT pa.partner_id, COALESCE(p.name, '') FROM partner_assignment pa
LEFT JOIN partner p ON p.id = pa.partner_id
WHERE pa.school_id = $1 AND NOT (pa.status = ANY($2))
ORDER BY 2`, schoolID, rules.Engine.HandoverReleasedStatuses)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the partners: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (person, error) {
		var p person
		var id *string
		err := row.Scan(&id, &p.name)
		if id != nil {
			p.id = *id
		}
		return p, err
	})
}
