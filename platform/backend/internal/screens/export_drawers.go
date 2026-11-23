package screens

import (
	"context"
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The Export options forms of the Budget, Weekly Advance Request, Fund
// Allocation and Planning Oversight pages (budget_views, finance_views and
// oversight_views' export drawers, over export_drawer_context). Only opening
// the form is here; the workbook each one downloads is still the existing
// application's.

const (
	roleCD         = "CountryDirector"
	roleRVP        = "RegionalVicePresident"
	roleRPL        = "RegionalProgramLead"
	roleIA         = "ImpactAssessment"
	roleAccountant = "Accountant"
	rolePC         = "ProjectCoordinator"
	exportGrant    = "data.export"
	everyone       = "all"
)

// exportPages is PAGE_PERMISSIONS for the pages these forms belong to.
var exportPages = map[string][]string{
	"monthly_budget":               {rbac.CCEO, rbac.ProgramLead, roleCD, roleIA, roleAccountant, rbac.Admin, roleRVP, rolePC},
	"consolidated_fund_allocation": {roleCD, roleAccountant, roleIA, roleRVP, rbac.Admin},
	"fund_requests":                {rbac.CCEO, rbac.ProgramLead, roleCD, roleIA, roleAccountant, rolePC, rbac.Admin},
	"team_planning_oversight":      {rbac.ProgramLead, roleCD, roleRVP, roleRPL, roleIA, roleAccountant, rbac.Admin},
	"country_planning_oversight":   {roleCD, roleRVP, roleRPL, roleIA, rbac.Admin},
}

// oversightCountryRoles read the whole country on Planning Oversight (_lens_roles).
var oversightCountryRoles = []string{roleCD, roleRVP, roleIA, roleAccountant, rbac.Admin}

var (
	exportMonths = [][2]string{{"10", "October"}, {"11", "November"}, {"12", "December"}, {"1", "January"}, {"2", "February"}, {"3", "March"},
		{"4", "April"}, {"5", "May"}, {"6", "June"}, {"7", "July"}, {"8", "August"}, {"9", "September"}}
	exportStatuses = [][2]string{{"scheduled", "All scheduled plans"}, {"all", "Scheduled and completed plans"}}
	exportKinds    = [][2]string{{"planned", "Visits, trainings & cluster meetings"}, {"visits_trainings", "Visits & trainings"},
		{"visits", "Visits only"}, {"group_trainings", "Group trainings only"}, {"meetings", "Cluster meetings only"},
		{"online", "Online trainings only"}, {"training_schools", "Schools with Planned Training"},
		{"meeting_schools", "Schools with Planned Cluster Meeting"}, {"core_visits", "Core School Visits"},
		{"client_visits", "Client School Visits"}, {"core_trainings", "Core Schools with Planned Trainings"},
		{"all", "All activities (meetings and events included)"}}
	requestStatuses = [][2]string{{"", "All statuses"}, {"disbursed", "Disbursed"}, {"confirmed_for_advance", "Ready"},
		{"pending_responsible_confirmation", "Draft"}, {"self_funded", "Self-funded"}}
	exportTabKinds = map[string]string{"visits": "visits", "meetings": "meetings", "trainings": "trainings"}
	exportQuarters = map[string][2]int{"Q1": {10, 12}, "Q2": {1, 3}, "Q3": {4, 6}, "Q4": {7, 9}}
	isoWeek        = regexp.MustCompile(`^(\d{4})-W(\d{1,2})$`)
	exportDayZone  = time.FixedZone("EAT", 3*60*60)
)

const planningSubtitle = "Choose the period, then download the planned visits, trainings and cluster meetings in it"

// exportForm is one Export options form.
type exportForm struct {
	path, title, subtitle, pageName, whoseName, whoseLabel, statusLabel string
	pages                                                               []string
	needsExport, finance, planning, country, requests                   bool
}

var exportForms = []exportForm{
	{path: "/budget/export-drawer", title: "Export Budget", pageName: "Monthly Budget", pages: []string{"monthly_budget"}, needsExport: true,
		subtitle: "The Activity cost plan of the period as the Budget page lays it out, with the planned activities and cost lines behind it, as one Excel workbook"},
	{path: "/finance/fund-allocation/export-drawer", pageName: "Consolidated Fund Allocation", pages: []string{"consolidated_fund_allocation"}, finance: true},
	{path: "/fund-requests/weekly/export-drawer", title: "Export Weekly Advance Requests", pageName: "Fund Requests", pages: []string{"fund_requests"}, needsExport: true,
		subtitle: "The requests of the period and the planned activities' cost lines behind them, as one Excel workbook",
		requests: true, statusLabel: "Request Status", whoseName: "staff", whoseLabel: "Whose Requests"},
	{path: "/team-planning-oversight/export-drawer", title: "Export Team Planning Oversight", pageName: "Team Planning Oversight", subtitle: planningSubtitle,
		pages: []string{"team_planning_oversight", "country_planning_oversight"}, needsExport: true, planning: true,
		whoseName: "program_lead", whoseLabel: "Whose Plans"},
	{path: "/country-planning-oversight/export-drawer", title: "Export Country Planning Oversight", pageName: "Team Planning Oversight", subtitle: planningSubtitle,
		pages: []string{"team_planning_oversight", "country_planning_oversight"}, needsExport: true, planning: true, country: true,
		whoseName: "program_lead", whoseLabel: "Whose Plans"},
}

func exportFormFor(path string) (exportForm, bool) {
	path = strings.TrimSuffix(path, "/")
	for _, form := range exportForms {
		if form.path == path {
			return form, true
		}
	}
	return exportForm{}, false
}

func (f exportForm) allowed(p auth.Principal) bool { return f.refusal(p) == "" }

// refusal is the view's page and export gates, in their order and words. An
// acting appointment's withheld pages are not decided here, so it is refused
// rather than guessed.
func (f exportForm) refusal(p auth.Principal) string {
	if p.InActingAppointment {
		return "This export is not available while you are acting in another role."
	}
	if !slices.ContainsFunc(f.pages, func(page string) bool { return slices.Contains(exportPages[page], p.ActiveRole) }) {
		return "Access Denied: Your active role does not have permission to view " + f.pageName + "."
	}
	if f.needsExport && !rbac.Grants(p.ActiveRole, exportGrant) {
		return "Your role does not include data export."
	}
	return ""
}

// exportPeriod is the period the form opens on (drawer_period).
type exportPeriod struct {
	from, to         int
	mode, start, end string
}

func queryMonth(raw string) (int, bool) {
	month, err := strconv.Atoi(strings.TrimSpace(raw))
	return month, err == nil && month >= 1 && month <= 12
}

func fyBounds(fy string) (time.Time, time.Time) {
	year, err := strconv.Atoi(fy)
	if err != nil {
		year = 0
	}
	return time.Date(year-1, 10, 1, 0, 0, 0, 0, time.UTC), time.Date(year, 10, 1, 0, 0, 0, 0, time.UTC)
}

func exportDrawerPeriod(q url.Values, fy string, today time.Time) exportPeriod {
	fyStart, fyEnd := fyBounds(fy)
	found := exportPeriod{from: int(today.Month()), to: int(today.Month()), mode: "month_range"}
	found.start, found.end = fyStart.Format(time.DateOnly), fyEnd.AddDate(0, 0, -1).Format(time.DateOnly)
	period := strings.ToLower(strings.TrimSpace(q.Get("period")))
	from, hasFrom := queryMonth(q.Get("from_month"))
	to, hasTo := queryMonth(q.Get("to_month"))
	month, hasMonth := queryMonth(q.Get("month"))
	quarter, hasQuarter := exportQuarters[strings.ToUpper(strings.TrimSpace(q.Get("quarter")))]
	switch {
	case hasFrom && hasTo:
		found.from, found.to = from, to
	case period == "quarter" && hasQuarter:
		found.from, found.to = quarter[0], quarter[1]
	case period == "week":
		if start, end, ok := exportWeekDates(q, fy, today); ok {
			found.mode, found.start, found.end = "custom_dates", start.Format(time.DateOnly), end.AddDate(0, 0, -1).Format(time.DateOnly)
		}
	case (period == "" || period == "month") && hasMonth:
		found.from, found.to = month, month
	}
	return found
}

// exportWeekDates is _period_filters for a week link: the days it names,
// the end not included.
func exportWeekDates(q url.Values, fy string, today time.Time) (time.Time, time.Time, bool) {
	fyStart, fyEnd := fyBounds(fy)
	switch strings.ToLower(strings.TrimSpace(q.Get("period_type"))) {
	case "fy":
		return fyStart, fyEnd, true
	case "custom_dates":
		return customDates(q)
	case "month_range":
		from, hasFrom := queryMonth(q.Get("from_month"))
		if !hasFrom {
			from = 10
		}
		to := 9
		if hasFrom {
			to = from
		}
		start, end := monthRangeDates(fy, from, to)
		return start, end.AddDate(0, 0, 1), true
	}
	if q.Get("start_date") != "" && q.Get("end_date") != "" {
		return customDates(q)
	}
	reference := fyStart
	if schooldirectory.OperationalFY(today) == fy {
		reference = today
	}
	week := weekStart(strings.TrimSpace(q.Get("week")), reference)
	return week, week.AddDate(0, 0, 7), true
}

func customDates(q url.Values) (time.Time, time.Time, bool) {
	start, errStart := time.Parse(time.DateOnly, strings.TrimSpace(q.Get("start_date")))
	end, errEnd := time.Parse(time.DateOnly, strings.TrimSpace(q.Get("end_date")))
	if errStart != nil || errEnd != nil {
		return time.Time{}, time.Time{}, false
	}
	if start.After(end) {
		start, end = end, start
	}
	return start, end.AddDate(0, 0, 1), true
}

func monthRangeDates(fy string, from, to int) (time.Time, time.Time) {
	position := func(month int) int { return (month + 2) % 12 }
	if position(from) > position(to) {
		from, to = to, from
	}
	year, _ := strconv.Atoi(fy)
	yearOf := func(month int) int {
		if month >= 10 {
			return year - 1
		}
		return year
	}
	return time.Date(yearOf(from), time.Month(from), 1, 0, 0, 0, 0, time.UTC),
		time.Date(yearOf(to), time.Month(to)+1, 0, 0, 0, 0, 0, time.UTC)
}

func weekStart(raw string, reference time.Time) time.Time {
	year, week := reference.ISOWeek()
	if m := isoWeek.FindStringSubmatch(raw); m != nil {
		y, _ := strconv.Atoi(m[1])
		if w, _ := strconv.Atoi(m[2]); w >= 1 && w <= 53 {
			year, week = y, w
		}
	}
	jan4 := time.Date(year, 1, 4, 0, 0, 0, 0, time.UTC)
	return jan4.AddDate(0, 0, -((int(jan4.Weekday())+6)%7)+(week-1)*7)
}

func exportChoice(name, label, kind, value string, choices [][2]string, showWhen ...string) *screensv1.DrawerItem {
	field := &screensv1.DrawerField{Name: name, Label: label, Kind: kind, Value: value}
	for _, c := range choices {
		field.Options = append(field.Options, &screensv1.DrawerOption{Value: c[0], Label: c[1]})
	}
	if len(showWhen) > 0 {
		field.ShowWhen = []*screensv1.DrawerCondition{{Field: "period_type", Values: showWhen}}
	}
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: field}}
}

func exportFYChoices(today time.Time) [][2]string {
	current, _ := strconv.Atoi(schooldirectory.OperationalFY(today))
	out := [][2]string{}
	for year := 2025; year <= max(current+1, 2027); year++ {
		out = append(out, [2]string{strconv.Itoa(year), "FY " + strconv.Itoa(year)})
	}
	return out
}

// drawer draws the form; whose is the "Whose" list a country reader gets.
func (f exportForm) drawer(q url.Values, today time.Time, whose [][2]string) *screensv1.PageDrawer {
	fy := strings.TrimSpace(q.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(today)
	}
	out := &screensv1.PageDrawer{Title: f.title, Subtitle: f.subtitle, HasRequired: true, SubmitLabel: "Download Excel", CancelLabel: "Cancel", CanSubmit: true}
	if f.finance {
		month := strings.TrimSpace(q.Get("month"))
		if month == "" {
			month = "April"
		}
		out.Title = fmt.Sprintf("Export consolidated allocation for %s %s", month, fy)
		out.Items = []*screensv1.DrawerItem{exportChoice("export_mode", "Sections to include", "select", "full", [][2]string{
			{"full", "Full monthly allocation (combined)"}, {"field_only", "Field activity allocation only"}, {"admin_only", "Admin budget only (CD items)"}})}
		return out
	}
	period := exportDrawerPeriod(q, fy, today)
	dateField := func(name, label, value string) *screensv1.DrawerItem {
		return exportChoice(name, label, "date", value, nil, "custom_dates")
	}
	out.Items = []*screensv1.DrawerItem{
		exportChoice("period_type", "Period Customization", "radio", period.mode, [][2]string{
			{"month_range", "From (Month) to (Month)"}, {"custom_dates", "Custom Dates"}, {"fy", "Full FY"}}),
		exportChoice("from_month", "From (Month)", "select", strconv.Itoa(period.from), exportMonths, "month_range"),
		exportChoice("to_month", "To (Month)", "select", strconv.Itoa(period.to), exportMonths, "month_range"),
		dateField("start_date", "Start Date", period.start),
		dateField("end_date", "End Date", period.end),
		exportChoice("fy", "Financial Year", "select", fy, exportFYChoices(today)),
	}
	if len(whose) > 0 {
		out.Items = append(out.Items, exportChoice(f.whoseName, f.whoseLabel, "select", everyone, whose))
	}
	statuses, statusLabel, statusValue := exportStatuses, "Plan Status", exportStatuses[0][0]
	if f.requests {
		statuses, statusLabel, statusValue = requestStatuses, f.statusLabel, ""
	}
	kinds, kind := exportKinds, "planned"
	if f.planning {
		if tab, ok := exportTabKinds[strings.ToLower(strings.TrimSpace(q.Get("activity")))]; ok {
			kind = tab
		}
		if kind == "trainings" {
			at := slices.IndexFunc(exportKinds, func(c [2]string) bool { return c[0] == "group_trainings" }) + 1
			kinds = slices.Insert(slices.Clone(exportKinds), at, [2]string{"trainings", "Trainings only (group and in-school)"})
		}
	}
	out.Items = append(out.Items,
		exportChoice("status", statusLabel, "select", statusValue, statuses),
		exportChoice("activity_type", "Activity Type", "select", kind, kinds))
	return out
}

// exportDrawerInGo answers an Export options form; served is false for any
// other path.
func (s *Service) exportDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	path, rawQuery, _ := strings.Cut(rawPath, "?")
	form, ok := exportFormFor(path)
	if !ok {
		return nil, false, nil
	}
	if reason := form.refusal(p); reason != "" {
		return &screensv1.GetDrawerResponse{Refusal: reason}, true, nil
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return nil, true, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "This export link is not valid.")
	}
	today := s.clock().In(exportDayZone)
	day := time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, time.UTC)
	whose, err := s.exportWhose(ctx, p, form, day)
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.GetDrawerResponse{Drawer: form.drawer(query, day, whose)}, true, nil
}

// exportWhose is the "Whose" list: every officer for a country reader of the
// Weekly Advance Request, each Programme Lead's team on Planning Oversight.
func (s *Service) exportWhose(ctx context.Context, p auth.Principal, form exportForm, now time.Time) ([][2]string, error) {
	var sql string
	var args []any
	label := func(name string) string { return name }
	switch {
	case form.requests:
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
		if err != nil {
			return nil, fmt.Errorf("screens: reading the export reader's scope: %w", err)
		}
		if !scope.CountryScope {
			return nil, nil
		}
		sql = `SELECT sp.user_id, COALESCE(u.name, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL ORDER BY u.name, sp.id`
		return s.exportWhoseRows(ctx, sql, args, [2]string{everyone, "Everyone"}, label)
	case form.planning && (form.country || slices.Contains(oversightCountryRoles, p.ActiveRole)):
		sql = `SELECT sp.id, COALESCE(NULLIF(u.name, ''), u.email, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (u.active_role = $1 OR $1 = ANY(COALESCE(u.roles, '{}'))) ORDER BY u.name, sp.id`
		args = []any{rbac.ProgramLead}
		return s.exportWhoseRows(ctx, sql, args, [2]string{everyone, "Everyone"}, func(name string) string { return name + "'s team" })
	}
	return nil, nil
}

func (s *Service) exportWhoseRows(ctx context.Context, sql string, args []any, first [2]string, label func(string) string) ([][2]string, error) {
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("screens: reading the export's people: %w", err)
	}
	defer rows.Close()
	out := [][2]string{first}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("screens: reading the export's people: %w", err)
		}
		out = append(out, [2]string{id, label(name)})
	}
	return out, rows.Err()
}
