package myplan

import (
	"context"
	"fmt"
	"net/url"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers (apps.mobile_feed.views.NATIVE_PAGES
// names my_plan, the URL /my-plan).
const Path = "/my-plan"

// Service builds My Plan.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
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
	if rules.PartnerRoleBridge || plans(p) {
		return nil, false, nil
	}
	now := s.now()
	period, readable := ReadPeriod(query, now)
	if !readable {
		return nil, false, nil
	}
	held, err := holdsAnything(ctx, s.db, p)
	if err != nil || held {
		return nil, false, err
	}
	choices, err := s.choices(ctx)
	if err != nil {
		return nil, true, err
	}
	return emptyPage(period, schooldirectory.FYOptions(now), choices, NewQuery(query)), true, nil
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
