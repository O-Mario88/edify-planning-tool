package activities

import (
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode"
)

// The plan's verdict against the verified SSA (apps.ssa.plan_alignment:
// plan_nature, default_focus, assess, _school_evidence, reason_for) and the
// recommendation source the snapshot and the stamp leave on the activity.

// pyFloat marshals as Python's json.dumps writes a float: "5.0", not "5".
type pyFloat float64

func (f pyFloat) MarshalJSON() ([]byte, error) { return []byte(pyRepr(float64(f))), nil }

// pyRepr is repr(float) for the scores and averages a save stores (0–100).
func pyRepr(x float64) string {
	text := strconv.FormatFloat(x, 'f', -1, 64)
	if !strings.ContainsAny(text, ".eEn") {
		text += ".0"
	}
	return text
}

func optFloat(p *float64) any {
	if p == nil {
		return nil
	}
	return pyFloat(*p)
}

func optString(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// planNature is plan_alignment.plan_nature.
func planNature(activityType string, modes []string, collectsSSA bool) string {
	a := rules.Alignment
	if collectsSSA || in(a.CollectionKinds, activityType) || in(modes, "ssa_completion_prerequisite") {
		return "collection"
	}
	administrativeOnly := len(modes) > 0
	for _, m := range modes {
		if m != "administrative" {
			administrativeOnly = false
		}
	}
	if in(a.NotSchoolImprovementKinds, activityType) || administrativeOnly {
		return "not_applicable"
	}
	return "support"
}

// defaultFocus is plan_alignment.default_focus for a school.
func defaultFocus(activityType string, modes []string, need schoolNeed, collectsSSA bool) string {
	if planNature(activityType, modes, collectsSSA) != "support" {
		return ""
	}
	if len(modes) > 0 && !in(modes, "any_ssa_intervention") {
		return ""
	}
	if len(need.Priorities) > 0 {
		return need.Priorities[0]
	}
	return ""
}

type evidence struct {
	Alignment string
	Focus     string
	Data      map[string]any
}

// assess is plan_alignment.assess for a school.
func assess(activityType, focus, focusSource string, modes []string, need schoolNeed, collectsSSA bool, today time.Time) evidence {
	nature := planNature(activityType, modes, collectsSSA)
	data := map[string]any{
		"engine":      rules.Alignment.EngineVersion,
		"assessedOn":  today.Format(time.DateOnly),
		"nature":      nature,
		"focus":       optString(focus),
		"focusSource": "",
	}
	if focus != "" {
		data["focusSource"] = focusSource
	}
	if need.Record != nil {
		data["school"] = schoolEvidence(need, focus)
	}
	if need.PendingSince != nil {
		data["pendingSsaDate"] = need.PendingSince.UTC().Format(time.DateOnly)
	}
	var alignment string
	switch {
	case nature == "collection":
		alignment = "ssa_collection"
	case nature == "not_applicable":
		alignment = "not_applicable"
	case need.Stale:
		alignment = "stale_ssa"
	case !need.assessed():
		alignment = "no_ssa"
	case focus == "":
		alignment = "no_focus"
	case slices.Contains(need.Priorities, focus):
		alignment = "priority"
	default:
		alignment = "off_priority"
	}
	data["alignment"] = alignment
	return evidence{Alignment: alignment, Focus: focus, Data: data}
}

func schoolEvidence(need schoolNeed, focus string) map[string]any {
	r := need.Record
	out := map[string]any{
		"ssaId": r.ID, "ssaDate": nil, "ssaFy": r.FY, "averageScore": optFloat(r.AverageScore),
		"priorities": append([]string{}, need.Priorities...), "top": nil,
		"focusScore": nil, "focusBand": nil, "focusRank": nil,
	}
	if r.Date != nil {
		out["ssaDate"] = pyIsoformat(*r.Date)
	}
	if len(need.Ranked) > 0 {
		top := need.Ranked[0]
		out["top"] = map[string]any{
			"intervention": top.Intervention, "label": top.Label, "score": pyFloat(top.Score), "band": top.Band,
		}
	}
	for i, row := range need.Ranked {
		if focus != "" && row.Intervention == focus {
			out["focusScore"], out["focusBand"], out["focusRank"] = pyFloat(row.Score), row.Band, i+1
		}
	}
	return out
}

// pyIsoformat is datetime.isoformat() of an aware UTC datetime as Django
// reads a timestamptz: "2026-02-10T00:00:00+00:00", microseconds when set.
func pyIsoformat(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 != 0 {
		return t.Format("2006-01-02T15:04:05.000000") + "+00:00"
	}
	return t.Format("2006-01-02T15:04:05") + "+00:00"
}

// reasonFor is plan_alignment.reason_for for a school's verdict.
func reasonFor(e evidence) string {
	focusLabel := rules.labels[e.Focus]
	pending := ""
	if d, ok := e.Data["pendingSsaDate"].(string); ok && d != "" {
		pending = fmt.Sprintf(" A newer SSA (%s) is waiting for verification.", d)
	}
	school, _ := e.Data["school"].(map[string]any)
	switch e.Alignment {
	case "ssa_collection":
		return "Collects the SSA this school's support will be planned from."
	case "not_applicable":
		return "Not school-improvement work, so no SSA intervention applies."
	case "no_ssa":
		return "No verified SSA yet: collect the assessment so support can target a measured need." + pending
	case "stale_ssa":
		when := ""
		if fy, _ := school["ssaFy"].(string); fy != "" {
			when = fmt.Sprintf(" (FY%s)", fy)
		}
		return fmt.Sprintf("The verified SSA%s is out of date: collect this year's assessment before planning support from it.", when) + pending
	case "no_focus":
		return fmt.Sprintf("Names no intervention although the SSA ranks %s first.", topLabel(school, "a need"))
	}
	if school == nil {
		return ""
	}
	where := "not scored"
	if rank, ok := school["focusRank"].(int); ok {
		where = fmt.Sprintf("ranked %d of the school's needs", rank)
	}
	score := "None"
	if s, ok := school["focusScore"].(pyFloat); ok {
		score = pyRepr(float64(s))
	}
	suffix := ""
	if e.Alignment != "priority" {
		suffix = fmt.Sprintf("; the SSA ranks %s first", topLabel(school, "another need"))
	}
	return fmt.Sprintf("Targets %s (%s/10, %s)%s.", focusLabel, score, where, suffix)
}

func topLabel(school map[string]any, fallback string) string {
	if top, ok := school["top"].(map[string]any); ok {
		if label, ok := top["label"].(string); ok {
			return label
		}
	}
	return fallback
}

// pyTitle is str.title(): a letter after a non-letter is upper-cased, the
// rest lower-cased.
func pyTitle(text string) string {
	var b strings.Builder
	prev := false
	for _, r := range text {
		if unicode.IsLetter(r) {
			if prev {
				b.WriteRune(unicode.ToLower(r))
			} else {
				b.WriteRune(unicode.ToUpper(r))
			}
			prev = true
			continue
		}
		prev = false
		b.WriteRune(r)
	}
	return b.String()
}

// standardSupport is _create's recommendation reason and source for a
// standard_support item (3100–3123).
func standardSupport(rationale, target, itemID string, source *ssaRecord) (string, map[string]any) {
	reason := strings.TrimSpace(rationale)
	if reason == "" {
		reason = "Standard field support."
		if target != "" {
			reason = fmt.Sprintf("Standard field support targeting %s.", pyTitle(strings.ReplaceAll(target, "_", " ")))
		}
	}
	src := map[string]any{
		"engine": "standard_support", "sourceSsaId": nil, "verificationState": "none",
		"catalogueItemId": itemID, "recommended": false, "standardSupport": true,
		"targetIntervention": optString(target), "projectId": nil, "executorType": "staff", "context": "school",
	}
	if source != nil {
		src["sourceSsaId"], src["verificationState"] = source.ID, "confirmed"
	}
	return reason, src
}
