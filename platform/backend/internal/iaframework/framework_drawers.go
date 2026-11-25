package iaframework

// The framework's drawers (apps.frontend.views.ia_framework_views) drawn and
// saved in Go with Django absent: a new or existing outcome area, a new or
// existing indicator, a loan purpose's measurement, Submit and Review, and
// the areas' "Draft the proposed areas" form. They are the shared HR form
// drawer: facts, a note, the fields and the submit, or the facts and a note.

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
)

// ProposeForm is the areas tab's "Draft the proposed areas" form.
const ProposeForm = "propose"

var (
	areaNewPath      = regexp.MustCompile(`^/ia/framework/areas/(new|save)/?$`)
	areaOnePath      = regexp.MustCompile(`^/ia/framework/areas/([A-Za-z0-9]{1,30})/(save)?$`)
	indicatorNewPath = regexp.MustCompile(`^/ia/framework/indicators/(new|save)/?$`)
	indicatorOnePath = regexp.MustCompile(`^/ia/framework/indicators/([A-Za-z0-9]{1,30})/(save)?$`)
	purposePath      = regexp.MustCompile(`^/ia/framework/purposes/([A-Za-z0-9]{1,30})/(save)?$`)
	submitPath       = regexp.MustCompile(`^/ia/framework/(area|indicator)/([A-Za-z0-9]{1,30})/submit(/save)?$`)
	reviewPath       = regexp.MustCompile(`^/ia/framework/(area|indicator)/([A-Za-z0-9]{1,30})/review(/save)?$`)
)

type spec struct {
	title, subtitle, submit, empty, note string
	facts                                [][2]string
	fields                               []*screensv1.DrawerField
}

// drawer is partials/hr/form_drawer.html.
func drawer(s spec) *screensv1.PageDrawer {
	d := &screensv1.PageDrawer{Title: s.title, Subtitle: s.subtitle}
	if len(s.facts) > 0 {
		facts := make([]*screensv1.PageFact, 0, len(s.facts))
		for _, f := range s.facts {
			v := f[1]
			if v == "" {
				v = "—"
			}
			facts = append(facts, &screensv1.PageFact{Label: f[0], Value: v})
		}
		d.Items = append(d.Items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: facts}}})
	}
	if s.note != "" {
		d.Items = append(d.Items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: s.note, Tone: "info"}}})
	}
	if s.submit == "" {
		if s.empty != "" {
			d.Items = append(d.Items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: s.empty, Tone: "info"}}})
		}
		d.CancelLabel = "Close"
		return d
	}
	for _, f := range s.fields {
		if f.Required {
			d.HasRequired = true
		}
		d.Items = append(d.Items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: f}})
	}
	d.CanSubmit, d.SubmitLabel, d.CancelLabel = true, s.submit, "Cancel"
	return d
}

func options(pairs [][2]string, blank string) []*screensv1.DrawerOption {
	var out []*screensv1.DrawerOption
	if blank != "" {
		out = append(out, &screensv1.DrawerOption{Value: "", Label: blank})
	}
	for _, p := range pairs {
		out = append(out, &screensv1.DrawerOption{Value: p[0], Label: p[1]})
	}
	return out
}

func maxLen(n int32) *int32 { return &n }

// names is user id → name, for the review facts.
func (f Framework) userNames(ctx context.Context, ids ...string) (map[string]string, error) {
	out := map[string]string{}
	rows, err := f.DB.Query(ctx, `SELECT id, COALESCE(name, '') FROM "user" WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("iaframework: reading the names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, err
		}
		out[id] = name
	}
	return out, rows.Err()
}

func nameOrDash(names map[string]string, id string) string {
	if n, ok := names[id]; ok {
		return n
	}
	return "—"
}

// reviewFacts is _review_facts.
func (f Framework) reviewFacts(ctx context.Context, r *record) ([][2]string, error) {
	ids := []string{r.author}
	if r.reviewer != "" {
		ids = append(ids, r.reviewer)
	}
	names, err := f.userNames(ctx, ids...)
	if err != nil {
		return nil, err
	}
	facts := [][2]string{{"Version", fmt.Sprintf("v%d", r.version)}, {"Status", statusLabel(r.status)},
		{"Written by", nameOrDash(names, r.author)}, {"Why", r.changeReason}}
	if r.reviewer != "" {
		facts = append(facts, [2]string{"Reviewed by", nameOrDash(names, r.reviewer) + " · " + rules.Saves.ReviewBases[r.basis]})
	}
	if r.note != "" {
		facts = append(facts, [2]string{"Review note", r.note})
	}
	return facts, nil
}

func areaFields(r *record) []*screensv1.DrawerField {
	name, definition, reason := "", "", ""
	var chosen []string
	if r != nil {
		name, definition, chosen = r.name, r.fields["definition"], r.domains
		if pending(r.status) {
			reason = r.changeReason
		}
	}
	return []*screensv1.DrawerField{
		{Name: "name", Label: "Name", Kind: "text", Required: true, Value: name, MaxLength: maxLen(120)},
		{Name: "definition", Label: "Definition", Kind: "textarea", Required: true, Value: definition,
			Help: "What change in a partner school this area means, in plain words."},
		{Name: "interventions", Label: "SSA domains read as its proxy", Kind: "checklist", Required: true,
			Value: strings.Join(chosen, ","), Options: options(rules.Saves.InterventionChoices, "")},
		{Name: "change_reason", Label: "Why (change reason)", Kind: "textarea", Value: reason},
	}
}

func (f Framework) areaDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	a, err := f.load(ctx, nil, kindArea, id, false)
	if err != nil {
		return nil, err
	}
	labels := make([]string, 0, len(a.domains))
	for _, d := range a.domains {
		l := rules.InterventionLabels[d]
		if l == "" {
			l = d
		}
		labels = append(labels, l)
	}
	review, err := f.reviewFacts(ctx, a)
	if err != nil {
		return nil, err
	}
	facts := append([][2]string{{"Definition", a.fields["definition"]}, {"SSA domains (proxy)", strings.Join(labels, ", ")}}, review...)
	editable := mayAuthor(p) && (a.status == statusApproved || (pending(a.status) && a.author == p.UserID))
	if !editable {
		return drawer(spec{title: a.name, subtitle: "Outcome area", facts: facts}), nil
	}
	subtitle := "Draft — a second reviewer approves it"
	if a.status == statusApproved {
		subtitle = "Editing an approved area drafts a new version"
	}
	return drawer(spec{title: a.name, subtitle: subtitle, submit: "Save draft", facts: facts, fields: areaFields(a)}), nil
}

func (f Framework) indicatorFields(ctx context.Context, r *record) ([]*screensv1.DrawerField, error) {
	rows, err := f.DB.Query(ctx, `SELECT id, name, version FROM impact_outcome_area WHERE status <> ALL($1) ORDER BY name, version DESC`,
		[]string{statusSuperseded, statusRetired})
	if err != nil {
		return nil, fmt.Errorf("iaframework: reading the outcome areas: %w", err)
	}
	var areas [][2]string
	for rows.Next() {
		var id, name string
		var version int
		if err := rows.Scan(&id, &name, &version); err != nil {
			rows.Close()
			return nil, err
		}
		areas = append(areas, [2]string{id, fmt.Sprintf("%s (v%d)", name, version)})
	}
	rows.Close()
	value := func(name string) string {
		if r == nil {
			return ""
		}
		if name == "name" {
			return r.name
		}
		return r.fields[name]
	}
	var fields []*screensv1.DrawerField
	if r == nil {
		fields = append(fields, &screensv1.DrawerField{Name: "key", Label: "Key", Kind: "text", MaxLength: maxLen(80),
			Help: "Letters, numbers and hyphens; left empty it is made from the name."})
	}
	area, effective, reason := "", "", ""
	if r != nil {
		if r.areaID != nil {
			area = *r.areaID
		}
		if r.effective != nil {
			effective = r.effective.Format(time.DateOnly)
		}
		if pending(r.status) {
			reason = r.changeReason
		}
	}
	fields = append(fields,
		&screensv1.DrawerField{Name: "name", Label: "Name", Kind: "text", Required: true, Value: value("name"), MaxLength: maxLen(160)},
		&screensv1.DrawerField{Name: "level", Label: "Level", Kind: "select", Required: true, Value: value("level"),
			Options: options(rules.Saves.LevelChoices, "Choose a level"), Help: "Counting delivered work is an output; change in schools is an outcome."},
		&screensv1.DrawerField{Name: "outcome_area", Label: "Outcome area", Kind: "select", Value: area, Options: options(areas, "None")},
		&screensv1.DrawerField{Name: "source", Label: "Evidence source", Kind: "select", Required: true, Value: value("source"),
			Options: options(rules.Saves.SourceChoices, "Choose a source")},
		&screensv1.DrawerField{Name: "unit", Label: "Unit", Kind: "text", Required: true, Value: value("unit"), MaxLength: maxLen(48)},
		&screensv1.DrawerField{Name: "calculation", Label: "Calculation", Kind: "textarea", Required: true, Value: value("calculation")},
		&screensv1.DrawerField{Name: "population", Label: "Population", Kind: "textarea", Value: value("population")},
		&screensv1.DrawerField{Name: "denominator", Label: "Denominator", Kind: "textarea", Value: value("denominator")},
		&screensv1.DrawerField{Name: "baseline_rule", Label: "Baseline rule", Kind: "textarea", Value: value("baseline_rule")},
		&screensv1.DrawerField{Name: "frequency", Label: "Frequency", Kind: "text", Value: value("frequency"), MaxLength: maxLen(64)},
		&screensv1.DrawerField{Name: "disaggregation", Label: "Disaggregation", Kind: "textarea", Value: value("disaggregation")},
		&screensv1.DrawerField{Name: "limitations", Label: "Limitations", Kind: "textarea", Value: value("limitations")},
		&screensv1.DrawerField{Name: "data_owner_role", Label: "Data owner role", Kind: "text", Value: value("data_owner_role"), MaxLength: maxLen(32)},
		&screensv1.DrawerField{Name: "effective_from", Label: "Effective from", Kind: "date", Value: effective},
		&screensv1.DrawerField{Name: "change_reason", Label: "Why (change reason)", Kind: "textarea", Value: reason},
	)
	return fields, nil
}

func (f Framework) indicatorDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	r, err := f.load(ctx, nil, kindIndicator, id, false)
	if err != nil {
		return nil, err
	}
	review, err := f.reviewFacts(ctx, r)
	if err != nil {
		return nil, err
	}
	scope := r.country
	if scope == "" {
		scope = "All countries"
	}
	facts := append([][2]string{{"Key", r.key}, {"Level", label(rules.Levels, r.fields["level"])}, {"Source", label(rules.Sources, r.fields["source"])},
		{"Calculation", r.fields["calculation"]}, {"Denominator", r.fields["denominator"]}, {"Limitations", r.fields["limitations"]},
		{"Scope", scope}}, review...)
	rows, err := f.DB.Query(ctx, `SELECT version, status, effective_from FROM impact_indicator_definition WHERE key = $1 ORDER BY version DESC`, r.key)
	if err != nil {
		return nil, fmt.Errorf("iaframework: reading the indicator's versions: %w", err)
	}
	var history []string
	for rows.Next() {
		var version int
		var status string
		var from *time.Time
		if err := rows.Scan(&version, &status, &from); err != nil {
			rows.Close()
			return nil, err
		}
		line := fmt.Sprintf("v%d · %s", version, statusLabel(status))
		if from != nil {
			line += " · from " + from.Format("2 Jan 2006")
		}
		history = append(history, line)
	}
	rows.Close()
	facts = append(facts, [2]string{"Versions", strings.Join(history, "\n")})
	editable := mayAuthor(p) && !strings.HasPrefix(r.key, rules.LoanPurposeKeyPrefix) &&
		(r.status == statusApproved || (pending(r.status) && r.author == p.UserID))
	if !editable {
		return drawer(spec{title: r.name, subtitle: "Indicator", facts: facts}), nil
	}
	fields, err := f.indicatorFields(ctx, r)
	if err != nil {
		return nil, err
	}
	subtitle := "Draft — a second reviewer approves it"
	if r.status == statusApproved {
		subtitle = "Editing an approved indicator drafts a new version"
	}
	return drawer(spec{title: r.name, subtitle: subtitle, submit: "Save draft", facts: facts, fields: fields}), nil
}

func (f Framework) purposeDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	lp, err := f.purposeOf(ctx, nil, id)
	if err != nil {
		return nil, err
	}
	var latest *record
	var latestID string
	err = f.DB.QueryRow(ctx, `SELECT id FROM impact_indicator_definition WHERE key = $1 ORDER BY version DESC LIMIT 1`, purposeKey(lp.code)).Scan(&latestID)
	if err != nil && !isNoRows(err) {
		return nil, fmt.Errorf("iaframework: reading the purpose's measurement: %w", err)
	}
	if latestID != "" {
		if latest, err = f.load(ctx, nil, kindIndicator, latestID, false); err != nil {
			return nil, err
		}
	}
	var source *record
	if latest != nil && latest.status != statusApproved {
		source = latest
	}
	orNot := func(v string) string {
		if v == "" {
			return "Not defined"
		}
		return v
	}
	facts := [][2]string{{"Purpose", fmt.Sprintf("%s (%s)", lp.label, lp.code)}, {"Unit", lp.unit},
		{"Current indicators", orNot(strings.Join(lp.indicators, "\n"))}, {"Current verification", orNot(lp.verification)}}
	if latest != nil {
		review, err := f.reviewFacts(ctx, latest)
		if err != nil {
			return nil, err
		}
		facts = append(facts, review...)
	}
	if !mayAuthor(p) {
		return drawer(spec{title: lp.label, subtitle: "Loan purpose", facts: facts}), nil
	}
	if latest != nil && latest.status == statusInReview {
		return drawer(spec{title: lp.label, subtitle: "Loan purpose measurement", facts: facts, empty: "This measurement is with a reviewer."}), nil
	}
	indicators, evidence, method, limitations, reason := strings.Join(lp.indicators, "\n"), strings.Join(lp.evidence, "\n"), lp.verification, "", ""
	if source != nil {
		indicators, evidence, method, limitations, reason = source.fields["calculation"], source.fields["disaggregation"],
			source.fields["baseline_rule"], source.fields["limitations"], source.changeReason
	}
	one := 1.0
	return drawer(spec{title: lp.label, subtitle: "Saved as a draft; a second reviewer approves it", submit: "Save draft", facts: facts,
		fields: []*screensv1.DrawerField{
			{Name: "impact_indicators", Label: "Impact indicators (one per line)", Kind: "textarea", Required: true, Value: indicators},
			{Name: "required_evidence", Label: "Required evidence (one per line)", Kind: "textarea", Required: true, Value: evidence},
			{Name: "verification_method", Label: "Verification method", Kind: "textarea", Required: true, Value: method},
			{Name: "follow_up_days", Label: "Follow-up, days after disbursement", Kind: "number", Required: true, Min: &one,
				Value: fmt.Sprint(lp.followUp)},
			{Name: "limitations", Label: "Limitations", Kind: "textarea", Value: limitations},
			{Name: "change_reason", Label: "Why (change reason)", Kind: "textarea", Value: reason},
		}}), nil
}

func isNoRows(err error) bool { return err != nil && strings.Contains(err.Error(), "no rows") }

func (f Framework) submitDrawer(ctx context.Context, p auth.Principal, kind, id string) (*screensv1.PageDrawer, error) {
	r, err := f.load(ctx, nil, kind, id, false)
	if err != nil {
		return nil, err
	}
	facts, err := f.reviewFacts(ctx, r)
	if err != nil {
		return nil, err
	}
	title := "Submit " + r.name
	if !(mayAuthor(p) && pending(r.status) && r.author == p.UserID) {
		return drawer(spec{title: title, subtitle: "Measurement framework", facts: facts,
			empty: "Only the officer who wrote a draft submits it for review."}), nil
	}
	return drawer(spec{title: title, subtitle: "A second Impact Assessment officer reviews it", submit: "Submit for review", facts: facts,
		fields: []*screensv1.DrawerField{{Name: "change_reason", Label: "What this establishes or changes, and why", Kind: "textarea",
			Required: true, Value: r.changeReason}}}), nil
}

func (f Framework) reviewDrawer(ctx context.Context, p auth.Principal, kind, id string) (*screensv1.PageDrawer, error) {
	r, err := f.load(ctx, nil, kind, id, false)
	if err != nil {
		return nil, err
	}
	basis := ""
	if r.status == statusInReview {
		country := r.country
		if country == "" {
			if country, err = f.authorCountry(ctx, r); err != nil {
				return nil, err
			}
		}
		reader, err := f.readerOf(ctx, p)
		if err != nil {
			return nil, err
		}
		res := &resolver{db: f.DB, r: reader, officers: map[string][]string{}}
		ok, err := res.may(ctx, r.author, country)
		if err != nil {
			return nil, err
		}
		if ok {
			basis = "peer_ia"
			if p.ActiveRole == rules.CDRole {
				basis = "cd_fallback"
			}
		}
	}
	review, err := f.reviewFacts(ctx, r)
	if err != nil {
		return nil, err
	}
	var facts [][2]string
	if kind == kindIndicator {
		facts = append([][2]string{{"Calculation", r.fields["calculation"]}, {"Limitations", r.fields["limitations"]}}, review...)
	} else {
		facts = append([][2]string{{"Definition", r.fields["definition"]}}, review...)
	}
	title := "Review " + r.name
	if basis == "" {
		return drawer(spec{title: title, subtitle: "Measurement framework", facts: facts,
			empty: "A second Impact Assessment officer in the author's country reviews this; the Country Director acknowledges only where there is none."}), nil
	}
	subtitle := "Review as a second Impact Assessment officer"
	if basis == "cd_fallback" {
		subtitle = "Acknowledge as Country Director (no second IA officer in the country)"
	}
	return drawer(spec{title: title, subtitle: subtitle, submit: "Record decision", facts: facts, fields: []*screensv1.DrawerField{
		{Name: "decision", Label: "Decision", Kind: "select", Required: true, Value: "approve", Options: options(rules.Saves.ReviewDecisions, "")},
		{Name: "note", Label: "Review note", Kind: "textarea", Help: "Required when returning it."},
	}}), nil
}

// Drawer draws the framework's drawers; served is false for any other path
// or a role whose page refuses it.
func (f Framework) Drawer(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.PageDrawer, bool, error) {
	path, _, _ := strings.Cut(rawPath, "?")
	if !strings.HasPrefix(path, Path) || !pageaccess.CanOpen(p.ActiveRole, false, path) {
		return nil, false, nil
	}
	var d *screensv1.PageDrawer
	var err error
	switch {
	case path == Path+"areas/new":
		if !mayAuthor(p) {
			d = drawer(spec{title: "New outcome area", subtitle: "Measurement framework", empty: "Only Impact Assessment defines outcome areas."})
			break
		}
		d = drawer(spec{title: "New outcome area", subtitle: "Saved as a draft; a second reviewer approves it", submit: "Save draft",
			fields: areaFields(nil)})
	case path == Path+"indicators/new":
		if !mayAuthor(p) {
			d = drawer(spec{title: "New indicator", subtitle: "Measurement framework", empty: "Only Impact Assessment defines indicators."})
			break
		}
		var fields []*screensv1.DrawerField
		if fields, err = f.indicatorFields(ctx, nil); err == nil {
			d = drawer(spec{title: "New indicator", subtitle: "Saved as a draft; a second reviewer approves it", submit: "Save draft", fields: fields})
		}
	case areaOnePath.MatchString(path) && !strings.HasSuffix(path, "/save"):
		d, err = f.areaDrawer(ctx, p, areaOnePath.FindStringSubmatch(path)[1])
	case indicatorOnePath.MatchString(path) && !strings.HasSuffix(path, "/save"):
		d, err = f.indicatorDrawer(ctx, p, indicatorOnePath.FindStringSubmatch(path)[1])
	case purposePath.MatchString(path) && !strings.HasSuffix(path, "/save"):
		d, err = f.purposeDrawer(ctx, p, purposePath.FindStringSubmatch(path)[1])
	case submitPath.MatchString(path) && !strings.HasSuffix(path, "/save"):
		m := submitPath.FindStringSubmatch(path)
		d, err = f.submitDrawer(ctx, p, m[1], m[2])
	case reviewPath.MatchString(path) && !strings.HasSuffix(path, "/save"):
		m := reviewPath.FindStringSubmatch(path)
		d, err = f.reviewDrawer(ctx, p, m[1], m[2])
	default:
		return nil, false, nil
	}
	return d, true, err
}

func tabURL(tab string) string { return Path + "?" + url.Values{"tab": {tab}}.Encode() }

// Saved is a save's answer: its message and where the register returns.
type Saved struct{ Message, Back string }

// Save is the framework's saves; served is false for any other path.
func (f Framework) Save(ctx context.Context, p auth.Principal, rawPath, form string, values map[string]string) (*Saved, bool, error) {
	path, _, _ := strings.Cut(rawPath, "?")
	if !strings.HasPrefix(path, Path) || !pageaccess.CanOpen(p.ActiveRole, false, path) {
		return nil, false, nil
	}
	area := func() map[string]string {
		return map[string]string{"name": values["name"], "definition": values["definition"], "interventions": values["interventions"],
			"change_reason": values["change_reason"]}
	}
	indicator := func() map[string]string {
		out := map[string]string{}
		for _, k := range append([]string{"key", "name", "level", "outcome_area", "source", "unit", "calculation", "effective_from",
			"change_reason"}, rules.Saves.IndicatorTextFields...) {
			out[k] = values[k]
		}
		return out
	}
	switch {
	case (path == Path && form == ProposeForm) || path == Path+"areas/propose":
		n, err := f.ProposeAreas(ctx, p)
		if err != nil {
			return nil, true, err
		}
		plural := "s"
		if n == 1 {
			plural = ""
		}
		return &Saved{Message: fmt.Sprintf("%d proposed outcome area%s drafted for review.", n, plural), Back: tabURL("areas")}, true, nil
	case areaNewPath.MatchString(path), areaOnePath.MatchString(path):
		id := ""
		if m := areaOnePath.FindStringSubmatch(path); m != nil {
			id = m[1]
			if _, err := f.load(ctx, nil, kindArea, id, false); err != nil {
				return nil, true, err
			}
		}
		name, version, err := f.SaveArea(ctx, p, id, area())
		if err != nil {
			return nil, true, err
		}
		return &Saved{Message: fmt.Sprintf("%s v%d saved as a draft.", name, version), Back: tabURL("areas")}, true, nil
	case indicatorNewPath.MatchString(path), indicatorOnePath.MatchString(path):
		id := ""
		if m := indicatorOnePath.FindStringSubmatch(path); m != nil {
			id = m[1]
			if _, err := f.load(ctx, nil, kindIndicator, id, false); err != nil {
				return nil, true, err
			}
		}
		name, version, err := f.SaveIndicator(ctx, p, id, indicator())
		if err != nil {
			return nil, true, err
		}
		return &Saved{Message: fmt.Sprintf("%s v%d saved as a draft.", name, version), Back: tabURL("indicators")}, true, nil
	case purposePath.MatchString(path):
		data := map[string]string{}
		for _, k := range []string{"impact_indicators", "required_evidence", "verification_method", "follow_up_days", "limitations", "change_reason"} {
			data[k] = values[k]
		}
		label, version, err := f.SavePurpose(ctx, p, purposePath.FindStringSubmatch(path)[1], data)
		if err != nil {
			return nil, true, err
		}
		return &Saved{Message: fmt.Sprintf("Measurement for %s saved as draft v%d.", label, version), Back: tabURL("purposes")}, true, nil
	case submitPath.MatchString(path):
		m := submitPath.FindStringSubmatch(path)
		back, err := f.tabFor(ctx, m[1], m[2])
		if err != nil {
			return nil, true, err
		}
		name, err := f.Submit(ctx, p, m[1], m[2], values["change_reason"])
		if err != nil {
			return nil, true, err
		}
		return &Saved{Message: name + " submitted for review.", Back: back}, true, nil
	case reviewPath.MatchString(path):
		m := reviewPath.FindStringSubmatch(path)
		back, err := f.tabFor(ctx, m[1], m[2])
		if err != nil {
			return nil, true, err
		}
		decision := values["decision"]
		name, err := f.Review(ctx, p, m[1], m[2], decision, values["note"])
		if err != nil {
			return nil, true, err
		}
		what := "returned to its author"
		if decision == "approve" {
			what = "approved"
		}
		return &Saved{Message: name + " " + what + ".", Back: back}, true, nil
	}
	return nil, false, nil
}

// tabFor is _tab_for.
func (f Framework) tabFor(ctx context.Context, kind, id string) (string, error) {
	r, err := f.load(ctx, nil, kind, id, false)
	if err != nil {
		return "", err
	}
	switch {
	case kind == kindArea:
		return tabURL("areas"), nil
	case strings.HasPrefix(r.key, rules.LoanPurposeKeyPrefix):
		return tabURL("purposes"), nil
	}
	return tabURL("indicators"), nil
}

// IsRefusal says whether err is a framework rule saying no; notFound when
// the view answers 404.
func IsRefusal(err error) (message string, notFound, ok bool) {
	var r *Refusal
	if errors.As(err, &r) {
		return r.Message, r.NotFound, true
	}
	return "", false, false
}
