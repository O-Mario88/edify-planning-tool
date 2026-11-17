package planningmonitor

import (
	"context"
	"errors"
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
// data form, IA (whose monitors are Planning Oversight tabs) and the
// regional readers hand on; the path without its slash is not a page.
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
	if slices.Contains(page.OversightRoles, p.ActiveRole) || !slices.Contains(page.CountryRoles, p.ActiveRole) {
		return nil, false, nil
	}
	for key, values := range query {
		v := strings.TrimSpace(strings.Join(values, ""))
		switch {
		case key == "fy":
		case key == "view" && (v == "" || strings.ToLower(v) == "planning" || strings.ToLower(v) == "monitor"):
		case v == "":
		default:
			return nil, false, nil
		}
	}
	now := pg.now()
	years := schooldirectory.FYOptions(now)
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		next, err := workplan.NextOpenFY(ctx, pg.db, now.In(nairobi), nairobi)
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
	m, err := ReadCountry(ctx, pg.db, p, fy, now)
	if errors.Is(err, ErrNotDrawn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	ledger, err := m.Ledger(ctx, pg.db)
	if err != nil {
		return nil, true, err
	}
	header := &screensv1.PageHeader{Title: "Planning Monitor",
		Description: "Each Programme Lead's and CCEO's year against the visits it should hold — 280 and 560 — their partner work, " +
			"the schools planned for training, and the schools nobody has planned for yet."}
	return &screensv1.GetPageResponse{Header: header, Blocks: CountryBlocks(m, ledger, years), WebPath: PagePath}, true, nil
}
