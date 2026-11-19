package adminpanel

import (
	"context"
	"fmt"
	"slices"
	"strconv"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// GeographyPath is Geographical Location Setup
// (extended_views.admin_region_district_setup_view,
// pages/admin/region_district_setup.html): the districts not yet classified,
// every region's districts by name, the Secondary District Groups and the
// new-district form. Classifying, creating and approving stay the existing
// page's.
const GeographyPath = "/admin-panel/region-district-setup"

type region struct {
	id, name  string
	districts []string
}

type districtGroup struct {
	id, name, status string
	members          [][2]string
}

func (s *Service) geography(ctx context.Context, p auth.Principal) (*screensv1.GetPageResponse, bool, error) {
	regions, err := s.regions(ctx)
	if err != nil {
		return nil, true, err
	}
	groups, err := s.districtGroups(ctx)
	if err != nil {
		return nil, true, err
	}
	var unclassified int
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM district WHERE district_type IS NULL`).Scan(&unclassified); err != nil {
		return nil, true, fmt.Errorf("adminpanel: counting the unclassified districts: %w", err)
	}
	var blocks []*screensv1.PageBlock
	if unclassified > 0 {
		blocks = append(blocks, titled("", text(strconv.Itoa(unclassified)+" district(s) not yet classified as Primary or Secondary"),
			text("Staff cannot schedule school visits in an unclassified district — Daily Visit Batch costing needs to know whether the day's shared cost pool includes accommodation/overnight dinner. Classify each district below.")))
	}
	var listed []*screensv1.PagePanelItem
	for _, r := range regions {
		listed = append(listed, text(closedschools.Collapse(r.name)+" Region"), text(strconv.Itoa(len(r.districts))+" District(s)"))
		for _, d := range r.districts {
			listed = append(listed, text(closedschools.Collapse(d)))
		}
		if len(r.districts) == 0 {
			listed = append(listed, text("No districts registered in this region."))
		}
	}
	blocks = append(blocks, titled("Active Districts by Region", listed...), groupsBlock(groups, slices.Contains(rules.DistrictProfileRoles, p.ActiveRole)))
	options := []*screensv1.DrawerOption{{Value: "", Label: "Select Region..."}}
	for _, r := range regions {
		options = append(options, &screensv1.DrawerOption{Value: r.id, Label: closedschools.Collapse(r.name)})
	}
	field := func(f *screensv1.DrawerField) *screensv1.PageFormItem {
		return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: f}}
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
		Title: "Add New District", SubmitLabel: "Create District", Key: "/admin/region-district-setup",
		Items: []*screensv1.PageFormItem{
			field(&screensv1.DrawerField{Name: "district_name", Label: "District Name", Kind: "text", Required: true, Placeholder: "e.g. Mukono"}),
			field(&screensv1.DrawerField{Name: "region_id", Label: "Region Assignment", Kind: "select", Required: true, Options: options}),
		}}}})
	return page(header("Administration", "Geographical Location Setup", "Manage administrative levels, regions, districts, and parishes"),
		GeographyPath, blocks...), true, nil
}

const groupsLine = "Optional names for nearby secondary districts often visited together. Staff can schedule schools from any districts on the same day; a group only labels that route."

// groupsBlock is the Secondary District Groups card: with no group it reads
// as its create form; with groups, as a panel of each group's name, state
// and districts.
func groupsBlock(groups []districtGroup, links bool) *screensv1.PageBlock {
	if len(groups) == 0 {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
			Title: "Secondary District Groups", Text: groupsLine, SubmitLabel: "Create Group", Key: "create_group",
			Items: []*screensv1.PageFormItem{{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{
				Name: "group_name", Kind: "text", Required: true, Placeholder: "e.g. Kitgum Secondary Route"}}}}}}}
	}
	var items []*screensv1.PagePanelItem
	for _, g := range groups {
		state := "Draft"
		if g.status == "approved" {
			state = "Approved"
		}
		items = append(items, text(closedschools.Collapse(g.name)), text(state))
		if len(g.members) == 0 {
			items = append(items, text("No districts added yet."))
			continue
		}
		var ls []*screensv1.PageLink
		for _, m := range g.members {
			if !links {
				items = append(items, text(closedschools.Collapse(m[1])))
				continue
			}
			ls = append(ls, &screensv1.PageLink{Text: closedschools.Collapse(m[1]), Href: "/districts/" + m[0]})
		}
		if len(ls) > 0 {
			items = append(items, linkItem(ls...))
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Secondary District Groups", Subtitle: groupsLine, Badges: []*screensv1.PageBadge{}, Items: items}}}
}

// regions are every region by name with its districts by name.
func (s *Service) regions(ctx context.Context) ([]region, error) {
	rows, err := s.db.Query(ctx, `SELECT r.id, r.name, d.name FROM region r LEFT JOIN district d ON d.region_id = r.id
ORDER BY r.name, r.id, d.name, d.id`)
	if err != nil {
		return nil, fmt.Errorf("adminpanel: reading the regions: %w", err)
	}
	type line struct {
		id, name string
		district *string
	}
	lines, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (line, error) {
		var l line
		return l, r.Scan(&l.id, &l.name, &l.district)
	})
	if err != nil {
		return nil, fmt.Errorf("adminpanel: reading the regions: %w", err)
	}
	var out []region
	for _, l := range lines {
		if len(out) == 0 || out[len(out)-1].id != l.id {
			out = append(out, region{id: l.id, name: l.name})
		}
		if l.district != nil {
			out[len(out)-1].districts = append(out[len(out)-1].districts, *l.district)
		}
	}
	return out, nil
}

// districtGroups are the Secondary District Groups by name, each with its
// member districts.
func (s *Service) districtGroups(ctx context.Context) ([]districtGroup, error) {
	rows, err := s.db.Query(ctx, `SELECT g.id, g.name, COALESCE(g.status, ''), d.id, d.name
FROM secondary_district_group g
LEFT JOIN secondary_district_group_member m ON m.group_id = g.id
LEFT JOIN district d ON d.id = m.district_id
ORDER BY g.name, g.id, m.created_at, m.id`)
	if err != nil {
		return nil, fmt.Errorf("adminpanel: reading the district groups: %w", err)
	}
	type line struct {
		id, name, status     string
		districtID, district *string
	}
	lines, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (line, error) {
		var l line
		return l, r.Scan(&l.id, &l.name, &l.status, &l.districtID, &l.district)
	})
	if err != nil {
		return nil, fmt.Errorf("adminpanel: reading the district groups: %w", err)
	}
	var out []districtGroup
	for _, l := range lines {
		if len(out) == 0 || out[len(out)-1].id != l.id {
			out = append(out, districtGroup{id: l.id, name: l.name, status: l.status})
		}
		if l.districtID != nil && l.district != nil {
			out[len(out)-1].members = append(out[len(out)-1].members, [2]string{*l.districtID, *l.district})
		}
	}
	return out, nil
}
