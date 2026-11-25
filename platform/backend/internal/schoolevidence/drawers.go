package schoolevidence

// School evidence's drawers (apps.frontend.views.ia_school_evidence_views)
// drawn in Go with Django absent: Record a learning result, discipleship
// practice or an EdTech deployment; one record (verify it, correct or
// withdraw it, or read it); and Record an EdTech check. They are the shared
// HR form drawer.

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iaframework"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
)

var (
	newPath    = regexp.MustCompile(`^/ia/school-evidence/(learning|discipleship|edtech)/(new|save)/?$`)
	recordPath = regexp.MustCompile(`^/ia/school-evidence/(learning|discipleship|edtech|check)/([A-Za-z0-9]{1,30})/(decide|correct)?$`)
	checkPath  = regexp.MustCompile(`^/ia/school-evidence/edtech/([A-Za-z0-9]{1,30})/check(/save)?$`)
)

type spec struct {
	title, subtitle, submit, empty, note, noteTone string
	facts                                          [][2]string
	fields                                         []*screensv1.DrawerField
}

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
	if s.submit == "" {
		if s.empty != "" {
			d.Items = append(d.Items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: s.empty, Tone: "info"}}})
		}
		d.CancelLabel = "Close"
		return d
	}
	if s.note != "" {
		tone := s.noteTone
		if tone == "" {
			tone = "info"
		}
		d.Items = append(d.Items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: s.note, Tone: tone}}})
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

func opts(pairs [][2]string, blank string) []*screensv1.DrawerOption {
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

func zero() *float64 { v := 0.0; return &v }

func one() *float64 { v := 1.0; return &v }

func step(v float64) *float64 { return &v }

// row is one record's columns, as JSON reads them (numbers kept as written).
type row map[string]any

func (r row) str(key string) string {
	switch v := r[key].(type) {
	case nil:
		return ""
	case string:
		if len(v) >= 10 && len(v) <= 32 && v[4] == '-' && strings.Contains(v, "T") {
			return v
		}
		return v
	case json.Number:
		return v.String()
	case bool:
		if v {
			return "True"
		}
		return "False"
	}
	return fmt.Sprint(r[key])
}

// value is _value: a field's current value for the form.
func (r row) value(key, fallback string) string {
	if r == nil || r[key] == nil {
		return fallback
	}
	return r.str(key)
}

func commonFields(r row) []*screensv1.DrawerField {
	return []*screensv1.DrawerField{
		{Name: "evidence_reference", Label: "Evidence reference", Kind: "text", Value: r.value("evidence_reference", ""), MaxLength: maxLen(512),
			Placeholder: "Salesforce record, report or file reference"},
		{Name: "notes", Label: "Notes", Kind: "textarea", Value: r.value("notes", ""), MaxLength: maxLen(4000)},
	}
}

func schoolField(r row) []*screensv1.DrawerField {
	if r != nil {
		return nil
	}
	return []*screensv1.DrawerField{{Name: "school_id", Label: "School ID", Kind: "text", Required: true, MaxLength: maxLen(64),
		Help: "The school's directory ID; the school must be in your country."}}
}

func learningFields(r row) []*screensv1.DrawerField {
	fs := append(schoolField(r),
		&screensv1.DrawerField{Name: "assessment_type", Label: "Assessment", Kind: "select", Required: true, Options: opts(rules.AssessmentTypes, ""),
			Value: r.value("assessment_type", "onetest")},
		&screensv1.DrawerField{Name: "assessed_on", Label: "Assessed on", Kind: "date", Required: true, Value: r.value("assessed_on", "")},
		&screensv1.DrawerField{Name: "grade_level", Label: "Class or grade", Kind: "text", Required: true, MaxLength: maxLen(32), Placeholder: "e.g. P6",
			Value: r.value("grade_level", "")},
		&screensv1.DrawerField{Name: "subject", Label: "Subject", Kind: "text", Required: true, MaxLength: maxLen(64), Placeholder: "e.g. Literacy",
			Value: r.value("subject", "")},
		&screensv1.DrawerField{Name: "learners_tested", Label: "Learners tested", Kind: "number", Required: true, Min: one(), Value: r.value("learners_tested", "")},
		&screensv1.DrawerField{Name: "mean_score", Label: "Mean score", Kind: "number", Min: zero(), Step: step(0.01), Value: r.value("mean_score", ""),
			Help: "Record the mean score, the learners proficient, or both."},
		&screensv1.DrawerField{Name: "max_score", Label: "Maximum possible score", Kind: "number", Min: zero(), Step: step(0.01), Value: r.value("max_score", ""),
			Help: "Lets results on different scales be compared as a percentage."},
		&screensv1.DrawerField{Name: "learners_proficient", Label: "Learners proficient", Kind: "number", Min: zero(), Value: r.value("learners_proficient", "")},
	)
	return append(fs, commonFields(r)...)
}

func yesNoField(name, label string, r row) *screensv1.DrawerField {
	v := ""
	switch r.value(name, "") {
	case "True":
		v = "yes"
	case "False":
		v = "no"
	}
	return &screensv1.DrawerField{Name: name, Label: label, Kind: "select", Value: v,
		Options: opts([][2]string{{"yes", "Yes"}, {"no", "No"}}, "Not observed")}
}

func discipleshipFields(r row) []*screensv1.DrawerField {
	n := func(name, label string) *screensv1.DrawerField {
		return &screensv1.DrawerField{Name: name, Label: label, Kind: "number", Min: zero(), Value: r.value(name, "")}
	}
	fs := append(schoolField(r),
		&screensv1.DrawerField{Name: "observed_on", Label: "Observed on", Kind: "date", Required: true, Value: r.value("observed_on", "")},
		n("devotions_per_week", "Whole-school devotions a week"), n("discipleship_groups_active", "Active discipleship or Bible groups"),
		n("learners_in_groups", "Learners in those groups"), n("learners_enrolled", "Learners enrolled"),
		n("staff_in_devotions_pct", "Staff taking part in devotions (%)"),
		yesNoField("spiritual_lead_in_post", "A spiritual lead is in post", r), yesNoField("bible_lessons_timetabled", "Bible lessons are timetabled", r),
	)
	return append(fs, commonFields(r)...)
}

func (e Evidence) projects(ctx context.Context) ([][2]string, error) {
	rows, err := e.DB.Query(ctx, `SELECT id, name FROM project WHERE deleted_at IS NULL ORDER BY name`)
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the projects: %w", err)
	}
	defer rows.Close()
	var out [][2]string
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, err
		}
		out = append(out, [2]string{id, name})
	}
	return out, rows.Err()
}

func (e Evidence) edtechFields(ctx context.Context, r row) ([]*screensv1.DrawerField, error) {
	projects, err := e.projects(ctx)
	if err != nil {
		return nil, err
	}
	n := func(name, label string) *screensv1.DrawerField {
		return &screensv1.DrawerField{Name: name, Label: label, Kind: "number", Min: zero(), Value: r.value(name, "")}
	}
	fs := append(schoolField(r),
		&screensv1.DrawerField{Name: "asset_type", Label: "Technology", Kind: "select", Required: true, Options: opts(rules.AssetTypes, "Choose"),
			Value: r.value("asset_type", "")},
		&screensv1.DrawerField{Name: "quantity", Label: "Units deployed", Kind: "number", Required: true, Min: one(), Value: r.value("quantity", "")},
		&screensv1.DrawerField{Name: "deployed_on", Label: "Deployed on", Kind: "date", Required: true, Value: r.value("deployed_on", "")},
		&screensv1.DrawerField{Name: "funding", Label: "Funded by", Kind: "select", Required: true, Options: opts(rules.Funding, "Choose"),
			Value: r.value("funding", "")},
		&screensv1.DrawerField{Name: "project", Label: "Special project", Kind: "select", Options: opts(projects, "None"),
			Value: r.value("project_id", ""), Help: "Required when a special project funded it."},
		n("teachers_trained", "Teachers trained to use it"), n("learners_with_access", "Learners with access"),
	)
	return append(fs, commonFields(r)...), nil
}

func checkFields(r row) []*screensv1.DrawerField {
	n := func(name, label string) *screensv1.DrawerField {
		return &screensv1.DrawerField{Name: name, Label: label, Kind: "number", Min: zero(), Value: r.value(name, "")}
	}
	units := n("units_functional", "Units working")
	units.Required = true
	fs := []*screensv1.DrawerField{
		{Name: "checked_on", Label: "Checked on", Kind: "date", Required: true, Value: r.value("checked_on", "")},
		units, n("teachers_using", "Teachers using them"), n("learners_using", "Learners using them"),
		{Name: "weekly_use_hours", Label: "Hours of use a week", Kind: "number", Min: zero(), Step: step(0.1), Value: r.value("weekly_use_hours", "")},
		{Name: "issues", Label: "Issues found", Kind: "textarea", Value: r.value("issues", ""), MaxLength: maxLen(4000)},
	}
	return append(fs, commonFields(r)...)
}

func (e Evidence) fieldsFor(ctx context.Context, kind string, r row) ([]*screensv1.DrawerField, error) {
	switch kind {
	case learning:
		return learningFields(r), nil
	case discipleship:
		return discipleshipFields(r), nil
	case edtech:
		return e.edtechFields(ctx, r)
	}
	return checkFields(r), nil
}

// load reads one record in the reader's reach as JSON, with its school and,
// for a check, its deployment; nil when it is not in reach.
func (e Evidence) load(ctx context.Context, p auth.Principal, kind, id string) (row, error) {
	var args []any
	where, err := e.reach(ctx, p, &args)
	if err != nil {
		return nil, err
	}
	extra := "NULL::jsonb"
	if kind == check {
		extra = "(SELECT to_jsonb(d) FROM impact_edtech_deployment d WHERE d.id = x.deployment_id)"
	} else if kind == edtech {
		extra = "(SELECT jsonb_build_object('name', j.name) FROM project j WHERE j.id = x.project_id)"
	}
	var raw []byte
	err = e.DB.QueryRow(ctx, `SELECT to_jsonb(x) || jsonb_build_object('school_name', s.name, 'related', `+extra+`)
FROM `+kinds[kind].table+` x JOIN school s ON s.id = x.school_id
WHERE x.deleted_at IS NULL AND `+where+fmt.Sprintf(` AND x.id = $%d`, len(args)+1), append(args, id)...).Scan(&raw)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the record: %w", err)
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var r row
	if err := dec.Decode(&r); err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the record: %w", err)
	}
	return r, nil
}

// dayOf is _day of a stored date or moment.
func dayOf(v string) string {
	if v == "" {
		return ""
	}
	for _, layout := range []string{time.DateOnly, time.RFC3339Nano, "2006-01-02T15:04:05.999999-07:00"} {
		if t, err := time.Parse(layout, v); err == nil {
			return t.Format("2 Jan 2006")
		}
	}
	return v
}

func yesNoLabel(v string) string {
	switch v {
	case "True":
		return "Yes"
	case "False":
		return "No"
	}
	return ""
}

func (e Evidence) userName(ctx context.Context, id string) (string, bool, error) {
	if id == "" {
		return "", false, nil
	}
	var name string
	err := e.DB.QueryRow(ctx, `SELECT COALESCE(name, '') FROM "user" WHERE id = $1`, id).Scan(&name)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", false, nil
	}
	if err != nil {
		return "", false, fmt.Errorf("schoolevidence: reading a name: %w", err)
	}
	return name, true, nil
}

// facts is _facts.
func (e Evidence) facts(ctx context.Context, kind string, r row) ([][2]string, error) {
	facts := [][2]string{{"School", r.str("school_name")}, {"Financial year", "FY" + r.str("fy")}}
	switch kind {
	case learning:
		facts = append(facts, [2]string{"Assessment", label(rules.AssessmentTypes, r.str("assessment_type"))},
			[2]string{"Assessed on", dayOf(r.str("assessed_on"))}, [2]string{"Class · subject", r.str("grade_level") + " · " + r.str("subject")},
			[2]string{"Learners tested", r.str("learners_tested")}, [2]string{"Mean score", r.str("mean_score")},
			[2]string{"Maximum score", r.str("max_score")}, [2]string{"Learners proficient", r.str("learners_proficient")})
	case discipleship:
		staff := r.str("staff_in_devotions_pct")
		if staff != "" {
			staff += "%"
		}
		facts = append(facts, [2]string{"Observed on", dayOf(r.str("observed_on"))}, [2]string{"Devotions a week", r.str("devotions_per_week")},
			[2]string{"Active groups", r.str("discipleship_groups_active")}, [2]string{"Learners in groups", r.str("learners_in_groups")},
			[2]string{"Learners enrolled", r.str("learners_enrolled")}, [2]string{"Staff in devotions", staff},
			[2]string{"Spiritual lead in post", yesNoLabel(r.str("spiritual_lead_in_post"))},
			[2]string{"Bible lessons timetabled", yesNoLabel(r.str("bible_lessons_timetabled"))})
	case edtech:
		project := ""
		if rel, ok := r["related"].(map[string]any); ok {
			project = fmt.Sprint(rel["name"])
		}
		facts = append(facts, [2]string{"Technology", r.str("quantity") + " × " + label(rules.AssetTypes, r.str("asset_type"))},
			[2]string{"Deployed on", dayOf(r.str("deployed_on"))}, [2]string{"Funded by", label(rules.Funding, r.str("funding"))},
			[2]string{"Special project", project}, [2]string{"Teachers trained", r.str("teachers_trained")},
			[2]string{"Learners with access", r.str("learners_with_access")})
	default:
		d := row{}
		if rel, ok := r["related"].(map[string]any); ok {
			d = row(rel)
		}
		facts = append(facts, [2]string{"Deployment", fmt.Sprintf("%s × %s, deployed %s", d.str("quantity"), label(rules.AssetTypes, d.str("asset_type")),
			dayOf(d.str("deployed_on")))}, [2]string{"Checked on", dayOf(r.str("checked_on"))}, [2]string{"Units working", r.str("units_functional")},
			[2]string{"Teachers using", r.str("teachers_using")}, [2]string{"Learners using", r.str("learners_using")},
			[2]string{"Hours of use a week", r.str("weekly_use_hours")}, [2]string{"Issues", r.str("issues")})
	}
	if r.str("source_activity_id") != "" {
		facts = append(facts, [2]string{"Recorded from", "The OneTest diagnostic visit it came from"})
	}
	recorder, found, err := e.userName(ctx, r.str("recorded_by_user_id"))
	if err != nil {
		return nil, err
	}
	if !found {
		recorder = "Staff member"
	}
	facts = append(facts, [2]string{"Evidence reference", r.str("evidence_reference")}, [2]string{"Notes", r.str("notes")},
		[2]string{"Recorded by", recorder}, [2]string{"Status", label(rules.Statuses, r.str("verification_status"))})
	if v := r.str("verified_by_user_id"); v != "" {
		who, _, err := e.userName(ctx, v)
		if err != nil {
			return nil, err
		}
		title := "Confirmed by"
		if r.str("verification_status") == returned {
			title = "Returned by"
		}
		facts = append(facts, [2]string{title, who + " · " + dayOf(r.str("verified_at"))})
	}
	if v := r.str("return_reason"); v != "" {
		facts = append(facts, [2]string{"What to correct", v})
	}
	return facts, nil
}

// canVerify is decorate's can_verify.
func (e Evidence) canVerify(ctx context.Context, p auth.Principal, r row) (bool, error) {
	if r.str("verification_status") != pending {
		return false, nil
	}
	reviewer, err := iaframework.NewReviewer(ctx, e.DB, p)
	if err != nil {
		return false, err
	}
	return reviewer.May(ctx, r.str("recorded_by_user_id"), r.str("country"))
}

var newTitles = map[string]string{learning: "Record a learning result", discipleship: "Record discipleship practice", edtech: "Record an EdTech deployment"}

func (e Evidence) newDrawer(ctx context.Context, p auth.Principal, kind string) (*screensv1.PageDrawer, error) {
	if !mayRecord(p) {
		return drawer(spec{title: newTitles[kind], subtitle: "School evidence", empty: "Only Impact Assessment records school evidence."}), nil
	}
	fields, err := e.fieldsFor(ctx, kind, nil)
	if err != nil {
		return nil, err
	}
	note := ""
	if kind == learning {
		note = "Class-level results only: no pupil names or records."
	}
	return drawer(spec{title: newTitles[kind], subtitle: "School evidence · pending until a second person confirms it", submit: "Record",
		fields: fields, note: note}), nil
}

func (e Evidence) recordDrawer(ctx context.Context, p auth.Principal, kind, id string) (*screensv1.PageDrawer, error) {
	r, err := e.load(ctx, p, kind, id)
	if err != nil {
		return nil, err
	}
	kindLabel := kinds[kind].label
	if r == nil {
		return drawer(spec{title: kindLabel, subtitle: "School evidence", empty: "This record is not in your country."}), nil
	}
	facts, err := e.facts(ctx, kind, r)
	if err != nil {
		return nil, err
	}
	status := r.str("verification_status")
	subtitle := r.str("school_name") + " · " + label(rules.Statuses, status)
	verify, err := e.canVerify(ctx, p, r)
	if err != nil {
		return nil, err
	}
	if verify {
		return drawer(spec{title: "Verify " + strings.ToLower(kindLabel), subtitle: subtitle, submit: "Save decision", facts: facts,
			note: "Check the figures against the evidence reference before confirming.",
			fields: []*screensv1.DrawerField{
				{Name: "decision", Label: "Decision", Kind: "select", Required: true, Value: "confirm",
					Options: opts([][2]string{{"confirm", "Confirm — it counts as evidence"}, {"return", "Return to the recorder to correct"}}, "")},
				{Name: "reason", Label: "What needs correcting", Kind: "textarea", MaxLength: maxLen(4000),
					Help: "Required when you return it; the recorder reads it."},
			}}), nil
	}
	mine := r.str("recorded_by_user_id") == p.UserID
	if mine && status != confirmed {
		fields, err := e.fieldsFor(ctx, kind, r)
		if err != nil {
			return nil, err
		}
		fields = append(fields, &screensv1.DrawerField{Name: "withdraw", Label: "Withdraw this record instead", Kind: "checkbox",
			Help: "It was recorded in error; it will not count and stays in the audit trail."})
		kept := [][2]string{facts[0]}
		for _, f := range facts {
			if f[0] == "What to correct" {
				kept = append(kept, f)
			}
		}
		tone := "info"
		if status == returned {
			tone = "warning"
		}
		return drawer(spec{title: "Correct " + strings.ToLower(kindLabel), subtitle: subtitle, submit: "Save and send for verification",
			facts: kept, fields: fields, noteTone: tone,
			note: "You recorded this, so someone else confirms it. Saving sends it back for verification."}), nil
	}
	note := "Read only."
	switch {
	case mine && status == pending:
		note = "You recorded this, so a second Impact Assessment officer confirms it."
	case status == pending:
		note = "A second Impact Assessment officer in this country confirms it; the Country Director confirms only where the recorder is the country's one officer."
	}
	return drawer(spec{title: kindLabel, subtitle: subtitle, facts: facts, empty: note}), nil
}

func (e Evidence) checkDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	const title = "Record an EdTech check"
	d, err := e.visibleDeployment(ctx, p, id)
	if err != nil {
		return nil, err
	}
	switch {
	case d == nil:
		return drawer(spec{title: title, subtitle: "School evidence", empty: "This deployment is not in your country."}), nil
	case !mayRecord(p):
		return drawer(spec{title: title, subtitle: d.schoolName, empty: "Only Impact Assessment records checks."}), nil
	case d.status != confirmed:
		return drawer(spec{title: title, subtitle: d.schoolName, empty: "Check a deployment once it is confirmed."}), nil
	}
	return drawer(spec{title: title, subtitle: fmt.Sprintf("%s · %d × %s", d.schoolName, d.quantity, label(rules.AssetTypes, d.asset)),
		submit: "Record check", fields: checkFields(nil)}), nil
}

// Drawer draws school evidence's drawers; served is false for any other
// path or a role whose page refuses it.
func (e Evidence) Drawer(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.PageDrawer, bool, error) {
	path, _, _ := strings.Cut(rawPath, "?")
	if !strings.HasPrefix(path, Path) || !pageaccess.CanOpen(p.ActiveRole, false, path) {
		return nil, false, nil
	}
	var d *screensv1.PageDrawer
	var err error
	switch {
	case newPath.MatchString(path) && strings.Contains(path, "/new"):
		d, err = e.newDrawer(ctx, p, newPath.FindStringSubmatch(path)[1])
	case checkPath.MatchString(path) && !strings.HasSuffix(path, "/save"):
		d, err = e.checkDrawer(ctx, p, checkPath.FindStringSubmatch(path)[1])
	case recordPath.MatchString(path):
		m := recordPath.FindStringSubmatch(path)
		if m[3] != "" || m[2] == "new" || m[2] == "save" {
			return nil, false, nil
		}
		d, err = e.recordDrawer(ctx, p, m[1], m[2])
	default:
		return nil, false, nil
	}
	return d, true, err
}

// Saved is a save's answer: its message and where the register returns.
type Saved struct{ Message, Back string }

func tabURL(kind string) string { return Path + "?" + url.Values{"tab": {tabOf(kind)}}.Encode() }

// Save is school evidence's saves; served is false for any other path.
func (e Evidence) Save(ctx context.Context, p auth.Principal, rawPath string, values map[string]string) (*Saved, bool, error) {
	path, _, _ := strings.Cut(rawPath, "?")
	if !strings.HasPrefix(path, Path) || !pageaccess.CanOpen(p.ActiveRole, false, path) {
		return nil, false, nil
	}
	switch {
	case newPath.MatchString(path):
		kind := newPath.FindStringSubmatch(path)[1]
		name, err := e.Record(ctx, p, kind, values)
		if err != nil {
			return nil, true, err
		}
		return &Saved{Message: fmt.Sprintf("%s recorded for %s; it counts once someone else confirms it.", kinds[kind].label, name),
			Back: tabURL(kind)}, true, nil
	case checkPath.MatchString(path):
		name, err := e.RecordCheck(ctx, p, checkPath.FindStringSubmatch(path)[1], values)
		if err != nil {
			return nil, true, err
		}
		return &Saved{Message: "Check recorded for " + name + "; it counts once someone else confirms it.", Back: tabURL(edtech)}, true, nil
	case recordPath.MatchString(path):
		m := recordPath.FindStringSubmatch(path)
		kind, id, step := m[1], m[2], m[3]
		if step == "" {
			r, err := e.load(ctx, p, kind, id)
			if err != nil {
				return nil, true, err
			}
			if r == nil {
				return nil, true, missing("That record is not in your country.")
			}
			verify, err := e.canVerify(ctx, p, r)
			if err != nil {
				return nil, true, err
			}
			step = "correct"
			if verify {
				step = "decide"
			}
		}
		if step == "decide" {
			decision := values["decision"]
			name, err := e.Decide(ctx, p, kind, id, decision, values["reason"])
			if err != nil {
				return nil, true, err
			}
			what := "returned to the recorder"
			if decision == "confirm" {
				what = "confirmed"
			}
			return &Saved{Message: fmt.Sprintf("%s for %s %s.", kinds[kind].label, name, what), Back: tabURL(kind)}, true, nil
		}
		withdrawing := checkedValue(values["withdraw"])
		var name string
		var err error
		if withdrawing {
			name, err = e.Withdraw(ctx, p, kind, id)
		} else {
			name, err = e.Correct(ctx, p, kind, id, values)
		}
		if err != nil {
			return nil, true, err
		}
		what := "sent for verification"
		if withdrawing {
			what = "withdrawn"
		}
		return &Saved{Message: fmt.Sprintf("%s for %s %s.", kinds[kind].label, name, what), Back: tabURL(kind)}, true, nil
	}
	return nil, false, nil
}

func checkedValue(v string) bool {
	v = strings.TrimSpace(strings.ToLower(v))
	return v != "" && v != "false" && v != "off" && v != "0"
}

// IsRefusal says whether err is an evidence rule saying no.
func IsRefusal(err error) (message string, notFound, ok bool) {
	var r *Refusal
	if errors.As(err, &r) {
		return r.Message, r.NotFound, true
	}
	return "", false, false
}
