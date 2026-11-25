package weeklyrequest

import (
	"bytes"
	"context"
	"encoding/csv"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// exportRefusal is the view's refusal of a role without data export.
const exportRefusal = "Your role does not include data export."

// exportBook is the export's sheets' headings and the activity types' words.
type exportBook struct {
	RequestHeaders []string          `json:"request_headers"`
	LineHeaders    []string          `json:"line_headers"`
	ActivityTypes  map[string]string `json:"activity_types"`
}

// csvHeaders are _export_weekly_fund_requests_csv's.
var csvHeaders = []string{"Request ID", "Week Start", "Requested By", "Total Amount (UGX)", "Disbursed (UGX)", "Status", "FY"}

// exportLimit is the [:5000] both exports read the requests through.
const exportLimit = 5000

// ExportFile is weekly_fund_requests_view's export: export=csv the filtered
// requests as weekly_fund_requests.csv, export=xlsx (or excel) the requests
// whose week touches the drawer's period and every cost line behind them in
// it. handled is false for an export Go does not read yet.
func (s *Service) ExportFile(ctx context.Context, p auth.Principal, query url.Values) (string, []byte, bool, error) {
	export := strings.ToLower(strings.TrimSpace(query.Get("export")))
	if export != "csv" && export != "xlsx" && export != "excel" {
		return "", nil, false, nil
	}
	r, ok := rules.Roles[p.ActiveRole]
	if !ok || !r.Page {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	if !r.DataExport {
		return "", nil, true, workbook.Refusal(exportRefusal)
	}
	if p.InActingAppointment || strings.EqualFold(strings.TrimSpace(query.Get("format")), "csv") {
		return "", nil, false, nil
	}
	now := s.now()
	today := now.In(kampala)
	fy, err := pageFY(query, today)
	if err != nil {
		return "", nil, false, nil
	}
	a := ask{fy: fy, district: strings.TrimSpace(query.Get("district")), staff: strings.TrimSpace(query.Get("staff")),
		status: strings.TrimSpace(query.Get("status")), query: query}
	if a.staff == rules.EveryoneStaff {
		a.staff, a.everyone = "", true
	}
	sc, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return "", nil, true, err
	}
	base, err := s.scopeFor(ctx, p, sc, a, fy)
	if err != nil {
		return "", nil, true, err
	}
	q := &args{}
	where := base.requests(a, q)
	if export == "csv" {
		body, err := s.requestsCSV(ctx, where, q)
		return "weekly_fund_requests.csv", body, true, err
	}
	periodFY := strings.TrimSpace(query.Get("fy"))
	if periodFY == "" {
		periodFY = schooldirectory.OperationalFY(now)
	}
	fyN, err := strconv.Atoi(periodFY)
	if err != nil {
		return "", nil, false, nil
	}
	start, end, _ := myplan.DrawerPeriod(query, fyN)
	kind := myplan.ReadExportKind(query)
	sheets, ok, err := s.exportSheets(ctx, p, where, q, start, end, kind, now)
	if err != nil || !ok {
		return "", nil, ok, err
	}
	var buf bytes.Buffer
	if err := workbook.Write(&buf, sheets); err != nil {
		return "", nil, true, err
	}
	stem := "weekly-advance-requests-" + fy + "-" + start.Format(time.DateOnly) + "-to-" + end.Format(time.DateOnly)
	return stem + ".xlsx", buf.Bytes(), true, nil
}

// weeklyRequest is one request the export lists.
type weeklyRequest struct {
	id, user, name, status, fy string
	start, end                 time.Time
	total, disbursed           int64
}

func (s *Service) readRequests(ctx context.Context, where string, q *args, extra string) ([]weeklyRequest, error) {
	rows, err := s.db.Query(ctx, `SELECT w.id, COALESCE(w.responsible_user, ''), u.name, COALESCE(w.status, ''), COALESCE(w.fy, ''),
  w.week_start_date, w.week_end_date, COALESCE(w.total_amount, 0)::bigint, COALESCE(w.disbursed_amount, 0)::bigint
FROM weekly_fund_request w LEFT JOIN "user" u ON u.id = w.responsible_user
WHERE `+where+extra+` ORDER BY w.week_start_date DESC LIMIT `+strconv.Itoa(exportLimit), (*q)...)
	if err != nil {
		return nil, fmt.Errorf("weeklyrequest: reading the requests to export: %w", err)
	}
	defer rows.Close()
	var out []weeklyRequest
	for rows.Next() {
		var r weeklyRequest
		var name *string
		if err := rows.Scan(&r.id, &r.user, &name, &r.status, &r.fy, &r.start, &r.end, &r.total, &r.disbursed); err != nil {
			return nil, err
		}
		// names.get(user, user): the account's name, else its id.
		r.name = r.user
		if name != nil {
			r.name = *name
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// requestsCSV is _export_weekly_fund_requests_csv.
func (s *Service) requestsCSV(ctx context.Context, where string, q *args) ([]byte, error) {
	reqs, err := s.readRequests(ctx, where, q, "")
	if err != nil {
		return nil, err
	}
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	w.UseCRLF = true
	cells := func(vs ...workbook.Cell) error { return w.Write(workbook.SafeCSVRow(vs)) }
	head := make([]workbook.Cell, len(csvHeaders))
	for i, h := range csvHeaders {
		head[i] = workbook.Text(h)
	}
	if err := cells(head...); err != nil {
		return nil, err
	}
	for _, r := range reqs {
		if err := cells(workbook.Text(r.id), workbook.Date(r.start), workbook.Text(r.name), workbook.Int(r.total),
			workbook.Int(r.disbursed), workbook.Text(r.status), workbook.Text(r.fy)); err != nil {
			return nil, err
		}
	}
	w.Flush()
	return buf.Bytes(), w.Error()
}

// exportSheets is _export_weekly_fund_requests_xlsx's Requests and Cost
// Lines, or My Plan's table of the lines' activities for a list of schools.
func (s *Service) exportSheets(ctx context.Context, p auth.Principal, where string, q *args, start, end time.Time, kind string,
	now time.Time) ([]workbook.Sheet, bool, error) {
	overlap := " AND w.week_start_date <= " + q.add(end) + "::date AND w.week_end_date >= " + q.add(start) + "::date"
	reqs, err := s.readRequests(ctx, where, q, overlap)
	if err != nil {
		return nil, true, err
	}
	byID := map[string]weeklyRequest{}
	ids := []string{}
	for _, r := range reqs {
		byID[r.id] = r
		ids = append(ids, r.id)
	}
	rows, err := s.db.Query(ctx, `SELECT s.weekly_fund_request_id, a.id, COALESCE(a.activity_type, ''), COALESCE(a.programme_delivery_mode, ''),
  COALESCE(l.planned_date, a.planned_date), COALESCE(sc.school_id, ''), COALESCE(sc.name, ''),
  COALESCE(NULLIF(sd.name, ''), cd.name, ''), COALESCE(cl.name, ''), COALESCE(NULLIF(s.description, ''), s.line_item_type, ''),
  s.quantity, s.unit_cost, s.total_cost
FROM weekly_fund_request_line s
JOIN weekly_fund_request w ON w.id = s.weekly_fund_request_id
JOIN activity_schedule_cost_line l ON l.id = s.activity_budget_line_id
JOIN activity a ON a.id = l.activity_id
LEFT JOIN school sc ON sc.id = a.school_id LEFT JOIN district sd ON sd.id = sc.district_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id LEFT JOIN district cd ON cd.id = cl.district_id
WHERE s.weekly_fund_request_id = ANY($1) AND a.deleted_at IS NULL
ORDER BY w.week_start_date, s.id`, ids)
	if err != nil {
		return nil, true, fmt.Errorf("weeklyrequest: reading the requests' lines: %w", err)
	}
	defer rows.Close()
	book := rules.ExportBook
	txt := workbook.Text
	num := func(n *int64) workbook.Cell {
		if n == nil {
			return workbook.Empty()
		}
		return workbook.Int(*n)
	}
	counted := map[string]int{}
	lineRows := [][]workbook.Cell{}
	activities := []string{}
	for rows.Next() {
		var req, act, typ, mode, code, school, district, cluster, item string
		var day *time.Time
		var qty, unit, total *int64
		if err := rows.Scan(&req, &act, &typ, &mode, &day, &code, &school, &district, &cluster, &item, &qty, &unit, &total); err != nil {
			return nil, true, err
		}
		if day == nil || day.Before(start) || day.After(end) {
			continue
		}
		if !myplan.KeepsKind(kind, typ, mode == "online") {
			continue
		}
		w := byID[req]
		counted[req]++
		activities = append(activities, act)
		label, ok := book.ActivityTypes[typ]
		if !ok {
			label = typ
		}
		lineRows = append(lineRows, []workbook.Cell{txt(w.id), workbook.Date(w.start), txt(w.name), txt(w.status), txt(act),
			workbook.Date(*day), txt(label), txt(code), txt(school), txt(district), txt(cluster), txt(item), num(qty), num(unit), num(total)})
	}
	if err := rows.Err(); err != nil {
		return nil, true, err
	}
	if budgetpage.IsSchoolList(kind) {
		sheets, ported, err := myplan.TableSheets(ctx, s.db, p.Country, activities, kind, now, false)
		return sheets, ported, err
	}
	requestRows := [][]workbook.Cell{}
	for _, r := range reqs {
		if counted[r.id] == 0 {
			continue
		}
		requestRows = append(requestRows, []workbook.Cell{txt(r.id), workbook.Date(r.start), workbook.Date(r.end), txt(r.name),
			txt(r.status), txt(r.fy), workbook.Int(int64(counted[r.id])), workbook.Int(r.total), workbook.Int(r.disbursed)})
	}
	return []workbook.Sheet{
		{Title: "Requests", Headers: book.RequestHeaders, Rows: requestRows,
			NumberFormats: map[int]string{2: "d mmm yyyy", 3: "d mmm yyyy", 8: "#,##0", 9: "#,##0"}},
		{Title: "Cost Lines", Headers: book.LineHeaders, Rows: lineRows,
			NumberFormats: map[int]string{2: "d mmm yyyy", 6: "d mmm yyyy", 14: "#,##0", 15: "#,##0"}},
	}, true, nil
}
