package cpdlearning

import (
	"context"
	"errors"
	"math"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	_ "time/tzdata" // the page's day is Nairobi's wherever the gateway runs

	"golang.org/x/text/cases"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// PagePath is the page's path.
const PagePath = "/cpd-learning"

// fund_status is read by the page's chips but the view never passes it on,
// so it changes nothing.
var ownQuery = []string{"fy", "country", "role", "status", "reminder", "q", "page", "fund_status"}

var plainNumber = regexp.MustCompile(`^\d+$`)

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("cpdlearning: " + err.Error())
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

// ask is the page's filters as asked.
type ask struct {
	fy, country, role, status, reminder, search string
	page                                        int
}

func readAsk(query url.Values, now time.Time) (ask, bool) {
	for key := range query {
		if !slices.Contains(ownQuery, key) {
			return ask{}, false
		}
	}
	a := ask{
		fy: strings.TrimSpace(query.Get("fy")), country: strings.TrimSpace(query.Get("country")),
		role: strings.TrimSpace(query.Get("role")), status: strings.TrimSpace(query.Get("status")),
		reminder: strings.TrimSpace(query.Get("reminder")), search: strings.TrimSpace(query.Get("q")), page: 1,
	}
	if a.fy == "" {
		a.fy = schooldirectory.OperationalFY(now)
	}
	if !slices.Contains(schooldirectory.FYOptions(now), a.fy) {
		return ask{}, false
	}
	if raw := query.Get("page"); raw != "" {
		if !plainNumber.MatchString(raw) {
			return ask{}, false
		}
		a.page, _ = strconv.Atoi(raw)
		a.page = max(1, a.page)
	}
	return a, true
}

// Build answers /cpd-learning.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != PagePath {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	if p.StaffProfileID == "" || p.InActingAppointment {
		return nil, false, nil
	}
	now := s.now()
	a, ok := readAsk(query, now)
	if !ok {
		return nil, false, nil
	}
	waiting, err := waitingOnOthers(ctx, s.db, p.StaffProfileID)
	if err != nil {
		return nil, true, err
	}
	if waiting {
		return nil, false, nil
	}
	sc, err := readScope(ctx, s.db, p, now)
	if errors.Is(err, errHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	d, ok, err := read(ctx, reader{db: s.db, sc: sc, fy: a.fy}, a, role, now)
	if err != nil || !ok {
		return nil, err != nil, err
	}
	if role.TeamView {
		// A Programme Lead reads the page as their team's development.
		h := &screensv1.PageHeader{Eyebrow: "Team performance", Title: "Team Professional Development",
			Description: "Your officers' development requests: decide the ones waiting on you, then follow up courses that have stalled — FY " + a.fy + "."}
		return &screensv1.GetPageResponse{Header: h, Blocks: d.teamBlocks(), WebPath: PagePath}, true, nil
	}
	desc := "Oversee course tracking, fund accountability, and HR sign-off across every staff member's PD plan — FY " + a.fy
	if sc.locked != "" {
		desc += " · " + sc.locked
	}
	h := &screensv1.PageHeader{Eyebrow: "People & Culture", Title: "Professional Development Dashboard", Description: desc + "."}
	return &screensv1.GetPageResponse{Header: h, Blocks: d.blocks(), WebPath: PagePath}, true, nil
}

// dashboard is get_dashboard's context, as far as the body draws it.
type dashboard struct {
	ask
	role           roleRules
	years          []string
	locked         string
	country        string
	countries      []string
	currency       string
	today          time.Time
	rows           []request // all_rows: the year's requests, searched
	tracker        []trackerRow
	totalCents     int64
	committed      int64
	accounted      int64
	fund           []person
	roleRows       []roleRow
	roleStaff      int
	roleCents      int64
	certsVerified  int
	trackerEntries int
}

type trackerRow struct {
	request
	tag                      string
	staffCents, staffBalance int64
	staffCurrency            string
}

type roleRow struct {
	role, currency string
	perStaff       int64
	count          int
}

// read gathers the dashboard; false hands the page on (a table longer
// than one page).
func read(ctx context.Context, r reader, a ask, role roleRules, now time.Time) (*dashboard, bool, error) {
	d := &dashboard{ask: a, role: role, years: schooldirectory.FYOptions(now), locked: r.sc.locked, today: dayOf(now.In(zone))}
	d.country = a.country
	if d.locked != "" {
		d.country = d.locked
	}
	var err error
	if d.countries, err = r.countryOptions(ctx); err != nil {
		return nil, false, err
	}
	allocs, err := r.allocations(ctx, d.country, a.role)
	if err != nil {
		return nil, false, err
	}
	all, err := r.requests(ctx, d.country, a.role)
	if err != nil {
		return nil, false, err
	}
	d.rows = all
	if a.search != "" {
		needle := cases.Fold().String(a.search)
		d.rows = nil
		for _, req := range all {
			if strings.Contains(cases.Fold().String(req.staffName), needle) || strings.Contains(cases.Fold().String(req.course), needle) {
				d.rows = append(d.rows, req)
			}
		}
	}
	d.currency = defaultCurrency
	if len(allocs) > 0 {
		d.currency = allocs[0].currency
	}
	for _, al := range allocs {
		d.totalCents += al.cents
	}
	for _, req := range d.rows {
		if in(rules.CommittedStatuses, req.status) {
			d.committed += req.requested
		}
		d.accounted += req.accounted
	}
	if ok, err := d.readTracker(ctx, r, allocs); err != nil || !ok {
		return nil, false, err
	}
	if d.fund, err = r.people(ctx, d.country, a.role); err != nil {
		return nil, false, err
	}
	if len(d.fund) > tablePageSize {
		return nil, false, nil
	}
	sortFund(d.fund)
	if err := d.readRoles(ctx, r); err != nil {
		return nil, false, err
	}
	closed := []string{}
	for _, req := range d.rows {
		if req.status == statusClosed {
			closed = append(closed, req.id)
		}
	}
	if d.certsVerified, err = r.certifiedClosed(ctx, closed); err != nil {
		return nil, false, err
	}
	return d, true, nil
}

// readTracker is the tracker's rows under the status and reminder filters,
// each with the person's envelope and what is left of it.
func (d *dashboard) readTracker(ctx context.Context, r reader, allocs []allocation) (bool, error) {
	for _, req := range d.rows {
		tag := d.reminderTag(req)
		if d.status != "" && bucket(req.status) != d.status {
			continue
		}
		if d.reminder != "" && tag != d.reminder {
			continue
		}
		d.tracker = append(d.tracker, trackerRow{request: req, tag: tag})
	}
	d.trackerEntries = len(d.tracker)
	if d.trackerEntries > tablePageSize {
		return false, nil
	}
	byStaff := map[string]allocation{}
	for _, al := range allocs {
		byStaff[al.staffID] = al
	}
	ids := []string{}
	for _, t := range d.tracker {
		if !slices.Contains(ids, t.staffID) {
			ids = append(ids, t.staffID)
		}
	}
	spent, err := r.spent(ctx, ids)
	if err != nil {
		return false, err
	}
	for i := range d.tracker {
		t := &d.tracker[i]
		t.staffCurrency = d.currency
		if al, ok := byStaff[t.staffID]; ok {
			t.staffCents, t.staffCurrency = al.cents, al.currency
		}
		t.staffBalance = t.staffCents - spent[t.staffID]
	}
	return true, nil
}

// readRoles is _role_allocation_settings: each eligible role with staff in
// the country (or a default set for it), its default and its total.
func (d *dashboard) readRoles(ctx context.Context, r reader) error {
	country := d.country
	if country == "" {
		country = defaultCountry
	}
	defaults, err := r.roleDefaults(ctx, country)
	if err != nil {
		return err
	}
	byRole := map[string]allocation{}
	for _, def := range defaults {
		byRole[def.role] = def.allocation
	}
	counts, err := r.roleCounts(ctx, country)
	if err != nil {
		return err
	}
	for _, role := range eligibleRoles() {
		def, set := byRole[role]
		if counts[role] == 0 && !set {
			continue
		}
		row := roleRow{role: role, currency: defaultCurrency, count: counts[role]}
		if set {
			row.perStaff, row.currency = def.cents, def.currency
		}
		d.roleRows = append(d.roleRows, row)
		d.roleStaff += row.count
		d.roleCents += row.perStaff * int64(row.count)
	}
	return nil
}

// reminderTag is _reminder_tag.
func (d *dashboard) reminderTag(r request) string {
	switch {
	case in(rules.PendingCertificateStatuses, r.status):
		if days(r.end, d.today) >= 7 {
			return "overdue"
		}
		return "due"
	case r.status == statusEnrollment && days(d.today, r.start) >= 0 && days(d.today, r.start) <= 7:
		return "due"
	case pendingAccountability(r):
		if days(dayOf(r.updated.UTC()), d.today) >= 14 {
			return "overdue"
		}
		return "due"
	}
	return "none"
}

func pendingAccountability(r request) bool {
	return in(rules.PendingAccountabilityStatuses, r.status) && in(rules.FundedTypes, r.funding)
}

func dayOf(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

// days is (to - from).days between two calendar days.
func days(from, to time.Time) int {
	return int(math.Round(dayOf(to).Sub(dayOf(from)).Hours() / 24))
}
