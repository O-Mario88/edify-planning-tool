package iaredaction

// Package iaredaction is the audience versions of a frozen impact report
// (apps.impact.redaction): a pure
// function of the stored snapshot. The school version carries that school's
// own results and the words with every other school's and every person's
// name, and every id, scrubbed; the donor version aggregates only, with
// small cells suppressed.

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
)

const (
	smallCell           = 5
	suppressed          = "suppressed"
	schoolPlaceholder   = "[a school]"
	personPlaceholder   = "[a staff member]"
	idPlaceholder       = "[reference]"
	redactionSchool     = "school"
	redactionDonor      = "donor"
	redactionLeadership = "leadership"
)

// schoolStateLabels are redaction.SCHOOL_STATE_LABELS.
var schoolStateLabels = map[string]string{
	"improved": "Improved", "declined": "Declined", "maintained_strong": "Kept a strong score", "no_change": "No change",
	"baseline_missing": "No starting assessment yet", "evidence_review": "Follow-up assessment being checked",
	"not_scheduled": "Follow-up not yet scheduled", "overdue": "Follow-up assessment overdue", "due": "Follow-up assessment due",
	"upcoming": "Follow-up assessment coming up",
}

func str(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case string:
		return x
	case json.Number:
		return x.String()
	}
	b, _ := json.Marshal(v)
	return string(b)
}

func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case json.Number:
		f, _ := x.Float64()
		return f != 0
	case []any:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	}
	return true
}

func object(v any) map[string]any {
	m, _ := v.(map[string]any)
	if m == nil {
		return map[string]any{}
	}
	return m
}

// namesAndIDs is redaction._names_and_ids.
func namesAndIDs(snapshot map[string]any, keepSchool string) (map[string]bool, map[string]bool) {
	names, ids := map[string]bool{}, map[string]bool{}
	for _, raw := range list(snapshot["rows"]) {
		row := object(raw)
		if str(row["school_id"]) != keepSchool && truthy(row["school"]) {
			names[str(row["school"])] = true
		}
		if truthy(row["owner"]) {
			names[str(row["owner"])] = true
		}
		for _, k := range []string{"school_id", "project_id", "baseline_id", "follow_up_id", "owner_id", "assignment_id"} {
			if truthy(row[k]) {
				ids[str(row[k])] = true
			}
		}
	}
	for _, person := range list(snapshot["people"]) {
		if truthy(person) {
			names[str(person)] = true
		}
	}
	for _, ref := range list(object(snapshot["lending"])["verified_ids"]) {
		ids[str(ref)] = true
	}
	for _, raw := range list(snapshot["findings"]) {
		if f := object(raw); truthy(f["id"]) {
			ids[str(f["id"])] = true
		}
	}
	report := object(snapshot["report"])
	for _, k := range []string{"id", "project_id"} {
		if truthy(report[k]) {
			ids[str(report[k])] = true
		}
	}
	for n := range names {
		if t := strings.TrimSpace(n); len([]rune(t)) < 3 || t == "Unassigned" {
			delete(names, n)
		}
	}
	for i := range ids {
		if len([]rune(i)) < 6 {
			delete(ids, i)
		}
	}
	return names, ids
}

func byLengthDesc(set map[string]bool) []string {
	out := make([]string, 0, len(set))
	for k := range set {
		out = append(out, k)
	}
	sort.SliceStable(out, func(i, j int) bool {
		if len([]rune(out[i])) != len([]rune(out[j])) {
			return len([]rune(out[i])) > len([]rune(out[j]))
		}
		return out[i] < out[j]
	})
	return out
}

// scrub is redaction.scrub.
func scrub(text string, names, ids map[string]bool, placeholder string) string {
	for _, name := range byLengthDesc(names) {
		text = regexp.MustCompile("(?i)"+regexp.QuoteMeta(name)).ReplaceAllLiteralString(text, placeholder)
	}
	for _, ref := range byLengthDesc(ids) {
		text = strings.ReplaceAll(text, ref, idPlaceholder)
	}
	return text
}

// scrubPeopleAndSchools is redaction._scrub_people_and_schools.
func scrubPeopleAndSchools(text string, snapshot map[string]any, keepSchool string) string {
	names, ids := namesAndIDs(snapshot, keepSchool)
	owners := map[string]bool{}
	for _, raw := range list(snapshot["rows"]) {
		row := object(raw)
		if o := str(row["owner"]); truthy(row["owner"]) && names[o] {
			owners[o] = true
		}
	}
	for _, person := range list(snapshot["people"]) {
		if truthy(person) {
			owners[str(person)] = true
		}
	}
	text = scrub(text, owners, nil, personPlaceholder)
	rest := map[string]bool{}
	for n := range names {
		if !owners[n] {
			rest[n] = true
		}
	}
	return scrub(text, rest, ids, schoolPlaceholder)
}

func orDefault(v any, fallback any) any {
	if v == nil {
		return fallback
	}
	return v
}

// SchoolPayload is redaction.school_payload.
func SchoolPayload(snapshot map[string]any, school, schoolName string, narrative map[string]string) map[string]any {
	report := object(snapshot["report"])
	clean := func(text string) string { return scrubPeopleAndSchools(text, snapshot, school) }
	results := []any{}
	for _, raw := range list(snapshot["rows"]) {
		row := object(raw)
		if str(row["school_id"]) != school {
			continue
		}
		status, ok := schoolStateLabels[str(row["state"])]
		if !ok {
			status = str(row["status"])
		}
		results = append(results, map[string]any{"area": orDefault(row["intervention"], ""), "programme": orDefault(row["project"], ""),
			"baseline": row["baseline"], "follow_up": row["follow_up"], "change": row["delta"],
			"baseline_date": orDefault(row["baseline_date"], ""), "follow_up_date": orDefault(row["follow_up_date"], ""), "status": status})
	}
	limitations := []any{}
	if truthy(snapshot["limitation"]) {
		limitations = append(limitations, snapshot["limitation"])
	}
	periodStart, periodEnd := report["period_start"], report["period_end"]
	if !truthy(periodStart) {
		periodStart = ""
	}
	if !truthy(periodEnd) {
		periodEnd = ""
	}
	return map[string]any{
		"profile": redactionSchool,
		"school":  map[string]any{"name": schoolName},
		"report": map[string]any{"title": clean(str(report["title"])), "fy": orDefault(report["fy"], ""), "period_start": periodStart,
			"period_end": periodEnd, "version": orDefault(report["version"], 1)},
		"results":     results,
		"narrative":   map[string]any{"findings": clean(narrative["findings"]), "limitations": clean(narrative["limitations"])},
		"limitations": limitations,
	}
}

// numberOf is a snapshot count as an int, and whether it is one (a JSON
// integer: Python's isinstance(n, int)).
func numberOf(v any) (int, bool) {
	n, ok := v.(json.Number)
	if !ok || strings.ContainsAny(n.String(), ".eE") {
		return 0, false
	}
	i, err := n.Int64()
	return int(i), err == nil
}

// small is redaction._small.
func small(v any) bool {
	n, ok := numberOf(v)
	return ok && n > 0 && n < smallCell
}

// orZeroValue is `value or 0`.
func orZeroValue(v any) any {
	if !truthy(v) {
		return json.Number("0")
	}
	return v
}

// countCell is redaction.count_cell.
func countCell(v any) any {
	if small(v) {
		return suppressed
	}
	return v
}

// shareCell is redaction.share_cell.
func shareCell(value, base any) any {
	if !truthy(base) {
		return nil
	}
	if n, ok := numberOf(base); ok && n < smallCell {
		return suppressed
	}
	return value
}

func gradeLabel(block map[string]any) string {
	if g, ok := block["grade"].(map[string]any); ok {
		return str(g["label"])
	}
	return ""
}

func getOr(m map[string]any, key string, fallback any) any {
	if v, ok := m[key]; ok {
		return v
	}
	return fallback
}

// DonorPayload is redaction.donor_payload.
func DonorPayload(snapshot map[string]any, narrative map[string]string, recommendations []map[string]any) map[string]any {
	report := object(snapshot["report"])
	clean := func(text string) string { return scrubPeopleAndSchools(text, snapshot, "") }
	cohort := object(snapshot["cohort"])
	measured := orZeroValue(cohort["measured"])
	donorCohort := map[string]any{
		"enrolments": countCell(orZeroValue(cohort["total"])), "schools": countCell(orZeroValue(cohort["unique_schools"])),
		"measured": countCell(measured), "measured_schools": countCell(orZeroValue(cohort["measured_schools"])),
		"improved": countCell(orZeroValue(cohort["improved"])), "improved_pct": shareCell(cohort["improved_pct"], measured),
		"declined": countCell(orZeroValue(cohort["declined"])), "declined_pct": shareCell(cohort["declined_pct"], measured),
		"no_change": countCell(orZeroValue(cohort["no_change"])), "maintained": countCell(orZeroValue(cohort["maintained"])),
		"baseline_missing": countCell(orZeroValue(cohort["baseline_missing"])),
	}
	domains := []any{}
	for _, raw := range list(snapshot["domains"]) {
		d := object(raw)
		schools := orZeroValue(d["schools"])
		domains = append(domains, map[string]any{"name": getOr(d, "name", ""), "measured": countCell(orZeroValue(d["pairs"])),
			"schools": countCell(schools), "improved_pct": shareCell(d["improved_pct"], schools),
			"declined_pct": shareCell(d["declined_pct"], schools), "median_change": shareCell(d["delta"], schools)})
	}
	portfolio := object(snapshot["portfolio"])
	pMeasured := orZeroValue(portfolio["measured"])
	pRows := []any{}
	for _, raw := range list(portfolio["rows"]) {
		row := object(raw)
		n := orZeroValue(row["n"])
		pRows = append(pRows, map[string]any{"name": getOr(row, "name", ""), "is_area": truthy(row["is_area"]), "measured": countCell(n),
			"improved_pct": shareCell(row["improved_pct"], n), "declined_pct": shareCell(row["declined_pct"], n),
			"median_change": shareCell(row["median_change"], n), "evidence": gradeLabel(row)})
	}
	donorPortfolio := map[string]any{
		"fy": getOr(portfolio, "fy", ""), "prev_fy": getOr(portfolio, "prev_fy", ""),
		"schools_in_scope": countCell(orZeroValue(portfolio["schools_in_scope"])), "measured": countCell(pMeasured),
		"improved_pct": shareCell(portfolio["improved_pct"], pMeasured), "declined_pct": shareCell(portfolio["declined_pct"], pMeasured),
		"median_interval_days": shareCell(portfolio["median_interval_days"], pMeasured), "rule_label": getOr(portfolio, "rule_label", ""),
		"evidence": gradeLabel(portfolio), "rows": pRows,
	}
	evidence := object(snapshot["evidence"])
	block := func(raw any, keys ...string) map[string]any {
		b := object(raw)
		schools := orZeroValue(b["schools"])
		if small(schools) {
			return map[string]any{"schools": suppressed, suppressed: true}
		}
		out := map[string]any{"schools": schools, "evidence": gradeLabel(b)}
		for _, k := range keys {
			v := b[k]
			if !truthy(schools) && strings.HasSuffix(k, "_pct") {
				v = nil
			}
			out[k] = v
		}
		return out
	}
	lending := object(snapshot["lending"])
	byClass := map[string]any{}
	for label, n := range object(lending["by_classification"]) {
		byClass[label] = countCell(n)
	}
	recs := []any{}
	for _, r := range recommendations {
		recs = append(recs, map[string]any{"text": clean(str(r["text"])), "owner": getOr(r, "owner_label", "")})
	}
	limitations := []any{}
	for _, t := range []any{snapshot["limitation"], portfolio["limitation"]} {
		if truthy(t) {
			limitations = append(limitations, t)
		}
	}
	periodStart, periodEnd := report["period_start"], report["period_end"]
	if !truthy(periodStart) {
		periodStart = ""
	}
	if !truthy(periodEnd) {
		periodEnd = ""
	}
	labels := list(report["programme_area_labels"])
	if labels == nil {
		labels = []any{}
	}
	payload := map[string]any{
		"profile": redactionDonor, "small_cell_threshold": smallCell,
		"report": map[string]any{"title": clean(str(report["title"])), "country": getOr(report, "country", ""), "fy": getOr(report, "fy", ""),
			"period_start": periodStart, "period_end": periodEnd, "programme_areas": labels, "version": getOr(report, "version", 1)},
		"narrative": map[string]any{"methodology": clean(narrative["methodology"]), "findings": clean(narrative["findings"]),
			"limitations": clean(narrative["limitations"])},
		"recommendations": recs, "cohort": donorCohort, "domains": domains, "portfolio": donorPortfolio,
		"evidence": map[string]any{
			"learning":     block(evidence["learning"], "comparisons", "improved_pct", "declined_pct"),
			"discipleship": block(evidence["discipleship"], "with_groups_pct", "with_lead_pct", "learners_in_groups_pct"),
			"edtech":       block(evidence["edtech"], "deployments", "units", "functional_pct"),
		},
		"lending": map[string]any{"verified_conclusions": countCell(json.Number(fmt.Sprint(len(list(lending["verified_ids"]))))),
			"by_classification": byClass},
		"limitations": limitations,
	}
	payload["suppressed_cells"] = countSuppressed(payload)
	return payload
}

// countSuppressed is redaction._count_suppressed.
func countSuppressed(v any) int {
	switch x := v.(type) {
	case string:
		if x == suppressed {
			return 1
		}
	case map[string]any:
		n := 0
		for k, inner := range x {
			if k != suppressed {
				n += countSuppressed(inner)
			}
		}
		return n
	case []any:
		n := 0
		for _, inner := range x {
			n += countSuppressed(inner)
		}
		return n
	}
	return 0
}

func list(v any) []any {
	l, _ := v.([]any)
	return l
}

// Suppressed is redaction.SUPPRESSED.
const Suppressed = suppressed
