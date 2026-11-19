// Package fieldpages builds the School Map (extended_views.map_view,
// pages/map/index.html), the Search page (search_view; with a query,
// search.go) and the Schedule School Visit form as the existing feed reads
// them.
package fieldpages

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Map         bool `json:"map"`
		Search      bool `json:"search"`
		Schedule    bool `json:"schedule"`
		SearchStaff bool `json:"search_staff"`
	} `json:"roles"`
	EveryCountrySearchRoles []string          `json:"every_country_search_roles"`
	PartnerReleasedStatuses []string          `json:"partner_released_statuses"`
	ActivityStatuses        map[string]string `json:"activity_statuses"`
	Interventions           [][2]string       `json:"interventions"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("fieldpages: reading rules.json: %v", err))
	}
	if len(r.Roles) == 0 {
		panic("fieldpages: rules.json lacks the doors")
	}
	return r
}()

const (
	mapPath    = "/map"
	searchPath = "/search"
)

// mapScriptTexts are what the feed reads of the map's own script once a
// school has coordinates: the string literals of its error and popup
// markup, each a panel of its own.
var mapScriptTexts = []string{"Map could not be loaded", "' + message + '", "' + p.name + '"}

// Service builds the pages.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the pages over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers path for p; served is false for another path, a role
// without rules, and a visit form for a school with a confirmed SSA (the
// existing page's).
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	path = strings.TrimSuffix(path, "/")
	if path != mapPath && path != searchPath && path != schedulePath {
		return nil, false, nil
	}
	doors, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if path == schedulePath {
		if !doors.Schedule {
			return nil, true, pagegate.ErrNotAvailable
		}
		return s.schedule(ctx, p, query)
	}
	if path == searchPath {
		if !doors.Search {
			return nil, true, pagegate.ErrNotAvailable
		}
		if q := strings.TrimSpace(query.Get("q")); q != "" {
			out, err := s.search(ctx, p, q)
			return out, true, err
		}
		return page(header("Search", "Search", "Edify Operations · Search"), path), true, nil
	}
	if !doors.Map {
		return nil, true, pagegate.ErrNotAvailable
	}
	out, err := s.schoolMap(ctx, p)
	if err != nil {
		return nil, true, err
	}
	out.WebPath = path
	return out, true, nil
}

func header(eyebrow, title, description string) *screensv1.PageHeader {
	return &screensv1.PageHeader{Eyebrow: eyebrow, Title: title, Description: description,
		Badges: []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
}

func page(h *screensv1.PageHeader, path string, blocks ...*screensv1.PageBlock) *screensv1.GetPageResponse {
	if blocks == nil {
		blocks = []*screensv1.PageBlock{}
	}
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks, Tabs: []*screensv1.PageTab{},
		Dialogs: []*screensv1.PageDialog{}, WebPath: path}
}

func panel(items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Badges: []*screensv1.PageBadge{}, Items: items}}}
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

// schoolMap is map_view: the reader's schools (school_queryset: the scope's
// operating schools, the team's included), counted with and without
// coordinates (a verified geo point first, then the upload's).
func (s *Service) schoolMap(ctx context.Context, p auth.Principal) (*screensv1.GetPageResponse, error) {
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, err
	}
	var args []any
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	where := schooldirectory.ReadScope(scope, arg)
	var total, located int64
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*),
  COUNT(*) FILTER (WHERE COALESCE(g.latitude, s.latitude) IS NOT NULL AND COALESCE(g.longitude, s.longitude) IS NOT NULL)
FROM school s LEFT JOIN LATERAL (SELECT latitude, longitude FROM school_geo_point gp WHERE gp.school_id = s.id LIMIT 1) g ON true
WHERE `+where, args...).Scan(&total, &located); err != nil {
		return nil, fmt.Errorf("fieldpages: counting the schools with coordinates: %w", err)
	}
	h := header("Schools & Field", "School Map",
		"Every school with verified coordinates, plotted live. Coordinates power Route Intelligence.")
	var blocks []*screensv1.PageBlock
	if missing := total - located; missing > 0 {
		blocks = append(blocks, panel(
			text(closedschools.Comma(missing)+" school(s) have no coordinates yet — route estimates for them fall back to sub-county data."),
			&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
				{Text: "Location data quality →", Href: "/system-health"}}}}}))
	}
	if located == 0 {
		blocks = append(blocks, panel(text("No school coordinates captured yet"),
			text("The map activates automatically as coordinates arrive — from school uploads or verified GPS points captured during visits. Nothing is plotted until the data is real.")))
	} else {
		for _, t := range mapScriptTexts {
			blocks = append(blocks, panel(text(t)))
		}
	}
	return page(h, mapPath, blocks...), nil
}
