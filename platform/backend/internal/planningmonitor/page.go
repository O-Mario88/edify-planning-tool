package planningmonitor

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workplan"
)

// PagePath is the Planning Monitor on its own (oversight_views.
// planning_monitor_view).
const PagePath = monitorPath

// dashboardSection is where a Programme Lead reads the monitor.
const dashboardSection = "/dashboard#planning-monitor"

// nairobi is the platform's time zone (TIME_ZONE), for the planning year.
var nairobi = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		return time.FixedZone("EAT", 3*60*60)
	}
	return z
}()

// Page answers /planning-monitor/.
type Page struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewPage is the page over db.
func NewPage(db schooldirectory.Querier, now func() time.Time) *Page { return &Page{db: db, now: now} }

// Build draws the Planning tab for a country reader (the Country Director,
// the Admin) and sends a Programme Lead to their dashboard's section. The
// Execution tab, a chosen Lead or gap (whose list files follow-ups), the
// data form and the regional readers hand on; IA, whose monitors are
// Planning Oversight tabs, is sent to the same tab there. The path without
// its slash is not a page.
func (pg *Page) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path == strings.TrimSuffix(PagePath, "/") {
		return nil, true, pagegate.ErrNotAvailable
	}
	if path != PagePath {
		return nil, false, nil
	}
	page := rules.Page
	if !slices.Contains(page.Roles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if p.InActingAppointment {
		return nil, false, nil
	}
	if p.ActiveRole == page.DashboardRole {
		if len(query) > 0 {
			return nil, false, nil
		}
		return &screensv1.GetPageResponse{Redirect: dashboardSection}, true, nil
	}
	if slices.Contains(page.OversightRoles, p.ActiveRole) {
		return toOversight(query)
	}
	region := slices.Contains(page.RegionLensRoles, p.ActiveRole)
	if !region && !slices.Contains(page.CountryLensRoles, p.ActiveRole) {
		return nil, false, nil
	}
	execution := strings.ToLower(strings.TrimSpace(query.Get("view"))) == "execution"
	for key, values := range query {
		v := strings.ToLower(strings.TrimSpace(strings.Join(values, "")))
		switch {
		case key == "fy":
		case key == "view" && (v == "" || v == "planning" || v == "monitor" || v == "execution"):
		case v == "":
		default:
			return nil, false, nil
		}
	}
	countryReader := slices.Contains(page.CountryRoles, p.ActiveRole)
	if !countryReader {
		// A superuser is a country reader whatever their role.
		var superuser bool
		if err := pg.db.QueryRow(ctx, `SELECT COALESCE(is_superuser, FALSE) FROM "user" WHERE id = $1`, p.UserID).Scan(&superuser); err != nil {
			return nil, true, fmt.Errorf("planningmonitor: reading the reader: %w", err)
		}
		if superuser {
			return nil, false, nil
		}
	}
	now := pg.now()
	years := schooldirectory.FYOptions(now)
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" && execution {
		// Execution happens in the running year.
		fy = schooldirectory.OperationalFY(now)
	}
	if fy == "" {
		next, err := workplan.NextOpenFY(ctx, pg.db, p.Country, now.In(nairobi), nairobi)
		if err != nil {
			return nil, true, err
		}
		fy = next
	}
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	if !slices.Contains(years, fy) {
		return nil, false, nil
	}
	read := ReadCountry
	if region {
		read = ReadRegion
	}
	m, err := read(ctx, pg.db, p, fy, now)
	if errors.Is(err, ErrNotDrawn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	if execution {
		t := now.In(nairobi)
		x, err := readExecution(ctx, pg.db, m, fy, time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC), region)
		if err != nil {
			return nil, true, err
		}
		return &screensv1.GetPageResponse{Header: &screensv1.PageHeader{Title: "Planning Monitor",
			Description: "Each Programme Lead's and CCEO's plan as it is delivered, completed with its Salesforce ID and form, and verified — and what is past its date."},
			Blocks: executionBlocks(x, fy, years, countryReader), WebPath: PagePath}, true, nil
	}
	ledger, err := m.Ledger(ctx, pg.db)
	if err != nil {
		return nil, true, err
	}
	header := &screensv1.PageHeader{Title: "Planning Monitor",
		Description: "Each Programme Lead's and CCEO's year against the visits it should hold — 280 and 560 — their partner work, " +
			"the schools planned for training, and the schools nobody has planned for yet."}
	return &screensv1.GetPageResponse{Header: header, Blocks: CountryBlocks(m, ledger, years, countryReader), WebPath: PagePath}, true, nil
}

// toOversight is _to_planning_monitor for a reader who keeps the monitors as
// Planning Oversight tabs: the same query, its view the tab's. Django keeps
// the request's own key order, which url.Values does not, so a query with
// more than one other key, or a key given twice, hands on, as does the data
// form.
func toOversight(query url.Values) (*screensv1.GetPageResponse, bool, error) {
	view := "monitor"
	if strings.ToLower(strings.TrimSpace(query.Get("view"))) == "execution" {
		view = "execution"
	}
	other := []string{}
	for key, values := range query {
		switch {
		case key == "format" || len(values) != 1:
			return nil, false, nil
		case key != "view":
			other = append(other, url.QueryEscape(key)+"="+url.QueryEscape(values[0]))
		}
	}
	if len(other) > 1 {
		return nil, false, nil
	}
	pairs := append(other, "view="+view)
	if _, given := query["view"]; given && len(other) == 1 {
		// Django replaces the view where the request gave it, which may be
		// before or after the other key.
		return nil, false, nil
	}
	return &screensv1.GetPageResponse{Redirect: rules.Page.OversightPath + "?" + strings.Join(pairs, "&")}, true, nil
}
