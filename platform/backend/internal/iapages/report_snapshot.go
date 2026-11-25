package iapages

// The evidence an impact report freezes when it is submitted
// (apps.impact.reports.build_snapshot): everything it rests on, computed in
// the author's own scope, as the JSON the report keeps.

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strconv"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// snapshotSchema is reports.SNAPSHOT_SCHEMA.
const snapshotSchema = 1

// evidenceMinN is evidence_strength.MIN_N.
const evidenceMinN = 8

// SnapshotReport is what build_snapshot reads of its report.
type SnapshotReport struct {
	ID, Title, Country, FY, ProjectID, Project string
	Version                                    int
	Start, End                                 *time.Time
	ProgrammeAreas                             []string
}

// periodBounds is reports.period_bounds: the report's own dates, filled
// from its financial year.
func periodBounds(r SnapshotReport) (*time.Time, *time.Time) {
	start, end := r.Start, r.End
	if r.FY != "" && (start == nil || end == nil) {
		n, _ := strconv.Atoi(r.FY)
		if start == nil {
			d := time.Date(n-1, time.October, 1, 0, 0, 0, 0, time.UTC)
			start = &d
		}
		if end == nil {
			d := time.Date(n, time.September, 30, 0, 0, 0, 0, time.UTC)
			end = &d
		}
	}
	return start, end
}

func isoOrNil(t *time.Time) any {
	if t == nil {
		return nil
	}
	return t.Format(time.DateOnly)
}

func intOrNil(p *int) any {
	if p == nil {
		return nil
	}
	return *p
}

func floatOrNil(p *float64) any {
	if p == nil {
		return nil
	}
	return *p
}

// evidenceGrade is evidence_strength.grade for a before-and-after reading
// (the only design these callers use) with no flags.
func evidenceGrade(n int, confirmedShare, missingShare *float64) map[string]any {
	base := func(level, label string, reasons []any) map[string]any {
		return map[string]any{"grade": level, "label": label, "reasons": reasons, "min_n": evidenceMinN,
			"design_label": "Before and after (no comparison group)"}
	}
	if n < evidenceMinN {
		return base("insufficient", "Insufficient evidence", []any{fmt.Sprintf("Fewer than %d measured schools (%d).", evidenceMinN, n)})
	}
	reasons := []any{"Before and after readings only; no comparison group."}
	if missingShare != nil && *missingShare > 0.5 {
		reasons = append(reasons, fmt.Sprintf("%d%% of schools are unmeasured.", pyRoundInt(*missingShare*100)))
	}
	if confirmedShare != nil && *confirmedShare < 0.8 {
		reasons = append(reasons, fmt.Sprintf("Only %d%% of readings are independently confirmed.", pyRoundInt(*confirmedShare*100)))
	}
	reasons = append(reasons, "Association is not proof that the programme caused the change.")
	return base("descriptive", "Descriptive (before and after only)", reasons)
}

func pyRoundInt(x float64) int {
	f := float64(int(x))
	diff := x - f
	switch {
	case diff > 0.5:
		return int(f) + 1
	case diff < 0.5:
		return int(f)
	case int(f)%2 == 0:
		return int(f)
	}
	return int(f) + 1
}

// ReportSnapshot is build_snapshot for the report as p, at now. The
// generated_at it carries is the caller's to add.
func ReportSnapshot(ctx context.Context, db schooldirectory.Querier, p auth.Principal, r SnapshotReport, now time.Time) (map[string]any, error) {
	s := NewService(db, func() time.Time { return now })
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	start, end := periodBounds(r)
	w := outcomeWorkspace{scopeLabel: "Assigned access scope"}
	if !scope.SummaryOnly {
		schools, sargs := activeSchools(scope)
		if w, err = s.workspace(ctx, scope, schools, sargs, r.ProjectID, now); err != nil {
			return nil, err
		}
	}
	rows, undated := rowsInPeriod(w.rows, start, end)
	cohort := summariseRows(rows)
	cohort["outside_period_undated"] = undated
	measured := []evidenceRow{}
	for _, row := range rows {
		if row.measured {
			measured = append(measured, row)
		}
	}
	labels := []any{}
	areas := []any{}
	for _, a := range r.ProgrammeAreas {
		areas = append(areas, a)
		label := a
		if l, ok := rules.ReportProgrammes[a]; ok {
			label = l
		}
		labels = append(labels, label)
	}
	name := p.Name
	snapshot := map[string]any{
		"schema": snapshotSchema,
		"report": map[string]any{"id": r.ID, "title": r.Title, "version": r.Version, "country": r.Country, "fy": r.FY,
			"period_start": isoOrNil(start), "period_end": isoOrNil(end), "project_id": r.ProjectID, "project": r.Project,
			"programme_areas": areas, "programme_area_labels": labels},
		"generated_by": map[string]any{"id": p.UserID, "role": p.ActiveRole},
		"people":       []any{name},
		"scope_label":  w.scopeLabel,
		"cohort":       cohort,
		"domains":      snapshotDomains(measured),
		"rows":         snapshotRows(rows),
		"limitation":   rules.Dashboard.Outcomes.Limitation,
	}
	snapshot["mapping_versions"] = mappingVersions(rows)
	if snapshot["findings"], err = s.approvedFindings(ctx, r, start, end); err != nil {
		return nil, err
	}
	if snapshot["lending"], err = s.lendingEvidence(ctx, p, start, end); err != nil {
		return nil, err
	}
	if snapshot["collection"], err = s.stateCounts(ctx, scope, r.FY); err != nil {
		return nil, err
	}
	if snapshot["evidence"], err = s.outcomeEvidence(ctx, scope, r.FY); err != nil {
		return nil, err
	}
	options := schooldirectory.FYOptions(now)
	comparable := false
	for _, o := range options {
		comparable = comparable || (o == r.FY && mustInt(o) > mustInt(options[0]))
	}
	snapshot["portfolio"], snapshot["portfolio_note"] = nil, "FY"+r.FY+" has no earlier year on the platform to compare with."
	if comparable {
		if snapshot["portfolio"], err = s.portfolioChange(ctx, scope, r.FY); err != nil {
			return nil, err
		}
		snapshot["portfolio_note"] = ""
	}
	return snapshot, nil
}

// rowsInPeriod is reports.rows_in_period.
func rowsInPeriod(rows []evidenceRow, start, end *time.Time) ([]evidenceRow, int) {
	if start == nil && end == nil {
		return rows, 0
	}
	kept, undated := []evidenceRow{}, 0
	for _, row := range rows {
		raw := row.due
		if row.measured {
			raw = row.followUpDate
		}
		if raw == "" {
			undated++
			continue
		}
		day, err := time.Parse(time.DateOnly, raw[:min(10, len(raw))])
		if err != nil {
			undated++
			continue
		}
		if (start == nil || !day.Before(*start)) && (end == nil || !day.After(*end)) {
			kept = append(kept, row)
		}
	}
	return kept, undated
}

// summariseRows is reports.summarise_rows.
func summariseRows(rows []evidenceRow) map[string]any {
	counts := map[string]int{}
	schools, measuredSchools := map[string]bool{}, map[string]bool{}
	n := 0
	for _, row := range rows {
		counts[row.state]++
		schools[row.schoolID] = true
		if row.measured {
			n++
			measuredSchools[row.schoolID] = true
		}
	}
	return map[string]any{
		"total": len(rows), "unique_schools": len(schools), "measured": n, "measured_schools": len(measuredSchools),
		"unmeasured": len(rows) - n, "improved": counts["improved"], "improved_pct": intOrNil(share(counts["improved"], n)),
		"declined": counts["declined"], "declined_pct": intOrNil(share(counts["declined"], n)),
		"maintained": counts["maintained_strong"], "no_change": counts["no_change"], "baseline_missing": counts["baseline_missing"],
		"overdue": counts["overdue"], "due": counts["due"], "not_scheduled": counts["not_scheduled"],
	}
}

// snapshotDomains is ia_workflow._cohort_domains with every key it keeps.
func snapshotDomains(measured []evidenceRow) []any {
	out := []any{}
	for _, iv := range rules.Dashboard.Outcomes.Interventions {
		pairs, deltas := 0, []float64{}
		schools := map[string]bool{}
		improved, declined, maintained := 0, 0, 0
		for _, row := range measured {
			if row.code != iv[0] {
				continue
			}
			pairs++
			schools[row.schoolID] = true
			switch row.state {
			case "improved":
				improved++
			case "declined":
				declined++
			case "maintained_strong":
				maintained++
			}
			if row.state != "maintained_strong" && row.delta != nil {
				deltas = append(deltas, *row.delta)
			}
		}
		var delta any
		if len(schools) >= evidenceMinN {
			delta = floatOrNil(medianOf(deltas))
		}
		out = append(out, map[string]any{"code": iv[0], "name": iv[1], "pairs": pairs, "schools": len(schools),
			"improved": improved, "improved_pct": intOrNil(share(improved, pairs)), "declined": declined,
			"declined_pct": intOrNil(share(declined, pairs)), "maintained": maintained, "delta": delta,
			"withheld": len(schools) > 0 && len(schools) < evidenceMinN})
	}
	return out
}

// snapshotRows are the rows as reports.ROW_KEYS keeps them.
func snapshotRows(rows []evidenceRow) []any {
	out := []any{}
	for _, r := range rows {
		out = append(out, map[string]any{
			"assignment_id": r.assignmentID, "school_id": r.schoolID, "school": r.school, "owner_id": r.ownerID, "owner": r.owner,
			"project_id": r.projectID, "project": r.project, "intervention_code": r.code, "intervention": r.intervention,
			"state": r.state, "status": r.status, "measured": r.measured, "baseline": floatOrNil(r.baseline),
			"follow_up": floatOrNil(r.followUp), "delta": floatOrNil(r.delta), "baseline_date": r.baselineDate,
			"follow_up_date": r.followUpDate, "baseline_id": r.baselineID, "follow_up_id": r.followUpID,
			"mapping_version": intOrNil(r.mappingVersion), "due": r.due, "action": r.action,
		})
	}
	return out
}

// mappingVersions is build_snapshot's mapping_versions: enrolments per
// intervention and mapping version, by label then version.
func mappingVersions(rows []evidenceRow) []any {
	type key struct {
		label   string
		version int
		set     bool
	}
	counts := map[key]int{}
	for _, r := range rows {
		k := key{label: r.intervention}
		if r.mappingVersion != nil {
			k.version, k.set = *r.mappingVersion, true
		}
		counts[k]++
	}
	keys := make([]key, 0, len(counts))
	for k := range counts {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool {
		if keys[i].label != keys[j].label {
			return keys[i].label < keys[j].label
		}
		return keys[i].version < keys[j].version
	})
	out := []any{}
	for _, k := range keys {
		var version any
		if k.set {
			version = k.version
		}
		out = append(out, map[string]any{"intervention": k.label, "mapping_version": version, "enrolments": counts[k]})
	}
	return out
}

// approvedFindings is reports._approved_findings.
func (s *Service) approvedFindings(ctx context.Context, r SnapshotReport, start, end *time.Time) ([]any, error) {
	args := []any{r.Country}
	where := "f.country = $1 AND f.status = 'approved'"
	if start != nil {
		args = append(args, start.Format(time.DateOnly))
		where += fmt.Sprintf(" AND (f.reviewed_at AT TIME ZONE 'Africa/Kampala')::date >= $%d::date", len(args))
	}
	if end != nil {
		args = append(args, end.Format(time.DateOnly))
		where += fmt.Sprintf(" AND (f.reviewed_at AT TIME ZONE 'Africa/Kampala')::date <= $%d::date", len(args))
	}
	if len(r.ProgrammeAreas) > 0 {
		args = append(args, r.ProgrammeAreas)
		where += fmt.Sprintf(" AND f.programme = ANY($%d)", len(args))
	}
	rows, err := s.db.Query(ctx, `SELECT f.id, f.programme, f.statement, f.limitations, COALESCE(f.metric_snapshot->>'grade_label', ''),
  f.reviewed_at FROM impact_finding f WHERE `+where+` ORDER BY f.reviewed_at DESC NULLS LAST LIMIT 25`, args...)
	if err != nil {
		return nil, fmt.Errorf("iapages: the approved findings: %w", err)
	}
	defer rows.Close()
	out := []any{}
	for rows.Next() {
		var id, programme, statement, limitations, evidence string
		var reviewed *time.Time
		if err := rows.Scan(&id, &programme, &statement, &limitations, &evidence, &reviewed); err != nil {
			return nil, fmt.Errorf("iapages: an approved finding: %w", err)
		}
		label := programme
		if l, ok := rules.ReportProgrammes[programme]; ok {
			label = l
		}
		var at any
		if reviewed != nil {
			at = DjangoTime(*reviewed)
		}
		out = append(out, map[string]any{"id": id, "programme": label, "statement": statement, "limitations": limitations,
			"evidence": evidence, "reviewed_at": at})
	}
	return out, rows.Err()
}

// DjangoTime is DjangoJSONEncoder's datetime: ISO 8601 in UTC, to the
// millisecond, with Z.
func DjangoTime(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05Z")
	}
	return t.Format("2006-01-02T15:04:05.000Z")
}

// lendingEvidence is reports._lending_evidence.
func (s *Service) lendingEvidence(ctx context.Context, p auth.Principal, start, end *time.Time) (map[string]any, error) {
	args := []any{}
	scope, err := s.loanScope(ctx, p, &args)
	if err != nil {
		return nil, err
	}
	where := "a.loan_id IN " + fmt.Sprintf(inScope, scope) + " AND a.ia_status = 'verified'"
	if start != nil {
		args = append(args, start.Format(time.DateOnly))
		where += fmt.Sprintf(" AND (a.ia_verified_at AT TIME ZONE 'Africa/Kampala')::date >= $%d::date", len(args))
	}
	if end != nil {
		args = append(args, end.Format(time.DateOnly))
		where += fmt.Sprintf(" AND (a.ia_verified_at AT TIME ZONE 'Africa/Kampala')::date <= $%d::date", len(args))
	}
	rows, err := s.db.Query(ctx, "SELECT a.id, COALESCE(a.classification, '') FROM bt_loan_impact_assessment a WHERE "+where+" ORDER BY a.id", args...)
	if err != nil {
		return nil, fmt.Errorf("iapages: the verified loan conclusions: %w", err)
	}
	defer rows.Close()
	ids, by := []any{}, map[string]any{}
	for rows.Next() {
		var id, classification string
		if err := rows.Scan(&id, &classification); err != nil {
			return nil, fmt.Errorf("iapages: a verified loan conclusion: %w", err)
		}
		ids = append(ids, id)
		count, _ := by[classification].(int)
		by[classification] = count + 1
	}
	return map[string]any{"verified_ids": ids, "by_classification": by}, rows.Err()
}

// stateCounts is ia_collection.state_counts over the whole collection
// population for the year fy.
func (s *Service) stateCounts(ctx context.Context, scope schooldirectory.Scope, fy string) (map[string]any, error) {
	c := rules.Dashboard.Collection
	out := map[string]any{}
	for _, st := range c.States {
		out[st[0]] = 0
	}
	schools, args := collectionScope(scope)
	n := len(args)
	args = append(slices.Clone(args), fy, c.OpenStatuses, c.DeliveredStatuses)
	counted := fmt.Sprintf(`SELECT %s AS state FROM school s %s WHERE %s`, stateSQL(n+1, n+2, n+3), latestJoin, schools)
	rows, err := s.db.Query(ctx, "SELECT state, count(*) FROM ("+counted+") x GROUP BY state", args...)
	if err != nil {
		return nil, fmt.Errorf("iapages: counting the collection states: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var st string
		var k int
		if err := rows.Scan(&st, &k); err != nil {
			return nil, fmt.Errorf("iapages: counting a collection state: %w", err)
		}
		out[st] = k
	}
	return out, rows.Err()
}

// PeriodLabel is reports.period_label for a report's year and dates.
func PeriodLabel(fy string, start, end *time.Time) string {
	return periodLabel(report{fy: fy, start: start, end: end})
}
