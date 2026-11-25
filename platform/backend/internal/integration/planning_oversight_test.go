//go:build integration

package integration

import (
	"context"
	"net/http"
	"strconv"
	"strings"
	"testing"

	"connectrpc.com/connect"

	"google.golang.org/protobuf/encoding/protojson"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

const (
	teamPlanningOversight    = "/team-planning-oversight/"
	countryPlanningOversight = "/country-planning-oversight/"
)

// The gateway under test has no existing application behind it, so a page
// Go hands on is "not available here yet" (Unavailable), and a page Go
// refuses is the feed's "not available" (NotFound).
func TestPlanningOversightRefusesTheReadersItsGatesRefuse(t *testing.T) {
	borrowAccount(t, "cceo@edify.org")
	cceo := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	for _, path := range []string{teamPlanningOversight, countryPlanningOversight} {
		for _, query := range []map[string]string{nil, {"view": "trainings"}, {"view": "execution"}} {
			if _, err := pageOf(cceo, path, query); connect.CodeOf(err) != connect.CodeNotFound {
				t.Fatalf("a CCEO opening %s %v: %v, want not found", path, query, err)
			}
		}
	}

	borrowAccount(t, "pl1@edify.org")
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(lead, countryPlanningOversight, nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a Programme Lead opening Country Oversight: %v, want not found", err)
	}
	if _, err := pageOf(lead, teamPlanningOversight, map[string]string{"format": "xml"}); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a format the feed cannot render: %v, want not found", err)
	}
	// A lens Go does not draw is the existing application's.
	if _, err := pageOf(lead, teamPlanningOversight, map[string]string{"view": "monitor"}); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("a Programme Lead opening the monitor lens: %v, want handed on", err)
	}
}

// Piece 2: the Team Plan of a Programme Lead is drawn by Go, with work in
// the period or none; an advanced filter is handed on.
func TestPlanningOversightTeamPlanIsGosWhenTheTeamHasNothingPlanned(t *testing.T) {
	borrowAccount(t, "pl1@edify.org")
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(lead, teamPlanningOversight, map[string]string{"fy": "2026", "district_id": "nowhere"}); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("an advanced filter: %v, want handed on", err)
	}
	busy, err := pageOf(lead, teamPlanningOversight, map[string]string{"fy": "2026", "period": "fy"})
	if err != nil {
		t.Fatalf("a team with FY 2026 work: %v", err)
	}
	// The tiles, the Whole team tab and the Field Plan fold the same work.
	total := busy.GetBlocks()[2].GetStrip().GetMetrics()[0].GetValue()
	tabs := busy.GetBlocks()[3].GetPanel().GetItems()[0].GetLinks().GetLinks()
	if tabs[0].GetText() != "Whole team" || tabs[0].GetCaption() != strings.ReplaceAll(total, ",", "") {
		t.Fatalf("Whole team tab %q, first tile %q", tabs[0].GetCaption(), total)
	}
	if got := busy.GetBlocks()[5].GetPanel().GetItems()[3].GetText(); got != tabs[0].GetCaption()+" planned" {
		t.Fatalf("field plan count = %q, want %s planned", got, tabs[0].GetCaption())
	}
	for _, b := range busy.GetBlocks() {
		if table := b.GetTable(); table != nil && table.GetPager() != nil && len(table.GetRows()) != 50 {
			t.Fatalf("a paged table shows %d rows, want 50", len(table.GetRows()))
		}
	}
	page, err := pageOf(lead, teamPlanningOversight, map[string]string{"fy": "2025", "owner": "mine"})
	if err != nil {
		t.Fatalf("a team with nothing in FY 2025: %v", err)
	}
	if got := page.GetHeader().GetTitle(); got != "Planning Oversight" {
		t.Fatalf("title = %q", got)
	}
	blocks := page.GetBlocks()
	if len(blocks) != 17 {
		t.Fatalf("%d blocks, want 17", len(blocks))
	}
	if got := blocks[0].GetLinkTabs().GetTabs()[0].GetLabel(); got != "Team Plan" {
		t.Fatalf("first lens = %q", got)
	}
	if got := blocks[4].GetSection(); got != "My Work" {
		t.Fatalf("section = %q, want My Work", got)
	}
	if got := blocks[5].GetPanel().GetItems()[1].GetHeading(); !strings.HasSuffix(got, " Field Plan FY 2025") {
		t.Fatalf("field plan heading = %q", got)
	}
	links := blocks[3].GetPanel().GetItems()[0].GetLinks().GetLinks()
	if links[0].GetText() != "Whole team" || links[1].GetText() != "My Work" || links[0].GetCaption() != "0" {
		t.Fatalf("owner tabs = %v", links[:2])
	}
	if got := blocks[2].GetStrip().GetMetrics()[0].GetValue(); got != "0" {
		t.Fatalf("first tile = %q", got)
	}
	if got := blocks[16].GetPanel().GetTitle(); got != "Flagged schools" {
		t.Fatalf("last panel = %q", got)
	}
}

// Piece 3: a country reader's Team Plan is drawn by Go: a tab per
// Programme Lead, the tiles folding the chosen Lead's work (the first tab),
// the chosen Lead's officers as switches with only the open one's tables
// drawn. A lens the reader does not hold falls back to it, as the page does.
func TestPlanningOversightCountryLensIsGos(t *testing.T) {
	borrowAccount(t, "cd@edify.org")
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(director, teamPlanningOversight, map[string]string{"fy": "2026", "period": "fy"})
	if err != nil {
		t.Fatalf("the Country Director's Team Plan: %v", err)
	}
	var strip, leads, switches int
	var total string
	for i, b := range page.GetBlocks() {
		switch {
		case b.GetStrip() != nil:
			strip = i
			total = b.GetStrip().GetMetrics()[0].GetValue()
		case b.GetSegments() != nil:
			switches = i
			open := 0
			for _, s := range b.GetSegments().GetSegments() {
				if len(s.GetBlocks()) > 1 {
					open++
				}
			}
			if open > 1 {
				t.Fatalf("%d officer panels drawn, want at most one", open)
			}
		}
	}
	if got := page.GetBlocks()[strip].GetStrip().GetTitle(); got != "Country overview" {
		t.Fatalf("strip title %q", got)
	}
	tabs := page.GetBlocks()[strip+1].GetPanel().GetItems()[0].GetLinks().GetLinks()
	leads = len(tabs)
	if leads == 0 || tabs[0].GetCaption() != strings.ReplaceAll(total, ",", "") {
		t.Fatalf("%d Lead tabs, the first holding %s, the tile %q", leads, tabs[0].GetCaption(), total)
	}
	if switches == 0 {
		t.Fatal("no officer switches")
	}

	borrowAccount(t, "accountant@edify.org")
	accountant := sessionOf(t, "accountant@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(accountant, teamPlanningOversight, map[string]string{"view": "trainings"}); err != nil {
		t.Fatalf("a lens the Accountant does not hold: %v, want the Team Plan", err)
	}
}

// The Schools & Coverage lens is drawn by Go: the summary line counts the
// schools the planned tables hold, and the two coverage tables split the
// operating schools between a planned session and none.
func TestPlanningOversightCoverageLensIsGos(t *testing.T) {
	borrowAccount(t, "pl1@edify.org")
	lead := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(lead, teamPlanningOversight, map[string]string{"view": "coverage", "fy": "2026", "period": "fy"})
	if err != nil {
		t.Fatalf("the Lead's coverage lens: %v", err)
	}
	blocks := page.GetBlocks()
	var active string
	for _, tab := range blocks[0].GetLinkTabs().GetTabs() {
		if tab.GetActive() {
			active = tab.GetLabel()
		}
	}
	if active == "" || !strings.Contains(strings.ToLower(active), "coverage") {
		t.Fatalf("active lens %q", active)
	}
	summary := blocks[2].GetPanel().GetItems()[0]
	if !strings.HasPrefix(summary.GetText(), summary.GetLead()+" school") || !strings.HasSuffix(summary.GetText(), " with none.") {
		t.Fatalf("summary %q (lead %q)", summary.GetText(), summary.GetLead())
	}
	var titles []string
	for _, b := range blocks {
		if p := b.GetPanel(); p != nil && p.GetTitle() != "" {
			titles = append(titles, p.GetTitle())
		}
		if tbl := b.GetTable(); tbl != nil && len(tbl.GetRows()) > 50 {
			t.Fatalf("a table shows %d rows, past a page", len(tbl.GetRows()))
		}
	}
	want := []string{"Planned Schools · FY 2026", "Schools with Planned Cluster Training or Meeting", "Schools with No Training Planned"}
	if len(titles) != 3 || titles[0] != want[0] || titles[1] != want[1] || titles[2] != want[2] {
		t.Fatalf("panels %q, want %q", titles, want)
	}
}

// Country Oversight's planning-coverage lens is drawn by Go in the existing
// page's design (coverage_page, as the feed reads it): the lens strip, the
// filters, the cards, the school types, the four charts by Programme Lead,
// the drill-down with its capacity and the country's row, and the open
// follow-ups. Each chart's Lead rows add up to the country's own row.
func TestCountryOversightCoverageIsGosInTheExistingDesign(t *testing.T) {
	borrowAccount(t, "cd@edify.org")
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(director, countryPlanningOversight, map[string]string{"fy": "2026", "period": "fy"})
	if err != nil {
		t.Fatalf("the Director's Country Oversight: %v", err)
	}
	if page.GetHeader().GetTitle() != "Country Planning Oversight" || page.GetWebPath() != countryPlanningOversight {
		t.Fatalf("title %q, web path %q", page.GetHeader().GetTitle(), page.GetWebPath())
	}
	blocks := page.GetBlocks()
	if tabs := blocks[0].GetLinkTabs().GetTabs(); len(tabs) != 2 || !tabs[0].GetActive() || tabs[0].GetLabel() != "General Planning" {
		t.Fatalf("lens strip %v", tabs)
	}
	if blocks[1].GetFilters() == nil || blocks[1].GetFilters().GetFilters()[0].GetValue() != "2026" {
		t.Fatalf("filters %v", blocks[1])
	}
	var sections, titles []string
	var visitChart, people *screensv1.PageTable
	for i, b := range blocks {
		if s := b.GetSection(); s != "" {
			sections = append(sections, s)
			if s == "Visits Planned Against Target by Program Lead" {
				visitChart = blocks[i+2].GetTable()
			}
		}
		if p := b.GetPanel(); p != nil && p.GetTitle() != "" {
			titles = append(titles, p.GetTitle())
		}
		if tbl := b.GetTable(); tbl != nil && len(tbl.GetColumns()) > 0 && tbl.GetColumns()[0].GetLabel() == "Name" {
			people = tbl
		}
	}
	wantSections := []string{"Visits Planned Against Target by Program Lead", "Schools With a Visit Planned by Program Lead",
		"Training Planning by Program Lead", "Cluster & Cluster-Meeting Coverage"}
	if strings.Join(sections, "|") != strings.Join(wantSections, "|") {
		t.Fatalf("sections %q", sections)
	}
	if len(titles) != 3 || titles[0] != "Planned and Not Yet Planned by School Type" ||
		titles[1] != "Country → Program Lead → CCEO → Partner Drill-down" || !strings.HasPrefix(titles[2], "Open Follow-ups ") {
		t.Fatalf("panels %q", titles)
	}
	if visitChart == nil || people == nil || len(people.GetRows()) != 1 {
		t.Fatalf("visit chart %v, people %v", visitChart, people)
	}
	country := people.GetRows()[0].GetCells()
	if !strings.HasSuffix(country[0].GetText(), " (Total)") {
		t.Fatalf("country row %q", country[0].GetText())
	}
	planned := 0
	for _, row := range visitChart.GetRows() {
		n, err := strconv.Atoi(row.GetCells()[2].GetText())
		if err != nil {
			t.Fatalf("a Lead's visits planned %q", row.GetCells()[2].GetText())
		}
		planned += n
	}
	if got := strings.SplitN(country[1].GetText(), " ", 2)[0]; strings.ReplaceAll(got, ",", "") != strconv.Itoa(planned) {
		t.Fatalf("the country planned %s, its Leads %d", got, planned)
	}
	// The Country Plan lens is still the existing application's.
	if _, err := pageOf(director, countryPlanningOversight, map[string]string{"view": "plan"}); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("the Country Plan lens: %v, want handed on", err)
	}
}

// The school tables behind Country Oversight's figures are Go's
// (tables.build, country_table.html): the fifteen table tabs, the table
// page's nine filters, fifty rows a page, and as many schools as the page's
// own figure counts, Staff Visit Plans as many visits. A table Go does not
// draw yet is handed on.
func TestCountryOversightSchoolTablesAreGos(t *testing.T) {
	borrowAccount(t, "cd@edify.org")
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	query := map[string]string{"fy": "2026", "period": "fy"}
	page, err := pageOf(director, countryPlanningOversight, query)
	if err != nil {
		t.Fatalf("the page: %v", err)
	}
	var people *screensv1.PageTable
	for _, b := range page.GetBlocks() {
		if tbl := b.GetTable(); tbl != nil && len(tbl.GetColumns()) > 14 && tbl.GetColumns()[0].GetLabel() == "Name" {
			people = tbl
		}
	}
	if people == nil || people.GetColumns()[14].GetLabel() != "Not Yet Planned" {
		t.Fatalf("people table %v", people)
	}
	want := strings.ReplaceAll(people.GetRows()[0].GetCells()[14].GetText(), ",", "")
	table, err := pageOf(director, countryPlanningOversight+"table/not-planned", query)
	if err != nil {
		t.Fatalf("Unplanned Schools: %v", err)
	}
	if table.GetHeader().GetTitle() != "Unplanned Schools" || table.GetWebPath() != countryPlanningOversight+"table/not-planned" {
		t.Fatalf("header %v, web path %q", table.GetHeader(), table.GetWebPath())
	}
	blocks := table.GetBlocks()
	tabs := blocks[0].GetLinkTabs().GetTabs()
	active := 0
	for _, tab := range tabs {
		if tab.GetActive() {
			active++
			if tab.GetLabel() != "Unplanned" {
				t.Fatalf("active tab %q", tab.GetLabel())
			}
		}
	}
	if len(tabs) != 15 || active != 1 || len(blocks[1].GetFilters().GetFilters()) != 9 {
		t.Fatalf("tabs %d (active %d), filters %v", len(tabs), active, blocks[1].GetFilters())
	}
	rows := blocks[2].GetTable()
	if !strings.HasPrefix(rows.GetTitle(), "Unplanned Schools · ") || len(rows.GetRows()) > 50 {
		t.Fatalf("table %q with %d rows", rows.GetTitle(), len(rows.GetRows()))
	}
	if got := strings.ReplaceAll(strings.Fields(rows.GetSubtitle())[0], ",", ""); got != want {
		t.Fatalf("the table lists %s schools, the page counts %s", got, want)
	}
	// Staff Visit Plans lists the visits the page's own figure counts.
	visits, err := pageOf(director, countryPlanningOversight+"table/visits", query)
	if err != nil {
		t.Fatalf("Staff Visit Plans: %v", err)
	}
	planned := strings.ReplaceAll(strings.Fields(people.GetRows()[0].GetCells()[1].GetText())[0], ",", "")
	if got := strings.ReplaceAll(strings.Fields(visits.GetBlocks()[2].GetTable().GetSubtitle())[0], ",", ""); got != planned {
		t.Fatalf("Staff Visit Plans lists %s visits, the page counts %s", got, planned)
	}
	// Every table but Project Schools is Go's; that one is handed on.
	for key, title := range map[string]string{"partners": "Schools Assigned to Partners", "clusters": "Clustered Schools",
		"duplicates": "Schools Planned Twice", "plans": "All Activities"} {
		page, err := pageOf(director, countryPlanningOversight+"table/"+key, query)
		if err != nil || !strings.HasPrefix(page.GetBlocks()[2].GetTable().GetTitle(), title+" · ") {
			t.Fatalf("%s: %v", title, err)
		}
	}
	if _, err := pageOf(director, countryPlanningOversight+"table/projects", query); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("Project Schools: %v, want handed on", err)
	}
}

// Country Oversight's Execution & Completion lens is Go's
// (country_execution, as the feed reads execution_page): the lens strip
// with Execution active, the six cards, the funnel whose Planned is the
// first card's figure, the readings, the requirement tables and the
// timeliness table. Another of the timeliness views is handed on.
func TestCountryExecutionIsGos(t *testing.T) {
	borrowAccount(t, "cd@edify.org")
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(director, countryPlanningOversight, map[string]string{"view": "execution", "fy": "2026", "period": "fy"})
	if err != nil {
		t.Fatalf("the Execution lens: %v", err)
	}
	if page.GetHeader().GetTitle() != "Execution & Completion" {
		t.Fatalf("title %q", page.GetHeader().GetTitle())
	}
	blocks := page.GetBlocks()
	if tabs := blocks[0].GetLinkTabs().GetTabs(); len(tabs) != 2 || !tabs[1].GetActive() {
		t.Fatalf("lens strip %v", tabs)
	}
	cards := blocks[3].GetPanel().GetItems()[0].GetLinks().GetLinks()
	if len(cards) != 6 || cards[0].GetText() != "Planned for the Period" {
		t.Fatalf("cards %v", cards)
	}
	planned := strings.Fields(cards[0].GetCaption())[0]
	var funnel *screensv1.PageTable
	sections := []string{}
	for i, b := range blocks {
		if s := b.GetSection(); s != "" {
			sections = append(sections, s)
			if strings.HasPrefix(s, "Execution Funnel") {
				funnel = blocks[i+2].GetTable()
			}
		}
	}
	if funnel == nil || funnel.GetRows()[0].GetCells()[0].GetText() != "Planned" ||
		funnel.GetRows()[0].GetCells()[1].GetText() != strings.ReplaceAll(planned, ",", "") {
		t.Fatalf("funnel %v, planned %s", funnel, planned)
	}
	if len(sections) < 4 || !strings.HasPrefix(sections[2], "Delivery by Program Lead") ||
		!strings.HasPrefix(sections[3], "Visits Delivered Against Target by Program Lead") {
		t.Fatalf("sections %q", sections)
	}
	schools, err := pageOf(director, countryPlanningOversight, map[string]string{"view": "execution", "table": "school", "fy": "2026", "period": "fy"})
	if err != nil {
		t.Fatalf("the schools view: %v", err)
	}
	if !strings.Contains(pageJSON(t, schools), `"School"`) {
		t.Fatalf("the schools view has no School column: %s", pageJSON(t, schools))
	}
}

// The target note reads the people's targets as My Targets reads them: a
// CCEO's explicit monthly targets for last year, no validated credit.
func TestCountryExecutionTargetNoteReadsMyTargets(t *testing.T) {
	ctx := context.Background()
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM monthly_personal_target WHERE id LIKE 'gcext%'`); err != nil {
			t.Errorf("clearing the targets: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	var staffID string
	if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = 'cceo1@edify.org'`).Scan(&staffID); err != nil {
		t.Fatalf("the CCEO: %v", err)
	}
	if _, err := admin.Exec(ctx, `INSERT INTO monthly_personal_target (created_at, updated_at, id, user_id, fy, month_of_fy, target, area_id)
		SELECT now(), now(), 'gcext' || m, sp.user_id, '2026', m, 2, a.id FROM staff_profile sp, generate_series(1, 12) m, target_area a
		WHERE sp.id = $1 AND a.key = 'school_visits'`, staffID); err != nil {
		t.Fatalf("setting the targets: %v", err)
	}
	borrowAccount(t, "cd@edify.org")
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(director, countryPlanningOversight, map[string]string{"view": "execution", "fy": "2026", "period": "quarter", "quarter": "Q2", "cceo": staffID})
	if err != nil {
		t.Fatalf("the Execution lens: %v", err)
	}
	if body := pageJSON(t, page); !strings.Contains(body, "planned output 6 · validated actual") {
		t.Fatalf("no target note with the quarter's six visits: %s", body)
	}
}

// pageJSON is a page as JSON, for a test that looks for words in it.
func pageJSON(t *testing.T, page *screensv1.GetPageResponse) string {
	t.Helper()
	body, err := protojson.Marshal(page)
	if err != nil {
		t.Fatalf("the page as JSON: %v", err)
	}
	return string(body)
}

// The consolidated tables behind the execution cards are Go's: behind the
// page's gate, the seven tabs, the table with what its rows add up to; a
// key the tables lack is handed on.
func TestCountryExecutionRecordsAreGos(t *testing.T) {
	borrowAccount(t, "cd@edify.org")
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(director, countryPlanningOversight+"execution/records/due", map[string]string{"view": "execution", "fy": "2026", "period": "fy"})
	if err != nil {
		t.Fatalf("the planned activities: %v", err)
	}
	if page.GetHeader().GetTitle() != "Activities Planned" {
		t.Fatalf("title %q", page.GetHeader().GetTitle())
	}
	blocks := page.GetBlocks()
	if tabs := blocks[0].GetLinkTabs().GetTabs(); len(tabs) != 7 || !tabs[0].GetActive() || tabs[6].GetLabel() != "Visits" {
		t.Fatalf("tabs %v", tabs)
	}
	table := blocks[2].GetTable()
	if !strings.HasPrefix(table.GetTitle(), "Activities Planned · ") {
		t.Fatalf("table title %q", table.GetTitle())
	}
	if !strings.Contains(table.GetSubtitle(), " planned delivered · ") {
		t.Fatalf("summary %q", table.GetSubtitle())
	}
	if _, err := pageOf(director, countryPlanningOversight+"execution/records/nonsense", nil); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("an unknown table: %v, want handed on", err)
	}
	borrowAccount(t, "cceo@edify.org")
	cceo := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(cceo, countryPlanningOversight+"execution/records/due", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a CCEO: %v, want not available", err)
	}
}

// The records behind an execution figure open in a drawer Go draws: the
// line with the period and count and the table of activities, behind the
// page's gate.
func TestCountryExecutionDrawerIsGos(t *testing.T) {
	ctx := context.Background()
	borrowAccount(t, "cd@edify.org")
	director := sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken()
	drawers := screensv1connect.NewPageDrawerServiceClient(http.DefaultClient, baseURL)
	path := "/country-planning-oversight/execution/drawer?kind=activities&stage=due&view=execution&fy=2026&period=fy"
	answer, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, director))
	if err != nil {
		t.Fatalf("the drawer: %v", err)
	}
	d := answer.Msg.GetDrawer()
	items := d.GetItems()
	if d.GetTitle() != "Activities planned" || len(items) < 2 || !strings.HasSuffix(items[0].GetText(), "activities") && !strings.HasSuffix(items[0].GetText(), "activity") {
		t.Fatalf("drawer %v", d)
	}
	if items[len(items)-1].GetBlock().GetTable() == nil && items[len(items)-1].GetBlock().GetPager() == nil {
		t.Fatalf("no table of activities: %v", items)
	}
	borrowAccount(t, "cceo@edify.org")
	cceo := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	refused, err := drawers.GetDrawer(ctx, authed(&screensv1.GetDrawerRequest{Path: path}, cceo))
	if err != nil || !strings.HasPrefix(refused.Msg.GetRefusal(), "Access Denied") {
		t.Fatalf("a CCEO: %v %v, want refused", refused, err)
	}
}
