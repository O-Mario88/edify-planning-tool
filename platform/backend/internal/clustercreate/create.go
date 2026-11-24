// Package clustercreate is creating a cluster in Go with Django absent: the
// Create cluster drawer (cluster_views.create_cluster_drawer_view), its staff
// list refill (eligible_staff_options_view) and its save (create_cluster_view
// and apps.clusters.services.create_cluster).
package clustercreate

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrHandOn says the existing application keeps this request.
var ErrHandOn = errors.New("clustercreate: handed on")

const (
	accessDenied = "Access Denied: You do not have permission to create clusters."
	failed       = "Failed to create cluster: "
	notFound     = "Not found."
)

// NewClusterSchool puts a school into the cluster just made
// (internal/clustermembership.Service.IntoNewCluster).
type NewClusterSchool interface {
	IntoNewCluster(ctx context.Context, p auth.Principal, clusterID, schoolID string, origin activities.Origin) (string, string, error)
}

// Service draws and saves the create form.
type Service struct {
	db      *pgxpool.Pool
	school  NewClusterSchool
	logger  *slog.Logger
	now     func() time.Time
	kampala *time.Location
}

// New makes the service.
func New(db *pgxpool.Pool, school NewClusterSchool, logger *slog.Logger, now func() time.Time) *Service {
	kampala, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		kampala = time.FixedZone("EAT", 3*60*60)
	}
	return &Service{db: db, school: school, logger: logger, now: now, kampala: kampala}
}

// Form is what create_cluster_view reads from the post.
type Form struct {
	Name, Region, District  string
	SubCounties             []string
	Type                    string
	LeaderName, LeaderPhone *string
	Owner, AssignSchool     string
}

func optional(v string) *string {
	if v = strings.TrimSpace(v); v == "" {
		return nil
	}
	return &v
}

// readForm is the view's reads: the trimmed fields, the ticked sub-counties
// (or the single sub_county_id), the type ("mixed" when not posted), and the
// school to put in the new cluster (the drawer's own query carries it).
func readForm(values map[string]string, query url.Values) Form {
	f := Form{
		Name: strings.TrimSpace(values["name"]), Region: strings.TrimSpace(values["region_id"]),
		District: strings.TrimSpace(values["district_id"]), Type: "mixed",
		LeaderName: optional(values["cluster_leader_name"]), LeaderPhone: optional(values["cluster_leader_phone"]),
		Owner: strings.TrimSpace(values["responsible_staff_id"]), AssignSchool: strings.TrimSpace(values["assign_school_id"]),
	}
	for _, id := range strings.Split(values["sub_county_ids"], ",") {
		if id = strings.TrimSpace(id); id != "" {
			f.SubCounties = append(f.SubCounties, id)
		}
	}
	if len(f.SubCounties) == 0 && values["sub_county_id"] != "" {
		f.SubCounties = []string{values["sub_county_id"]}
	}
	if t, posted := values["cluster_type"]; posted {
		f.Type = strings.TrimSpace(t)
	}
	if f.AssignSchool == "" {
		f.AssignSchool = strings.TrimSpace(query.Get("assign_school_id"))
	}
	return f
}

func missing(f Form) string {
	switch {
	case f.Name != "" && f.District != "" && len(f.SubCounties) > 0:
		return ""
	case len(f.SubCounties) == 0:
		return failed + "select at least one sub-county."
	}
	return failed + "missing fields."
}

func distinct(ids []string) []string {
	out := []string{}
	for _, id := range ids {
		if !contains(out, id) {
			out = append(out, id)
		}
	}
	return out
}

func contains(ids []string, id string) bool {
	for _, x := range ids {
		if x == id {
			return true
		}
	}
	return false
}

func createdMessage(name, schoolName, clusterName string) string {
	msg := fmt.Sprintf("Successfully created cluster '%s'.", name)
	if schoolName != "" {
		msg += fmt.Sprintf(" School '%s' has been assigned to the new cluster '%s'.", schoolName, clusterName)
	}
	return msg
}

// gate is the views' gates: the planning page for the drawer, and an acting
// appointment (which answers as its holder) handed on.
func gate(p auth.Principal) error {
	if p.InActingAppointment || !clusterpage.RoleDoors(p.ActiveRole).AddSchools {
		return ErrHandOn
	}
	return nil
}

// Create is create_cluster_view's POST: the answer's message, or the
// refusal in the view's words.
func (s *Service) Create(ctx context.Context, p auth.Principal, values map[string]string, query url.Values, origin activities.Origin) (string, string, error) {
	if err := gate(p); err != nil {
		return "", "", err
	}
	if !rbac.Grants(p.ActiveRole, "cluster.assign") {
		return "", accessDenied, nil
	}
	f := readForm(values, query)
	if refusal := missing(f); refusal != "" {
		return "", refusal, nil
	}
	var region *string
	err := s.db.QueryRow(ctx, `SELECT region_id FROM district WHERE id = $1`, f.District).Scan(&region)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", notFound, nil
	}
	if err != nil {
		return "", "", fmt.Errorf("clustercreate: reading the district: %w", err)
	}
	if f.Region == "" && region != nil {
		f.Region = *region
	}
	if f.Owner == "" {
		if f.Owner, err = s.defaultOwner(ctx, p); err != nil {
			return "", "", err
		}
	}
	refusal, err := s.check(ctx, p, &f, region)
	if err != nil || refusal != "" {
		return "", prefixed(refusal), err
	}
	id := cuid.New()
	if err := s.write(ctx, id, f); err != nil {
		return "", "", err
	}
	if f.AssignSchool == "" {
		return createdMessage(f.Name, "", ""), "", nil
	}
	// The view puts the school in after the cluster is made, and a failure
	// there leaves the cluster made: its answer is the creation's alone.
	schoolName, refusal, err := s.school.IntoNewCluster(ctx, p, id, f.AssignSchool, origin)
	if err != nil || refusal != "" {
		if s.logger != nil {
			s.logger.Warn("clustercreate: the school was not put in the new cluster", "cluster", id, "refusal", refusal, "err", err)
		}
		return createdMessage(f.Name, "", ""), "", nil
	}
	return createdMessage(f.Name, schoolName, f.Name), "", nil
}

// defaultOwner is _default_cluster_owner: the creator, unless a country or
// summary reader, who leaves it unowned.
func (s *Service) defaultOwner(ctx context.Context, p auth.Principal) (string, error) {
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return "", err
	}
	if scope.CountryScope || scope.SummaryOnly {
		return "", nil
	}
	return p.UserID, nil
}

func prefixed(reason string) string {
	if reason == "" {
		return ""
	}
	return failed + reason
}

// FromSchool is create_cluster as a school's Add to Cluster calls it: the
// school's region, district and sub-county, filed under owner (or nobody).
// It answers the new cluster's id, or the service's refusal in its own words.
func (s *Service) FromSchool(ctx context.Context, p auth.Principal, name, region, district, subCounty, owner string) (string, string, error) {
	f := Form{Name: strings.TrimSpace(name), Region: region, District: district, Type: "mixed", Owner: owner}
	if subCounty != "" {
		f.SubCounties = []string{subCounty}
	}
	var districtRegion *string
	err := s.db.QueryRow(ctx, `SELECT region_id FROM district WHERE id = $1`, district).Scan(&districtRegion)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", "district does not belong to region", nil
	}
	if err != nil {
		return "", "", fmt.Errorf("clustercreate: reading the district: %w", err)
	}
	refusal, err := s.check(ctx, p, &f, districtRegion)
	if err != nil || refusal != "" {
		return "", refusal, err
	}
	id := cuid.New()
	return id, "", s.write(ctx, id, f)
}

// check is create_cluster's validation, in its order, in its words.
func (s *Service) check(ctx context.Context, p auth.Principal, f *Form, region *string) (string, error) {
	if region == nil || *region != f.Region {
		return "district does not belong to region", nil
	}
	allowed, err := s.creationDistricts(ctx, p.StaffProfileID)
	if err != nil {
		return "", err
	}
	if !containsDistrict(allowed, f.District) {
		return "District outside your scope", nil
	}
	f.SubCounties = distinct(f.SubCounties)
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(district_id, '') FROM sub_county WHERE id = ANY($1)`, f.SubCounties)
	if err != nil {
		return "", fmt.Errorf("clustercreate: reading the sub-counties: %w", err)
	}
	found, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) ([2]string, error) {
		var x [2]string
		return x, r.Scan(&x[0], &x[1])
	})
	if err != nil {
		return "", err
	}
	if len(found) != len(f.SubCounties) {
		return "Unknown sub-county", nil
	}
	for _, sc := range found {
		if sc[1] != f.District {
			return "sub-county does not belong to district", nil
		}
	}
	var taken bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cluster WHERE district_id = $1 AND UPPER(name) = UPPER($2) AND deleted_at IS NULL)`,
		f.District, f.Name).Scan(&taken); err != nil {
		return "", fmt.Errorf("clustercreate: reading the district's cluster names: %w", err)
	}
	if taken {
		return "A cluster with this name already exists in this district.", nil
	}
	return "", nil
}

func containsDistrict(ds []District, id string) bool {
	for _, d := range ds {
		if d.ID == id {
			return true
		}
	}
	return false
}

func (s *Service) write(ctx context.Context, id string, f Form) error {
	now := s.now()
	rowIDs := make([]string, len(f.SubCounties))
	for i := range rowIDs {
		rowIDs[i] = cuid.New()
	}
	var owner *string
	if f.Owner != "" {
		owner = &f.Owner
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("clustercreate: opening the save: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `SELECT gateway_cluster_create.create($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)`,
		id, f.Name, f.Region, f.District, f.SubCounties, rowIDs, f.Type, owner, f.LeaderName, f.LeaderPhone,
		now, now.In(s.kampala).Format(time.DateOnly), cuid.New()); err != nil {
		return fmt.Errorf("clustercreate: creating the cluster: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("clustercreate: committing the cluster: %w", err)
	}
	return nil
}
