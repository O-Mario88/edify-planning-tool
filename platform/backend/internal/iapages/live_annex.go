package iapages

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// The live evidence annex (ia_outcome_views.impact_report_download): today's
// project cohort evidence for a period, labelled a draft, with who generated
// it and a hash of its rows. The dashboard's Impact reports view offers it.

// AnnexPath is the annex download's path, which the web sends to the quick
// export with the form's fields as its query.
const AnnexPath = annexKey

// RowKeys are reports.ROW_KEYS: the columns of an annex's evidence rows.
var RowKeys = []string{"assignment_id", "school_id", "school", "owner_id", "owner", "project_id", "project", "intervention_code",
	"intervention", "state", "status", "measured", "baseline", "follow_up", "delta", "baseline_date", "follow_up_date",
	"baseline_id", "follow_up_id", "mapping_version", "due", "action"}

// liveAnnexKeys are the view's own ROW_KEYS (ia_outcome_views), not the
// frozen annex's.
var liveAnnexKeys = []string{"project", "project_id", "school", "school_id", "intervention", "status", "baseline", "follow_up",
	"delta", "baseline_date", "follow_up_date", "baseline_id", "follow_up_id", "mapping_version", "due", "owner", "action"}

// annexCounts are the summary figures the annex lists, in its order.
var annexCounts = []string{"total", "unique_schools", "measured", "unmeasured", "improved", "declined", "maintained",
	"no_change", "baseline_missing", "overdue"}

const (
	annexExportRefusal = "Export permission required."
	annexAllPeriods    = "All recorded project enrolments; each uses its own assessment window"
)

// CSVCell is reports.csv_value as the CSV writer writes it: nothing for no
// value, Yes or No, a number as Python prints it, and text a spreadsheet
// would read as a formula behind an apostrophe.
func CSVCell(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case bool:
		if x {
			return "Yes"
		}
		return "No"
	case json.Number:
		return x.String()
	case int:
		return strconv.Itoa(x)
	case float64:
		return pyFloatRepr(x)
	}
	text := fmt.Sprint(v)
	trimmed := strings.TrimLeft(text, " \t\n\r\x0b\x0c")
	if strings.HasPrefix(trimmed, "=") || strings.HasPrefix(trimmed, "+") || strings.HasPrefix(trimmed, "-") ||
		strings.HasPrefix(trimmed, "@") || strings.HasPrefix(text, "\t") || strings.HasPrefix(text, "\r") || strings.HasPrefix(text, "\n") {
		return "'" + text
	}
	return text
}

// annexPeriod is _period: the financial year's dates, narrowed by the dates
// given, and the period's words.
func annexPeriod(query url.Values, now time.Time) (*time.Time, *time.Time, string, error) {
	fy := strings.TrimSpace(query.Get("fy"))
	var start, end *time.Time
	if fy != "" {
		if !slices.Contains(schooldirectory.FYOptions(now), fy) {
			return nil, nil, "", workbook.BadRequest("Choose a financial year from the list.")
		}
		start, end = periodBounds(SnapshotReport{FY: fy})
	}
	for _, key := range []string{"period_start", "period_end"} {
		raw := strings.TrimSpace(query.Get(key))
		if raw == "" {
			continue
		}
		chosen, err := time.Parse(time.DateOnly, raw)
		if err != nil {
			return nil, nil, "", workbook.BadRequest("Period dates must be dates (YYYY-MM-DD).")
		}
		switch {
		case key == "period_start" && (start == nil || chosen.After(*start)):
			start = &chosen
		case key == "period_end" && (end == nil || chosen.Before(*end)):
			end = &chosen
		}
	}
	if start != nil && end != nil && start.After(*end) {
		return nil, nil, "", workbook.BadRequest("The period must start before it ends.")
	}
	if start == nil && end == nil {
		return nil, nil, annexAllPeriods, nil
	}
	from, to := "the start", "today"
	if start != nil {
		from = start.Format(time.DateOnly)
	}
	if end != nil {
		to = end.Format(time.DateOnly)
	}
	label := from + " to " + to
	if fy != "" {
		label = "FY" + fy + ": " + label
	}
	return start, end, label, nil
}

// LiveAnnexFile is impact_report_download's file for p and the audit row
// its download writes (iareports writes it). Handled false for an acting
// reader, whose cover the page gate decides.
func (s *Service) LiveAnnexFile(ctx context.Context, p auth.Principal, query url.Values) (string, []byte, audit.Entry, bool, error) {
	none := audit.Entry{}
	if p.InActingAppointment {
		return "", nil, none, false, nil
	}
	if role, ok := rules.Pages[DashboardPath].Roles[p.ActiveRole]; !ok || !role.Page {
		return "", nil, none, true, pagegate.ErrNotAvailable
	}
	if !slices.Contains(rules.ExportRoles, p.ActiveRole) {
		return "", nil, none, true, workbook.Refusal(annexExportRefusal)
	}
	now := s.now()
	start, end, period, err := annexPeriod(query, now)
	if err != nil {
		return "", nil, none, true, err
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return "", nil, none, true, err
	}
	project := query.Get("project")
	w := outcomeWorkspace{scopeLabel: scope.Country}
	if w.scopeLabel == "" {
		w.scopeLabel = "Assigned access scope"
	}
	if !scope.SummaryOnly {
		schools, sargs := activeSchools(scope)
		if w, err = s.workspace(ctx, scope, schools, sargs, project, now); err != nil {
			return "", nil, none, true, err
		}
	}
	rows, undated := rowsInPeriod(w.rows, start, end)
	summary := summariseRows(rows)
	data := annexDataRows(rows)
	hash, err := annexHash(data)
	if err != nil {
		return "", nil, none, true, err
	}
	var name string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(name, '') FROM "user" WHERE id = $1`, p.UserID).Scan(&name); err != nil {
		return "", nil, none, true, fmt.Errorf("iapages: reading the reader's name: %w", err)
	}
	body, err := annexCSV(p.ActiveRole, name, now, w.scopeLabel, period, hash, summary, start != nil || end != nil, undated, data)
	if err != nil {
		return "", nil, none, true, err
	}
	var projectOrNil any
	if project != "" {
		projectOrNil = project
	}
	entry := audit.Entry{Action: "ia.evidence_annex.downloaded", SubjectKind: audit.Text("IAEvidenceAnnex"),
		SubjectID: audit.Text(hash[:32]), ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
		Payload: map[string]any{"project": projectOrNil, "period": period, "scope_label": w.scopeLabel, "row_count": len(rows),
			"measured": summary["measured"], "rows_sha256": hash}}
	return "ia-impact-evidence.csv", body, entry, true, nil
}

// annexDataRows are the rows' values under liveAnnexKeys.
func annexDataRows(rows []evidenceRow) [][]any {
	out := [][]any{}
	for _, raw := range snapshotRows(rows) {
		row := raw.(map[string]any)
		line := make([]any, len(liveAnnexKeys))
		for i, k := range liveAnnexKeys {
			line[i] = row[k]
		}
		out = append(out, line)
	}
	return out
}

// annexHash is the sha256 of stable_stringify([ROW_KEYS, *data_rows]).
func annexHash(data [][]any) (string, error) {
	header := make([]any, len(liveAnnexKeys))
	for i, k := range liveAnnexKeys {
		header[i] = k
	}
	all := []any{header}
	for _, line := range data {
		all = append(all, line)
	}
	text, err := audit.StableStringify(all)
	if err != nil {
		return "", fmt.Errorf("iapages: hashing the evidence annex: %w", err)
	}
	sum := sha256.Sum256([]byte(text))
	return hex.EncodeToString(sum[:]), nil
}

// annexCSV writes the annex's heading lines, figures and rows. The view's
// findings, limitations and recommendations lines come only from its other
// form, which the Impact reports view does not draw.
func annexCSV(role, name string, now time.Time, scopeLabel, period, hash string, summary map[string]any, narrowed bool, undated int, data [][]any) ([]byte, error) {
	out := [][]any{
		{"Impact Assessment evidence annex", "Draft for review"},
		{"generated_at", pyISOTime(now)},
		{"generated_by", name},
		{"generated_by_role", role},
		{"scope_label", scopeLabel},
		{"period", period},
		{"rows_sha256", hash},
	}
	for _, k := range annexCounts {
		out = append(out, []any{k, summary[k]})
	}
	if narrowed {
		out = append(out, []any{"enrolments_without_a_date_in_any_period", undated})
	}
	out = append(out, []any{"limitation", rules.Dashboard.Outcomes.Limitation},
		[]any{"Counting unit", "Project-school enrolments, not unique schools"}, []any{})
	header := make([]any, len(liveAnnexKeys))
	for i, k := range liveAnnexKeys {
		header[i] = k
	}
	out = append(out, header)
	for _, line := range data {
		out = append(out, line)
	}
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	w.UseCRLF = true
	for _, row := range out {
		cells := make([]string, len(row))
		for i, v := range row {
			cells[i] = CSVCell(v)
		}
		if err := w.Write(cells); err != nil {
			return nil, fmt.Errorf("iapages: writing the evidence annex: %w", err)
		}
	}
	w.Flush()
	return buf.Bytes(), w.Error()
}

// pyISOTime is timezone.now().isoformat() in UTC.
func pyISOTime(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05+00:00")
	}
	return t.Format("2006-01-02T15:04:05.000000+00:00")
}
