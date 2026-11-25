package clustermembership

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The cluster's Add Schools drawer (/clusters/<id>/bulk-assign-drawer) and
// its save: cluster_views.cluster_bulk_assign_drawer_view.

// Cluster is the cluster as the drawer and save read it.
type Cluster struct {
	ID, Name, Owner, DistrictID, DistrictName string
	// Served are the districts whose schools the drawer offers; nil offers
	// the reader's whole direct portfolio (the reader owns the cluster).
	Served []string
}

// Candidate is a school the drawer offers.
type Candidate struct{ ID, Code, Name string }

func text(t string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: t}}
}

func field(f *screensv1.DrawerField) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: f}}
}

// drawerFor is partials/clusters/bulk_assign_drawer.html as the feed reads
// it. The feed's closing line also carried the tick counter's labels with no
// numbers ("ticked · enrolled · average SSA —"); Go keeps the sentence only.
func drawerFor(c Cluster, schools []Candidate) *screensv1.PageDrawer {
	title := "Add schools to " + c.Name
	if len(schools) == 0 {
		return &screensv1.PageDrawer{Title: title, HasRequired: true, CancelLabel: "Cancel", Items: []*screensv1.DrawerItem{
			{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Tone: "info",
				Text: "All schools are clustered Every candidate school in " + c.DistrictName + " district already belongs to a cluster."}}},
		}}
	}
	options := make([]*screensv1.DrawerOption, 0, len(schools))
	for _, s := range schools {
		options = append(options, &screensv1.DrawerOption{Value: s.ID, Label: s.Name, Detail: s.Code})
	}
	return &screensv1.PageDrawer{Title: title, HasRequired: true, SubmitLabel: "Save schools to cluster", CancelLabel: "Cancel", CanSubmit: true,
		Items: []*screensv1.DrawerItem{
			field(&screensv1.DrawerField{Label: "Search schools", Kind: "text", Placeholder: "Search by name or ID"}),
			field(&screensv1.DrawerField{Label: "Select all visible schools", Kind: "checkbox"}),
			field(&screensv1.DrawerField{Name: "school_ids", Kind: "checklist", Options: options}),
			text("Tick the schools to add, then save."),
		}}
}

func addedMessage(n int, cluster string, skipped []string) string {
	msg := fmt.Sprintf("Successfully assigned %d schools to %s.", n, cluster)
	if len(skipped) > 0 {
		msg += fmt.Sprintf(" Skipped %d already-clustered: %s.", len(skipped), strings.Join(skipped, ", "))
	}
	return msg
}

// open is the view's gates: the planning page and a cluster the reader may
// read (an acting appointment answers as its holder: handed on).
func (s *Service) open(ctx context.Context, p auth.Principal, id string) (*Cluster, schooldirectory.Scope, error) {
	var scope schooldirectory.Scope
	if p.InActingAppointment {
		return nil, scope, ErrHandOn
	}
	access, err := s.access.ProfileAccess(ctx, p, strings.TrimSpace(id))
	if err != nil {
		return nil, scope, err
	}
	if !access.Readable || !access.AddSchools {
		return nil, scope, ErrHandOn
	}
	if scope, err = schooldirectory.ResolveScope(ctx, s.db, p, s.now()); err != nil {
		return nil, scope, err
	}
	var c Cluster
	var owner, district, districtName *string
	err = s.db.QueryRow(ctx, `SELECT c.id, c.name, c.responsible_staff_id, c.district_id, d.name
FROM cluster c LEFT JOIN district d ON d.id = c.district_id WHERE c.id = $1 AND c.deleted_at IS NULL`, strings.TrimSpace(id)).
		Scan(&c.ID, &c.Name, &owner, &district, &districtName)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, scope, ErrHandOn
	}
	if err != nil {
		return nil, scope, fmt.Errorf("clustermembership: reading the cluster: %w", err)
	}
	c.Owner, c.DistrictID, c.DistrictName = deref(owner), deref(district), deref(districtName)
	if c.Owner != "" && (c.Owner == p.UserID || c.Owner == p.StaffProfileID) && !scope.CountryScope && !scope.SummaryOnly {
		return &c, scope, nil
	}
	today := s.now().In(s.kampala).Format(time.DateOnly)
	rows, err := s.db.Query(ctx, `SELECT district_id FROM cluster_service_district
WHERE cluster_id = $1 AND active AND effective_from <= $2::date AND (effective_to IS NULL OR effective_to >= $2::date)`, c.ID, today)
	if err != nil {
		return nil, scope, fmt.Errorf("clustermembership: reading the served districts: %w", err)
	}
	served, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, scope, err
	}
	c.Served = []string{}
	if c.DistrictID != "" {
		c.Served = append(c.Served, c.DistrictID)
	}
	c.Served = append(c.Served, served...)
	return &c, scope, nil
}

// operatingStatuses are OPERATING_STATUSES.
var operatingStatuses = []string{"active", "reopened"}

func deref(v *string) string {
	if v == nil {
		return ""
	}
	return *v
}

// portfolio is the direct portfolio within the cluster's served districts,
// numbering its parameters through arg.
func portfolio(scope schooldirectory.Scope, c *Cluster, arg func(any) string) string {
	where := schooldirectory.DirectPortfolio(scope, arg) + " AND s.deleted_at IS NULL"
	if c.Served != nil {
		where += " AND s.district_id = ANY(" + arg(c.Served) + ")"
	}
	return where
}

func numbered(args *[]any) func(any) string {
	return func(v any) string { *args = append(*args, v); return "$" + strconv.Itoa(len(*args)) }
}

// Drawer is the drawer's GET.
func (s *Service) Drawer(ctx context.Context, p auth.Principal, clusterID string) (*screensv1.PageDrawer, error) {
	c, scope, err := s.open(ctx, p, clusterID)
	if err != nil {
		return nil, err
	}
	var args []any
	where := portfolio(scope, c, numbered(&args))
	if scope.CountryScope || scope.SummaryOnly {
		// A country or summary reader's pool is every operating unclustered
		// school in the cluster's served districts (active_schools()); what
		// they may save is still their direct portfolio.
		args = nil
		arg := numbered(&args)
		where = "s.deleted_at IS NULL AND s.operational_status = ANY(" + arg(operatingStatuses) + ")"
		if c.Served != nil {
			where += " AND s.district_id = ANY(" + arg(c.Served) + ")"
		}
	}
	rows, err := s.db.Query(ctx, `SELECT s.id, COALESCE(s.school_id, ''), s.name FROM school s
LEFT JOIN sub_county sc ON sc.id = s.sub_county_id
WHERE `+where+` AND s.cluster_status = 'unclustered' ORDER BY sc.name, s.name`, args...)
	if err != nil {
		return nil, fmt.Errorf("clustermembership: reading the unclustered schools: %w", err)
	}
	schools, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (Candidate, error) {
		var x Candidate
		return x, r.Scan(&x.ID, &x.Code, &x.Name)
	})
	if err != nil {
		return nil, err
	}
	return drawerFor(*c, schools), nil
}

type ticked struct {
	School
	Code, ClusterID, Status string
}

// AddSchools is the drawer's POST: each ticked school of the reader's in the
// served districts joins the cluster through assign_school; one already
// clustered is skipped. A refusal stops the press there, as the existing
// save's exception does, and the schools before it stay in the cluster.
func (s *Service) AddSchools(ctx context.Context, p auth.Principal, clusterID string, schoolIDs []string, origin activities.Origin) (string, string, error) {
	c, scope, err := s.open(ctx, p, clusterID)
	if err != nil {
		return "", "", err
	}
	assigned, skipped := 0, []string{}
	for _, id := range schoolIDs {
		school, found, err := s.ticked(ctx, scope, c, id)
		if err != nil {
			return "", "", err
		}
		if !found {
			continue
		}
		if school.ClusterID != "" || school.Status == "clustered" {
			skipped = append(skipped, school.Name)
			continue
		}
		refusal, err := s.assignSchool(ctx, p, scope, c, school, "", origin)
		if err != nil || refusal != "" {
			return "", refusal, err
		}
		assigned++
	}
	return addedMessage(assigned, c.Name, skipped), "", nil
}

func (s *Service) ticked(ctx context.Context, scope schooldirectory.Scope, c *Cluster, id string) (ticked, bool, error) {
	var args []any
	arg := numbered(&args)
	where := portfolio(scope, c, arg)
	var t ticked
	var code, cluster, status, owner *string
	err := s.db.QueryRow(ctx, `SELECT s.id, s.name, s.school_id, s.cluster_id, s.cluster_status, s.account_owner_id
FROM school s WHERE `+where+` AND s.id = `+arg(id)+` ORDER BY s.created_at DESC LIMIT 1`, args...).
		Scan(&t.ID, &t.Name, &code, &cluster, &status, &owner)
	if errors.Is(err, pgx.ErrNoRows) {
		return t, false, nil
	}
	if err != nil {
		return t, false, fmt.Errorf("clustermembership: reading a ticked school: %w", err)
	}
	t.Code, t.ClusterID, t.Status, t.AccountOwner = deref(code), deref(cluster), deref(status), deref(owner)
	return t, true, nil
}

// assignSchool is apps.clusters.services.assign_school: the direct-portfolio
// school with the ticked school's School ID (newest first) and a cluster the
// reader plans in directly, then the membership service. A school with no
// School ID is the ticked school itself: the existing lookup by an empty ID
// matches any of the reader's schools without one (docs/migration/189).
func (s *Service) assignSchool(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, c *Cluster, t ticked, reason string, origin activities.Origin) (string, error) {
	var args []any
	arg := numbered(&args)
	school := t.School
	if t.Code != "" {
		var owner *string
		err := s.db.QueryRow(ctx, `SELECT s.id, s.name, s.account_owner_id FROM school s
WHERE `+schooldirectory.DirectPortfolio(scope, arg)+` AND s.deleted_at IS NULL AND s.school_id = `+arg(t.Code)+`
ORDER BY s.created_at DESC LIMIT 1`, args...).Scan(&school.ID, &school.Name, &owner)
		if errors.Is(err, pgx.ErrNoRows) {
			return notInScope, nil
		}
		if err != nil {
			return "", fmt.Errorf("clustermembership: reading the school by its School ID: %w", err)
		}
		school.AccountOwner = deref(owner)
	}
	args = nil
	where, err := clusterpage.ScopedClusters(ctx, s.db, scope, true, arg)
	if err != nil {
		return "", err
	}
	var writable bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cluster c WHERE c.deleted_at IS NULL AND `+where+` AND c.id = `+arg(c.ID)+`)`, args...).Scan(&writable); err != nil {
		return "", fmt.Errorf("clustermembership: reading whether the cluster is the reader's: %w", err)
	}
	if !writable {
		return oversightOnly, nil
	}
	_, refusal, err := s.Join(ctx, p, school, c.ID, c.Name, reason, origin)
	return refusal, err
}
