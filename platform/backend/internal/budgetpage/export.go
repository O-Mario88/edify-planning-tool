package budgetpage

import (
	"context"
	"fmt"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// ExportRefusal is budget_export_view's refusal of a role without data
// export.
const ExportRefusal = "Your role does not include data export."

// ExportGate is budget_export_view's two checks: the Budget page's own
// permission, then data export.
func ExportGate(role string) error {
	r, ok := rules.Roles[role]
	if !ok || !r.Page {
		return pagegate.ErrNotAvailable
	}
	if !r.DataExport {
		return workbook.Refusal(ExportRefusal)
	}
	return nil
}

// ExportLine is one cost line of the Budget export with what its sheets
// read of its activity (_EXPORT_LINE_FIELDS, _EXPORT_ACTIVITY_FIELDS).
type ExportLine struct {
	l                                        line
	fiscalYear                               string
	quantity, unitCost                       *int64
	ActivityID, ActivityType, Status, Mode   string
	activityFY, purpose                      string
	activityPlanned                          *time.Time
	schoolCode, schoolName, schoolDistrict   string
	clusterName, clusterDistrict, eventPlace string
	partnerID                                string
}

// ExportLines is services.export_lines before the drawer's kind and status:
// the cost lines the reader's Budget reads for [start, end], by planned
// day. ok is false for a request the export does not read here yet (a
// district or staff narrowing, a reader whose scope the page hands on).
func ExportLines(ctx context.Context, db schooldirectory.Querier, p auth.Principal, query url.Values, start, end time.Time,
	now time.Time) ([]ExportLine, bool, error) {
	for _, key := range []string{"district", "staff"} {
		if strings.TrimSpace(query.Get(key)) != "" {
			return nil, false, nil
		}
	}
	years := []string{schooldirectory.OperationalFY(start)}
	if y := schooldirectory.OperationalFY(end); y != years[0] {
		years = append(years, y)
		sort.Strings(years)
	}
	fyText := strings.TrimSpace(query.Get("fy"))
	if fyText == "" {
		fyText = years[0]
	}
	fy, err := strconv.Atoi(fyText)
	if err != nil {
		return nil, false, nil
	}
	a := ask{fy: fy, isProgramLead: p.ActiveRole == "Program Lead", weekYears: years}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, true, fmt.Errorf("budgetpage: resolving the reader's scope: %w", err)
	}
	// scoped_budget_lines' choice over the budget_scope budget_export_view
	// hands on (blank when the link has none): the admin ledger and the
	// country only when asked by a reader allowed them, a Lead's team when
	// asked, else the reader's own lines.
	s := &Service{db: db}
	var owners []string
	requested := strings.TrimSpace(query.Get("budget_scope"))
	switch {
	case requested == "admin" && (p.ActiveRole == "CountryDirector" || p.ActiveRole == "Admin"):
		owners = []string{}
	case requested == "country" && (scope.CountryScope || in(rules.CountryLedgerRoles, p.ActiveRole)),
		// _workspace_owner_ids: a reader with the country's scope owns every line.
		scope.CountryScope:
		if p.Country != nil {
			a.countryIDs = []string{p.Country.ID}
		} else if several, err := s.multiCountry(ctx); err != nil || several {
			return nil, err == nil, err
		}
	default:
		if owners, err = s.owners(ctx, p, scope, a.isProgramLead && requested == "team"); err != nil {
			return nil, true, err
		}
	}
	where, args := a.lineWhere(owners, start, end)
	rows, err := db.Query(ctx, `
		SELECT l.activity_id, COALESCE(l.responsible_user, ''), COALESCE(l.label, ''), COALESCE(l.cost_setting_key, ''),
		       COALESCE(l.line_item_type, ''), COALESCE(l.amount, 0), COALESCE(l.unit_cost, 0), COALESCE(l.quantity, 0),
		       l.planned_date, l.partner_id,
		       COALESCE(a.activity_type, ''), COALESCE(a.programme_activity_type, ''), COALESCE(a.delivery_type, ''),
		       COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0), COALESCE(a.other_participants, 0),
		       COALESCE(a.expected_participants, 0), COALESCE(a.daily_visit_batch_id, ''),
		       COALESCE(l.fiscal_year, ''), l.quantity, l.unit_cost, COALESCE(a.status, ''), COALESCE(a.programme_delivery_mode, ''),
		       COALESCE(a.fy, ''), COALESCE(a.activity_purpose_text, ''), a.planned_date,
		       COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(sd.name, ''), COALESCE(cl.name, ''),
		       COALESCE(cd.name, ''), COALESCE(ed.name, ''), COALESCE(a.assigned_partner_id, '')
		FROM activity_schedule_cost_line l
		JOIN activity a ON a.id = l.activity_id
		LEFT JOIN school s ON s.id = a.school_id
		LEFT JOIN district sd ON sd.id = s.district_id
		LEFT JOIN cluster cl ON cl.id = a.cluster_id
		LEFT JOIN district cd ON cd.id = cl.district_id
		LEFT JOIN district ed ON ed.id = a.event_district_id
		WHERE `+where+`
		ORDER BY l.planned_date, l.activity_id, l.id`, args...)
	if err != nil {
		return nil, true, fmt.Errorf("budgetpage: reading the export's cost lines: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (ExportLine, error) {
		var e ExportLine
		l := &e.l
		err := row.Scan(&l.activityID, &l.responsibleUser, &l.label, &l.settingKey, &l.lineItemType, &l.amount, &l.unitCost,
			&l.quantity, &l.plannedDate, &l.partnerID, &l.activityType, &l.programmeType, &l.deliveryType,
			&l.teachers, &l.leaders, &l.others, &l.expected, &l.batchID,
			&e.fiscalYear, &e.quantity, &e.unitCost, &e.Status, &e.Mode, &e.activityFY, &e.purpose, &e.activityPlanned,
			&e.schoolCode, &e.schoolName, &e.schoolDistrict, &e.clusterName, &e.clusterDistrict, &e.eventPlace, &e.partnerID)
		e.ActivityID, e.ActivityType = l.activityID, l.activityType
		return e, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("budgetpage: reading the export's cost lines: %w", err)
	}
	return out, true, nil
}

// ExportBook is _budget_export_book: the Activity cost plan, the planned
// activities, their cost lines and the total by activity type.
func ExportBook(ctx context.Context, db schooldirectory.Querier, lines []ExportLine, period string) ([]workbook.Sheet, error) {
	plain := make([]line, len(lines))
	for i, e := range lines {
		plain[i] = e.l
	}
	s := &Service{db: db}
	dayRates, err := s.dayRates(ctx, plain)
	if err != nil {
		return nil, err
	}
	names, err := s.names(ctx, plain)
	if err != nil {
		return nil, err
	}
	partnerIDs := []string{}
	for _, e := range lines {
		if e.partnerID != "" {
			partnerIDs = append(partnerIDs, e.partnerID)
		}
	}
	partners := map[string]string{}
	if len(partnerIDs) > 0 {
		rs, err := db.Query(ctx, `SELECT id, COALESCE(name, '') FROM partner WHERE id = ANY($1)`, partnerIDs)
		if err != nil {
			return nil, fmt.Errorf("budgetpage: reading the partners: %w", err)
		}
		for rs.Next() {
			var id, name string
			if err := rs.Scan(&id, &name); err != nil {
				rs.Close()
				return nil, err
			}
			partners[id] = name
		}
		rs.Close()
	}
	book := rules.ExportBook
	txt, num := workbook.Text, workbook.Int
	day := func(t *time.Time) workbook.Cell {
		if t == nil {
			return workbook.Empty()
		}
		return workbook.Date(*t)
	}
	maybe := func(n *int64) workbook.Cell {
		if n == nil {
			return workbook.Empty()
		}
		return num(*n)
	}
	type activityRow struct {
		cells  []workbook.Cell
		kind   string
		budget int64
	}
	activities := map[string]*activityRow{}
	order := []string{}
	lineRows := [][]workbook.Cell{}
	for _, e := range lines {
		l := e.l
		when := l.plannedDate
		if when == nil {
			when = e.activityPlanned
		}
		kind := label(rules.ActivityTypes, e.ActivityType)
		district := e.schoolDistrict
		for _, d := range []string{e.clusterDistrict, e.eventPlace} {
			if district == "" {
				district = d
			}
		}
		row, seen := activities[e.ActivityID]
		if !seen {
			delivery := []string{}
			if l.deliveryType == "partner" {
				delivery = append(delivery, "Partner")
			}
			if e.Mode == "online" {
				delivery = append(delivery, "Online")
			}
			if len(delivery) == 0 {
				delivery = []string{"Staff"}
			}
			fy := e.activityFY
			if fy == "" {
				fy = e.fiscalYear
			}
			row = &activityRow{kind: kind, cells: []workbook.Cell{txt(e.ActivityID), txt(fy), day(when), txt(kind),
				txt(strings.Join(delivery, " ")), txt(e.purpose), txt(e.schoolCode), txt(e.schoolName), txt(district),
				txt(e.clusterName), txt(names[l.responsibleUser]), txt(partners[e.partnerID]), txt(label(book.StatusLabels, e.Status))}}
			activities[e.ActivityID] = row
			order = append(order, e.ActivityID)
		}
		row.budget += l.amount
		item := l.label
		if item == "" {
			item = l.lineItemType
		}
		lineRows = append(lineRows, []workbook.Cell{txt(e.ActivityID), day(when), txt(kind), txt(e.schoolCode), txt(e.schoolName),
			txt(district), txt(item), txt(l.settingKey), maybe(e.quantity), maybe(e.unitCost), num(l.amount), txt(names[l.responsibleUser])})
	}
	activityRows := [][]workbook.Cell{}
	byKind := map[string][2]int64{}
	var total int64
	for _, id := range order {
		r := activities[id]
		activityRows = append(activityRows, append(r.cells, num(r.budget)))
		k := byKind[r.kind]
		byKind[r.kind] = [2]int64{k[0] + 1, k[1] + r.budget}
		total += r.budget
	}
	kinds := make([]string, 0, len(byKind))
	for k := range byKind {
		kinds = append(kinds, k)
	}
	sort.Strings(kinds)
	summary := [][]workbook.Cell{}
	for _, k := range kinds {
		summary = append(summary, []workbook.Cell{txt(k), num(byKind[k][0]), num(byKind[k][1])})
	}
	summary = append(summary, []workbook.Cell{txt("Total"), num(int64(len(order))), num(total)})
	return []workbook.Sheet{
		costPlanSheet(groups(plain, dayRates), period),
		{Title: "Planned Activities", Headers: book.ActivityHeaders, Rows: activityRows,
			NumberFormats: map[int]string{3: "d mmm yyyy", 14: book.Money}},
		{Title: "Cost Lines", Headers: book.LineHeaders, Rows: lineRows,
			NumberFormats: map[int]string{2: "d mmm yyyy", 10: book.Money, 11: book.Money}},
		{Title: "Summary", Headers: book.SummaryHeaders, Rows: summary, NumberFormats: map[int]string{3: book.Money}},
	}, nil
}

// ExportStatusLabel and ExportKindLabel are the drawer's words for a Plan
// Status and an Activity Type (the period line names them).
func ExportStatusLabel(status string) string {
	return orWord(rules.ExportBook.PlanStatusLabels[status], status)
}
func ExportKindLabel(kind string) string { return orWord(rules.ExportBook.KindLabels[kind], kind) }

// IsSchoolList is one of export_kinds.SCHOOL_LISTS.
func IsSchoolList(kind string) bool { return in(rules.ExportBook.SchoolLists, kind) }

func orWord(s, fallback string) string {
	if s == "" {
		return fallback
	}
	return s
}
