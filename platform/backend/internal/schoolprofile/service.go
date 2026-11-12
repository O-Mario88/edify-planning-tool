package schoolprofile

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Querier is the read a profile needs; *pgxpool.Pool satisfies it.
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

var (
	// ErrForbidden: the role may not open school profiles (require_page).
	ErrForbidden = errors.New("schoolprofile: the role may not open school profiles")
	// ErrNotFound: no such school, or not the reader's (get_one), which the
	// existing application answers alike.
	ErrNotFound = errors.New("schoolprofile: school not found")
)

// Service builds school profiles.
type Service struct {
	db  Querier
	now func() time.Time
}

// NewService reads db; now is the clock (time.Now).
func NewService(db Querier, now func() time.Time) *Service {
	if now == nil {
		now = time.Now
	}
	return &Service{db: db, now: now}
}

// detailsTab is the school's own record; the others Go answers are the
// profile engine's.
const detailsTab = "details"

// servedTabs are the tabs Go answers; the rest (and no tab, the Overview)
// are still the existing application's.
var servedTabs = map[string]bool{detailsTab: true, "overview": true, "ssa": true, "activities": true, "projects": true, "stories": true, "academic": true, "core": true}

// stillExisting are the tabs that are the existing application's whatever
// the school. (Core School is too where a school has it; at a school that
// does not, it is the Overview.)
var stillExisting = map[string]bool{}

// section is the open tab's blocks: the school's record, or the engine's
// frame and section for the year and period asked; and the bar for the
// tab's ticked rows, where it has one.
func (s *Service) section(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, sc school, tab string, req *screensv1.GetSchoolProfileRequest, now time.Time) ([]*screensv1.PageBlock, *screensv1.PageSelection, error) {
	if tab == detailsTab {
		blocks, err := s.details(ctx, p, sc, now)
		return blocks, nil, err
	}
	d := rules.Doors[p.ActiveRole]
	l := lensOf(sc, tab, req.GetFy(), req.GetPeriod(), schooldirectory.OperationalFY(now))
	if tab == "core" {
		// Not an engine tab: no scope line, facts or filters above it.
		blocks, err := s.coreTab(ctx, scope, d, sc, l, now)
		return blocks, nil, err
	}
	frame, err := s.frame(ctx, d, sc, l)
	if err != nil {
		return nil, nil, err
	}
	var blocks []*screensv1.PageBlock
	var selection *screensv1.PageSelection
	switch tab {
	case "projects":
		blocks, err = s.projectsTab(ctx, d, sc, l)
	case "stories":
		blocks, err = s.storiesTab(ctx, sc, l)
	case "academic":
		blocks, err = s.academicTab(ctx, sc, l)
	case "overview":
		blocks, err = s.overviewTab(ctx, d, sc, l, now)
	case "ssa":
		blocks, err = s.ssaTab(ctx, sc, l)
	case "activities":
		blocks, selection, err = s.participationTab(ctx, p, scope, d, sc, l, now)
	}
	if err != nil {
		return nil, nil, err
	}
	return append(frame, blocks...), selection, nil
}

// school is the profile's record, as the page reads it.
type school struct {
	ID, SchoolID, Name, Type, Status, Readiness string
	RegionName                                  string
	DistrictID, DistrictName                    string
	HasDistrict                                 bool
	SubCountyID, SubCountyName                  string
	HasSubCounty                                bool
	ParishName                                  string
	Enrollment                                  *int
	Latitude, Longitude                         *float64
	CohortYear, CohortNumber                    *int
	OwnerID, OwnerNameRaw                       string
	Phone, ContactName, Director, Headteacher   string
	LastEnrollment                              *time.Time
	Address                                     string
	ClusterID                                   string
	QualityScore                                *int
	QualityStatus                               *string
}

func (s school) closed() bool { return slices.Contains(rules.ClosedStatuses, s.Status) }

func (s school) core() bool { return slices.Contains(rules.Gate.CoreRuleTypes, s.Type) }

// Build is the profile of the school req names, for p. served is false where
// the existing application still answers: a tab other than Details, a Core
// or closed school, a school with Business Transformation records, or a
// reader working in an acting capacity (the caller checks that).
func (s *Service) Build(ctx context.Context, p auth.Principal, req *screensv1.GetSchoolProfileRequest) (*screensv1.GetSchoolProfileResponse, bool, error) {
	if !rules.Doors[p.ActiveRole].Profile {
		return nil, true, ErrForbidden
	}
	tab := req.GetTab()
	if stillExisting[tab] {
		return nil, false, nil
	}
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	key := req.GetSchoolId()
	id, err := schooldirectory.Openable(ctx, s.db, p, scope, key, rules.ClosedStatuses, rules.Doors[p.ActiveRole].Take)
	if err != nil {
		return nil, true, err
	}
	if id == "" {
		return nil, true, ErrNotFound
	}
	sc, err := s.load(ctx, id)
	if err != nil {
		return nil, true, err
	}
	if sc.closed() {
		return nil, false, nil
	}
	// A tab the school's profile does not have is its first, the Overview
	// (profile_views.profile_context).
	known := false
	for _, t := range tabs(sc, "") {
		known = known || t.GetKey() == tab
	}
	if !known {
		tab = "overview"
	}
	if !servedTabs[tab] {
		return nil, false, nil
	}
	if tab == detailsTab || tab == "overview" {
		// The Details tab's Business Transformation panel and the Overview's
		// loans strip read the loan register, still the existing
		// application's.
		held, err := s.hasBusinessTransformation(ctx, sc.ID)
		if err != nil {
			return nil, true, err
		}
		if held {
			return nil, false, nil
		}
	}
	header, err := s.header(ctx, p, scope, sc, now)
	if err != nil {
		return nil, true, err
	}
	blocks, selection, err := s.section(ctx, p, scope, sc, tab, req, now)
	if errors.Is(err, errTooLong) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return &screensv1.GetSchoolProfileResponse{
		Header:    header,
		Tabs:      tabs(sc, tab),
		Blocks:    blocks,
		WebPath:   "/schools/" + key,
		Dialogs:   []*screensv1.PageDialog{},
		Selection: selection,
	}, true, nil
}

func (s *Service) load(ctx context.Context, id string) (school, error) {
	var sc school
	var enrollment, cohortYear, cohortNumber, quality *int32
	err := s.db.QueryRow(ctx, `
SELECT s.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(s.school_type, ''),
  COALESCE(s.operational_status, ''), COALESCE(s.planning_readiness, ''), COALESCE(r.name, ''),
  COALESCE(s.district_id, ''), COALESCE(d.name, ''), d.id IS NOT NULL,
  COALESCE(s.sub_county_id, ''), COALESCE(sc.name, ''), sc.id IS NOT NULL, COALESCE(pa.name, ''),
  s.enrollment, s.latitude, s.longitude, s.core_cohort_year, s.core_cohort_number,
  COALESCE(s.account_owner_id, ''), COALESCE(s.account_owner_name_raw, ''),
  COALESCE(s.school_phone, ''), COALESCE(s.primary_contact_name, ''), COALESCE(s.director_name, ''),
  COALESCE(s.headteacher_name, ''), s.last_enrollment_date, COALESCE(s.shipping_address, ''),
  COALESCE(s.cluster_id, ''), s.data_quality_score, s.data_quality_status
FROM school s
LEFT JOIN region r ON r.id = s.region_id
LEFT JOIN district d ON d.id = s.district_id
LEFT JOIN sub_county sc ON sc.id = s.sub_county_id
LEFT JOIN parish pa ON pa.id = s.parish_id
WHERE s.id = $1`, id).Scan(&sc.ID, &sc.SchoolID, &sc.Name, &sc.Type, &sc.Status, &sc.Readiness, &sc.RegionName,
		&sc.DistrictID, &sc.DistrictName, &sc.HasDistrict, &sc.SubCountyID, &sc.SubCountyName, &sc.HasSubCounty, &sc.ParishName,
		&enrollment, &sc.Latitude, &sc.Longitude, &cohortYear, &cohortNumber, &sc.OwnerID, &sc.OwnerNameRaw,
		&sc.Phone, &sc.ContactName, &sc.Director, &sc.Headteacher, &sc.LastEnrollment, &sc.Address,
		&sc.ClusterID, &quality, &sc.QualityStatus)
	if err != nil {
		return sc, fmt.Errorf("schoolprofile: reading the school: %w", err)
	}
	sc.Enrollment, sc.CohortYear, sc.CohortNumber, sc.QualityScore = intOf(enrollment), intOf(cohortYear), intOf(cohortNumber), intOf(quality)
	return sc, nil
}

func intOf(v *int32) *int {
	if v == nil {
		return nil
	}
	n := int(*v)
	return &n
}

// hasBusinessTransformation: a case or an MFI loan at the school, whose
// panel (the loan register's scoping) is still the existing application's.
func (s *Service) hasBusinessTransformation(ctx context.Context, schoolID string) (bool, error) {
	var held bool
	err := s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM bt_case WHERE school_id = $1) OR EXISTS (SELECT 1 FROM bt_mfi_loan WHERE school_id = $1)`, schoolID).Scan(&held)
	if err != nil {
		return false, fmt.Errorf("schoolprofile: reading Business Transformation: %w", err)
	}
	return held, nil
}

// localFY is ssa.creation.current_fy: the year Kampala's day falls in.
func localFY(now time.Time) string {
	day := now.In(kampala)
	if day.Month() >= time.October {
		return strconv.Itoa(day.Year() + 1)
	}
	return strconv.Itoa(day.Year())
}

// tabs are the profile's tab strip: the engine's sections over one school,
// the Core School tab of a Core lifecycle school (Core, Core Trained, Core
// Graduate, Champion), then Details.
func tabs(sc school, open string) []*screensv1.PageTab {
	keys := [][2]string{
		{"overview", "Overview"}, {"ssa", "SSA"}, {"activities", "Participation"},
		{"academic", "Academic"}, {"stories", "Stories"}, {"projects", "Projects"},
	}
	if slices.Contains(rules.CoreLifecycleTypes, sc.Type) {
		keys = append(keys, [2]string{"core", "Core School"})
	}
	keys = append(keys, [2]string{"details", "Details"})
	out := make([]*screensv1.PageTab, 0, len(keys))
	for _, k := range keys {
		out = append(out, &screensv1.PageTab{Key: k[0], Label: k[1], Active: k[0] == open})
	}
	return out
}
