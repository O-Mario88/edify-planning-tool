package planningpage

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
)

// Path is the page this package answers.
const Path = "/planning"

// Service builds the Planning page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers /planning's Client and Core tabs for p. served is false for
// another path, another tab, a page opened from a priority allocation, and
// a query the existing view cannot read (a page that is not a number).
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	doors, ok := rules.Doors[p.ActiveRole]
	if !ok || !doors.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	if query.Get("priority_allocation") != "" {
		return nil, false, nil
	}
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	operational := schooldirectory.OperationalFY(now)
	f, readable := readFilters(query, operational, scope.CountryScope, now)
	if !readable || !in([]string{"client", "core", "partner", "scheduled", "clusters"}, f.tab) {
		return nil, false, nil
	}
	page, err := s.page(ctx, p, scope, doors, f, operational, now)
	return page, true, err
}

func (s *Service) page(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, doors Doors, f filterState,
	operational string, now time.Time) (*screensv1.GetPageResponse, error) {
	support := clusterpage.SupportRuleOn(p)
	owners := []string{}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" {
			owners = append(owners, id)
		}
	}

	// The portfolio alone: the strip and the filter menus.
	baseB := &sqlb{}
	base := schooldirectory.DirectPortfolio(scope, baseB.arg)
	// The filter menus: the portfolio's districts, and the people who hold
	// its schools by their Program Lead.
	districts := []option{}
	if err := each(ctx, s.db, "districts", `SELECT d.id, COALESCE(d.name, '') FROM district d
WHERE d.id IN (SELECT s.district_id FROM school s WHERE `+base+`) ORDER BY d.name`, func(rows pgx.Rows) error {
		var o option
		if err := rows.Scan(&o.value, &o.label); err != nil {
			return err
		}
		districts = append(districts, o)
		return nil
	}, baseB.args...); err != nil {
		return nil, err
	}
	staff, err := s.staffOptions(ctx, base, baseB.args)
	if err != nil {
		return nil, err
	}
	filters := formFilters(f, schooldirectory.FYOptions(now), districts, staff, support)
	strip, err := stripBlock(ctx, s.db, base, baseB.args, f.dataFY)
	if err != nil {
		return nil, err
	}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: filters, Hidden: map[string]string{"tab": f.tab}}}},
		strip,
	}
	if line, err := workload(ctx, s.db, p, f.fy); err != nil {
		return nil, err
	} else if line != nil {
		blocks = append(blocks, line)
	}
	blocks = append(blocks, tabs(f, filters))

	var rest []*screensv1.PageBlock
	var err2 error
	if f.tab == "clusters" {
		rest, err2 = s.clustersTab(ctx, p, scope, f)
	} else {
		rest, err2 = s.schoolsTab(ctx, scope, doors, f, owners, support, base, baseB.args, operational, now)
	}
	if err2 != nil {
		return nil, err2
	}
	blocks = append(blocks, rest...)
	bar := selection(doors)
	if f.tab == "scheduled" {
		bar = activityBar()
	}
	return &screensv1.GetPageResponse{Header: header(), Blocks: blocks, WebPath: Path, Selection: bar}, nil
}

// schoolsTab is a tab of schools (Client, Core, Assigned to Partner,
// Scheduled): its rows by name or by holder, its pager or empty card.
func (s *Service) schoolsTab(ctx context.Context, scope schooldirectory.Scope, doors Doors, f filterState, owners []string,
	support bool, base string, baseArgs []any, operational string, now time.Time) ([]*screensv1.PageBlock, error) {
	blocks := []*screensv1.PageBlock{}
	b := &sqlb{}
	where := filtered(b, scope, f, owners, support) + " AND " + tableCondition(b, f, support)
	total, err := count(ctx, s.db, "the table", "SELECT count(*) FROM school s WHERE "+where, b.args...)
	if err != nil {
		return nil, err
	}

	// The page's schools, by name or by the people who hold them.
	order := "s.name"
	var directory map[string]*owner
	groupCounts := map[string]int{}
	whereArgs := slices.Clone(b.args)
	if f.group == "owner" {
		ids, err := distinctOwners(ctx, s.db, where, whereArgs)
		if err != nil {
			return nil, err
		}
		if directory, err = ownerDirectory(ctx, s.db, ids); err != nil {
			return nil, err
		}
		ranked := slices.Clone(ids)
		key := func(id string) [2]string {
			if o := directory[id]; o != nil {
				return o.sortKey()
			}
			return [2]string{"￿", "￿"}
		}
		slices.SortStableFunc(ranked, func(a, c string) int {
			ka, kc := key(a), key(c)
			if n := strings.Compare(ka[0], kc[0]); n != 0 {
				return n
			}
			return strings.Compare(ka[1], kc[1])
		})
		order = fmt.Sprintf("COALESCE(array_position(%s::varchar[], s.account_owner_id) - 1, %d), s.name", b.arg(ranked), len(ranked))
		if err := each(ctx, s.db, "group counts", "SELECT s.account_owner_id, count(*) FROM school s WHERE "+where+" GROUP BY s.account_owner_id",
			func(rows pgx.Rows) error {
				var id *string
				var n int
				if err := rows.Scan(&id, &n); err != nil {
					return err
				}
				k := ""
				if id != nil {
					k = *id
				}
				groupCounts[k] = n
				return nil
			}, whereArgs...); err != nil {
			return nil, err
		}
	}
	ids := []string{}
	start := (f.page - 1) * f.perPage
	if err := each(ctx, s.db, "the page", fmt.Sprintf("SELECT s.id FROM school s WHERE %s ORDER BY %s LIMIT %d OFFSET %d",
		where, order, f.perPage, start), func(rows pgx.Rows) error {
		var id string
		if err := rows.Scan(&id); err != nil {
			return err
		}
		ids = append(ids, id)
		return nil
	}, b.args...); err != nil {
		return nil, err
	}
	list, at, err := readSchools(ctx, s.db, ids)
	if err != nil {
		return nil, err
	}
	horizon, err := schoolplanning.Horizon(ctx, s.db, f.dataFY, atoi(operational), schooldirectory.FYOptions(now), now)
	if err != nil {
		return nil, err
	}
	if err := enrich(ctx, s.db, list, at, f.dataFY, operational, horizon, support, now); err != nil {
		return nil, err
	}

	if f.tab == "scheduled" {
		// view_controls.html: the Scheduled tab's List View / Calendar View
		// switch, read as a panel of its two words.
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
			{Kind: &screensv1.PagePanelItem_Text{Text: "List View"}}, {Kind: &screensv1.PagePanelItem_Text{Text: "Calendar View"}},
		}}}})
	}
	pages := (total + f.perPage - 1) / f.perPage
	summary, pageLinks := pager(f, total, pages, "schools")
	if len(list) == 0 && f.tab == "partner" {
		blocks = append(blocks, emptyMessageBlocks(f, "No partner assignments pending.", summary, pageLinks)...)
	} else if len(list) == 0 {
		anyClustered, err := count(ctx, s.db, "clustered schools", `SELECT count(*) FROM (SELECT 1 FROM school s WHERE `+base+`
  AND s.cluster_status = 'clustered' AND s.cluster_id IS NOT NULL AND s.cluster_id <> '' LIMIT 1) x`, baseArgs...)
		if err != nil {
			return nil, err
		}
		blocks = append(blocks, emptyBlocks(f, anyClustered > 0, summary, pageLinks)...)
	} else {
		columns := []string{"ID", "School Name", "Cluster", "Visit Plan Status", "Training Plan Status", "Visit Lock"}
		if support {
			columns = append(columns, "Responsible")
		}
		columns = append(columns, "Actions")
		table := &screensv1.PageTable{}
		for _, c := range columns {
			table.Columns = append(table.Columns, &screensv1.PageColumn{Label: c})
		}
		last := "\x00"
		for _, sc := range list {
			if f.group == "owner" && sc.OwnerID != last {
				last = sc.OwnerID
				table.Rows = append(table.Rows, groupRow(groupLabel(directory[sc.OwnerID]), groupCounts[sc.OwnerID]))
			}
			table.Rows = append(table.Rows, row(sc, doors, support, f.fy))
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}}, pagerBlock(f, summary, pageLinks))
	}
	return blocks, nil
}

// staffOptions is owner_groups.owner_filter_groups over the portfolio,
// flattened as the feed reads the menu: each Program Lead's officers, then
// the officers with none.
func (s *Service) staffOptions(ctx context.Context, base string, args []any) ([]option, error) {
	ids, err := distinctOwners(ctx, s.db, base, args)
	if err != nil {
		return nil, err
	}
	directory, err := ownerDirectory(ctx, s.db, ids)
	if err != nil {
		return nil, err
	}
	entries := []*owner{}
	seen := map[*owner]bool{}
	for _, id := range ids {
		if o := directory[id]; o != nil && !seen[o] {
			seen[o] = true
			entries = append(entries, o)
		}
	}
	slices.SortStableFunc(entries, func(a, c *owner) int {
		ka, kc := a.sortKey(), c.sortKey()
		if n := strings.Compare(ka[0], kc[0]); n != 0 {
			return n
		}
		return strings.Compare(ka[1], kc[1])
	})
	type group struct {
		label  string
		owners []option
	}
	groups := []*group{}
	byLabel := map[string]*group{}
	done := map[string]bool{}
	for _, o := range entries {
		if done[o.profileID] {
			continue
		}
		done[o.profileID] = true
		label := o.plName
		if label == "" {
			label = "No Program Lead"
		}
		g := byLabel[label]
		if g == nil {
			g = &group{label: label}
			byLabel[label] = g
			groups = append(groups, g)
		}
		g.owners = append(g.owners, option{o.profileID, o.name})
	}
	slices.SortStableFunc(groups, func(a, c *group) int {
		an, cn := a.label == "No Program Lead", c.label == "No Program Lead"
		if an != cn {
			if an {
				return 1
			}
			return -1
		}
		return strings.Compare(a.label, c.label)
	})
	out := []option{}
	for _, g := range groups {
		out = append(out, g.owners...)
	}
	return out, nil
}

func atoi(s string) int {
	n := 0
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0
		}
		n = n*10 + int(c-'0')
	}
	return n
}
