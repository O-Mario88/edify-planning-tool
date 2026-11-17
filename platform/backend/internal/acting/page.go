package acting

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// PagePath is Acting Leadership (acting_views.acting_leadership_view).
const PagePath = "/acting-leadership"

// pageSize is each table's page (TABLE_PAGE_SIZE).
const pageSize = 50

// pageKeys are the query keys the page reads (each table's page).
var pageKeys = []string{"current_page", "upcoming_page", "history_page"}

// pageRoles are the roles the page opens to (export_acting_policy).
var pageRoles = func() []string {
	var document struct {
		PageRoles []string `json:"page_roles"`
	}
	if err := json.Unmarshal(policyJSON, &document); err != nil || len(document.PageRoles) == 0 {
		panic(fmt.Sprintf("acting: the embedded page roles are unreadable: %v", err))
	}
	return document.PageRoles
}()

// Page draws the Acting Leadership page from the board.
type Page struct{ service *Service }

// NewPage is the page over its own read of the appointments (it neither
// notifies nor issues tokens).
func NewPage(pool *pgxpool.Pool, now func() time.Time) *Page {
	return &Page{service: NewService(NewStore(pool), now, nil, nil)}
}

// Build answers /acting-leadership for a reader the page opens to. A table
// running past a page and a query key the page does not read hand on.
func (pg *Page) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if strings.TrimSuffix(path, "/") != PagePath {
		return nil, false, nil
	}
	if !slices.Contains(pageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if !slices.Contains(pageKeys, key) {
			return nil, false, nil
		}
	}
	board, err := pg.service.Board(ctx, p)
	if err != nil {
		return nil, true, err
	}
	if len(board.Current) > pageSize || len(board.Upcoming) > pageSize || len(board.History) > pageSize {
		return nil, false, nil
	}
	header := &screensv1.PageHeader{
		Title: "Acting Leadership",
		Description: "Who is acting as Program Lead or Country Director, for which month, and who appointed them. " +
			"An appointment gives operational access for the month and ends with it; nobody's permanent role or reporting line changes.",
	}
	if board.CanAppointLabel != "" {
		label := "Appoint " + board.CanAppointLabel
		header.Actions = []*screensv1.PageAction{{Key: strings.ReplaceAll(strings.ToLower(label), " ", "_"), Label: label,
			Primary: true, Enabled: true, Href: PagePath + "/appoint", Drawer: true}}
	}
	return &screensv1.GetPageResponse{Header: header, WebPath: PagePath, Blocks: []*screensv1.PageBlock{
		appointmentTable("Current", "active", "Nobody is acting this month.", "Period", false, board.Current),
		appointmentTable("Upcoming", "scheduled", "No appointment is scheduled.", "Month", false, board.Upcoming),
		appointmentTable("History", "ended or cancelled", "No acting appointment has ended yet.", "Period", true, board.History),
	}}, true, nil
}

// shortPeriod is short_period_label: "1 – 30 Nov 2026".
func shortPeriod(month string) string {
	start, end, err := parseMonth(month)
	if err != nil {
		return month
	}
	return fmt.Sprintf("%d – %d %s", start.Day(), end.Day(), start.Format("Jan 2006"))
}

// appointmentTable is one of the page's tables (partials/acting/_rows.html).
func appointmentTable(title, summary, empty, period string, appointedBy bool, rows []*identityv1.ActingAppointment) *screensv1.PageBlock {
	t := &screensv1.PageTable{Title: title, Subtitle: fmt.Sprintf("%d %s", len(rows), summary)}
	if len(rows) == 0 {
		t.EmptyMessage = empty
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
	}
	named := "Scope"
	if appointedBy {
		named = "Appointed by"
	}
	for _, label := range []string{"Person", "Permanent role", "Acting role", period, named, "Status"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: label})
	}
	t.Columns = append(t.Columns, &screensv1.PageColumn{Numeric: true})
	for _, a := range rows {
		when := shortPeriod(a.Month)
		if period == "Month" {
			when = a.MonthLabel
		}
		who := a.ScopeLabel
		if appointedBy {
			who = a.AppointedByName
		}
		actions := []*screensv1.PageAction{{Key: "menu", Label: "View record", Enabled: true, Href: PagePath + "/" + a.Id, Drawer: true}}
		if a.CanChangeMonth {
			actions = append(actions, &screensv1.PageAction{Key: "menu", Label: "Change month", Enabled: true, Href: PagePath + "/" + a.Id + "/reschedule", Drawer: true})
		}
		if a.CanCancel {
			actions = append(actions, &screensv1.PageAction{Key: "menu", Label: "Cancel appointment", Enabled: true, Href: PagePath + "/" + a.Id + "/cancel", Drawer: true})
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: a.AppointeeName}, {Text: a.AppointeeRole}, {Text: a.ShortLabel}, {Text: when}, {Text: who},
			{Text: a.StateLabel, Tone: "primary", Badge: true}, {Actions: actions},
		}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}
