package projectmonitoring

import (
	"strings"
	"time"
)

// lens is who is reading: monitoring.sees_whole_project, controls_project_
// work, and the reader's own ids (apps.core.scoping.owner_ids).
type lens struct {
	whole, controls bool
	role, staffID   string
	mine            []string
}

// focus is one InterventionReading: where a focus intervention started at
// the school and where it is.
type focus struct {
	Code, Label, Abbreviation string
	Baseline, Latest          *float64
	LatestOn                  *time.Time
}

// change is InterventionReading.change: round(latest - baseline, 2).
func (f focus) change() *float64 {
	if f.Baseline == nil || f.Latest == nil {
		return nil
	}
	v := pyRound(*f.Latest-*f.Baseline, 2)
	return &v
}

// schoolRow is one ProjectSchoolRow of a school awaiting the Project
// Coordinator: no work planned, handed over or done.
type schoolRow struct {
	e                       enrolment
	ProjectName             string
	AddedBy                 string
	Purpose                 string
	Intervention, Code      string
	Previous, Current       *float64
	Focus                   []focus
	ImpactLabel             string
	LeaveURL                string
	ScheduleURL, PartnerURL string
}

// improvement is ProjectSchoolRow.ssa_improvement.
func (r schoolRow) improvement() *float64 {
	if r.Previous == nil || r.Current == nil {
		return nil
	}
	v := pyRound(*r.Current-*r.Previous, 2)
	return &v
}

// value is the row attribute a column filter reads (ROW_FILTERS).
func (r schoolRow) value(key string) string {
	switch key {
	case "district":
		return r.e.District
	case "purpose":
		return r.Purpose
	}
	// partner, training and activity status: nothing until work exists.
	return ""
}

// matches is ProjectSchoolRow.matches for a row with no work: its plan stage
// is not planned and its execution none.
func (r schoolRow) matches(stage string, picks map[string]string) bool {
	for _, f := range rules.RowFilters {
		if want := picks[f[0]]; want != "" && r.value(f[0]) != want {
			return false
		}
	}
	if stage == "" {
		return true
	}
	if _, ok := rules.ExecLabels[stage]; ok {
		return stage == "none"
	}
	return stage == "not_planned"
}

// impact is ssa_impact.project_impact, the parts the page reads.
type impact struct {
	Added, Cohort, Improved int
}

func projectImpact(rows []enrolment) impact {
	out := impact{Added: len(rows)}
	for _, r := range rows {
		if r.Baseline == nil || !in(rules.Measured, r.Impact) {
			continue
		}
		out.Cohort++
		if r.Impact == "improved" {
			out.Improved++
		}
	}
	return out
}

// projectRow is one ProjectMonitoringRow.
type projectRow struct {
	p        project
	schools  int
	mine     int
	impact   impact
	rows     []schoolRow
	everyone []schoolRow
}

// enrolmentCode is monitoring._enrolment_code; enrolmentLabel is
// _enrolment_intervention.
func enrolmentCode(e enrolment, p project) string {
	if !p.measuredBySSA() {
		return ""
	}
	primary, _ := p.plan()
	for _, c := range []string{e.Matched, e.SupportArea, primary} {
		if c != "" {
			return c
		}
	}
	return ""
}

func enrolmentLabel(e enrolment, p project) string {
	if !p.measuredBySSA() {
		return rules.General
	}
	return choiceLabel(enrolmentCode(e, p))
}

// choiceLabel is partner_oversight_service.choice_label over SsaIntervention.
func choiceLabel(code string) string {
	if code == "" {
		return ""
	}
	if label, ok := interventionLabel(code); ok {
		return label
	}
	return pyTitle(strings.ReplaceAll(code, "_", " "))
}

// readingOf is monitoring._reading: the confirmed score the school entered
// the project with in this intervention, and its latest since.
func readingOf(code string, e enrolment, entered time.Time, history []reading, matched string) focus {
	label, ok := interventionLabel(code)
	if !ok {
		label = pyTitle(strings.ReplaceAll(code, "_", " "))
	}
	f := focus{Code: code, Label: label, Abbreviation: rules.Abbreviations[code]}
	var baseline *reading
	for i := range history {
		if !history[i].Day.After(entered) {
			baseline = &history[i]
		}
	}
	if baseline != nil {
		v := baseline.Score
		f.Baseline = &v
	}
	if code == matched && e.Baseline != nil {
		v := *e.Baseline
		f.Baseline = &v
	}
	for i := range history {
		if baseline == nil || history[i].Day.After(baseline.Day) {
			v, day := history[i].Score, history[i].Day
			f.Latest, f.LatestOn = &v, &day
		}
	}
	return f
}

// schoolRowOf builds the row of one enrolment with no work (monitoring.
// _school_rows, _attach_ssa, _attach_work and _attach_scores).
func schoolRowOf(e enrolment, p project, names map[string]string, readings map[string]map[string][]reading, l lens) schoolRow {
	r := schoolRow{e: e, ProjectName: p.Name, AddedBy: names[e.AssignedBy]}
	if r.AddedBy == "" {
		r.AddedBy = "—"
	}
	entered := e.enrolledOn()
	school := readings[e.SchoolPK]
	primary, supporting := p.plan()
	matched := e.Matched
	if matched == "" {
		matched = primary
	}
	codes := []string{}
	for _, c := range append([]string{matched, primary}, supporting...) {
		if c != "" && !in(codes, c) {
			codes = append(codes, c)
		}
	}
	anyBaseline := false
	for _, c := range codes {
		f := readingOf(c, e, entered, school[c], matched)
		anyBaseline = anyBaseline || f.Baseline != nil
		r.Focus = append(r.Focus, f)
	}
	switch label, ok := rules.ImpactLabels[e.Impact]; {
	case ok:
		r.ImpactLabel = label
	case len(codes) == 0:
		r.ImpactLabel = "No focus set"
	case e.Baseline == nil && !anyBaseline:
		r.ImpactLabel = "Previous FY SSA missing"
	default:
		// Nothing verified yet: no work exists in view.
		r.ImpactLabel = "Awaiting delivery"
	}
	r.Purpose = e.Participation
	r.Intervention = enrolmentLabel(e, p)
	r.Code = enrolmentCode(e, p)
	if r.Code != "" {
		var reading *focus
		for i := range r.Focus {
			if r.Focus[i].Code == r.Code {
				reading = &r.Focus[i]
				break
			}
		}
		if reading == nil {
			f := readingOf(r.Code, e, entered, school[r.Code], e.Matched)
			reading = &f
		}
		r.Previous, r.Current = reading.Baseline, reading.Latest
	}
	return r
}
