package clustercreate

import (
	"context"
	"fmt"
	"net/url"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// District is a district the reader may create a cluster in.
type District struct{ ID, Name string }

// SubCounty is one of those districts' sub-counties, and the cluster that
// already covers it (information only: the one-cluster rule was lifted).
type SubCounty struct{ ID, Name, DistrictID, CoveredBy string }

// Staff is a person the cluster may be filed under.
type Staff struct{ UserID, Name, Role string }

// holdingStatuses are CLUSTER_HOLDING_STATUSES.
var holdingStatuses = []string{"active", "needs_review"}

func field(f *screensv1.DrawerField) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: f}}
}

func length(n int32) *int32 { return &n }

// StaffOptions is a district's staff as the select offers them.
func StaffOptions(staff []Staff) []*screensv1.DrawerOption {
	options := []*screensv1.DrawerOption{{Value: "", Label: "No assigned staff"}}
	for _, sp := range staff {
		options = append(options, &screensv1.DrawerOption{Value: sp.UserID, Label: sp.Name + " (" + sp.Role + ")"})
	}
	return options
}

// drawerFor is partials/clusters/create_cluster_drawer.html as the feed reads it.
func drawerFor(districts []District, subs []SubCounty, selected string, staff []Staff) *screensv1.PageDrawer {
	districtOptions := []*screensv1.DrawerOption{{Value: "", Label: "Select a district"}}
	for _, d := range districts {
		districtOptions = append(districtOptions, &screensv1.DrawerOption{Value: d.ID, Label: d.Name})
	}
	subOptions := []*screensv1.DrawerOption{}
	for _, sc := range subs {
		detail := ""
		if sc.CoveredBy != "" {
			detail = "Also in " + sc.CoveredBy
		}
		subOptions = append(subOptions, &screensv1.DrawerOption{Value: sc.ID, Label: sc.Name, Detail: detail, Group: sc.DistrictID})
	}
	return &screensv1.PageDrawer{Title: "Create cluster", HasRequired: true, SubmitLabel: "Create cluster", CancelLabel: "Cancel", CanSubmit: true,
		Items: []*screensv1.DrawerItem{
			field(&screensv1.DrawerField{Name: "district_id", Label: "District", Kind: "select", Value: selected, Required: true,
				Options: districtOptions, ReloadsPath: "/clusters/eligible-staff", ReloadsTarget: "responsible_staff_id"}),
			field(&screensv1.DrawerField{Name: "responsible_staff_id", Label: "Assigned staff (optional)", Kind: "select",
				Help: "CCEOs and Programme Leads with schools in the selected district.", Options: StaffOptions(staff)}),
			field(&screensv1.DrawerField{Name: "sub_county_ids", Label: "Sub-counties", Kind: "checklist", Required: true,
				Options: subOptions, GroupBy: "district_id"}),
			field(&screensv1.DrawerField{Name: "name", Label: "Cluster name", Kind: "text", Required: true,
				Help:        "Auto-suggested from your selection — edit if you like. Must be unique within the district.",
				Placeholder: "e.g. Mukono Central Cluster", MaxLength: length(255)}),
			{Kind: &screensv1.DrawerItem_Heading{Heading: "Cluster leader"}},
			{Kind: &screensv1.DrawerItem_Text{Text: "No school leaders on file for the selected area yet — enter the leader’s details below."}},
			field(&screensv1.DrawerField{Name: "cluster_leader_name", Label: "Leader name", Kind: "text", Placeholder: "e.g. Esther Naluwu", MaxLength: length(255)}),
			field(&screensv1.DrawerField{Name: "cluster_leader_phone", Label: "Leader phone", Kind: "tel", Placeholder: "e.g. +256 772 000 000", MaxLength: length(64)}),
		}}
}

// Drawer is create_cluster_drawer_view.
func (s *Service) Drawer(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.PageDrawer, error) {
	if err := gate(p); err != nil {
		return nil, err
	}
	districts, err := s.creationDistricts(ctx, p.StaffProfileID)
	if err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(districts))
	for _, d := range districts {
		ids = append(ids, d.ID)
	}
	subs, err := s.subCounties(ctx, ids)
	if err != nil {
		return nil, err
	}
	selected := strings.TrimSpace(query.Get("district_id"))
	if !contains(ids, selected) {
		selected = ""
		if len(ids) > 0 {
			selected = ids[0]
		}
	}
	staff, err := s.EligibleStaff(ctx, selected)
	if err != nil {
		return nil, err
	}
	return drawerFor(districts, subs, selected, staff), nil
}

// creationDistricts is cluster_creation_district_ids: the districts of the
// reader's own assigned operating schools, by name.
func (s *Service) creationDistricts(ctx context.Context, staffID string) ([]District, error) {
	if staffID == "" {
		return []District{}, nil
	}
	rows, err := s.db.Query(ctx, `SELECT d.id, d.name FROM district d WHERE d.id IN (
  SELECT s.district_id FROM school s WHERE s.deleted_at IS NULL AND s.district_id IS NOT NULL
     AND s.operational_status IN ('active', 'reopened')
     AND s.id IN (SELECT a.school_id FROM staff_school_assignment a WHERE a.staff_id = $1))
ORDER BY d.name`, staffID)
	if err != nil {
		return nil, fmt.Errorf("clustercreate: reading the creation districts: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (District, error) {
		var d District
		return d, r.Scan(&d.ID, &d.Name)
	})
}

// subCounties are the districts' sub-counties by name, with covered_sub_counties'
// holder: a cluster's primary sub-county first (clusters by name), then its
// coverage rows.
func (s *Service) subCounties(ctx context.Context, districts []string) ([]SubCounty, error) {
	covered := map[string]string{}
	rows, err := s.db.Query(ctx, `SELECT c.sub_county_id, c.name FROM cluster c
WHERE c.deleted_at IS NULL AND c.status = ANY($1) AND c.sub_county_id IS NOT NULL ORDER BY c.name
`, holdingStatuses)
	if err != nil {
		return nil, fmt.Errorf("clustercreate: reading the covered sub-counties: %w", err)
	}
	if err := keepFirst(rows, covered); err != nil {
		return nil, err
	}
	rows, err = s.db.Query(ctx, `SELECT cs.sub_county_id, c.name FROM cluster_sub_county cs
JOIN cluster c ON c.id = cs.cluster_id WHERE c.deleted_at IS NULL AND c.status = ANY($1)`, holdingStatuses)
	if err != nil {
		return nil, fmt.Errorf("clustercreate: reading the coverage rows: %w", err)
	}
	if err := keepFirst(rows, covered); err != nil {
		return nil, err
	}
	rows, err = s.db.Query(ctx, `SELECT id, name, COALESCE(district_id, '') FROM sub_county WHERE district_id = ANY($1) ORDER BY name`, districts)
	if err != nil {
		return nil, fmt.Errorf("clustercreate: reading the sub-counties: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (SubCounty, error) {
		var sc SubCounty
		err := r.Scan(&sc.ID, &sc.Name, &sc.DistrictID)
		sc.CoveredBy = covered[sc.ID]
		return sc, err
	})
}

func keepFirst(rows pgx.Rows, into map[string]string) error {
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return err
		}
		if _, seen := into[id]; !seen {
			into[id] = name
		}
	}
	return rows.Err()
}

// StaffChoices is the staff select's refill when the district changes
// (/clusters/eligible-staff, eligible_staff_options_view), offered as the
// drawer offers them. The feed never served this refill; Go does.
func (s *Service) StaffChoices(ctx context.Context, p auth.Principal, district string) ([]*screensv1.DrawerOption, error) {
	if err := gate(p); err != nil {
		return nil, err
	}
	staff, err := s.EligibleStaff(ctx, strings.TrimSpace(district))
	if err != nil {
		return nil, err
	}
	return StaffOptions(staff), nil
}

// EligibleStaff is get_eligible_staff: the staff with schools in the
// district, else in its region, else every active CCEO and Programme Lead;
// with no district, the first 50 staff. By name throughout.
func (s *Service) EligibleStaff(ctx context.Context, district string) ([]Staff, error) {
	const pick = `SELECT u.id, COALESCE(u.name, 'None'), COALESCE(u.active_role, 'None')
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE sp.deleted_at IS NULL AND `
	if district == "" {
		return s.staff(ctx, pick+`TRUE ORDER BY u.name LIMIT 50`)
	}
	staff, err := s.staff(ctx, pick+`sp.id IN (SELECT a.staff_id FROM staff_school_assignment a WHERE a.school_id IN (
  SELECT s.id FROM school s WHERE s.deleted_at IS NULL AND s.district_id = $1)) ORDER BY u.name`, district)
	if err != nil || len(staff) > 0 {
		return staff, err
	}
	staff, err = s.staff(ctx, pick+`sp.id IN (SELECT a.staff_id FROM staff_school_assignment a WHERE a.school_id IN (
  SELECT s.id FROM school s WHERE s.deleted_at IS NULL AND s.region_id = (SELECT d.region_id FROM district d WHERE d.id = $1))) ORDER BY u.name`, district)
	if err != nil || len(staff) > 0 {
		return staff, err
	}
	return s.staff(ctx, pick+`u.is_active AND u.roles && ARRAY['CCEO', 'Program Lead', 'ProgramLead']::varchar[] ORDER BY u.name`)
}

func (s *Service) staff(ctx context.Context, sql string, args ...any) ([]Staff, error) {
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("clustercreate: reading the eligible staff: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (Staff, error) {
		var sp Staff
		return sp, r.Scan(&sp.UserID, &sp.Name, &sp.Role)
	})
}
