package myplan

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
)

// Path is the page this package answers (apps.mobile_feed.views.NATIVE_PAGES
// names my_plan, the URL /my-plan).
const Path = "/my-plan"

// Service builds My Plan.
type Service struct {
	db        schooldirectory.Querier
	now       func() time.Time
	summary   TrainingSummaryReader
	readiness ReadinessReader
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// passed is the query as the feed hands it to the page: without the keys
// that answer with a file (apps.mobile_feed.views.NOT_PASSED).
func passed(query url.Values) url.Values {
	out := url.Values{}
	for key, values := range query {
		if !in(rules.NotPassedQueryKeys, key) {
			out[key] = values
		}
	}
	return out
}

// Build answers /my-plan for p. served is false for another path (the parts
// under it are the existing application's), for a request the page answers
// with a workbook (the Export options drawer's period keys), for a period
// the existing view fails on, and for every reader whose page holds more
// than piece 1 draws: a Programme Lead or CCEO, a partner, or anyone with
// work, schools, clusters, hand-overs or training ceilings of their own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	// The feed's REST framework view answers a ?format= it has no renderer
	// for as not found, for everyone, before the page is asked.
	if format := query.Get("format"); format != "" && !in(rules.APIFormats, format) {
		return nil, true, pagegate.ErrNotAvailable
	}
	door, ok := rules.Doors[p.ActiveRole]
	if !ok || !door.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	query = passed(query)
	for _, key := range rules.ExportPeriodKeys {
		if query.Has(key) {
			return nil, false, nil
		}
	}
	if rules.PartnerRoleBridge {
		return nil, false, nil
	}
	planner := plans(p)
	now := s.now()
	period, readable := ReadPeriod(query, now)
	if !readable {
		return nil, false, nil
	}
	held, trains, err := holdsAnything(ctx, s.db, p, s.readiness != nil)
	if err != nil || held || (trains && s.summary == nil) {
		return nil, false, err
	}
	target := 0
	var ownReadiness *OwnReadiness
	if planner {
		if s.readiness != nil {
			var hasOwn bool
			if ownReadiness, hasOwn, err = s.readiness(ctx, s.db, p, period.FY, now); err != nil {
				return nil, false, err
			}
			if hasOwn && ownReadiness != nil {
				target = ownReadiness.StaffVisits.Target
			} else {
				target = visitTarget(p)
			}
		} else {
			if held, err = plannerHoldsAnything(ctx, s.db, p); err != nil || held {
				return nil, false, err
			}
			target = visitTarget(p)
		}
	}
	request := NewQuery(query)
	// The schools behind a readiness figure (?list=) are drawn by Go only
	// as the empty list a planner with no figures has; a planner with their
	// own readiness is handed on for one.
	if ownReadiness != nil && readinessList(request) != "" {
		return nil, false, nil
	}
	f := ReadFilters(request)
	owners := ownerIDs(p)
	plan, err := ReadPlan(ctx, s.db, owners, period, f, now)
	if err != nil {
		return nil, false, err
	}
	// A visits line too long for the tile (its whole sentence becomes the
	// note) is the existing application's when no readiness reader is attached.
	if s.readiness == nil {
		if target == 0 && utf8.RuneCountInString(visitsLine(plan.Counts)) > rules.Plan.HelperFigureChars {
			return nil, false, nil
		}
		if target > 0 && plan.Outreach > 0 {
			return nil, false, nil
		}
	}
	tables := PlanTablesResult{}
	if plan.Listed > 0 {
		if s.readiness == nil {
			for key := range query {
				// The tables' pagers, the programme schools' sections' by type.
				if strings.HasSuffix(key, "_page") || in(rules.Rows.ProgrammeSchoolTypes, key) {
					return nil, false, nil
				}
			}
		}
		var ported bool
		if tables, ported, err = ReadPlanTables(ctx, s.db, p.Country, owners, period, f, now); err != nil || !ported {
			return nil, false, err
		}
	}
	// Past the ceiling the tile says so (staff_plan.ceiling_notice), which
	// Go does not draw: handed on whichever readiness reader is attached.
	planned := 0
	if target > 0 {
		if planned, err = yearVisits(ctx, s.db, owners, period.FY); err != nil || planned > target {
			return nil, false, err
		}
	}
	var summary []TrainingSummaryRow
	if trains {
		if summary, err = s.summary(ctx, s.db, p.StaffProfileID, p.UserID, "", period.FY, now); err != nil {
			return nil, false, err
		}
		if s.readiness == nil && len(summary) > planTablePageSize {
			return nil, false, nil
		}
		if len(summary) > planTablePageSize {
			summary = summary[:planTablePageSize]
		}
	}
	var clusters []clusterPlanRow
	if s.readiness != nil {
		operational, _ := strconv.Atoi(schooldirectory.OperationalFY(now))
		years, err := schoolplanning.Horizon(ctx, s.db, p.Country, period.FY, operational, schooldirectory.FYOptions(now), now)
		if err != nil {
			return nil, false, err
		}
		if clusters, err = readClusterPlanningStatus(ctx, s.db, owners, years); err != nil {
			return nil, false, err
		}
	}
	choices, err := s.choices(ctx)
	if err != nil {
		return nil, true, err
	}
	return planPage(pageParts{period: period, years: schooldirectory.FYOptions(now), choices: choices, request: request,
		plan: plan, filters: f, target: target, planned: planned, readiness: ownReadiness,
		tables: tables, summary: summary, clusters: clusters}), true, nil
}

// choices are the District and Staff member selects' options: every
// district by name (District.objects.all()), and every active member of
// staff who is not deleted, by name.
func (s *Service) choices(ctx context.Context) (Choices, error) {
	var c Choices
	read := func(what, sql string, into *[]option) error {
		rows, err := s.db.Query(ctx, sql)
		if err != nil {
			return fmt.Errorf("myplan: reading %s: %w", what, err)
		}
		defer rows.Close()
		for rows.Next() {
			var o option
			var label *string
			if err := rows.Scan(&o.value, &label); err != nil {
				return fmt.Errorf("myplan: reading %s: %w", what, err)
			}
			// {{ name }} of a missing name is "None"; the feed reads an
			// option's text with its whitespace run together.
			o.label = "None"
			if label != nil {
				o.label = closedschools.PyCollapse(*label)
			}
			*into = append(*into, o)
		}
		if err := rows.Err(); err != nil {
			return fmt.Errorf("myplan: reading %s: %w", what, err)
		}
		return nil
	}
	if err := read("the districts", `SELECT d.id, d.name FROM district d ORDER BY d.name`, &c.Districts); err != nil {
		return c, err
	}
	err := read("the staff", `SELECT u.id, u.name FROM "user" u
WHERE u.status = 'active' AND u.deleted_at IS NULL ORDER BY u.name`, &c.Staff)
	return c, err
}
