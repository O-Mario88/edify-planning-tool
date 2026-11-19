package iapages

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// StoriesPath is Most Significant Change review.
const StoriesPath = "/ia/stories/"

const (
	storiesPageParam = "register_page"
	storySubmitted   = "submitted"
	storyDraft       = "draft"
)

// story is one change story with what its row shows.
type story struct {
	ID, Title, Author, Status, OutcomeArea, Intervention string
	School, ReviewedBy, ReturnReason                     *string
	Date                                                 time.Time
}

type storyCounts struct{ waiting, approved, spiritual, notAccepted int }

// storyReach is mscs_review.visible_stories as a WHERE clause on mscs_story
// `m` (its school `s` LEFT JOINed), its arguments appended to args: a
// country-bound reader sees the stories of their country's schools and the
// schoolless stories told there or by its staff; another country-scoped
// reader sees every story; anyone else none.
func storyReach(scope schooldirectory.Scope, args *[]any) string {
	if scope.CountryScope && scope.Country != "" {
		*args = append(*args, scope.Country)
		n := len(*args)
		return fmt.Sprintf(`(s.region_id IN (SELECT r.id FROM region r WHERE r.country = $%[1]d)
  OR (m.school_id IS NULL AND m.user_id IN (SELECT sp.user_id FROM staff_profile sp WHERE sp.country = $%[1]d AND sp.deleted_at IS NULL))
  OR (m.school_id IS NULL AND m.country = $%[1]d))`, n)
	}
	if scope.CountryScope {
		return "TRUE"
	}
	return "FALSE"
}

// fyBounds is get_fy_date_range: FY n runs from 1 October of n-1 to 1
// October of n.
func fyBounds(fy string) (time.Time, time.Time) {
	n, _ := strconv.Atoi(fy)
	return time.Date(n-1, time.October, 1, 0, 0, 0, 0, time.UTC), time.Date(n, time.October, 1, 0, 0, 0, 0, time.UTC)
}

// storyStatus is the asked status: submitted when none is asked, any known
// status, and every status ("") otherwise.
func storyStatus(query url.Values) string {
	values, asked := query["status"]
	if !asked || len(values) == 0 {
		return storySubmitted
	}
	status := values[len(values)-1]
	for _, s := range rules.StoryStatuses {
		if s[0] == status {
			return status
		}
	}
	return ""
}

// stories is ia_stories_views.stories_page.
func (s *Service) stories(ctx context.Context, p auth.Principal, role Role, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	now := s.now()
	fyChoices := schooldirectory.FYOptions(now)
	fy := query.Get("fy")
	if !slices.Contains(fyChoices, fy) {
		fy = schooldirectory.OperationalFY(now)
	}
	status := storyStatus(query)
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: resolving the reader's scope: %w", err)
	}
	start, end := fyBounds(fy)
	reachArgs := []any{}
	where := storyReach(scope, &reachArgs)
	const from = `FROM mscs_story m LEFT JOIN school s ON s.id = m.school_id `
	// inYear bounds the story date to the FY, its two arguments appended to
	// args.
	inYear := func(args *[]any) string {
		*args = append(*args, start, end)
		return fmt.Sprintf("m.story_date >= $%d::date AND m.story_date < $%d::date", len(*args)-1, len(*args))
	}

	var c storyCounts
	countArgs := slices.Clone(reachArgs)
	year := inYear(&countArgs)
	countArgs = append(countArgs, rules.SpiritualDomains)
	spiritual := len(countArgs)
	if err := s.db.QueryRow(ctx, fmt.Sprintf(`SELECT
  count(*) FILTER (WHERE m.status = 'submitted'),
  count(*) FILTER (WHERE m.status = 'approved' AND %[1]s),
  count(*) FILTER (WHERE m.status = 'approved' AND %[1]s AND (m.intervention = ANY($%[2]d) OR m.outcome_area IN (
    SELECT a.code FROM impact_outcome_area_domain d JOIN impact_outcome_area a ON a.id = d.area_id WHERE d.intervention = ANY($%[2]d)))),
  count(*) FILTER (WHERE m.status IN ('returned', 'rejected') AND %[1]s)
%[3]sWHERE %[4]s`, year, spiritual, from, where), countArgs...).Scan(&c.waiting, &c.approved, &c.spiritual, &c.notAccepted); err != nil {
		return nil, true, fmt.Errorf("iapages: counting the change stories: %w", err)
	}

	args := slices.Clone(reachArgs)
	listed := where
	if status != "" {
		args = append(args, status)
		listed += fmt.Sprintf(" AND m.status = $%d", len(args))
	}
	if status != storySubmitted {
		listed += " AND " + inYear(&args)
	}
	var total int
	if err := s.db.QueryRow(ctx, `SELECT count(*) `+from+`WHERE `+listed, args...).Scan(&total); err != nil {
		return nil, true, fmt.Errorf("iapages: counting the listed stories: %w", err)
	}
	size := rules.SamplePageSize
	number, pages := closedschools.PageOf(query.Get(storiesPageParam), total, size)
	pageArgs := append(append([]any{}, args...), size, (number-1)*size)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT m.id, m.title, m.user_id, m.status, m.outcome_area, m.intervention, s.name, m.reviewed_by, m.return_reason, m.story_date
%sWHERE %s ORDER BY m.story_date DESC, m.created_at DESC LIMIT $%d OFFSET $%d`, from, listed, len(pageArgs)-1, len(pageArgs)), pageArgs...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the change stories: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (story, error) {
		var x story
		err := r.Scan(&x.ID, &x.Title, &x.Author, &x.Status, &x.OutcomeArea, &x.Intervention, &x.School, &x.ReviewedBy, &x.ReturnReason, &x.Date)
		return x, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the change stories: %w", err)
	}
	ids := []string{}
	for _, x := range list {
		ids = append(ids, x.Author)
		if x.ReviewedBy != nil && *x.ReviewedBy != "" {
			ids = append(ids, *x.ReviewedBy)
		}
	}
	names, err := accountNames(ctx, s.db, ids)
	if err != nil {
		return nil, true, err
	}
	areas, err := s.outcomeAreaLabels(ctx)
	if err != nil {
		return nil, true, err
	}
	page := storiesView{role: role, me: p.UserID, fy: fy, fyChoices: fyChoices, status: status, counts: c,
		list: list, names: names, areas: areas, number: number, pages: pages, total: total}
	return page.response(query), true, nil
}

// outcomeAreaLabels is mscs_review.outcome_area_options as code → label:
// each code's newest version that is not retired or superseded, a draft
// marked so.
func (s *Service) outcomeAreaLabels(ctx context.Context) (map[string]string, error) {
	rows, err := s.db.Query(ctx, `SELECT code, name, status FROM impact_outcome_area
WHERE status <> ALL($1) ORDER BY code, version DESC`, rules.OutcomeAreaHiddenStatuses)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the outcome areas: %w", err)
	}
	defer rows.Close()
	out := map[string]string{}
	for rows.Next() {
		var code, name, status string
		if err := rows.Scan(&code, &name, &status); err != nil {
			return nil, fmt.Errorf("iapages: reading the outcome areas: %w", err)
		}
		if _, seen := out[code]; seen {
			continue
		}
		if status != rules.OutcomeAreaApprovedStatus {
			name += " (not yet approved)"
		}
		out[code] = name
	}
	return out, rows.Err()
}

type storiesView struct {
	role                 Role
	me, fy, status       string
	fyChoices            []string
	counts               storyCounts
	list                 []story
	names, areas         map[string]string
	number, pages, total int
}

// orDash is _cell's text: a dash for nothing.
func orDash(t string) string {
	if t == "" {
		return "—"
	}
	return closedschools.Collapse(t)
}

func statusLabel(status string) string {
	for _, s := range rules.StoryStatuses {
		if s[0] == status {
			return s[1]
		}
	}
	return status
}

// response is pages/ia/stories.html as the feed reads it.
func (v storiesView) response(query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "School progress", Title: "Most Significant Change",
		Description: "Stories of change in partner schools, reviewed by someone other than the person who told them. An approved story counts toward its author's target and as evidence of the outcome it describes."}
	blocks := workspaceStrip(v.role)
	statusOptions := []*screensv1.PageFilterOption{{Value: "", Label: "Every status"}}
	for _, s := range rules.StoryStatuses {
		if s[0] != storyDraft {
			statusOptions = append(statusOptions, &screensv1.PageFilterOption{Value: s[0], Label: s[1]})
		}
	}
	fyOptions := make([]*screensv1.PageFilterOption, 0, len(v.fyChoices))
	for _, o := range v.fyChoices {
		fyOptions = append(fyOptions, &screensv1.PageFilterOption{Value: o, Label: "FY" + o})
	}
	// A draft is listed but has no option, so the select reads nothing
	// chosen.
	shownStatus := v.status
	if shownStatus == storyDraft {
		shownStatus = ""
	}
	blocks = append(blocks,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Change stories at a glance", Metrics: []*screensv1.PageMetric{
			{Label: "Change Stories Awaiting Review", Value: strconv.Itoa(v.counts.waiting), Note: "reviewed by someone other than the author"},
			{Label: "Change Stories Approved This Year", Value: strconv.Itoa(v.counts.approved), Note: "FY" + v.fy + ", " + strconv.Itoa(v.counts.spiritual) + " evidencing spiritual formation"},
			{Label: "Change Stories Returned or Rejected This Year", Value: strconv.Itoa(v.counts.notAccepted), Note: "FY" + v.fy},
		}}}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
			{Name: "status", Value: shownStatus, Caption: "Status", Options: statusOptions},
			{Name: "fy", Value: v.fy, Caption: "Financial year", Options: fyOptions},
		}}}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Most Significant Change stories"}}},
	)
	t := &screensv1.PageTable{}
	if len(v.list) == 0 {
		t.EmptyMessage = "No stories here"
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No stories here Stories reach this list when staff submit them from My Targets or a field debrief."}}}}
	} else {
		for _, c := range []string{"Story", "School", "Told by", "Story date", "Status", "Evidences", "Reviewed by", ""} {
			t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
		}
		for _, x := range v.list {
			t.Rows = append(t.Rows, v.row(x))
		}
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if v.pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(storiesPageParam, v.number, v.pages, v.total, rules.SamplePageSize, query, rules.QueryKeysNotPassed))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: StoriesPath}
}

func (v storiesView) row(x story) *screensv1.PageRow {
	tags := []string{}
	area, ok := v.areas[x.OutcomeArea]
	if !ok {
		area = x.OutcomeArea
	}
	for _, t := range []string{area, rules.InterventionLabels[x.Intervention]} {
		if t != "" {
			tags = append(tags, t)
		}
	}
	status := statusLabel(x.Status)
	if x.ReturnReason != nil && *x.ReturnReason != "" {
		status += ": " + *x.ReturnReason
	}
	author, ok := v.names[x.Author]
	if !ok {
		author = "Staff member"
	}
	reviewer := ""
	if x.ReviewedBy != nil {
		reviewer = v.names[*x.ReviewedBy]
	}
	label := "Open"
	if x.Status == storySubmitted && x.Author != v.me {
		label = "Review"
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		{Text: orDash(x.Title)},
		{Text: orDash(deref(x.School))},
		{Text: orDash(author)},
		{Text: x.Date.Format("2 Jan 2006")},
		{Text: orDash(status)},
		{Text: orDash(strings.Join(tags, " · "))},
		{Text: orDash(reviewer)},
		{Actions: []*screensv1.PageAction{{Key: "button", Label: label, Primary: true, Enabled: true, Href: StoriesPath + x.ID + "/", Drawer: true}}},
	}}
}

// workspaceStrip is partials/_section_nav.html as the feed reads it, for a
// page that draws the IA workspace strip.
func workspaceStrip(role Role) []*screensv1.PageBlock {
	if role.Strip == nil {
		return []*screensv1.PageBlock{}
	}
	tabs := &screensv1.PageLinkTabs{Label: role.Strip.Label, Scrolls: role.Strip.Scrolls}
	for _, t := range role.Strip.Tabs {
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
	}
	return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}}}
}

// SpiritualStoriesBySchool is discipleship_summary's story counts: the
// approved change stories the reader may see that evidence spiritual
// formation (a spiritual SSA domain, or an outcome area read through one),
// told in FY fy about a school, by school.
func SpiritualStoriesBySchool(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope, fy string) (map[string]int, error) {
	args := []any{}
	where := storyReach(scope, &args)
	start, end := fyBounds(fy)
	args = append(args, start, end, rules.SpiritualDomains)
	n := len(args)
	rows, err := db.Query(ctx, fmt.Sprintf(`SELECT m.school_id, count(*) FROM mscs_story m LEFT JOIN school s ON s.id = m.school_id
WHERE %s AND m.status = 'approved' AND m.school_id IS NOT NULL
  AND m.story_date >= $%d::date AND m.story_date < $%d::date
  AND (m.intervention = ANY($%d) OR m.outcome_area IN (
    SELECT a.code FROM impact_outcome_area_domain d JOIN impact_outcome_area a ON a.id = d.area_id WHERE d.intervention = ANY($%d)))
GROUP BY m.school_id`, where, n-2, n-1, n, n), args...)
	if err != nil {
		return nil, fmt.Errorf("iapages: counting the schools' change stories: %w", err)
	}
	out := map[string]int{}
	for rows.Next() {
		var school string
		var count int
		if err := rows.Scan(&school, &count); err != nil {
			rows.Close()
			return nil, fmt.Errorf("iapages: counting the schools' change stories: %w", err)
		}
		out[school] = count
	}
	rows.Close()
	return out, rows.Err()
}
