package schoolevidence

// School evidence's saves (apps.impact.evidence_services) with Django
// absent: a learning result, discipleship record or EdTech deployment
// recorded by Impact Assessment, a check of a confirmed deployment, the
// recorder's correction or withdrawal, and the second person's decision to
// confirm or return it. Each check is the existing one, in its order and
// words; nothing counts until someone other than the recorder confirms it.

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"math/big"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iaframework"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Refusal is an evidence rule saying no, in the existing words.
type Refusal struct {
	Message  string
	NotFound bool
}

func (r *Refusal) Error() string { return r.Message }

func refuse(m string) error  { return &Refusal{Message: m} }
func missing(m string) error { return &Refusal{Message: m, NotFound: true} }

const (
	pending       = "pending"
	confirmed     = "confirmed"
	returned      = "returned"
	eventReturned = "ia.school_evidence.returned"
	referenceMax  = 512
	notesMax      = 4000
	noticeMax     = 500
	roleIA        = "ImpactAssessment"
	roleCD        = "CountryDirector"
)

// kindOf is one evidence kind: its table, model and label.
type kindOf struct{ table, model, label, dated string }

var kinds = map[string]kindOf{
	learning:     {"impact_learning_result", "LearningAssessmentResult", "Learning result", "assessed_on"},
	discipleship: {"impact_discipleship_record", "DiscipleshipIndicatorRecord", "Discipleship record", "observed_on"},
	edtech:       {"impact_edtech_deployment", "EdTechDeployment", "EdTech deployment", "deployed_on"},
	check:        {"impact_edtech_check", "EdTechCheck", "EdTech check", "checked_on"},
}

// tabOf is KIND_TAB.
func tabOf(kind string) string {
	if kind == check {
		return edtech
	}
	return kind
}

// Evidence is school evidence's saves over the gateway's pool.
type Evidence struct {
	DB     *pgxpool.Pool
	Push   activities.NoticePush
	Logger *slog.Logger
	Now    func() time.Time
}

func (e Evidence) now() time.Time {
	if e.Now != nil {
		return e.Now().UTC().Truncate(time.Microsecond)
	}
	return time.Now().UTC().Truncate(time.Microsecond)
}

func (e Evidence) today() time.Time {
	l := e.now().In(zone)
	return time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
}

func (e Evidence) write(ctx context.Context, fn func(pgx.Tx) error) error {
	tx, err := e.DB.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("schoolevidence: opening the save: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := fn(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// mayRecord is may_record.
func mayRecord(p auth.Principal) bool { return p.ActiveRole == roleIA }

const notRecorder = "Only Impact Assessment records school evidence here. Field staff record OneTest results from the visit they completed."

// reach is evidence_schools as a WHERE clause on school `s`.
func (e Evidence) reach(ctx context.Context, p auth.Principal, args *[]any) (string, error) {
	scope, err := schooldirectory.ResolveScope(ctx, e.DB, p, e.now())
	if err != nil {
		return "", fmt.Errorf("schoolevidence: resolving the reader's scope: %w", err)
	}
	if scope.SummaryOnly {
		return "false", nil
	}
	return schooldirectory.AnalyticsReach(scope, args), nil
}

func capitalize(key string) string {
	s := strings.ReplaceAll(key, "_", " ")
	if s == "" {
		return s
	}
	return strings.ToUpper(s[:1]) + strings.ToLower(s[1:])
}

// form reads one save's values as the services' parsers read data.
type form map[string]string

func (f form) raw(key string) string { return strings.TrimSpace(f[key]) }

// text is _text.
func (f form) text(key string, required bool, label string, max int) (string, error) {
	v := f.raw(key)
	if label == "" {
		label = capitalize(key)
	}
	if required && v == "" {
		return "", refuse(label + " is required.")
	}
	if max > 0 && utf8.RuneCountInString(v) > max {
		return "", refuse(fmt.Sprintf("%s is longer than %d characters.", label, max))
	}
	return v, nil
}

var isoDay = regexp.MustCompile(`^(\d{4})-?(\d{2})-?(\d{2})$`)

// date is _date.
func (f form) date(key, label string, required, notFuture bool, today time.Time) (*time.Time, error) {
	raw := f.raw(key)
	if raw == "" {
		if required {
			return nil, refuse(label + " is required.")
		}
		return nil, nil
	}
	if len(raw) > 10 {
		raw = raw[:10]
	}
	m := isoDay.FindStringSubmatch(raw)
	var d time.Time
	ok := m != nil
	if ok {
		y, _ := strconv.Atoi(m[1])
		mo, _ := strconv.Atoi(m[2])
		dd, _ := strconv.Atoi(m[3])
		d = time.Date(y, time.Month(mo), dd, 0, 0, 0, 0, time.UTC)
		ok = d.Year() == y && int(d.Month()) == mo && d.Day() == dd && y >= 1
	}
	if !ok {
		return nil, refuse(label + " must be a date (YYYY-MM-DD).")
	}
	if notFuture && d.After(today) {
		return nil, refuse(label + " cannot be in the future.")
	}
	return &d, nil
}

// integer is _int.
func (f form) integer(key, label string, required bool, minimum int, maximum *int) (*int, error) {
	raw := f.raw(key)
	if raw == "" {
		if required {
			return nil, refuse(label + " is required.")
		}
		return nil, nil
	}
	v, err := strconv.Atoi(strings.TrimPrefix(raw, "+"))
	if err != nil || strings.HasPrefix(raw, "+-") {
		return nil, refuse(label + " must be a whole number.")
	}
	if v < minimum {
		return nil, refuse(fmt.Sprintf("%s must be at least %d.", label, minimum))
	}
	if maximum != nil && v > *maximum {
		return nil, refuse(fmt.Sprintf("%s must be at most %d.", label, *maximum))
	}
	return &v, nil
}

func intPtr(n int) *int { return &n }

// decimal is _decimal: the value as Decimal quantizes it, half to even.
func (f form) decimal(key, label, minimum, maximum string, places int) (*string, error) {
	raw := f.raw(key)
	if raw == "" {
		return nil, nil
	}
	r, ok := new(big.Rat).SetString(raw)
	if !ok || strings.ContainsAny(raw, "/") {
		return nil, refuse(label + " must be a number.")
	}
	low, _ := new(big.Rat).SetString(minimum)
	if r.Cmp(low) < 0 {
		return nil, refuse(fmt.Sprintf("%s must be at least %s.", label, minimum))
	}
	if maximum != "" {
		high, _ := new(big.Rat).SetString(maximum)
		if r.Cmp(high) > 0 {
			return nil, refuse(fmt.Sprintf("%s must be at most %s.", label, maximum))
		}
	}
	out := quantize(r, places)
	return &out, nil
}

// quantize rounds r to places decimals, half to even, as a decimal string.
func quantize(r *big.Rat, places int) string {
	scale := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(places)), nil)
	scaled := new(big.Rat).Mul(r, new(big.Rat).SetInt(scale))
	num, den := scaled.Num(), scaled.Denom()
	q, rem := new(big.Int).QuoRem(num, den, new(big.Int))
	twice := new(big.Int).Mul(new(big.Int).Abs(rem), big.NewInt(2))
	switch twice.Cmp(den) {
	case 1:
		q.Add(q, big.NewInt(int64(num.Sign())))
	case 0:
		if q.Bit(0) == 1 {
			q.Add(q, big.NewInt(int64(num.Sign())))
		}
	}
	neg := q.Sign() < 0
	digits := new(big.Int).Abs(q).String()
	for len(digits) <= places {
		digits = "0" + digits
	}
	out := digits[:len(digits)-places]
	if places > 0 {
		out += "." + digits[len(digits)-places:]
	}
	if neg {
		out = "-" + out
	}
	return out
}

// tristate is _tristate.
func (f form) tristate(key string) *bool {
	switch strings.ToLower(f.raw(key)) {
	case "yes", "true", "1":
		v := true
		return &v
	case "no", "false", "0":
		v := false
		return &v
	}
	return nil
}

// choice is _choice.
func (f form) choice(key string, choices [][2]string, label string) (string, error) {
	v := f.raw(key)
	for _, c := range choices {
		if c[0] == v {
			return v, nil
		}
	}
	return "", refuse("Choose a " + strings.ToLower(label) + ".")
}

// school is the school a record is for.
type school struct{ id, name, country string }

// findSchool is find_school.
func (e Evidence) findSchool(ctx context.Context, p auth.Principal, code string) (*school, error) {
	code = strings.TrimSpace(code)
	if code == "" {
		return nil, refuse("School ID is required.")
	}
	var args []any
	where, err := e.reach(ctx, p, &args)
	if err != nil {
		return nil, err
	}
	args = append(args, code)
	var s school
	err = e.DB.QueryRow(ctx, `SELECT s.id, s.name, COALESCE(TRIM(g.country), '') FROM school s LEFT JOIN region g ON g.id = s.region_id
WHERE `+where+fmt.Sprintf(` AND (s.school_id = $%d OR s.id = $%d) ORDER BY s.created_at DESC LIMIT 1`, len(args), len(args)), args...).
		Scan(&s.id, &s.name, &s.country)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, refuse("No school with ID " + code + " is in your country.")
	}
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the school: %w", err)
	}
	return &s, nil
}

// fields are one kind's parsed columns, in their insert order.
type fields struct {
	cols   []string
	values []any
	dated  time.Time
}

func (fs *fields) add(col string, v any) {
	fs.cols = append(fs.cols, col)
	fs.values = append(fs.values, v)
}

func nilInt(v *int) any {
	if v == nil {
		return nil
	}
	return *v
}

func nilString(v *string) any {
	if v == nil {
		return nil
	}
	return *v
}

func nilBool(v *bool) any {
	if v == nil {
		return nil
	}
	return *v
}

// learningFields is _learning_fields.
func (e Evidence) learningFields(f form) (*fields, error) {
	learners, err := f.integer("learners_tested", "Learners tested", true, 1, nil)
	if err != nil {
		return nil, err
	}
	mean, err := f.decimal("mean_score", "Mean score", "0", "", 2)
	if err != nil {
		return nil, err
	}
	maximum, err := f.decimal("max_score", "Maximum score", "0.01", "", 2)
	if err != nil {
		return nil, err
	}
	proficient, err := f.integer("learners_proficient", "Learners proficient", false, 0, nil)
	if err != nil {
		return nil, err
	}
	if mean == nil && proficient == nil {
		return nil, refuse("Record a mean score or the number of learners proficient — a result needs at least one of them.")
	}
	if mean != nil && maximum != nil {
		m, _ := new(big.Rat).SetString(*mean)
		x, _ := new(big.Rat).SetString(*maximum)
		if m.Cmp(x) > 0 {
			return nil, refuse("The mean score cannot be above the maximum score.")
		}
	}
	if proficient != nil && *proficient > *learners {
		return nil, refuse("Learners proficient cannot exceed learners tested.")
	}
	assessment, err := f.choice("assessment_type", rules.AssessmentTypes, "Assessment type")
	if err != nil {
		return nil, err
	}
	assessed, err := f.date("assessed_on", "Assessment date", true, true, e.today())
	if err != nil {
		return nil, err
	}
	grade, err := f.text("grade_level", true, "Class or grade", 32)
	if err != nil {
		return nil, err
	}
	subject, err := f.text("subject", true, "Subject", 64)
	if err != nil {
		return nil, err
	}
	fs := &fields{dated: *assessed}
	fs.add("assessment_type", assessment)
	fs.add("assessed_on", *assessed)
	fs.add("grade_level", grade)
	fs.add("subject", subject)
	fs.add("learners_tested", *learners)
	fs.add("mean_score", nilString(mean))
	fs.add("max_score", nilString(maximum))
	fs.add("learners_proficient", nilInt(proficient))
	return fs, nil
}

// discipleshipFields is _discipleship_fields.
func (e Evidence) discipleshipFields(f form) (*fields, error) {
	observed, err := f.date("observed_on", "Observed on", true, true, e.today())
	if err != nil {
		return nil, err
	}
	devotions, err := f.integer("devotions_per_week", "Devotions per week", false, 0, intPtr(35))
	if err != nil {
		return nil, err
	}
	groups, err := f.integer("discipleship_groups_active", "Active discipleship groups", false, 0, nil)
	if err != nil {
		return nil, err
	}
	inGroups, err := f.integer("learners_in_groups", "Learners in discipleship groups", false, 0, nil)
	if err != nil {
		return nil, err
	}
	enrolled, err := f.integer("learners_enrolled", "Learners enrolled", false, 0, nil)
	if err != nil {
		return nil, err
	}
	staff, err := f.integer("staff_in_devotions_pct", "Staff in devotions (%)", false, 0, intPtr(100))
	if err != nil {
		return nil, err
	}
	lead, bible := f.tristate("spiritual_lead_in_post"), f.tristate("bible_lessons_timetabled")
	if devotions == nil && groups == nil && inGroups == nil && enrolled == nil && staff == nil && lead == nil && bible == nil {
		return nil, refuse("Record at least one discipleship indicator.")
	}
	if inGroups != nil && enrolled != nil && *inGroups > *enrolled {
		return nil, refuse("Learners in groups cannot exceed learners enrolled.")
	}
	fs := &fields{dated: *observed}
	fs.add("observed_on", *observed)
	fs.add("devotions_per_week", nilInt(devotions))
	fs.add("discipleship_groups_active", nilInt(groups))
	fs.add("learners_in_groups", nilInt(inGroups))
	fs.add("learners_enrolled", nilInt(enrolled))
	fs.add("staff_in_devotions_pct", nilInt(staff))
	fs.add("spiritual_lead_in_post", nilBool(lead))
	fs.add("bible_lessons_timetabled", nilBool(bible))
	return fs, nil
}

// deploymentFields is _deployment_fields.
func (e Evidence) deploymentFields(ctx context.Context, f form) (*fields, error) {
	var project any
	if id := f.raw("project"); id != "" {
		var found string
		err := e.DB.QueryRow(ctx, `SELECT id FROM project WHERE id = $1`, id).Scan(&found)
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, refuse("Choose a project from the list.")
		}
		if err != nil {
			return nil, fmt.Errorf("schoolevidence: reading the project: %w", err)
		}
		project = found
	}
	asset, err := f.choice("asset_type", rules.AssetTypes, "Technology")
	if err != nil {
		return nil, err
	}
	quantity, err := f.integer("quantity", "Quantity", true, 1, nil)
	if err != nil {
		return nil, err
	}
	deployed, err := f.date("deployed_on", "Deployed on", true, true, e.today())
	if err != nil {
		return nil, err
	}
	funding, err := f.choice("funding", rules.Funding, "Funding")
	if err != nil {
		return nil, err
	}
	teachers, err := f.integer("teachers_trained", "Teachers trained", false, 0, nil)
	if err != nil {
		return nil, err
	}
	learners, err := f.integer("learners_with_access", "Learners with access", false, 0, nil)
	if err != nil {
		return nil, err
	}
	if funding == "project" && project == nil {
		return nil, refuse("Name the special project that funded this technology.")
	}
	fs := &fields{dated: *deployed}
	fs.add("asset_type", asset)
	fs.add("quantity", *quantity)
	fs.add("deployed_on", *deployed)
	fs.add("funding", funding)
	fs.add("project_id", project)
	fs.add("teachers_trained", nilInt(teachers))
	fs.add("learners_with_access", nilInt(learners))
	return fs, nil
}

// deployment is a check's deployment.
type deployment struct {
	id, schoolID, schoolName, country, status, asset string
	quantity                                         int
	deployed                                         time.Time
}

// checkFields is _check_fields.
func (e Evidence) checkFields(f form, d *deployment) (*fields, error) {
	checked, err := f.date("checked_on", "Checked on", true, true, e.today())
	if err != nil {
		return nil, err
	}
	units, err := f.integer("units_functional", "Units working", true, 0, nil)
	if err != nil {
		return nil, err
	}
	teachers, err := f.integer("teachers_using", "Teachers using", false, 0, nil)
	if err != nil {
		return nil, err
	}
	learners, err := f.integer("learners_using", "Learners using", false, 0, nil)
	if err != nil {
		return nil, err
	}
	hours, err := f.decimal("weekly_use_hours", "Hours of use per week", "0", "168", 1)
	if err != nil {
		return nil, err
	}
	issues, err := f.text("issues", false, "", notesMax)
	if err != nil {
		return nil, err
	}
	if *units > d.quantity {
		return nil, refuse(fmt.Sprintf("Units working cannot exceed the %d deployed.", d.quantity))
	}
	if checked.Before(d.deployed) {
		return nil, refuse("A check cannot be dated before the deployment.")
	}
	fs := &fields{dated: *checked}
	fs.add("checked_on", *checked)
	fs.add("units_functional", *units)
	fs.add("teachers_using", nilInt(teachers))
	fs.add("learners_using", nilInt(learners))
	fs.add("weekly_use_hours", nilString(hours))
	fs.add("issues", issues)
	return fs, nil
}

func (e Evidence) parse(ctx context.Context, kind string, f form, d *deployment) (*fields, error) {
	switch kind {
	case learning:
		return e.learningFields(f)
	case discipleship:
		return e.discipleshipFields(f)
	case edtech:
		return e.deploymentFields(ctx, f)
	}
	return e.checkFields(f, d)
}

// duplicateLearning is _duplicate_learning.
func duplicateLearning(ctx context.Context, q pgx.Tx, schoolID string, fs *fields, exclude string) (bool, error) {
	get := func(col string) any {
		for i, c := range fs.cols {
			if c == col {
				return fs.values[i]
			}
		}
		return nil
	}
	var dup bool
	err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM impact_learning_result WHERE deleted_at IS NULL AND school_id = $1
  AND assessment_type = $2 AND assessed_on = $3 AND UPPER(grade_level) = UPPER($4) AND UPPER(subject) = UPPER($5) AND id <> $6)`,
		schoolID, get("assessment_type"), get("assessed_on"), get("grade_level"), get("subject"), exclude).Scan(&dup)
	if err != nil {
		return false, fmt.Errorf("schoolevidence: reading the school's results: %w", err)
	}
	return dup, nil
}

func operationalFY(d time.Time) string {
	if d.Month() >= time.October {
		return strconv.Itoa(d.Year() + 1)
	}
	return strconv.Itoa(d.Year())
}

func evidenceAudit(ctx context.Context, tx pgx.Tx, action, model, id, schoolID, country, status string, p auth.Principal,
	extra map[string]any, reason string, now time.Time) error {
	payload := map[string]any{"school_id": schoolID, "country": country, "status": status}
	for k, v := range extra {
		payload[k] = v
	}
	_, err := audit.Append(ctx, tx, audit.Entry{Action: action, SubjectKind: audit.Text(model), SubjectID: audit.Text(id),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true, Reason: audit.Text(reason),
		Payload: payload}, now)
	if err != nil {
		return fmt.Errorf("schoolevidence: auditing %s: %w", action, err)
	}
	return nil
}

func placeholders(from, n int) string {
	out := make([]string, n)
	for i := range out {
		out[i] = "$" + strconv.Itoa(from+i)
	}
	return strings.Join(out, ", ")
}

// Record is record(principal, kind, data) from the School Evidence page: the
// school's name.
func (e Evidence) Record(ctx context.Context, p auth.Principal, kind string, values map[string]string) (string, error) {
	if kind != learning && kind != discipleship && kind != edtech {
		return "", refuse("Unknown evidence type.")
	}
	if !mayRecord(p) {
		return "", &Refusal{Message: notRecorder, NotFound: false}
	}
	f := form(values)
	s, err := e.findSchool(ctx, p, values["school_id"])
	if err != nil {
		return "", err
	}
	fs, err := e.parse(ctx, kind, f, nil)
	if err != nil {
		return "", err
	}
	now := e.now()
	k := kinds[kind]
	err = e.write(ctx, func(tx pgx.Tx) error {
		if kind == learning {
			dup, err := duplicateLearning(ctx, tx, s.id, fs, "")
			if err != nil {
				return err
			}
			if dup {
				return refuse("This school already has a result for that assessment, date, class and subject. Correct the existing record instead.")
			}
		}
		reference, err := f.text("evidence_reference", false, "", referenceMax)
		if err != nil {
			return err
		}
		notes, err := f.text("notes", false, "", notesMax)
		if err != nil {
			return err
		}
		id := cuid.New()
		cols := append([]string{"id", "created_at", "updated_at", "source", "environment", "deleted_at", "country", "fy",
			"evidence_reference", "notes", "recorded_by_user_id", "verification_status", "verified_by_user_id", "verified_at",
			"return_reason", "school_id", "source_activity_id"}, fs.cols...)
		vals := append([]any{id, now, now, "manual_upload", "production", nil, s.country, operationalFY(fs.dated), reference, notes,
			p.UserID, pending, nil, nil, "", s.id, nil}, fs.values...)
		if _, err := tx.Exec(ctx, insertSQL(k.table, cols), vals...); err != nil {
			return fmt.Errorf("schoolevidence: recording the %s: %w", kind, err)
		}
		return evidenceAudit(ctx, tx, "ia.school_evidence."+kind+"_recorded", k.model, id, s.id, s.country, pending, p,
			map[string]any{"source_activity_id": nil}, "", now)
	})
	return s.name, err
}

// insertSQL is the one place a kind's table is named in an insert.
func insertSQL(table string, cols []string) string {
	body := "(" + strings.Join(cols, ", ") + ") VALUES (" + placeholders(1, len(cols)) + ")"
	switch table {
	case "impact_learning_result":
		return "INSERT INTO impact_learning_result " + body
	case "impact_discipleship_record":
		return "INSERT INTO impact_discipleship_record " + body
	case "impact_edtech_deployment":
		return "INSERT INTO impact_edtech_deployment " + body
	}
	return "INSERT INTO impact_edtech_check " + body
}

// visibleDeployment is visible(principal, EDTECH) for one deployment.
func (e Evidence) visibleDeployment(ctx context.Context, p auth.Principal, id string) (*deployment, error) {
	var args []any
	where, err := e.reach(ctx, p, &args)
	if err != nil {
		return nil, err
	}
	args = append(args, id)
	var d deployment
	err = e.DB.QueryRow(ctx, `SELECT x.id, x.school_id, s.name, x.country, x.verification_status, x.asset_type, x.quantity, x.deployed_on
FROM impact_edtech_deployment x JOIN school s ON s.id = x.school_id
WHERE x.deleted_at IS NULL AND `+where+fmt.Sprintf(` AND x.id = $%d`, len(args)), args...).
		Scan(&d.id, &d.schoolID, &d.schoolName, &d.country, &d.status, &d.asset, &d.quantity, &d.deployed)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the deployment: %w", err)
	}
	return &d, nil
}

// RecordCheck is record_check: the deployment's school.
func (e Evidence) RecordCheck(ctx context.Context, p auth.Principal, deploymentID string, values map[string]string) (string, error) {
	if !mayRecord(p) {
		return "", refuse(notRecorder)
	}
	d, err := e.visibleDeployment(ctx, p, deploymentID)
	if err != nil {
		return "", err
	}
	if d == nil {
		return "", missing("That deployment is not in your country.")
	}
	if d.status != confirmed {
		return "", refuse("Check a deployment once it is confirmed; until then its quantity and date may still change.")
	}
	f := form(values)
	fs, err := e.checkFields(f, d)
	if err != nil {
		return "", err
	}
	now := e.now()
	err = e.write(ctx, func(tx pgx.Tx) error {
		reference, err := f.text("evidence_reference", false, "", referenceMax)
		if err != nil {
			return err
		}
		notes, err := f.text("notes", false, "", notesMax)
		if err != nil {
			return err
		}
		id := cuid.New()
		cols := append([]string{"id", "created_at", "updated_at", "source", "environment", "deleted_at", "country", "fy",
			"evidence_reference", "notes", "recorded_by_user_id", "verification_status", "verified_by_user_id", "verified_at",
			"return_reason", "school_id", "source_activity_id", "deployment_id"}, fs.cols...)
		vals := append([]any{id, now, now, "manual_upload", "production", nil, d.country, operationalFY(fs.dated), reference, notes,
			p.UserID, pending, nil, nil, "", d.schoolID, nil, d.id}, fs.values...)
		if _, err := tx.Exec(ctx, insertSQL("impact_edtech_check", cols), vals...); err != nil {
			return fmt.Errorf("schoolevidence: recording the check: %w", err)
		}
		return evidenceAudit(ctx, tx, "ia.school_evidence.check_recorded", "EdTechCheck", id, d.schoolID, d.country, pending, p, nil, "", now)
	})
	return d.schoolName, err
}

// record is one evidence row as the saves read it.
type evidenceRow struct {
	id, schoolID, schoolName, country, status, recorder, deploymentID, sourceActivity string
}

func selectRecord(kind string) string {
	deploymentCol := "''"
	if kind == check {
		deploymentCol = "x.deployment_id"
	}
	return `SELECT x.id, x.school_id, s.name, x.country, x.verification_status, x.recorded_by_user_id, ` + deploymentCol +
		`, COALESCE(x.source_activity_id, '') FROM ` + kinds[kind].table + ` x JOIN school s ON s.id = x.school_id`
}

func scanRecord(row pgx.Row) (*evidenceRow, error) {
	var r evidenceRow
	err := row.Scan(&r.id, &r.schoolID, &r.schoolName, &r.country, &r.status, &r.recorder, &r.deploymentID, &r.sourceActivity)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	return &r, err
}

// ownOpenRecord is _own_open_record.
func ownOpenRecord(ctx context.Context, tx pgx.Tx, p auth.Principal, kind, id string) (*evidenceRow, error) {
	r, err := scanRecord(tx.QueryRow(ctx, selectRecord(kind)+` WHERE x.deleted_at IS NULL AND x.id = $1 AND x.recorded_by_user_id = $2
FOR UPDATE OF x`, id, p.UserID))
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the record: %w", err)
	}
	if r == nil {
		return nil, missing("That record is not one you recorded.")
	}
	if r.status == confirmed {
		return nil, refuse("A confirmed record can no longer be changed.")
	}
	return r, nil
}

// noticeContext is _notice_context.
func noticeContext(kind string, r *evidenceRow) (string, string) {
	if r.sourceActivity != "" {
		return "OneTestActivity", r.sourceActivity
	}
	return kinds[kind].model, r.id
}

func (e Evidence) resolveReturned(ctx context.Context, kind string, r *evidenceRow) {
	contextType, contextID := noticeContext(kind, r)
	err := e.write(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition($1, $2, $3, $4)`, eventReturned, contextType, contextID, e.now())
		return err
	})
	if err != nil && e.Logger != nil {
		e.Logger.WarnContext(ctx, "schoolevidence: the returned notice was not closed", "record", r.id, "err", err)
	}
}

// Correct is correct: the record's school.
func (e Evidence) Correct(ctx context.Context, p auth.Principal, kind, id string, values map[string]string) (string, error) {
	now := e.now()
	f := form(values)
	var r *evidenceRow
	err := e.write(ctx, func(tx pgx.Tx) error {
		var err error
		if r, err = ownOpenRecord(ctx, tx, p, kind, id); err != nil {
			return err
		}
		var d *deployment
		if kind == check {
			d = &deployment{}
			if err := tx.QueryRow(ctx, `SELECT quantity, deployed_on FROM impact_edtech_deployment WHERE id = $1`, r.deploymentID).
				Scan(&d.quantity, &d.deployed); err != nil {
				return fmt.Errorf("schoolevidence: reading the check's deployment: %w", err)
			}
		}
		fs, err := e.parse(ctx, kind, f, d)
		if err != nil {
			return err
		}
		if kind == learning {
			dup, err := duplicateLearning(ctx, tx, r.schoolID, fs, r.id)
			if err != nil {
				return err
			}
			if dup {
				return refuse("This school already has a result for that assessment, date, class and subject.")
			}
		}
		reference, err := f.text("evidence_reference", false, "", referenceMax)
		if err != nil {
			return err
		}
		notes, err := f.text("notes", false, "", notesMax)
		if err != nil {
			return err
		}
		wasReturned := r.status == returned
		sets := []string{}
		args := []any{r.id}
		for i, c := range fs.cols {
			args = append(args, fs.values[i])
			sets = append(sets, fmt.Sprintf("%s = $%d", c, len(args)))
		}
		for _, kv := range [][2]any{{"fy", operationalFY(fs.dated)}, {"evidence_reference", reference}, {"notes", notes},
			{"verification_status", pending}, {"return_reason", ""}, {"updated_at", now}} {
			args = append(args, kv[1])
			sets = append(sets, fmt.Sprintf("%s = $%d", kv[0], len(args)))
		}
		sets = append(sets, "verified_by_user_id = NULL", "verified_at = NULL")
		if _, err := tx.Exec(ctx, updateSQL(kind, strings.Join(sets, ", ")), args...); err != nil {
			return fmt.Errorf("schoolevidence: correcting the record: %w", err)
		}
		return evidenceAudit(ctx, tx, "ia.school_evidence."+kind+"_corrected", kinds[kind].model, r.id, r.schoolID, r.country, pending, p,
			map[string]any{"was_returned": wasReturned}, "", now)
	})
	if err != nil {
		return "", err
	}
	e.resolveReturned(ctx, kind, r)
	return r.schoolName, nil
}

// updateSQL is the one place a kind's table is named in an update.
func updateSQL(kind, sets string) string {
	tail := "SET " + sets + " WHERE id = $1"
	switch kind {
	case learning:
		return "UPDATE impact_learning_result " + tail
	case discipleship:
		return "UPDATE impact_discipleship_record " + tail
	case edtech:
		return "UPDATE impact_edtech_deployment " + tail
	}
	return "UPDATE impact_edtech_check " + tail
}

// Withdraw is withdraw: the record's school.
func (e Evidence) Withdraw(ctx context.Context, p auth.Principal, kind, id string) (string, error) {
	now := e.now()
	var r *evidenceRow
	err := e.write(ctx, func(tx pgx.Tx) error {
		var err error
		if r, err = ownOpenRecord(ctx, tx, p, kind, id); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, updateSQL(kind, "deleted_at = $2, updated_at = $2"), r.id, now); err != nil {
			return fmt.Errorf("schoolevidence: withdrawing the record: %w", err)
		}
		return evidenceAudit(ctx, tx, "ia.school_evidence."+kind+"_withdrawn", kinds[kind].model, r.id, r.schoolID, r.country, r.status, p,
			nil, "", now)
	})
	if err != nil {
		return "", err
	}
	e.resolveReturned(ctx, kind, r)
	return r.schoolName, nil
}

// canReview is assert_can_review: the reader's basis, or the refusal.
func (e Evidence) canReview(ctx context.Context, p auth.Principal, author, country string) (string, error) {
	reviewer, err := iaframework.NewReviewer(ctx, e.DB, p)
	if err != nil {
		return "", err
	}
	ok, err := reviewer.May(ctx, author, country)
	if err != nil {
		return "", err
	}
	if ok {
		if p.ActiveRole == roleIA {
			return "peer_ia", nil
		}
		return "cd_fallback", nil
	}
	switch {
	case p.UserID == author:
		return "", refuse("You wrote this, so a second reviewer has to review it.")
	case p.ActiveRole == roleCD:
		return "", refuse("Another Impact Assessment officer in this country reviews it; the Country Director acknowledges only where there is no second officer.")
	}
	return "", refuse("Only a second Impact Assessment officer in this country may review it.")
}

// Decide is decide: the record's school.
func (e Evidence) Decide(ctx context.Context, p auth.Principal, kind, id, decision, reason string) (string, error) {
	if decision != "confirm" && decision != "return" {
		return "", refuse("Choose confirm or return.")
	}
	reason = strings.TrimSpace(reason)
	if decision == "return" && reason == "" {
		return "", refuse("Say what the recorder needs to correct.")
	}
	var args []any
	where, err := e.reach(ctx, p, &args)
	if err != nil {
		return "", err
	}
	now := e.now()
	var r *evidenceRow
	err = e.write(ctx, func(tx pgx.Tx) error {
		r, err = scanRecord(tx.QueryRow(ctx, selectRecord(kind)+` WHERE x.deleted_at IS NULL AND `+where+
			fmt.Sprintf(` AND x.id = $%d FOR UPDATE OF x`, len(args)+1), append(args, id)...))
		if err != nil {
			return fmt.Errorf("schoolevidence: reading the record: %w", err)
		}
		if r == nil {
			return missing("That record is not in your country.")
		}
		if r.status != pending {
			return refuse("This record is already " + strings.ToLower(label(rules.Statuses, r.status)) + ".")
		}
		basis, err := e.canReview(ctx, p, r.recorder, r.country)
		if err != nil {
			return err
		}
		status, action := confirmed, "confirmed"
		if decision == "return" {
			status, action = returned, "returned"
		}
		returnReason := ""
		if decision == "return" {
			returnReason = reason
			if utf8.RuneCountInString(returnReason) > notesMax {
				returnReason = string([]rune(returnReason)[:notesMax])
			}
		}
		if _, err := tx.Exec(ctx, updateSQL(kind, "verification_status = $2, verified_by_user_id = $3, verified_at = $4, return_reason = $5, updated_at = $4"),
			r.id, status, p.UserID, now, returnReason); err != nil {
			return fmt.Errorf("schoolevidence: deciding the record: %w", err)
		}
		r.status = status
		var why2 any
		if reason != "" {
			why2 = reason
		}
		return evidenceAudit(ctx, tx, "ia.school_evidence."+kind+"_"+action, kinds[kind].model, r.id, r.schoolID, r.country, status, p,
			map[string]any{"review_basis": basis, "reason": why2}, reason, now)
	})
	if err != nil {
		return "", err
	}
	if decision == "return" {
		e.notifyReturned(ctx, kind, r, reason)
	} else {
		e.resolveReturned(ctx, kind, r)
	}
	return r.schoolName, nil
}

// notifyReturned is _notify_returned.
func (e Evidence) notifyReturned(ctx context.Context, kind string, r *evidenceRow, reason string) {
	contextType, contextID := noticeContext(kind, r)
	route, button := Path+"?status=returned", "Open School Evidence"
	if contextType == "OneTestActivity" {
		route, button = "/my-plan/"+contextID+"?learning_results=1", "Correct Results"
	} else {
		route, button = fmt.Sprintf("%s?tab=%s&status=returned&open=%s-%s", Path, tabOf(kind), kind, contextID), "Correct Evidence"
	}
	body := []rune(r.schoolName + ": " + reason)
	if len(body) > noticeMax {
		body = body[:noticeMax]
	}
	err := activities.SendNotices(ctx, e.DB, e.Push, nil, e.Logger, e.now(), contextID, "", activities.Origin{}, activities.Notice{
		Title: kinds[kind].label + " returned for correction", Body: string(body), Event: eventReturned, Category: "ia",
		ContextType: contextType, Priority: "high",
	}, []activities.NoticeTo{{UserID: r.recorder, Route: route, Label: button}})
	if err != nil && e.Logger != nil {
		e.Logger.WarnContext(ctx, "schoolevidence: the recorder was not told", "record", r.id, "err", err)
	}
}
