package clustermembership

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ClusterMaker makes the new cluster a school's drawer names
// (internal/clustercreate.Service.FromSchool).
type ClusterMaker interface {
	FromSchool(ctx context.Context, p auth.Principal, name, region, district, subCounty, owner string) (string, string, error)
}

// WithClusterMaker lets the school's drawer create a cluster.
func (s *Service) WithClusterMaker(m ClusterMaker) *Service {
	s.maker = m
	return s
}

const (
	schoolNotFound = "School not found."
	noAssignRight  = "You do not have permission to assign clusters."
	missingDetails = "This school needs a School ID, Name, and District before it can be clustered."
)

type schoolFlow struct {
	scope                   schooldirectory.Scope
	sc                      schoolFacts
	ownerProfile, ownerName string
	clusters                []ownerCluster
	current                 *ownerCluster
	isChange                bool
	st                      formState
}

// openSchool is add_to_cluster_flow up to its POST: the gates, then what the
// drawer lists. A refusal is the drawer's error page.
func (s *Service) openSchool(ctx context.Context, p auth.Principal, schoolID string) (*schoolFlow, string, error) {
	if p.InActingAppointment {
		return nil, "", ErrHandOn
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, "", err
	}
	if scope.CountryScope || scope.SummaryOnly {
		return nil, "", ErrHandOn
	}
	var args []any
	arg := numbered(&args)
	var readable bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM school s WHERE `+schooldirectory.ReadScope(scope, arg)+
		` AND s.deleted_at IS NULL AND s.id = `+arg(schoolID)+`)`, args...).Scan(&readable); err != nil {
		return nil, "", fmt.Errorf("clustermembership: reading the school's scope: %w", err)
	}
	if !readable {
		return nil, schoolNotFound, nil
	}
	if !rbac.Grants(p.ActiveRole, "cluster.assign") {
		return nil, noAssignRight, nil
	}
	args = nil
	var mine bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM school s WHERE `+schooldirectory.DirectPortfolio(scope, arg)+
		` AND s.id = `+arg(schoolID)+`)`, args...).Scan(&mine); err != nil {
		return nil, "", fmt.Errorf("clustermembership: reading the reader's portfolio: %w", err)
	}
	if !mine {
		return nil, oversightOnly, nil
	}
	f := &schoolFlow{scope: scope}
	if err := s.readSchool(ctx, schoolID, &f.sc); err != nil {
		return nil, "", err
	}
	if f.ownerProfile, f.ownerName, err = s.responsibleStaff(ctx, f.sc); err != nil {
		return nil, "", err
	}
	if err := s.readClusters(ctx, f); err != nil {
		return nil, "", err
	}
	return f, "", nil
}

func (s *Service) readSchool(ctx context.Context, id string, sc *schoolFacts) error {
	var code, district, districtName, sub, subName, region, cluster, status, owner *string
	err := s.db.QueryRow(ctx, `SELECT s.id, s.school_id, COALESCE(s.name, ''), s.district_id, d.name, s.sub_county_id, sc.name,
  s.region_id, s.cluster_id, s.cluster_status, s.account_owner_id
FROM school s LEFT JOIN district d ON d.id = s.district_id LEFT JOIN sub_county sc ON sc.id = s.sub_county_id
WHERE s.id = $1`, id).Scan(&sc.ID, &code, &sc.Name, &district, &districtName, &sub, &subName, &region, &cluster, &status, &owner)
	if err != nil {
		return fmt.Errorf("clustermembership: reading the school: %w", err)
	}
	sc.Code, sc.DistrictID, sc.District, sc.SubCountyID, sc.SubCounty = deref(code), deref(district), deref(districtName), deref(sub), deref(subName)
	sc.RegionID, sc.ClusterID, sc.ClusterStatus, sc.AccountOwner = deref(region), deref(cluster), deref(status), deref(owner)
	return nil
}

// responsibleStaff is the flow's get_responsible_staff: the account owner's
// live, active profile, else the one active profile holding the school.
func (s *Service) responsibleStaff(ctx context.Context, sc schoolFacts) (string, string, error) {
	var id, name string
	if sc.AccountOwner != "" {
		err := s.db.QueryRow(ctx, `SELECT sp.id, COALESCE(u.name, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE (sp.id = $1 OR sp.user_id = $1) AND sp.deleted_at IS NULL AND u.is_active ORDER BY sp.id LIMIT 1`, sc.AccountOwner).Scan(&id, &name)
		if err == nil {
			return id, name, nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return "", "", fmt.Errorf("clustermembership: reading the school's owner: %w", err)
		}
	}
	rows, err := s.db.Query(ctx, `SELECT sp.id, COALESCE(u.name, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.id IN (SELECT a.staff_id FROM staff_school_assignment a WHERE a.school_id = $1) AND sp.deleted_at IS NULL AND u.is_active
ORDER BY u.name, sp.id LIMIT 2`, sc.ID)
	if err != nil {
		return "", "", fmt.Errorf("clustermembership: reading the school's staff: %w", err)
	}
	found, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) ([2]string, error) {
		var x [2]string
		return x, r.Scan(&x[0], &x[1])
	})
	if err != nil || len(found) != 1 {
		return "", "", err
	}
	return found[0][0], found[0][1], nil
}

// schoolOwnerIDs is eligibility.school_owner_ids.
func (s *Service) schoolOwnerIDs(ctx context.Context, sc schoolFacts) ([]string, error) {
	owner := strings.TrimSpace(sc.AccountOwner)
	if owner == "" {
		rows, err := s.db.Query(ctx, `SELECT staff_id FROM staff_school_assignment WHERE school_id = $1 LIMIT 2`, sc.ID)
		if err != nil {
			return nil, fmt.Errorf("clustermembership: reading the school's staff: %w", err)
		}
		assigned, err := pgx.CollectRows(rows, pgx.RowTo[string])
		if err != nil || len(assigned) != 1 {
			return nil, err
		}
		owner = assigned[0]
	}
	ids := []string{owner}
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(user_id, '') FROM staff_profile WHERE deleted_at IS NULL AND (id = $1 OR user_id = $1)`, owner)
	if err != nil {
		return nil, fmt.Errorf("clustermembership: reading an owner's ids: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var profile, user string
		if err := rows.Scan(&profile, &user); err != nil {
			return nil, err
		}
		for _, id := range []string{profile, user} {
			if id != "" && !slices.Contains(ids, id) {
				ids = append(ids, id)
			}
		}
	}
	return ids, rows.Err()
}

// readClusters lists the owner's active clusters, marks and sorts them, and
// fills the form's state.
func (s *Service) readClusters(ctx context.Context, f *schoolFlow) error {
	sc := f.sc
	owners, err := s.schoolOwnerIDs(ctx, sc)
	if err != nil {
		return err
	}
	switch {
	case sc.DistrictID == "":
		f.st.ineligible = "This school has no district, so no cluster can be matched to it. Add the district on the school profile first."
	case len(owners) == 0:
		f.st.ineligible = "This school has no assigned staff owner, and a cluster belongs to the person responsible for its schools. Assign an owner first."
	}
	if sc.ClusterID != "" {
		var c ownerCluster
		var district *string
		err := s.db.QueryRow(ctx, `SELECT c.id, c.name, COALESCE(c.district_id, ''), d.name FROM cluster c LEFT JOIN district d ON d.id = c.district_id
WHERE c.id = $1 AND c.deleted_at IS NULL`, sc.ClusterID).Scan(&c.ID, &c.Name, &c.DistrictID, &district)
		if err == nil {
			c.District = deref(district)
			f.current = &c
		} else if !errors.Is(err, pgx.ErrNoRows) {
			return fmt.Errorf("clustermembership: reading the current cluster: %w", err)
		}
	}
	f.isChange = f.current != nil || sc.ClusterStatus == "clustered"
	if len(owners) > 0 {
		rows, err := s.db.Query(ctx, `SELECT c.id, c.name, COALESCE(c.district_id, ''), COALESCE(d.name, ''),
  (SELECT count(DISTINCT a.id) FROM school_cluster_assignment a WHERE a.cluster_id = c.id)
FROM cluster c LEFT JOIN district d ON d.id = c.district_id
WHERE c.responsible_staff_id = ANY($1) AND c.deleted_at IS NULL AND c.status = 'active' ORDER BY c.name`, owners)
		if err != nil {
			return fmt.Errorf("clustermembership: reading the owner's clusters: %w", err)
		}
		if f.clusters, err = pgx.CollectRows(rows, func(r pgx.CollectableRow) (ownerCluster, error) {
			var c ownerCluster
			return c, r.Scan(&c.ID, &c.Name, &c.DistrictID, &c.District, &c.Schools)
		}); err != nil {
			return err
		}
	}
	served, err := s.servedDistricts(ctx, f)
	if err != nil {
		return err
	}
	relationship := func(c ownerCluster) bool {
		if sc.DistrictID == "" {
			return false
		}
		return c.DistrictID == sc.DistrictID || slices.Contains(served[c.ID], sc.DistrictID)
	}
	selectable := []string{}
	for i := range f.clusters {
		c := &f.clusters[i]
		c.Serves = relationship(*c)
		c.Cross = sc.DistrictID != "" && c.DistrictID != sc.DistrictID
		c.Current = f.current != nil && c.ID == f.current.ID
		if !c.Current {
			selectable = append(selectable, c.ID)
		}
	}
	sortOwnerClusters(f.clusters)
	f.st.selectable, f.st.isChange = len(selectable) > 0, f.isChange
	if f.current != nil {
		f.st.current = f.current.Name
	}
	if sc.SubCountyID != "" && sc.DistrictID != "" {
		var covering string
		err := s.db.QueryRow(ctx, `SELECT c.id FROM cluster c WHERE c.district_id = $1 AND c.deleted_at IS NULL AND c.status = 'active'
  AND (c.sub_county_id = $2 OR EXISTS (SELECT 1 FROM cluster_sub_county cs WHERE cs.cluster_id = c.id AND cs.sub_county_id = $2))
ORDER BY c.name, c.id LIMIT 1`, sc.DistrictID, sc.SubCountyID).Scan(&covering)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return fmt.Errorf("clustermembership: reading the covering cluster: %w", err)
		}
		if slices.Contains(selectable, covering) {
			f.st.preselected = covering
		}
	}
	return nil
}

// servedDistricts is service_districts_by_cluster over the listed clusters
// and the current one: the districts each serves today.
func (s *Service) servedDistricts(ctx context.Context, f *schoolFlow) (map[string][]string, error) {
	ids := []string{}
	for _, c := range f.clusters {
		ids = append(ids, c.ID)
	}
	if f.current != nil {
		ids = append(ids, f.current.ID)
	}
	out := map[string][]string{}
	if len(ids) == 0 {
		return out, nil
	}
	today := s.now().In(s.kampala).Format(time.DateOnly)
	rows, err := s.db.Query(ctx, `SELECT cluster_id, district_id FROM cluster_service_district
WHERE cluster_id = ANY($1) AND active AND effective_from <= $2::date AND (effective_to IS NULL OR effective_to >= $2::date)`, ids, today)
	if err != nil {
		return nil, fmt.Errorf("clustermembership: reading the served districts: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var cluster, district string
		if err := rows.Scan(&cluster, &district); err != nil {
			return nil, err
		}
		out[cluster] = append(out[cluster], district)
	}
	return out, rows.Err()
}

func missingSchoolDetails(sc schoolFacts) bool {
	return sc.Code == "" || sc.Name == "" || sc.DistrictID == ""
}

// SchoolForm is the drawer's GET as the feed reads it.
func (s *Service) SchoolForm(ctx context.Context, p auth.Principal, schoolID string) (*screensv1.AddToClusterForm, error) {
	f, refusal, err := s.openSchool(ctx, p, strings.TrimSpace(schoolID))
	if err != nil {
		return nil, err
	}
	if refusal != "" {
		return &screensv1.AddToClusterForm{Refused: refusal}, nil
	}
	if missingSchoolDetails(f.sc) {
		f.st.errorText = missingDetails
	}
	return schoolForm(f.sc, f.ownerName, f.clusters, f.st), nil
}

func longEnough(reason string) bool { return utf8.RuneCountInString(reason) >= 5 }

// SchoolSave is the drawer's POST: the school in the chosen cluster, or in
// a new one, or the drawer's error in the flow's words.
func (s *Service) SchoolSave(ctx context.Context, p auth.Principal, req *screensv1.AddToClusterRequest, origin activities.Origin) (*screensv1.SchoolActionResult, error) {
	f, refusal, err := s.openSchool(ctx, p, strings.TrimSpace(req.GetSchoolId()))
	if err != nil {
		return nil, err
	}
	if refusal != "" {
		return &screensv1.SchoolActionResult{Refused: refusal}, nil
	}
	sc := f.sc
	if missingSchoolDetails(sc) {
		return &screensv1.SchoolActionResult{Error: missingDetails}, nil
	}
	clusterID, newName := strings.TrimSpace(req.GetClusterId()), strings.TrimSpace(req.GetNewClusterName())
	action := strings.ToLower(strings.TrimSpace(req.GetActionType()))
	if action != "existing" && action != "new" {
		action = "existing"
		if newName != "" && clusterID == "" {
			action = "new"
		}
	}
	reason := strings.TrimSpace(req.GetReason())
	if f.isChange {
		if !req.GetConfirmChange() {
			current := "its cluster"
			if f.current != nil {
				current = f.current.Name
			}
			return &screensv1.SchoolActionResult{Error: "Confirm that " + sc.Name + " should leave " + current + "."}, nil
		}
		if !longEnough(reason) {
			return &screensv1.SchoolActionResult{Error: "Give the reason for changing the cluster."}, nil
		}
	}
	var target Cluster
	if action == "existing" {
		i := slices.IndexFunc(f.clusters, func(c ownerCluster) bool { return c.ID == clusterID })
		if i < 0 {
			return &screensv1.SchoolActionResult{Error: "Select one of the clusters belonging to this school's owner."}, nil
		}
		c := f.clusters[i]
		switch {
		case c.Current:
			return &screensv1.SchoolActionResult{Error: sc.Name + " is already in " + c.Name + "."}, nil
		case c.Cross && !longEnough(reason):
			return &screensv1.SchoolActionResult{Error: c.Name + " is in " + c.District + ". Give the reason this school joins a cluster across the district border."}, nil
		}
		target = Cluster{ID: c.ID, Name: c.Name}
	} else {
		if newName == "" {
			return &screensv1.SchoolActionResult{Error: "Enter a cluster name to continue."}, nil
		}
		if s.maker == nil {
			return nil, ErrHandOn
		}
		id, refusal, err := s.maker.FromSchool(ctx, p, newName, sc.RegionID, sc.DistrictID, sc.SubCountyID, f.ownerProfile)
		if err != nil {
			return nil, err
		}
		if refusal != "" {
			return &screensv1.SchoolActionResult{Error: refusal}, nil
		}
		target = Cluster{ID: id, Name: newName}
	}
	t := ticked{School: School{ID: sc.ID, Name: sc.Name, AccountOwner: sc.AccountOwner}, Code: sc.Code, ClusterID: sc.ClusterID, Status: sc.ClusterStatus}
	if refusal, err := s.assignSchool(ctx, p, f.scope, &target, t, reason, origin); err != nil || refusal != "" {
		if err != nil {
			return nil, err
		}
		return &screensv1.SchoolActionResult{Error: refusal}, nil
	}
	verb := "added to"
	if f.isChange {
		verb = "moved to"
	}
	return &screensv1.SchoolActionResult{Saved: true, Message: sc.Name + " " + verb + " " + target.Name + "."}, nil
}
