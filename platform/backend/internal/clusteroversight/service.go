package clusteroversight

import (
	"context"
	"net/url"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers: Cluster Oversight as it opens, on
// its Command Center. It is the one address of the page the app's feed
// opens (apps.mobile_feed.views.NATIVE_PAGES names cluster_oversight, and
// not cluster_oversight_section).
const Path = "/cluster-oversight/"

// under is every other address of the page: the same without its slash,
// and its sections' own.
const under = "/cluster-oversight"

// ErrNotAvailable is the page refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = pagegate.ErrNotAvailable

// kampala is the application's time zone (settings.TIME_ZONE): the page's
// "today" is the local day.
var kampala = mustZone("Africa/Kampala")

func mustZone(name string) *time.Location {
	zone, err := time.LoadLocation(name)
	if err != nil {
		panic("clusteroversight: " + err.Error())
	}
	return zone
}

// Service builds the Cluster Oversight page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

type resolvedRoute struct {
	kind    string // "section", "scoring", "unknown"
	section string
	webPath string
}

func resolvePath(path string) (resolvedRoute, bool) {
	if path == Path || path == under {
		return resolvedRoute{kind: "section", section: rules.DefaultSection, webPath: Path}, true
	}
	if !strings.HasPrefix(path, Path) {
		return resolvedRoute{}, false
	}
	rest := strings.TrimSuffix(strings.TrimPrefix(path, Path), "/")
	if rest == "" {
		return resolvedRoute{kind: "section", section: rules.DefaultSection, webPath: Path}, true
	}
	if strings.Contains(rest, "/") {
		return resolvedRoute{kind: "unknown"}, true
	}
	if rest == "scoring" {
		return resolvedRoute{kind: "scoring", webPath: "/cluster-oversight/scoring"}, true
	}
	if isBuiltInSection(rest) {
		return resolvedRoute{kind: "section", section: rest, webPath: "/cluster-oversight/" + rest}, true
	}
	return resolvedRoute{kind: "unknown"}, true
}

// Build answers path for p with the page's query. served is false for a
// path this package does not answer.
//
// Every built-in Cluster Oversight section (/cluster-oversight/,
// /cluster-oversight/<section>) and /cluster-oversight/scoring is served
// directly in Go. Unknown paths under /cluster-oversight/ return
// ErrNotAvailable rather than falling back to Command Center.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	route, mine := resolvePath(path)
	if !mine {
		return nil, false, nil
	}
	if route.kind == "unknown" {
		return nil, true, ErrNotAvailable
	}
	doors, ok := rules.Doors[p.ActiveRole]
	if !ok || !doors.Page {
		return nil, true, ErrNotAvailable
	}
	if route.kind == "scoring" {
		if !doors.Scoring {
			return nil, true, ErrNotAvailable
		}
		setting, err := readScoreSetting(ctx, s.db)
		if err != nil {
			return nil, true, err
		}
		return scoringPage(setting), true, nil
	}
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	r := reach{}
	if !scope.CountryScope && !scope.SummaryOnly {
		if r, err = reachOf(ctx, s.db, scope); err != nil {
			return nil, true, err
		}
	}
	years := yearOptions(now)
	fy := strings.TrimSpace(query.Get("fy"))
	if !in(years, fy) {
		fy = schooldirectory.OperationalFY(now)
	}
	found, err := read(ctx, s.db, scope, r, fy)
	if err != nil {
		return nil, true, err
	}
	return sectionPage(found, reader{doors: doors, ids: nonEmpty(p.UserID, p.StaffProfileID)}, route.section, route.webPath, fy, years, now.In(kampala).Format(time.DateOnly), query), true, nil
}

// yearOptions is the view's sorted(fy_options(), reverse=True).
func yearOptions(now time.Time) []string {
	years := slices.Clone(schooldirectory.FYOptions(now))
	slices.Sort(years)
	slices.Reverse(years)
	return years
}

func nonEmpty(ids ...string) []string {
	out := []string{}
	for _, id := range ids {
		if id != "" {
			out = append(out, id)
		}
	}
	return out
}

// reader is who the page is drawn for: what their role may open, and the
// ids a cluster of their own is filed under (scoping.owner_ids).
type reader struct {
	doors Doors
	ids   []string
}

// page is the Command Center drawn from the records for one reader.
func page(r *records, who reader, fy string, years []string, today string, query url.Values) *screensv1.GetPageResponse {
	return sectionPage(r, who, rules.DefaultSection, Path, fy, years, today, query)
}

func sectionPage(r *records, who reader, sectionKey, webPath, fy string, years []string, today string, query url.Values) *screensv1.GetPageResponse {
	ws := load(r, fy, today, who.ids)
	section, _ := sectionMeta(sectionKey)
	// My Clusters is for someone who holds one, among more than they hold.
	showMine := len(ws.mine) > 0 && len(ws.mine) != len(ws.clusters)
	tbl := ws.buildSection(section.Key, who.doors, ssaArea(query), impactView(query))
	return &screensv1.GetPageResponse{
		Header: header(section, who.doors, fy, query),
		Blocks: []*screensv1.PageBlock{
			sectionTabs(section.Key, fy, who.doors, showMine),
			filtersBlock(section.Key, fy, years, query),
			tableBlock(tbl, who.doors, query),
		},
		WebPath: webPath,
	}
}
