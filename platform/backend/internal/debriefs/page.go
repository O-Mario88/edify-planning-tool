package debriefs

import (
	"context"
	"errors"
	"fmt"
	"math"
	"net/url"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	_ "time/tzdata" // the page's day is Nairobi's wherever the gateway runs

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// PagePath is the page's path.
const PagePath = "/debriefs"

var ownQuery = []string{"fy", "tab", "page", "district_id", "staff_id", "partner_id", "risk_level", "status", "q", "range_days"}

var plainNumber = regexp.MustCompile(`^\d+$`)

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("debriefs: " + err.Error())
	}
	return z
}()

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService returns the page's builder.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

type ask struct {
	fy, tab, district, staff, partner, risk, status, search string
	fyAsked, fyRange                                        bool
	rangeDays                                               int
	start, end                                              time.Time
}

// debrief is one debrief with what the dashboard reads of it.
type debrief struct {
	id, status, risk, completion, author, role, staff, partner, kind, debriefType, title string
	restricted                                                                           bool
	at                                                                                   time.Time
	schools                                                                              []string
	openCommitments, peerSolutions                                                       int
}

func day(t time.Time) time.Time { return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC) }

// Build answers /debriefs.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != PagePath {
		return nil, false, nil
	}
	if !rules.Pages[p.ActiveRole] {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if !slices.Contains(ownQuery, key) {
			return nil, false, nil
		}
	}
	now := s.now()
	today := day(now.In(zone))
	a := ask{tab: query.Get("tab"), district: query.Get("district_id"), staff: query.Get("staff_id"),
		partner: query.Get("partner_id"), risk: query.Get("risk_level"), status: query.Get("status"), search: query.Get("q")}
	if a.tab == "" {
		a.tab = "all"
	}
	a.fy, a.fyAsked = query.Get("fy"), query.Get("fy") != ""
	if !a.fyAsked {
		a.fy = schooldirectory.OperationalFY(now)
	}
	if pg := query.Get("page"); pg != "" && !plainNumber.MatchString(pg) {
		return nil, false, nil
	}
	switch raw := strings.ToLower(strings.TrimSpace(query.Get("range_days"))); {
	case raw == "fy":
		year, err := strconv.Atoi(a.fy)
		if err != nil {
			return nil, false, nil
		}
		// get_fy_date_range: 1 October of the year before to 1 October.
		a.fyRange = true
		a.start = time.Date(year-1, time.October, 1, 0, 0, 0, 0, time.UTC)
		a.end = time.Date(year, time.October, 1, 0, 0, 0, 0, time.UTC).AddDate(0, 0, -1)
		if today.Before(a.end) {
			a.end = today
		}
	case raw == "":
		a.rangeDays = 30
	case plainNumber.MatchString(raw):
		a.rangeDays, _ = strconv.Atoi(raw)
	default:
		return nil, false, nil
	}
	if !a.fyRange {
		a.start, a.end = today.AddDate(0, 0, -a.rangeDays), today
	}

	sc, err := readScope(ctx, s.db, p, now)
	if errors.Is(err, errHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	sc.filters(a)
	if a.staff != "" {
		sc.where += " AND d.staff_id = " + sc.arg(a.staff)
	}
	if a.partner != "" {
		sc.where += " AND d.partner_id = " + sc.arg(a.partner)
	}
	if a.status != "" {
		sc.where += " AND d.status = " + sc.arg(a.status)
	}

	r := &reader{db: s.db, sc: sc}
	rows, err := r.debriefs(ctx, a.start, a.end, "")
	if err != nil {
		return nil, true, err
	}
	prevStart := a.start.AddDate(0, 0, -int(a.end.Sub(a.start).Hours()/24)-1)
	prevRows, err := r.debriefs(ctx, prevStart, a.start.AddDate(0, 0, -1), "")
	if err != nil {
		return nil, true, err
	}

	blocks := []*screensv1.PageBlock{s.filterBlock(ctx, a, now), stripBlock(rows, prevRows)}
	trend := trendBlock(rows, a.start, a.end)
	donut, err := r.activityDonut(ctx, rows)
	if err != nil {
		return nil, true, err
	}
	challenges, err := r.challenges(ctx, rows)
	if err != nil {
		return nil, true, err
	}
	center, err := r.actionCenter(ctx, p.UserID, today)
	if err != nil {
		return nil, true, err
	}
	table, ok, err := r.table(ctx, p, a)
	if err != nil {
		return nil, true, err
	}
	if !ok {
		return nil, false, nil
	}
	recent, err := r.recent(ctx, now)
	if err != nil {
		return nil, true, err
	}
	solutions, err := r.peerSolutions(ctx, now)
	if err != nil {
		return nil, true, err
	}
	highlights, err := r.highlights(ctx, rows, challenges)
	if err != nil {
		return nil, true, err
	}
	blocks = append(blocks, trend, donut, challengePanel(challenges), center,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: "Team & Partner Debriefs"}},
		table, recent, solutions, riskBlock(rows), highlights)
	// The header's two links, drawn as buttons for every reader
	// (templates/pages/debriefs/dashboard.html).
	h := &screensv1.PageHeader{Eyebrow: "My Work", Title: "Field Debrief Dashboard",
		Description: "Real-time field intelligence from your team and partners to drive action and improve impact.",
		Actions: []*screensv1.PageAction{
			{Key: "weekly_report", Label: "Weekly Report", Enabled: true, Href: "/debriefs/weekly-report"},
			{Key: "new_field_debrief", Label: "New Field Debrief", Primary: true, Enabled: true, Href: "/debriefs/submit"},
		}}
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks, WebPath: PagePath}, true, nil
}

// reader reads the scoped debriefs.
type reader struct {
	db schooldirectory.Querier
	sc *scope
}

// debriefs is the scoped debriefs dated (in Nairobi) from start to end,
// newest first; extra narrows them further.
func (r *reader) debriefs(ctx context.Context, start, end time.Time, extra string) ([]debrief, error) {
	args := append(slices.Clone(r.sc.args), start, end)
	n := len(args)
	sql := fmt.Sprintf(`
		SELECT d.id, d.status, d.risk_level, COALESCE(d.completion_status, ''), d.submitted_by_user_id, d.submitted_by_role,
		       COALESCE(d.staff_id, ''), COALESCE(d.partner_id, ''), d.kind, d.debrief_type, d.title, d.is_restricted_incident,
		       d.date, d.linked_school_ids,
		       (SELECT COUNT(*) FROM daily_debrief_commitment c WHERE c.debrief_id = d.id AND c.status = 'open'),
		       (SELECT COUNT(*) FROM daily_debrief_peer_solution ps WHERE ps.debrief_id = d.id)
		FROM daily_debrief d
		WHERE d.deleted_at IS NULL AND %s
		  AND (d.date AT TIME ZONE 'Africa/Nairobi')::date BETWEEN $%d AND $%d %s
		ORDER BY d.date DESC`, r.sc.where, n-1, n, extra)
	return r.collect(ctx, sql, args...)
}

func (r *reader) collect(ctx context.Context, sql string, args ...any) ([]debrief, error) {
	rows, err := r.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the debriefs: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (debrief, error) {
		var d debrief
		err := row.Scan(&d.id, &d.status, &d.risk, &d.completion, &d.author, &d.role, &d.staff, &d.partner, &d.kind,
			&d.debriefType, &d.title, &d.restricted, &d.at, &d.schools, &d.openCommitments, &d.peerSolutions)
		return d, err
	})
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the debriefs: %w", err)
	}
	return out, nil
}

// base is the scoped debriefs of any date, as a condition.
func (r *reader) base() (string, []any) {
	return "d.deleted_at IS NULL AND " + r.sc.where, slices.Clone(r.sc.args)
}

func (s *Service) filterBlock(ctx context.Context, a ask, now time.Time) *screensv1.PageBlock {
	years := schooldirectory.FYOptions(now)
	fy := &screensv1.PageFilter{Name: "fy", Label: "Fiscal year", Caption: "Financial Year"}
	for _, y := range years {
		fy.Options = append(fy.Options, &screensv1.PageFilterOption{Value: y, Label: "FY " + y})
		if y == a.fy {
			fy.Value = y
		}
	}
	if fy.Value == "" && len(fy.Options) > 0 {
		fy.Value = fy.Options[0].Value
	}
	rng := &screensv1.PageFilter{Name: "range_days", Label: "Range days", Caption: "Range"}
	for _, o := range [][2]string{{"7", "Last 7 Days"}, {"30", "Last 30 Days"}, {"90", "Last 90 Days"}, {"fy", "Full FY " + a.fy}} {
		rng.Options = append(rng.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
		if (a.fyRange && o[0] == "fy") || (!a.fyRange && o[0] == strconv.Itoa(a.rangeDays)) {
			rng.Value = o[0]
		}
	}
	if rng.Value == "" {
		rng.Value = "7"
	}
	district := &screensv1.PageFilter{Name: "district_id", Label: "District ID", Caption: "District",
		Options: []*screensv1.PageFilterOption{{Value: "", Label: "All Districts"}}}
	if rows, err := s.db.Query(ctx, `SELECT id, name FROM district ORDER BY name`); err == nil {
		_ = forEach(rows, func(r pgx.Rows) error {
			var id, name string
			if err := r.Scan(&id, &name); err != nil {
				return err
			}
			district.Options = append(district.Options, &screensv1.PageFilterOption{Value: id, Label: name})
			if id == a.district {
				district.Value = id
			}
			return nil
		})
	}
	risk := &screensv1.PageFilter{Name: "risk_level", Label: "Risk level",
		Options: []*screensv1.PageFilterOption{{Value: "", Label: "Any"}}}
	for _, pair := range rules.RiskLevels {
		if pair[0] == "none" {
			continue
		}
		risk.Options = append(risk.Options, &screensv1.PageFilterOption{Value: pair[0], Label: pair[1]})
		if pair[0] == a.risk {
			risk.Value = pair[0]
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{fy, rng, district, risk}}}}
}

func forEach(rows pgx.Rows, each func(pgx.Rows) error) error {
	defer rows.Close()
	for rows.Next() {
		if err := each(rows); err != nil {
			return err
		}
	}
	return rows.Err()
}

// trendText is _pct_delta drawn as the strip's line under a figure.
func trendText(current, previous int) string {
	if previous == 0 {
		return ""
	}
	change := int(math.RoundToEven(float64(current-previous) / float64(previous) * 100))
	value := fmt.Sprintf("%d%%", abs(change))
	switch {
	case change > 0:
		return "↗ " + value
	case change < 0:
		return "↘ " + value
	}
	return value
}

func abs(n int) int {
	if n < 0 {
		return -n
	}
	return n
}

// counts is _kpis' eight figures over a period's debriefs.
func counts(rows []debrief) [8]int {
	var c [8]int
	for _, d := range rows {
		c[0]++
		switch d.completion {
		case "completed_as_planned":
			c[1]++
		case "partially_completed":
			c[2]++
		case "unsuccessful", "cancelled":
			c[3]++
		}
		if d.status == "action_required" {
			c[4]++
		}
		if d.risk == "critical" {
			c[5]++
		}
		c[6] += d.openCommitments
		c[7] += d.peerSolutions
	}
	return c
}

func stripBlock(rows, prev []debrief) *screensv1.PageBlock {
	now, before := counts(rows), counts(prev)
	strip := &screensv1.PageStrip{Title: "Debrief context"}
	for i, label := range rules.MetricLabels {
		m := &screensv1.PageMetric{Label: label, Value: strconv.Itoa(now[i])}
		if t := trendText(now[i], before[i]); t != "" {
			m.Helper, m.Tone = t, "neutral"
		}
		strip.Metrics = append(strip.Metrics, m)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: strip}}
}

// trendBlock is _trend: each day from start to end, the debriefs submitted,
// completed, needing action and critical, by the day of their UTC time.
func trendBlock(rows []debrief, start, end time.Time) *screensv1.PageBlock {
	days := []time.Time{}
	for d := start; !d.After(end); d = d.AddDate(0, 0, 1) {
		days = append(days, d)
	}
	index := map[time.Time]int{}
	for i, d := range days {
		index[d] = i
	}
	series := [4][]float64{}
	for i := range series {
		series[i] = make([]float64, len(days))
	}
	for _, d := range rows {
		i, ok := index[day(d.at.UTC())]
		if !ok {
			continue
		}
		series[0][i]++
		if d.status == "resolved" || d.status == "closed" {
			series[1][i]++
		}
		if d.status == "action_required" {
			series[2][i]++
		}
		if d.risk == "critical" {
			series[3][i]++
		}
	}
	chart := &screensv1.PageChart{Title: "Debrief Trend Over Time", Horizontal: true}
	for _, d := range days {
		chart.Categories = append(chart.Categories, d.Format("Jan 02"))
	}
	for i, name := range []string{"Submitted", "Completed", "Action Required", "Critical"} {
		chart.Series = append(chart.Series, &screensv1.PageSeries{Name: name, Values: series[i]})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Chart{Chart: chart}}
}

// counter is collections.Counter: counts in the order keys were first met.
type counter struct {
	keys []string
	n    map[string]int
}

func newCounter() *counter { return &counter{n: map[string]int{}} }

func (c *counter) add(k string) {
	if _, ok := c.n[k]; !ok {
		c.keys = append(c.keys, k)
	}
	c.n[k]++
}

// mostCommon is Counter.most_common(limit): by count, ties in the order met.
func (c *counter) mostCommon(limit int) []string {
	keys := slices.Clone(c.keys)
	sort.SliceStable(keys, func(i, j int) bool { return c.n[keys[i]] > c.n[keys[j]] })
	if len(keys) > limit {
		keys = keys[:limit]
	}
	return keys
}

func (c *counter) total() int {
	t := 0
	for _, v := range c.n {
		t += v
	}
	return t
}

func ids(rows []debrief) []string {
	out := make([]string, 0, len(rows))
	for _, d := range rows {
		out = append(out, d.id)
	}
	return out
}

func donutBlock(title, empty string, c *counter, keys []string) *screensv1.PageBlock {
	if c.total() == 0 {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title,
			Items: []*screensv1.PagePanelItem{text(empty)}}}}
	}
	values := []float64{}
	for _, k := range keys {
		values = append(values, float64(c.n[k]))
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Chart{Chart: &screensv1.PageChart{Title: title, Horizontal: true,
		Categories: keys, Series: []*screensv1.PageSeries{{Name: title, Values: values}}}}}
}

// activityDonut is _activity_type_donut: the period's linked activities by
// type, the six commonest.
func (r *reader) activityDonut(ctx context.Context, rows []debrief) (*screensv1.PageBlock, error) {
	byDebrief := map[string][]string{}
	if len(rows) > 0 {
		rs, err := r.db.Query(ctx, `SELECT l.debrief_id, a.activity_type FROM daily_debrief_activity_link l
			LEFT JOIN activity a ON a.id = l.activity_id WHERE l.debrief_id = ANY($1)`, ids(rows))
		if err != nil {
			return nil, fmt.Errorf("debriefs: reading the linked activities: %w", err)
		}
		err = forEach(rs, func(row pgx.Rows) error {
			var debriefID string
			var kind *string
			if err := row.Scan(&debriefID, &kind); err != nil {
				return err
			}
			name := "Other"
			if kind != nil {
				name = label(rules.ActivityTypes, *kind)
			}
			byDebrief[debriefID] = append(byDebrief[debriefID], name)
			return nil
		})
		if err != nil {
			return nil, fmt.Errorf("debriefs: reading the linked activities: %w", err)
		}
	}
	c := newCounter()
	for _, d := range rows {
		for _, name := range byDebrief[d.id] {
			c.add(name)
		}
	}
	return donutBlock("Debriefs by Activity Type", "No linked activities in this period.", c, c.mostCommon(6)), nil
}

// challenges is the period's challenges counted (the Counter
// _top_challenges and the highlights read).
func (r *reader) challenges(ctx context.Context, rows []debrief) (*counter, error) {
	c := newCounter()
	if len(rows) == 0 {
		return c, nil
	}
	rs, err := r.db.Query(ctx, `SELECT debrief_id, challenge_type FROM daily_debrief_challenge WHERE debrief_id = ANY($1)`, ids(rows))
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the challenges: %w", err)
	}
	byDebrief := map[string][]string{}
	err = forEach(rs, func(row pgx.Rows) error {
		var debriefID, kind string
		if err := row.Scan(&debriefID, &kind); err != nil {
			return err
		}
		byDebrief[debriefID] = append(byDebrief[debriefID], kind)
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the challenges: %w", err)
	}
	for _, d := range rows {
		for _, kind := range byDebrief[d.id] {
			c.add(kind)
		}
	}
	return c, nil
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func panel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

func links(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

// challengePanel is the top eight challenges, each with its count and share.
func challengePanel(c *counter) *screensv1.PageBlock {
	top := c.mostCommon(8)
	if len(top) == 0 {
		return panel("Top Challenges Reported", text("No challenges reported this period."))
	}
	total := c.total()
	items := []*screensv1.PagePanelItem{}
	for _, k := range top {
		pct := int(math.RoundToEven(float64(c.n[k]) / float64(total) * 100))
		items = append(items, text(label(rules.ChallengeTypes, k)), text(fmt.Sprintf("%d (%d%%)", c.n[k], pct)))
	}
	return panel("Top Challenges Reported", items...)
}

// actionCenter is _action_center: the reader's open and overdue actions,
// the escalations and their clarifications in scope, and the open
// commitments of every scoped debrief.
func (r *reader) actionCenter(ctx context.Context, user string, today time.Time) (*screensv1.PageBlock, error) {
	where, args := r.base()
	n := len(args)
	var mine, overdue, escalations, clarifications, commitments int
	err := r.db.QueryRow(ctx, fmt.Sprintf(`
		SELECT (SELECT COUNT(*) FROM daily_debrief_action WHERE owner_user_id = $%[1]d AND NOT (status IN ('resolved', 'closed'))),
		       (SELECT COUNT(*) FROM daily_debrief_action WHERE owner_user_id = $%[1]d AND due_date < $%[2]d
		          AND NOT (status IN ('resolved', 'closed'))),
		       (SELECT COUNT(*) FROM daily_debrief d WHERE %[3]s AND d.status = 'escalated'),
		       (SELECT COUNT(*) FROM daily_debrief d WHERE %[3]s AND d.status = 'clarification_requested'
		          AND d.submitted_by_user_id = $%[1]d),
		       (SELECT COUNT(*) FROM daily_debrief_commitment c JOIN daily_debrief d ON d.id = c.debrief_id
		          WHERE %[3]s AND c.status = 'open')`, n+1, n+2, where),
		append(args, user, today)...).Scan(&mine, &overdue, &escalations, &clarifications, &commitments)
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the action centre: %w", err)
	}
	rows := &screensv1.PageDataRows{}
	for _, row := range []struct {
		label string
		n     int
	}{{"Debriefs Requiring My Action", mine}, {"Escalations to Review", escalations},
		{"Clarifications Requested", clarifications}, {"Overdue Actions", overdue}, {"Open Commitments", commitments}} {
		rows.Rows = append(rows.Rows, &screensv1.PageDataRow{Label: row.label, Value: strconv.Itoa(row.n)})
	}
	return panel("Action Center", &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: rows}},
		links(&screensv1.PageLink{Text: "View Action Center →", Href: "/debriefs?tab=escalated"})), nil
}

// tabs is the table's tabs: the review queue for a Programme Lead, then the
// rest.
var tabs = [][2]string{
	{"all", "All Debriefs"}, {"mine", "My Debriefs"}, {"team", "Team Debriefs"}, {"partner", "Partner Debriefs"},
	{"escalated", "Escalated"}, {"peer_solutions", "Peer Solutions"},
}

// table is the team and partner table: every tab with its own rows, the
// asked tab open. ok is false when a tab runs past one page.
func (r *reader) table(ctx context.Context, p auth.Principal, a ask) (*screensv1.PageBlock, bool, error) {
	lead := p.ActiveRole == "Program Lead"
	awaiting := []debrief{}
	if lead && len(r.sc.team) > 0 {
		where, args := r.base()
		args = append(args, r.sc.team, rules.ReviewableStatuses, p.UserID)
		n := len(args)
		var err error
		awaiting, err = r.collect(ctx, fmt.Sprintf(`
			SELECT d.id, d.status, d.risk_level, COALESCE(d.completion_status, ''), d.submitted_by_user_id, d.submitted_by_role,
			       COALESCE(d.staff_id, ''), COALESCE(d.partner_id, ''), d.kind, d.debrief_type, d.title, d.is_restricted_incident,
			       d.date, d.linked_school_ids, 0, 0
			FROM daily_debrief d
			WHERE %s AND d.staff_id = ANY($%d) AND d.status = ANY($%d) AND NOT (d.submitted_by_user_id = $%d)
			ORDER BY d.date DESC`, where, n-2, n-1, n), args...)
		if err != nil {
			return nil, false, err
		}
	}
	labels := slices.Clone(tabs)
	if lead {
		labels = append([][2]string{{"awaiting_review", fmt.Sprintf("Awaiting my review (%d)", len(awaiting))}}, labels...)
	}
	tables := map[string]*screensv1.PageBlock{}
	for _, l := range labels {
		rows := awaiting
		if l[0] != "awaiting_review" {
			var err error
			if rows, err = r.tabRows(ctx, p.UserID, a, l[0]); err != nil {
				return nil, false, err
			}
		}
		if len(rows) > rules.PageSize {
			return nil, false, nil
		}
		t, err := r.tableBlock(ctx, rows, l[0])
		if err != nil {
			return nil, false, err
		}
		tables[l[0]] = t
	}
	return tabSegments(labels, a.tab, tables), true, nil
}

// tabSegments is the table's tabs, each holding its own rows; the asked
// tab is the one open. The existing feed draws every tab with the open
// tab's rows (owner, 2026-11-16: "Fix the tabs"; go-debrief-tabs in
// internal/parity/intended.json).
func tabSegments(labels [][2]string, active string, tables map[string]*screensv1.PageBlock) *screensv1.PageBlock {
	segs := &screensv1.PageSegments{}
	for _, l := range labels {
		segs.Segments = append(segs.Segments, &screensv1.PageSegment{Label: l[1], Active: l[0] == active,
			Blocks: []*screensv1.PageBlock{tables[l[0]]}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Segments{Segments: segs}}
}

// tabRows is _apply_tab: the period's scoped debriefs a tab lists.
func (r *reader) tabRows(ctx context.Context, user string, a ask, tab string) ([]debrief, error) {
	extra := ""
	switch tab {
	case "mine":
		extra = "AND d.submitted_by_user_id = $USER"
	case "team":
		extra = "AND NOT (d.submitted_by_user_id = $USER) AND NOT (d.debrief_type = 'partner')"
	case "partner":
		extra = "AND d.debrief_type = 'partner'"
	case "escalated":
		extra = "AND (d.status IN ('escalated', 'action_required') OR d.risk_level IN ('cd_attention', 'critical', 'hr_attention', 'ia_attention'))"
	case "peer_solutions":
		extra = "AND EXISTS (SELECT 1 FROM daily_debrief_peer_solution ps WHERE ps.debrief_id = d.id)"
	}
	saved := r.sc.args
	defer func() { r.sc.args = saved }()
	if strings.Contains(extra, "$USER") {
		r.sc.args = append(slices.Clone(saved), user)
		extra = strings.ReplaceAll(extra, "$USER", fmt.Sprintf("$%d", len(r.sc.args)))
	}
	return r.debriefs(ctx, a.start, a.end, extra)
}

// tableBlock is partials/debriefs/dashboard_table.html's table.
func (r *reader) tableBlock(ctx context.Context, rows []debrief, tab string) (*screensv1.PageBlock, error) {
	t := &screensv1.PageTable{}
	for _, c := range []string{"Date", "Submitted By", "Role", "Activity Type", "School ID", "School / Cluster / Partner",
		"Status", "Debrief Title", "Action Required", "Risk Level"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	if len(rows) == 0 {
		msg := "No Field Debriefs match these filters."
		if tab == "awaiting_review" {
			msg = "No team debriefs are waiting for your review."
		}
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: msg}}}}
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}, nil
	}
	look, err := r.lookups(ctx, rows)
	if err != nil {
		return nil, err
	}
	for _, d := range rows {
		author := look.names[d.author]
		if author == "" {
			author = "—"
		}
		kind := label(rules.Kinds, d.kind)
		if k, ok := look.firstLink[d.id]; ok {
			kind = k
		}
		school, target := "—", ""
		if d.partner != "" {
			target = look.partners[d.partner]
		}
		if len(d.schools) > 0 {
			if d.schools[0] != "" {
				school = ""
			}
			if target == "" {
				target = look.schools[d.schools[0]]
			}
		}
		if target == "" {
			target = "—"
		}
		title := d.title
		if title == "" {
			title = "(untitled)"
		}
		needed := "—"
		if d.status == "action_required" || d.status == "escalated" {
			needed = "Yes"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: d.at.In(zone).Format("02 Jan 2006")},
			{Text: author},
			{Text: d.role},
			{Text: kind},
			{Text: school},
			{Text: target},
			{Text: label(rules.Statuses, d.status), Tone: "primary", Badge: true},
			{Text: title, Href: "/debriefs/" + d.id},
			{Text: needed},
			{Text: riskLabel(d.risk), Tone: "primary", Badge: true},
		}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}, nil
}

type lookups struct {
	names, partners, schools, firstLink map[string]string
}

// lookups is _table_rows' reads: the authors, the partners and first
// schools named, and each debrief's first linked activity (by link id).
func (r *reader) lookups(ctx context.Context, rows []debrief) (lookups, error) {
	l := lookups{names: map[string]string{}, partners: map[string]string{}, schools: map[string]string{},
		firstLink: map[string]string{}}
	authors, partners, schools := []string{}, []string{}, []string{}
	for _, d := range rows {
		authors = append(authors, d.author)
		if d.partner != "" {
			partners = append(partners, d.partner)
		}
		if len(d.schools) > 0 {
			schools = append(schools, d.schools[0])
		}
	}
	read := func(sql string, into map[string]string, args ...any) error {
		rs, err := r.db.Query(ctx, sql, args...)
		if err != nil {
			return fmt.Errorf("debriefs: reading the table's names: %w", err)
		}
		return forEach(rs, func(row pgx.Rows) error {
			var k, v string
			if err := row.Scan(&k, &v); err != nil {
				return err
			}
			into[k] = v
			return nil
		})
	}
	if err := read(`SELECT id, COALESCE(name, '') FROM "user" WHERE id = ANY($1)`, l.names, authors); err != nil {
		return l, err
	}
	if err := read(`SELECT id, name FROM partner WHERE id = ANY($1) AND deleted_at IS NULL`, l.partners, partners); err != nil {
		return l, err
	}
	if err := read(`SELECT id, name FROM school WHERE id = ANY($1) AND deleted_at IS NULL`, l.schools, schools); err != nil {
		return l, err
	}
	err := read(`SELECT DISTINCT ON (l.debrief_id) l.debrief_id, COALESCE(a.activity_type, '')
		FROM daily_debrief_activity_link l LEFT JOIN activity a ON a.id = l.activity_id
		WHERE l.debrief_id = ANY($1) ORDER BY l.debrief_id, l.id`, l.firstLink, ids(rows))
	if err != nil {
		return l, err
	}
	for k, v := range l.firstLink {
		if v == "" {
			delete(l.firstLink, k)
			continue
		}
		l.firstLink[k] = label(rules.ActivityTypes, v)
	}
	return l, nil
}

// recent is the five newest scoped debriefs, whenever they were made.
func (r *reader) recent(ctx context.Context, now time.Time) (*screensv1.PageBlock, error) {
	where, args := r.base()
	rs, err := r.db.Query(ctx, `SELECT COALESCE(u.name, ''), d.title, d.date FROM daily_debrief d
		LEFT JOIN "user" u ON u.id = d.submitted_by_user_id WHERE `+where+` ORDER BY d.date DESC LIMIT 5`, args...)
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the recent activity: %w", err)
	}
	items := []*screensv1.PagePanelItem{}
	err = forEach(rs, func(row pgx.Rows) error {
		var name, title string
		var at time.Time
		if err := row.Scan(&name, &title, &at); err != nil {
			return err
		}
		if name == "" {
			name = "—"
		}
		items = append(items, text(name), text("submitted a debrief"), text(title+" · "+timesince(at, now)+" ago"))
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the recent activity: %w", err)
	}
	if len(items) == 0 {
		items = append(items, text("No recent activity."))
	}
	return panel("Recent Activity", items...), nil
}

// peerSolutions is _recent_peer_solutions: the five newest on any scoped
// debrief.
func (r *reader) peerSolutions(ctx context.Context, now time.Time) (*screensv1.PageBlock, error) {
	where, args := r.base()
	rs, err := r.db.Query(ctx, `
		SELECT ps.debrief_id, ps.suggestion, COALESCE(array_length(ps.endorsed_by_user_ids, 1), 0), ps.created_at,
		       u.id IS NOT NULL, COALESCE(u.name, '')
		FROM daily_debrief_peer_solution ps LEFT JOIN "user" u ON u.id = ps.author_user_id
		WHERE ps.debrief_id IN (SELECT d.id FROM daily_debrief d WHERE `+where+`)
		ORDER BY ps.created_at DESC LIMIT 5`, args...)
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the peer solutions: %w", err)
	}
	items := []*screensv1.PagePanelItem{}
	err = forEach(rs, func(row pgx.Rows) error {
		var debriefID, suggestion, name string
		var endorsements int
		var at time.Time
		var known bool
		if err := row.Scan(&debriefID, &suggestion, &endorsements, &at, &known, &name); err != nil {
			return err
		}
		if !known {
			name = "—"
		}
		plural := "s"
		if endorsements == 1 {
			plural = ""
		}
		items = append(items, links(&screensv1.PageLink{Text: truncate(suggestion, 80), Href: "/debriefs/" + debriefID}),
			text(fmt.Sprintf("%s · %s ago · %d endorsement%s", name, timesince(at, now), endorsements, plural)))
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the peer solutions: %w", err)
	}
	if len(items) == 0 {
		items = append(items, text("No peer solutions yet this period."))
	}
	return panel("Recent Peer Solutions", items...), nil
}

// riskBlock is _risk_donut: the period's debriefs by risk, in the ladder's
// order.
func riskBlock(rows []debrief) *screensv1.PageBlock {
	c := newCounter()
	for _, d := range rows {
		c.add(d.risk)
	}
	keys, values := []string{}, []float64{}
	for _, pair := range rules.RiskLevels {
		if c.n[pair[0]] > 0 {
			keys = append(keys, pair[1])
			values = append(values, float64(c.n[pair[0]]))
		}
	}
	if c.total() == 0 {
		return panel("Debriefs by Risk Level", text("No debriefs in this period."))
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Chart{Chart: &screensv1.PageChart{Title: "Debriefs by Risk Level",
		Horizontal: true, Categories: keys, Series: []*screensv1.PageSeries{{Name: "Debriefs by Risk Level", Values: values}}}}}
}

// highlights is _intelligence_highlights: the top challenge, the three
// largest open insights, the schools debriefed more than once and the
// critical escalations, six at most.
func (r *reader) highlights(ctx context.Context, rows []debrief, challenges *counter) (*screensv1.PageBlock, error) {
	lines := []string{}
	if top := challenges.mostCommon(1); len(top) > 0 {
		lines = append(lines, fmt.Sprintf("\"%s\" reported in %d debrief(s) this period.",
			label(rules.ChallengeTypes, top[0]), challenges.n[top[0]]))
	}
	rs, err := r.db.Query(ctx, `SELECT description FROM daily_debrief_insight WHERE status = 'open'
		ORDER BY occurrence_count DESC LIMIT 3`)
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the insights: %w", err)
	}
	err = forEach(rs, func(row pgx.Rows) error {
		var d string
		if err := row.Scan(&d); err != nil {
			return err
		}
		lines = append(lines, d)
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the insights: %w", err)
	}
	schools := newCounter()
	critical := 0
	for _, d := range rows {
		for _, s := range d.schools {
			schools.add(s)
		}
		if d.risk == "critical" {
			critical++
		}
	}
	repeats := 0
	for _, k := range schools.keys {
		if schools.n[k] >= 2 {
			repeats++
		}
	}
	if repeats > 0 {
		lines = append(lines, fmt.Sprintf("%d school(s) had more than one debrief this period.", repeats))
	}
	if critical > 0 {
		lines = append(lines, fmt.Sprintf("%d debrief(s) escalated as Critical.", critical))
	}
	if len(lines) > 6 {
		lines = lines[:6]
	}
	items := []*screensv1.PagePanelItem{}
	for _, l := range lines {
		items = append(items, text(l))
	}
	if len(items) == 0 {
		items = append(items, text("No notable patterns detected this period."))
	}
	return panel("Debrief Intelligence Highlights", items...), nil
}

// truncate is the truncatechars filter.
func truncate(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	return string([]rune(s)[:n-1]) + "…"
}

// timesince is django.utils.timesince.timesince(d, now): the two largest
// adjacent units between d and now, years and months by the calendar.
func timesince(d, now time.Time) string {
	d, now = d.UTC(), now.UTC()
	if !now.After(d) || now.Sub(d) < time.Second {
		return "0 minutes"
	}
	totalMonths := (now.Year()-d.Year())*12 + int(now.Month()) - int(d.Month())
	dTime := d.Sub(day(d))
	nowTime := now.Sub(day(now))
	if d.Day() > now.Day() || (d.Day() == now.Day() && dTime > nowTime) {
		totalMonths--
	}
	years, months := totalMonths/12, totalMonths%12
	pivot := d
	if years != 0 || months != 0 {
		py, pm := d.Year()+years, int(d.Month())+months
		if pm > 12 {
			pm -= 12
			py++
		}
		daysIn := []int{31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31}[pm-1]
		pivot = time.Date(py, time.Month(pm), min(daysIn, d.Day()), d.Hour(), d.Minute(), d.Second(), 0, time.UTC)
	}
	remaining := int64(now.Sub(pivot).Seconds())
	parts := []int64{int64(years), int64(months)}
	for _, chunk := range []int64{7 * 86400, 86400, 3600, 60} {
		parts = append(parts, remaining/chunk)
		remaining -= chunk * (remaining / chunk)
	}
	names := []string{"year", "month", "week", "day", "hour", "minute"}
	i := 0
	for i < len(parts) && parts[i] == 0 {
		i++
	}
	if i == len(parts) {
		return "0 minutes"
	}
	out := []string{}
	for depth := 0; i < len(parts) && depth < 2 && parts[i] != 0; i, depth = i+1, depth+1 {
		unit := names[i]
		if parts[i] != 1 {
			unit += "s"
		}
		out = append(out, fmt.Sprintf("%d %s", parts[i], unit))
	}
	return strings.Join(out, ", ")
}
