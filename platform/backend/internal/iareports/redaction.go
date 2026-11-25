package iareports

// Audience versions of a frozen report (apps.impact.redaction): a pure
// function of the stored snapshot. The school version carries that school's
// own results and the words with every other school's and every person's
// name, and every id, scrubbed; the donor version aggregates only, with
// small cells suppressed.

import (
	"encoding/json"
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

// schoolPayload is redaction.school_payload.
func schoolPayload(snapshot map[string]any, school, schoolName string, narrative map[string]string) map[string]any {
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
