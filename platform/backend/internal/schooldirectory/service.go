package schooldirectory

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	commonv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/common/v1"
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
)

// pageSize is the directory's page: the app never asks for another.
const pageSize = 50

// ErrForbidden is the existing page gate's refusal, in its words.
var ErrForbidden = errors.New("Your active role does not have permission to view this page.")

// Service builds the School Directory.
type Service struct {
	db  Querier
	now func() time.Time
}

// NewService returns the directory over db.
func NewService(db Querier, now func() time.Time) *Service {
	if now == nil {
		now = time.Now
	}
	return &Service{db: db, now: now}
}

// operationalFY is core.fy.get_operational_fy for now (read in UTC, as the
// existing code reads "now"): the year the FY ends, October to September.
func operationalFY(now time.Time) int {
	now = now.UTC()
	if now.Month() >= time.October {
		return now.Year() + 1
	}
	return now.Year()
}

// fyOptions is core.fy.fy_options: FY 2025 to a year ahead, at least 2027.
func fyOptions(now time.Time) []string {
	last := max(operationalFY(now)+1, 2027)
	out := []string{}
	for y := 2025; y <= last; y++ {
		out = append(out, strconv.Itoa(y))
	}
	return out
}

func (s *Service) count(ctx context.Context, b *sqlb, extra string) (int, error) {
	where := b.where()
	if extra != "" {
		where += " AND (" + extra + ")"
	}
	var n int
	err := s.db.QueryRow(ctx, `SELECT count(*) FROM school s WHERE `+where, b.args...).Scan(&n)
	return n, err
}

func (s *Service) exists(ctx context.Context, b *sqlb) (bool, error) {
	var found bool
	err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM school s WHERE `+b.where()+`)`, b.args...).Scan(&found)
	return found, err
}

// Build is school_directory_context and the app's feed of it, for a person
// working in their own role.
func (s *Service) Build(ctx context.Context, p auth.Principal, req *screensv1.GetSchoolDirectoryRequest) (*screensv1.GetSchoolDirectoryResponse, error) {
	if !rules.PageAccess[p.ActiveRole].Directory {
		return nil, ErrForbidden
	}
	now := s.now()
	d, err := s.listingFor(ctx, p, req, now)
	if err != nil {
		return nil, err
	}
	scope, base, unheld, canTake := d.scope, d.base, d.unheld, d.canTake
	gap, fy, options, tab := d.gap, d.fy, d.options, d.tab
	district, subCounty, schoolType, clusterStatus, projectStatus := d.district, d.subCounty, d.schoolType, d.clusterStatus, d.projectStatus
	gapCounts, tabCounts, listing := d.gapCounts, d.tabCounts, d.listing
	total := tabCounts[tab]

	order, err := s.order(ctx, scope, listing)
	if err != nil {
		return nil, err
	}
	pageNumber, totalPages := pick(req.GetPage(), total)
	rows, err := s.db.Query(ctx, `SELECT `+schoolColumns+` FROM school s LEFT JOIN district d ON d.id = s.district_id WHERE `+
		listing.where()+` ORDER BY `+order+fmt.Sprintf(` LIMIT %d OFFSET %d`, pageSize, (pageNumber-1)*pageSize), listing.args...)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading the page: %w", err)
	}
	page, err := pgx.CollectRows(rows, scanSchool)
	if err != nil {
		return nil, err
	}

	response := &screensv1.GetSchoolDirectoryResponse{
		ActiveTab: tab,
		Page: &commonv1.PageInfo{
			Page: int32(pageNumber), PageSize: pageSize, Total: int64(total), TotalPages: int32(totalPages),
		},
		CanAddSchool: (rbac.Grants(p.ActiveRole, "school.createSingle") || rbac.Grants(p.ActiveRole, "school.upload")) &&
			!scope.RegionScope,
		ReadOnly:          scope.RegionScope,
		MayTransferSchool: rbac.Grants(p.ActiveRole, "school.ownershipTransfer"),
		MayOpenProfile:    rules.PageAccess[p.ActiveRole].Profile,
	}
	for _, t := range rules.DirectoryTabs {
		response.Tabs = append(response.Tabs, &screensv1.DirectoryTab{Key: t[0], Label: t[1], Count: int32(tabCounts[t[0]])})
	}

	hasSchools, err := s.exists(ctx, base)
	if err != nil {
		return nil, err
	}
	if response.Filters, err = s.filters(ctx, base, hasSchools, filterState{
		fy: fy, fyOptions: options, district: district, subCounty: subCounty, schoolType: schoolType,
		clusterStatus: clusterStatus, projectStatus: projectStatus, gap: gap, gapCounts: gapCounts,
	}); err != nil {
		return nil, err
	}
	if canTake {
		n, err := s.count(ctx, unheld, "")
		if err != nil {
			return nil, err
		}
		response.Filters.Gaps = append(response.Filters.Gaps, &screensv1.DirectoryOption{
			Value: "unheld", Label: "Nobody Holds It (" + thousands(n) + ")",
		})
	}

	if response.Schools, err = s.rows(ctx, p, scope, page, fy, gap == "unheld" && canTake); err != nil {
		return nil, err
	}
	if len(page) == 0 {
		var anySchool bool
		if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM school WHERE deleted_at IS NULL)`).Scan(&anySchool); err != nil {
			return nil, err
		}
		switch {
		case !anySchool:
			response.EmptyState = "registry_empty"
		case !hasSchools:
			response.EmptyState = "scope_empty"
		default:
			response.EmptyState = "no_matches"
		}
	}
	if response.BulkClusters, err = bulkClusters(ctx, s.db, scope); err != nil {
		return nil, err
	}
	if response.BulkProjects, err = bulkProjects(ctx, s.db, p, scope); err != nil {
		return nil, err
	}
	return response, nil
}

// pick is Paginator.get_page: a page that is not a number is the first, one
// out of range the last.
func pick(requested int32, total int) (page, pages int) {
	pages = max((total+pageSize-1)/pageSize, 1)
	page = int(requested)
	if page == 0 {
		return 1, pages
	}
	if page < 1 || page > pages {
		return pages, pages
	}
	return page, pages
}

// order is the listing's order: by name, or for a country or region reader
// grouped by Program Lead and officer (owner_groups.owner_order).
func (s *Service) order(ctx context.Context, scope Scope, listing *sqlb) (string, error) {
	// The existing page orders by name alone, and 700 schools can share 52
	// names: the id settles a tie, so a school is on exactly one page.
	if !(scope.CountryScope || scope.RegionScope) {
		return "s.name, s.id", nil
	}
	ownerIDs, err := strings1(ctx, s.db, `SELECT DISTINCT s.account_owner_id FROM school s WHERE `+listing.where()+
		` AND s.account_owner_id IS NOT NULL AND s.account_owner_id <> ''`, listing.args...)
	if err != nil {
		return "", fmt.Errorf("schooldirectory: reading owners: %w", err)
	}
	directory, err := ownerDirectory(ctx, s.db, ownerIDs)
	if err != nil {
		return "", err
	}
	ranked := ownerRanking(ownerIDs, directory)
	ranks := listing.arg(ranked)
	return fmt.Sprintf("COALESCE(array_position(%s::varchar[], s.account_owner_id::varchar), %d), s.name, s.id", ranks, len(ranked)+1), nil
}

func (s *Service) gapCounts(ctx context.Context, filtered *sqlb, fy string) (map[string]int, error) {
	b := filtered.clone()
	columns := []string{}
	keys := []string{}
	for _, g := range gapConditions {
		columns = append(columns, "count(*) FILTER (WHERE "+g.condition+")")
		keys = append(keys, g.key)
	}
	columns = append(columns, "count(*) FILTER (WHERE "+anyGap()+")", "count(*) FILTER (WHERE "+b.noSSA(fy)+")")
	keys = append(keys, "any", "no_ssa")
	values := make([]int, len(keys))
	targets := make([]any, len(keys))
	for i := range values {
		targets[i] = &values[i]
	}
	if err := s.db.QueryRow(ctx, `SELECT `+strings.Join(columns, ", ")+` FROM school s WHERE `+b.where(), b.args...).Scan(targets...); err != nil {
		return nil, fmt.Errorf("schooldirectory: counting gaps: %w", err)
	}
	out := map[string]int{}
	for i, key := range keys {
		out[key] = values[i]
	}
	return out, nil
}

type filterState struct {
	fy                                string
	fyOptions                         []string
	district, subCounty, schoolType   string
	clusterStatus, projectStatus, gap string
	gapCounts                         map[string]int
}

func (s *Service) filters(ctx context.Context, base *sqlb, hasSchools bool, f filterState) (*screensv1.DirectoryFilters, error) {
	out := &screensv1.DirectoryFilters{
		Fy: f.fy, District: f.district, SubCounty: f.subCounty, SchoolType: f.schoolType,
		ClusterStatus: f.clusterStatus, ProjectStatus: f.projectStatus, Gap: f.gap,
		ClusterStatuses: []*screensv1.DirectoryOption{
			{Value: "clustered", Label: "Clustered"}, {Value: "unclustered", Label: "Unclustered"},
		},
		ProjectStatuses: []*screensv1.DirectoryOption{
			{Value: "assigned", Label: "Assigned"}, {Value: "unassigned", Label: "Not Assigned"},
		},
	}
	for _, fy := range f.fyOptions {
		out.FyOptions = append(out.FyOptions, &screensv1.DirectoryOption{Value: fy, Label: "FY " + fy})
	}
	for _, t := range rules.SchoolTypes {
		out.SchoolTypes = append(out.SchoolTypes, &screensv1.DirectoryOption{Value: t[0], Label: t[1]})
	}
	for _, g := range rules.GapLabels {
		out.Gaps = append(out.Gaps, &screensv1.DirectoryOption{
			Value: g[0], Label: g[1] + " (" + thousands(f.gapCounts[g[0]]) + ")",
		})
	}
	var err error
	if out.Districts, err = districtOptions(ctx, s.db, base, hasSchools); err != nil {
		return nil, fmt.Errorf("schooldirectory: reading districts: %w", err)
	}
	if out.SubCounties, err = subCountyOptions(ctx, s.db, base, hasSchools, f.district); err != nil {
		return nil, fmt.Errorf("schooldirectory: reading sub-counties: %w", err)
	}
	return out, nil
}

// rows are the page's schools as the feed draws them
// (SchoolDirectoryViewModel.from_school, directory_school,
// directory_actions).
func (s *Service) rows(ctx context.Context, p auth.Principal, scope Scope, page []school, fy string, takeable bool) ([]*screensv1.DirectorySchool, error) {
	out := []*screensv1.DirectorySchool{}
	if len(page) == 0 {
		return out, nil
	}
	schoolIDs := ids(page)
	ssa, err := ssaSummaries(ctx, s.db, schoolIDs, fy)
	if err != nil {
		return nil, err
	}
	visits, err := visitCounts(ctx, s.db, schoolIDs)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: counting visits: %w", err)
	}
	trainings, err := trainingCounts(ctx, s.db, schoolIDs)
	if err != nil {
		return nil, err
	}
	statuses, err := visitStatuses(ctx, s.db, schoolIDs, fy)
	if err != nil {
		return nil, err
	}
	covered, err := trainingCoverage(ctx, s.db, page, fy)
	if err != nil {
		return nil, err
	}
	clusterIDs, ownerIDs := []string{}, []string{}
	for _, sc := range page {
		clusterIDs = append(clusterIDs, sc.ClusterID)
		ownerIDs = append(ownerIDs, sc.OwnerID)
	}
	clusterNames := map[string]string{}
	rows, err := s.db.Query(ctx, `SELECT id, name FROM cluster WHERE deleted_at IS NULL AND id = ANY($1)`, uniq(clusterIDs))
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			rows.Close()
			return nil, err
		}
		clusterNames[id] = name
	}
	rows.Close()
	staffNames := map[string]string{}
	rows, err = s.db.Query(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(u.name, '') FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, uniq(ownerIDs))
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var id, userID, name string
		if err := rows.Scan(&id, &userID, &name); err != nil {
			rows.Close()
			return nil, err
		}
		if userID != "" && name != "" {
			staffNames[id] = name
			staffNames[userID] = name
		}
	}
	rows.Close()
	projects := map[string][]string{}
	rows, err = s.db.Query(ctx, `SELECT school_id, project_id FROM project_school_assignment WHERE school_id = ANY($1) ORDER BY created_at, id`, schoolIDs)
	if err != nil {
		return nil, err
	}
	for rows.Next() {
		var schoolID, projectID string
		if err := rows.Scan(&schoolID, &projectID); err != nil {
			rows.Close()
			return nil, err
		}
		projects[schoolID] = append(projects[schoolID], projectID)
	}
	rows.Close()
	var activeProjects bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM project WHERE deleted_at IS NULL)`).Scan(&activeProjects); err != nil {
		return nil, err
	}

	for _, sc := range page {
		clustered := sc.HasClusterColumn || sc.ClusterStatus == "clustered"
		clusterName := "Not assigned"
		if clustered && sc.ClusterID != "" {
			if name, ok := clusterNames[sc.ClusterID]; ok && name != "" && name != "—" {
				clusterName = name
			}
		}
		staffName := staffNames[sc.OwnerID]
		if staffName == "" {
			staffName = sc.OwnerNameRaw
		}
		if staffName == "" {
			staffName = "Unassigned"
		}
		row := &screensv1.DirectorySchool{
			Id: sc.ID, SchoolId: sc.SchoolID, Name: sc.Name,
			District: orDash(sc.DistrictName), DistrictId: sc.DistrictID,
			ShippingAddress: orDash(sc.ShippingAddress), SchoolType: schoolTypeLabel(sc.SchoolType),
			ClusterId: sc.ClusterID, ClusterName: clusterName, Enrolment: int32(sc.Enrollment),
			Phone: orDash(sc.Phone), Contact: orDash(sc.Contact), StaffName: staffName,
			SsaTone:    "neutral",
			VisitCount: int32(visits[sc.ID]), TrainingCount: int32(trainings[sc.ID]),
			ProjectIds: projects[sc.ID],
			SsaGroups:  []*screensv1.DirectorySsaGroup{},
		}
		if row.ProjectIds == nil {
			row.ProjectIds = []string{}
		}
		if summary, ok := ssa[sc.ID]; ok {
			row.SsaTone = summary.tone
			row.SsaAverage = summary.average
			for i, g := range rules.SSAGroups {
				group := &screensv1.DirectorySsaGroup{Key: g[0], Title: g[1], Tone: g[2], Items: []*screensv1.DirectorySsaItem{}}
				for _, item := range summary.groups[i] {
					group.Items = append(group.Items, &screensv1.DirectorySsaItem{
						Label: item.label, Score: item.score, Band: item.band, BandTone: item.tone,
					})
				}
				row.SsaGroups = append(row.SsaGroups, group)
			}
		}
		status := statuses[sc.ID]
		row.VisitStatusLabel = rules.VisitLabels[status.key]
		row.VisitStatusTone = rules.VisitTones[status.key]
		if status.next != nil {
			row.NextVisitDate = status.next.Format("2006-01-02")
		}
		c := covered[sc.ID]
		row.ClusterTrainingLabel, row.ClusterTrainingReason = c.label, c.reason
		switch {
		case c.planned:
			row.ClusterTrainingState = "positive"
		case c.required:
			row.ClusterTrainingState = "attention"
		}
		row.Actions = []*screensv1.DirectoryRowAction{}
		if !scope.RegionScope {
			row.Actions = actions(p, clustered, activeProjects, takeable)
		}
		out = append(out, row)
	}
	return out, nil
}

func orDash(value string) string {
	if value == "" {
		return "—"
	}
	return value
}

// actions are directory_actions, in the row menu's order and words.
func actions(p auth.Principal, clustered, activeProjects, takeable bool) []*screensv1.DirectoryRowAction {
	out := []*screensv1.DirectoryRowAction{}
	add := func(key, label string, enabled bool, reason string) {
		out = append(out, &screensv1.DirectoryRowAction{Key: key, Label: label, Enabled: enabled, Reason: reason})
	}
	if takeable {
		add("take", "Take This School", true, "")
		add("complete", "Open And Complete", true, "")
	}
	if p.ActiveRole == roleImpact {
		add("schedule", "Schedule", true, "")
	}
	if rbac.Grants(p.ActiveRole, "cluster.assign") {
		if clustered {
			add("change_cluster", "Change Cluster", true, "")
		} else {
			add("add_to_cluster", "Add to Cluster", true, "")
		}
	}
	if rbac.Grants(p.ActiveRole, "school.ownershipTransfer") {
		add("reassign_owner", "Reassign Owner", true, "")
	}
	if rbac.Grants(p.ActiveRole, "project.assignSchool") {
		if activeProjects {
			add("assign_to_project", "Add to Project", true, "")
		} else {
			add("assign_to_project", "Add to Project", false, "No active project available.")
		}
	}
	return out
}

// directoryListing is school_directory_context's reading of the request: the
// reader's scope and schools, the filters it validates, the counts by gap
// and tab, and the listing the active tab shows.
type directoryListing struct {
	scope                                                         Scope
	base, unheld, listing                                         *sqlb
	canTake                                                       bool
	gap, fy, tab                                                  string
	options                                                       []string
	district, subCounty, schoolType, clusterStatus, projectStatus string
	gapCounts                                                     map[string]int
	tabCounts                                                     map[string]int
}

func (s *Service) listingFor(ctx context.Context, p auth.Principal, req *screensv1.GetSchoolDirectoryRequest, now time.Time) (*directoryListing, error) {
	scope, err := resolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, err
	}

	// Schools nobody holds, for the field staff who may take them.
	canTake := in(rules.TakeRoles, p.ActiveRole) && p.StaffProfileID != ""
	var unheld *sqlb
	if canTake {
		var country *string
		err := s.db.QueryRow(ctx, `SELECT country FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL LIMIT 1`, p.UserID).Scan(&country)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return nil, fmt.Errorf("schooldirectory: reading the officer's country: %w", err)
		}
		c := ""
		if country != nil {
			c = *country
		}
		unheld = unheldBase(c)
	}
	base := scopeBase(scope)
	gap := strings.TrimSpace(req.GetGap())
	if _, known := gapLabel(gap); gap == "unheld" && unheld != nil {
		base = unheld.clone()
	} else if !known {
		gap = ""
	}

	fy := strings.TrimSpace(req.GetFy())
	options := fyOptions(now)
	if !in(options, fy) {
		fy = strconv.Itoa(operationalFY(now))
	}
	district := strings.TrimSpace(req.GetDistrict())
	subCounty := strings.TrimSpace(req.GetSubCounty())
	if subCounty != "" {
		var valid bool
		if district != "" {
			if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM sub_county WHERE id = $1 AND district_id = $2)`,
				subCounty, district).Scan(&valid); err != nil {
				return nil, err
			}
		}
		if !valid {
			subCounty = ""
		}
	}
	schoolType := strings.TrimSpace(req.GetSchoolType())
	clusterStatus := strings.TrimSpace(req.GetClusterStatus())
	projectStatus := strings.TrimSpace(req.GetProjectStatus())
	tab := strings.TrimSpace(req.GetTab())
	if !in([]string{"all", "unclustered", "clustered", "not_assigned", "assigned"}, tab) {
		tab = "all"
	}

	filtered := base.clone()
	if q := strings.TrimSpace(req.GetQ()); q != "" {
		filtered.search(q)
	}
	if district != "" {
		filtered.and("s.district_id = " + filtered.arg(district))
	}
	if subCounty != "" {
		filtered.and("s.sub_county_id = " + filtered.arg(subCounty))
	}
	if schoolType != "" {
		filtered.and("s.school_type = " + filtered.arg(schoolType))
	}
	if clusterStatus != "" {
		filtered.and("s.cluster_status = " + filtered.arg(clusterStatus))
	}
	switch projectStatus {
	case "assigned":
		filtered.and(inProject)
	case "unassigned":
		filtered.and(notInProject)
	}

	gapCounts, err := s.gapCounts(ctx, filtered, fy)
	if err != nil {
		return nil, err
	}
	if gap != "" && gap != "unheld" {
		if condition := filtered.gapCondition(gap, fy); condition != "" {
			filtered.and(condition)
		}
	}

	tabCounts := map[string]int{}
	for _, t := range rules.DirectoryTabs {
		n, err := s.count(ctx, filtered, tabCondition(t[0]))
		if err != nil {
			return nil, fmt.Errorf("schooldirectory: counting %s: %w", t[0], err)
		}
		tabCounts[t[0]] = n
	}
	listing := filtered.clone()
	if condition := tabCondition(tab); condition != "" {
		listing.and(condition)
	}
	return &directoryListing{scope: scope, base: base, unheld: unheld, listing: listing, canTake: canTake, gap: gap, fy: fy,
		tab: tab, options: options, district: district, subCounty: subCounty, schoolType: schoolType, clusterStatus: clusterStatus,
		projectStatus: projectStatus, gapCounts: gapCounts, tabCounts: tabCounts}, nil
}
