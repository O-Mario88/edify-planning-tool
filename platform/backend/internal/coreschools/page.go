package coreschools

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page Go answers.
const Path = "/core-schools"

// Service answers Core Schools Planning from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db, its moment read from now.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// page is one read of the page.
type page struct {
	db                schooldirectory.Querier
	p                 auth.Principal
	scope             schooldirectory.Scope
	door              door
	fy, operational   string
	f                 filters
	perPage, number   int
	pages             int
	tick, hasTeamCore bool
	all               []school // the filtered core schools
	shown             []school // this page of them
	now               time.Time
	// performanceFigures are read once, for the KPI strip and the tab.
	performanceFigures *performanceFigures
	// programmeRows is whether a programme table has a row to tick.
	programmeRows bool
	// oversight is the read-only Team Core Oversight lens.
	oversight bool
}

// Build answers /core-schools; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path && path != ChampionsPath && path != CandidatesPath {
		return nil, false, nil
	}
	d, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, true, pagegate.ErrNotAvailable
	}
	if path == ChampionsPath {
		resp, err := s.champions(ctx, p, query)
		return resp, true, err
	}
	if path == CandidatesPath {
		resp, err := s.candidates(ctx, p, query)
		if errors.Is(err, errPassOn) {
			return nil, false, nil
		}
		return resp, true, err
	}
	resp, err := s.build(ctx, p, d, query)
	if errors.Is(err, errPassOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return resp, true, nil
}

// knownKeys are the query keys the page reads.
var knownKeys = []string{"fy", "q", "region", "district", "staff", "partner", "school_type_filter", "ssa_status",
	"partner_assigned", "page", "per_page", "lens"}

// pageNumber is Paginator.get_page's reading of the asked page: a whole
// number, or the first; one out of range the last. A page int() would read
// where Go does not is handed on.
func pageNumber(raw string, pages int) (int, error) {
	if raw == "" {
		return 1, nil
	}
	if strings.TrimLeft(raw, "0123456789") == "" {
		n, err := strconv.Atoi(raw)
		if err != nil || n < 1 || n > pages {
			return pages, nil
		}
		return n, nil
	}
	if strings.IndexFunc(raw, func(r rune) bool {
		return r > unicode.MaxASCII || unicode.IsSpace(r) || r == '+' || r == '-' || r == '_'
	}) >= 0 {
		return 0, fmt.Errorf("the page %q: %w", raw, errPassOn)
	}
	return 1, nil
}

func (s *Service) build(ctx context.Context, p auth.Principal, d door, query url.Values) (*screensv1.GetPageResponse, error) {
	for key, values := range query {
		if !slices.Contains(knownKeys, key) && strings.Join(values, "") != "" {
			return nil, fmt.Errorf("the query %q: %w", key, errPassOn)
		}
	}
	now := s.now()
	pg := &page{db: s.db, p: p, door: d, now: now, operational: schooldirectory.OperationalFY(now)}
	pg.fy = strings.TrimSpace(query.Get("fy"))
	if !slices.Contains(schooldirectory.FYOptions(now), pg.fy) {
		pg.fy = pg.operational
	}
	get := func(key string) string {
		if v, ok := query[key]; ok && len(v) > 0 {
			return v[0]
		}
		return "All"
	}
	pg.f = filters{fy: pg.fy, q: strings.TrimSpace(query.Get("q")), region: get("region"), district: get("district"), staff: get("staff"),
		partner: get("partner"), schoolType: get("school_type_filter"), ssaStatus: get("ssa_status"), partnerAssigned: get("partner_assigned")}
	if strings.IndexFunc(pg.f.q, func(r rune) bool { return r > unicode.MaxASCII }) >= 0 {
		// icontains folds case as the database does; Go's ILIKE is the same
		// only for ASCII.
		return nil, fmt.Errorf("a search beyond ASCII: %w", errPassOn)
	}
	pg.perPage = rules.PageSizeDefault
	if raw := strings.TrimSpace(query.Get("per_page")); strings.TrimLeft(raw, "0123456789") == "" && raw != "" {
		if n, err := strconv.Atoi(raw); err == nil && slices.Contains(rules.PageSizes, n) {
			pg.perPage = n
		}
	} else if strings.IndexFunc(raw, func(r rune) bool { return r > unicode.MaxASCII }) >= 0 {
		return nil, fmt.Errorf("a page size beyond ASCII: %w", errPassOn)
	}
	var err error
	if pg.scope, err = schooldirectory.ResolveScope(ctx, s.db, p, now); err != nil {
		return nil, err
	}
	if pg.hasTeamCore, err = s.teamCore(ctx, pg.scope); err != nil {
		return nil, err
	}
	// With no lens asked, a reader who holds no core school directly but whose
	// team does (a Programme Lead) opens on the team's (owner, 2026-11-21,
	// doc 184 §2; core_schools_views, the same rule). A lens the reader cannot
	// hold falls back to their own schools.
	switch asked := query.Get("lens"); {
	case asked == "oversight":
		pg.oversight = pg.hasTeamCore
	case asked == "" && pg.hasTeamCore:
		holds, err := s.holdsCore(ctx, pg.scope)
		if err != nil {
			return nil, err
		}
		pg.oversight = !holds
	}
	pending, err := healPending(ctx, s.db, pg.scope, pg.oversight, pg.fy, pg.operational)
	if err != nil {
		return nil, err
	}
	if pending && !pagegate.DjangoAbsent(ctx) {
		return nil, fmt.Errorf("the packages would be healed: %w", errPassOn)
	}
	if pg.all, err = coreSchools(ctx, s.db, pg.scope, pg.oversight, pg.f); err != nil {
		return nil, err
	}
	pg.pages = max(1, (len(pg.all)+pg.perPage-1)/pg.perPage)
	if pg.number, err = pageNumber(query.Get("page"), pg.pages); err != nil {
		return nil, err
	}
	start := (pg.number - 1) * pg.perPage
	pg.shown = pg.all[start:min(start+pg.perPage, len(pg.all))]
	pg.tick = d.tick() && !pg.oversight
	if pg.oversight {
		return pg.oversightResponse(ctx)
	}
	return pg.response(ctx)
}

// teamCore is whether the reader's team holds any core-lifecycle school.
// holdsCore is whether the reader's direct portfolio holds a core school
// (direct_portfolio_schools(scope).filter(school_type="core").exists()).
func (s *Service) holdsCore(ctx context.Context, scope schooldirectory.Scope) (bool, error) {
	a := &sqlArgs{}
	clause := lensClause(scope, false, a)
	var holds bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM school s WHERE `+clause+` AND s.school_type = 'core')`,
		a.list...).Scan(&holds); err != nil {
		return false, fmt.Errorf("coreschools: reading the reader's own core schools: %w", err)
	}
	return holds, nil
}

func (s *Service) teamCore(ctx context.Context, scope schooldirectory.Scope) (bool, error) {
	team := teamSchoolIDs(scope)
	if len(team) == 0 {
		return false, nil
	}
	var any bool
	types := append([]string{"core"}, rules.ProgrammeSchoolTypes...)
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM school WHERE deleted_at IS NULL AND id = ANY($1) AND school_type = ANY($2))`,
		team, types).Scan(&any); err != nil {
		return false, fmt.Errorf("coreschools: reading the team's core schools: %w", err)
	}
	return any, nil
}

func (pg *page) response(ctx context.Context) (*screensv1.GetPageResponse, error) {
	resp := &screensv1.GetPageResponse{WebPath: Path, Header: &screensv1.PageHeader{
		Eyebrow: "Schools & Field", Title: "Core Schools Planning",
		Description: "Plan core packages and ongoing support for Core Trained, Core Graduate and Champion schools. Only Core Schools receive the 4 Visits + 4 Trainings package.",
	}}
	blocks := []*screensv1.PageBlock{}
	if pg.hasTeamCore {
		blocks = append(blocks, pg.lensTabs())
	}
	filters, err := pg.filterBlock(ctx)
	if err != nil {
		return nil, err
	}
	strip, err := pg.kpis(ctx)
	if err != nil {
		return nil, err
	}
	matrix, err := pg.matrixBlocks(ctx)
	if err != nil {
		return nil, err
	}
	blocks = append(blocks, filters, strip, pg.segments(matrix, pg.matrixCaption()))
	blocks = append(blocks, matrix...)
	for _, part := range []func(context.Context) ([]*screensv1.PageBlock, error){pg.queue, pg.impact, pg.performance, pg.right, pg.programme} {
		more, err := part(ctx)
		if err != nil {
			return nil, err
		}
		blocks = append(blocks, more...)
	}
	resp.Blocks = blocks
	if pg.tick && (len(pg.shown) > 0 || pg.programmeRows) {
		resp.Selection = pg.selection()
	}
	return resp, nil
}

// lensTabs is the portfolio scope rail.
func (pg *page) lensTabs() *screensv1.PageBlock {
	size := strconv.Itoa(pg.perPage)
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{Tabs: []*screensv1.PageLinkTab{
		{Label: "My Core Schools", Href: "/core-schools?lens=mine&fy=" + pg.fy + "&per_page=" + size, Active: !pg.oversight},
		{Label: "Team Core Oversight", Href: "/core-schools?lens=oversight&fy=" + pg.fy + "&per_page=" + size, Active: pg.oversight},
	}}}}
}

// oversightResponse is the Team Core Oversight lens: the rail, the filters,
// the strip over the team's core schools, then one read-only table and the
// programme tables. Nothing on it plans, so nothing is ticked.
func (pg *page) oversightResponse(ctx context.Context) (*screensv1.GetPageResponse, error) {
	filters, err := pg.filterBlock(ctx)
	if err != nil {
		return nil, err
	}
	strip, err := pg.kpis(ctx)
	if err != nil {
		return nil, err
	}
	tables, err := pg.oversightBlocks(ctx)
	if err != nil {
		return nil, err
	}
	return &screensv1.GetPageResponse{WebPath: Path, Header: &screensv1.PageHeader{
		Eyebrow: "Schools & Field", Title: "Team Core Oversight",
		Description: "Read-only view of the core packages your CCEOs are responsible for. Ask the owner to act — you cannot plan their work here.",
	}, Blocks: append([]*screensv1.PageBlock{pg.lensTabs(), filters, strip}, tables...)}, nil
}

// selection is partials/schools/bulk_bar.html's doors for the ticked set.
func (pg *page) selection() *screensv1.PageSelection {
	sel := &screensv1.PageSelection{Noun: "selected"}
	add := func(on bool, label, href string) {
		if on {
			sel.Actions = append(sel.Actions, &screensv1.PageSelectionAction{Label: label, Href: href, Param: "school_ids"})
		}
	}
	add(pg.door.AssignPartner, "Assign to partner", "/planning/bulk-assign-partner-drawer")
	add(pg.door.BulkSchedule, "Schedule visit", "/planning/bulk-schedule-drawer")
	add(pg.door.AssignProject, "Add to project", "/schools/bulk-assign-project-drawer")
	return sel
}

// matrixCaption is the first paragraph the feed meets in the tab panels: a
// row's "SSA detail", or the empty state's title.
func (pg *page) matrixCaption() string {
	switch {
	case len(pg.shown) > 0:
		return "SSA detail"
	case pg.f.narrowed():
		return "No Core Schools match these filters"
	}
	return "No Core Schools in your portfolio"
}

// segments is the four view tabs as the feed reads them: the matrix in the
// first, each lazy tab's loading line in the others, none chosen.
func (pg *page) segments(matrix []*screensv1.PageBlock, caption string) *screensv1.PageBlock {
	loading := func(text string) []*screensv1.PageBlock {
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: text}}}}}}}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Segments{Segments: &screensv1.PageSegments{
		Caption: caption,
		Segments: []*screensv1.PageSegment{
			{Label: "Core Service Package Matrix", Blocks: matrix},
			{Label: "Core Planning Queue", Blocks: loading("Loading the planning queue…")},
			{Label: "Intervention Impact Tracker", Blocks: loading("Loading intervention impact…")},
			{Label: "Staff vs Partner Performance", Blocks: loading("Loading performance insights…")},
		}}}}
}

func textPanel(texts ...string) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{}
	for _, t := range texts {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: items}}}
}

// matrixBlocks is partials/core_schools/matrix_table.html.
func (pg *page) matrixBlocks(ctx context.Context) ([]*screensv1.PageBlock, error) {
	blocks := []*screensv1.PageBlock{textPanel(fmt.Sprintf("Core Schools Matrix (%d Schools)", len(pg.all)),
		"Click a school to view SSA scores and live support counts")}
	if len(pg.shown) == 0 {
		empty := "No Core Schools in your portfolio. Only schools assigned directly to you appear here."
		if pg.f.narrowed() {
			empty = "No Core Schools match these filters. Clear a filter or change the search to widen the list."
		} else if pg.hasTeamCore {
			empty += " View Team Core Oversight"
		}
		return append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: empty}},
			&screensv1.PageBlock{Kind: &screensv1.PageBlock_Pager{Pager: &screensv1.PagePager{}}}), nil
	}
	if pg.tick {
		blocks = append(blocks, textPanel("Select all"))
	}
	rows, err := pg.matrixRows(ctx, pg.shown)
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		blocks = append(blocks, pg.record(r))
	}
	return append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Pager{Pager: pg.matrixPager()}}), nil
}

// matrixPager is the list footer's pager as the feed reads its buttons.
func (pg *page) matrixPager() *screensv1.PagePager {
	p := &screensv1.PagePager{}
	if pg.pages <= 1 {
		return p
	}
	add := func(label string, current bool) {
		p.Pages = append(p.Pages, &screensv1.PagePagerPage{Label: label, Current: current})
	}
	if pg.number > 1 {
		add("Prev", false)
		add("Prev", false)
		add("‹", false)
	}
	for _, n := range elided(pg.number, pg.pages) {
		if n == 0 {
			add("…", false)
		} else {
			add(strconv.Itoa(n), n == pg.number)
		}
	}
	if pg.number < pg.pages {
		add("Next", false)
		add("Next", false)
		add("›", false)
	}
	return p
}

// elided is get_elided_page_range(number, on_each_side=1, on_ends=1), a gap
// as 0.
func elided(number, pages int) []int {
	out := []int{}
	span := func(from, to int) {
		for n := from; n <= to; n++ {
			out = append(out, n)
		}
	}
	if pages <= 4 {
		span(1, pages)
		return out
	}
	if number > 4 {
		span(1, 1)
		out = append(out, 0)
		span(number-1, number)
	} else {
		span(1, number)
	}
	if number < pages-3 {
		span(number+1, number+1)
		out = append(out, 0)
		span(pages, pages)
	} else {
		span(number+1, pages)
	}
	return out
}
