package iaframework

// The framework's saves (apps.impact.framework) with Django absent: an
// outcome area or indicator drafted, edited while a draft and versioned once
// approved; a loan purpose's measurement drafted as an indicator; a draft
// submitted to a second reader; and the review that approves (superseding
// the version before, writing a loan purpose's profile) or returns it. Each
// check is the existing one, in its order and words.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// Refusal is a framework rule saying no, in the existing words.
type Refusal struct {
	Message  string
	NotFound bool
}

func (r *Refusal) Error() string { return r.Message }

func refuse(m string) error { return &Refusal{Message: m} }

const (
	statusDraft      = "draft"
	statusInReview   = "in_review"
	statusReturned   = "returned"
	statusApproved   = "approved"
	statusSuperseded = "superseded"
	statusRetired    = "retired"
	kindArea         = "area"
	kindIndicator    = "indicator"
	eventRequested   = "ia.framework.review_requested"
	eventDecided     = "ia.framework.review_decided"
	areaDomainNote   = "School-level SSA proxy"
	noticeMax        = 500
	notAuthor        = "Only Impact Assessment defines the measurement framework. The Country Director acknowledges a definition where the country has no second IA officer, but does not write one."
	notTheirDraft    = "Another officer wrote this draft; they finish it, or you review it once they submit it."
)

// Framework is the framework's saves over the gateway's pool.
type Framework struct {
	DB     *pgxpool.Pool
	Push   activities.NoticePush
	Logger *slog.Logger
	Now    func() time.Time
}

func (f Framework) now() time.Time {
	if f.Now != nil {
		return f.Now().UTC().Truncate(time.Microsecond)
	}
	return time.Now().UTC().Truncate(time.Microsecond)
}

// localDay is timezone.localdate() (settings.TIME_ZONE).
func (f Framework) localDay() time.Time {
	loc, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		loc = time.UTC
	}
	l := f.now().In(loc)
	return time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
}

func (f Framework) write(ctx context.Context, fn func(pgx.Tx) error) error {
	tx, err := f.DB.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("iaframework: opening the save: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := fn(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func pending(status string) bool { return slices.Contains(rules.PendingDefinitionStatuses, status) }

// mayAuthor is may_author.
func mayAuthor(p auth.Principal) bool {
	return p.ActiveRole == rules.IARole && rules.Roles[p.ActiveRole].Author
}

func (f Framework) readerOf(ctx context.Context, p auth.Principal) (reader, error) {
	r := reader{id: p.UserID, role: p.ActiveRole, author: mayAuthor(p)}
	err := f.DB.QueryRow(ctx, `SELECT COALESCE(country, '') FROM staff_profile WHERE user_id = $1 LIMIT 1`, p.UserID).Scan(&r.country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return r, fmt.Errorf("iaframework: reading the reader's country: %w", err)
	}
	r.country = strings.TrimSpace(r.country)
	return r, nil
}

// slugOf is _slug, refusing a text with no letters or numbers.
func slugOf(text string) (string, error) {
	out := slug(text)
	if out == "" {
		return "", refuse("Give it a name or a key made of letters and numbers.")
	}
	return out, nil
}

// record is the reviewed fields both kinds share.
type record struct {
	id, author, status, changeReason, reviewer, basis, note, name, country string
	version                                                                int
	// An area's code and domains; an indicator's key and fields.
	code      string
	domains   []string
	key       string
	fields    map[string]string
	areaID    *string
	effective *time.Time
}

func (r *record) title() string { return fmt.Sprintf("%s (v%d)", r.name, r.version) }

const areaSelect = `SELECT a.id, a.author_id, a.status, a.change_reason, COALESCE(a.reviewed_by_id, ''), a.review_basis, a.review_note,
  a.name, a.version, a.code, a.definition,
  COALESCE((SELECT array_agg(d.intervention ORDER BY d.created_at, d.id) FROM impact_outcome_area_domain d WHERE d.area_id = a.id), '{}')
FROM impact_outcome_area a`

func scanArea(row pgx.Row) (*record, error) {
	r := &record{fields: map[string]string{}}
	var definition string
	if err := row.Scan(&r.id, &r.author, &r.status, &r.changeReason, &r.reviewer, &r.basis, &r.note, &r.name, &r.version,
		&r.code, &definition, &r.domains); err != nil {
		return nil, err
	}
	r.fields["definition"] = definition
	return r, nil
}

// indicatorFields are the indicator's columns a save writes, in order.
var indicatorFields = []string{"name", "level", "unit", "source", "calculation", "population", "denominator", "baseline_rule",
	"frequency", "disaggregation", "limitations", "data_owner_role"}

func indicatorSelect() string {
	cols := []string{"i.id", "i.author_id", "i.status", "i.change_reason", "COALESCE(i.reviewed_by_id, '')", "i.review_basis",
		"i.review_note", "i.name", "i.version", "i.key", "i.country", "i.outcome_area_id", "i.effective_from"}
	for _, c := range indicatorFields {
		cols = append(cols, "i."+c)
	}
	return "SELECT " + strings.Join(cols, ", ") + " FROM impact_indicator_definition i"
}

func scanIndicator(row pgx.Row) (*record, error) {
	r := &record{fields: map[string]string{}}
	values := make([]string, len(indicatorFields))
	dest := []any{&r.id, &r.author, &r.status, &r.changeReason, &r.reviewer, &r.basis, &r.note, &r.name, &r.version, &r.key,
		&r.country, &r.areaID, &r.effective}
	for i := range values {
		dest = append(dest, &values[i])
	}
	if err := row.Scan(dest...); err != nil {
		return nil, err
	}
	for i, c := range indicatorFields {
		r.fields[c] = values[i]
	}
	return r, nil
}

func (f Framework) load(ctx context.Context, q pgx.Tx, kind, id string, lock bool) (*record, error) {
	var sql string
	var scan func(pgx.Row) (*record, error)
	switch kind {
	case kindArea:
		sql, scan = areaSelect+" WHERE a.id = $1", scanArea
	case kindIndicator:
		sql, scan = indicatorSelect()+" WHERE i.id = $1", scanIndicator
	default:
		return nil, &Refusal{Message: "That framework record does not exist.", NotFound: true}
	}
	if lock {
		sql += " FOR UPDATE"
	}
	var row pgx.Row
	if q != nil {
		row = q.QueryRow(ctx, sql, id)
	} else {
		row = f.DB.QueryRow(ctx, sql, id)
	}
	r, err := scan(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, &Refusal{Message: "That framework record does not exist.", NotFound: true}
	}
	if err != nil {
		return nil, fmt.Errorf("iaframework: reading the %s: %w", kind, err)
	}
	return r, nil
}

// frameworkAudit is framework._audit.
func frameworkAudit(ctx context.Context, tx pgx.Tx, action, subjectKind, id string, p auth.Principal, version any, status any,
	extra map[string]any, reason string, now time.Time) error {
	payload := map[string]any{"version": version, "status": status}
	for k, v := range extra {
		payload[k] = v
	}
	_, err := audit.Append(ctx, tx, audit.Entry{Action: action, SubjectKind: audit.Text(subjectKind), SubjectID: audit.Text(id),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true, Reason: audit.Text(reason),
		Payload: payload}, now)
	if err != nil {
		return fmt.Errorf("iaframework: auditing %s: %w", action, err)
	}
	return nil
}

func modelName(kind string) string {
	if kind == kindArea {
		return "OutcomeArea"
	}
	return "IndicatorDefinition"
}

func anyStrings(values []string) []any {
	out := make([]any, len(values))
	for i, v := range values {
		out[i] = v
	}
	return out
}

func insertDomains(ctx context.Context, tx pgx.Tx, areaID string, interventions []string, now time.Time) error {
	for _, code := range interventions {
		if _, err := tx.Exec(ctx, `INSERT INTO impact_outcome_area_domain (id, created_at, updated_at, intervention, note, area_id)
VALUES ($1, $2, $2, $3, $4, $5)`, cuid.New(), now, code, areaDomainNote, areaID); err != nil {
			return fmt.Errorf("iaframework: writing the area's domains: %w", err)
		}
	}
	return nil
}

// ProposeAreas is propose_default_areas: how many were drafted.
func (f Framework) ProposeAreas(ctx context.Context, p auth.Principal) (int, error) {
	if !mayAuthor(p) {
		return 0, refuse(notAuthor)
	}
	now := f.now()
	created := 0
	err := f.write(ctx, func(tx pgx.Tx) error {
		var existing []string
		if err := tx.QueryRow(ctx, `SELECT COALESCE(array_agg(code), '{}') FROM impact_outcome_area`).Scan(&existing); err != nil {
			return fmt.Errorf("iaframework: reading the areas: %w", err)
		}
		for _, a := range rules.Saves.ProposedAreas {
			if slices.Contains(existing, a.Code) {
				continue
			}
			id := cuid.New()
			if _, err := tx.Exec(ctx, `INSERT INTO impact_outcome_area (id, created_at, updated_at, author_id, author_role, submitted_at,
  reviewed_by_id, reviewed_at, review_basis, review_note, code, name, definition, status, version, change_reason)
VALUES ($1, $2, $2, $3, $4, NULL, NULL, NULL, '', '', $5, $6, $7, 'draft', 1, $8)`, id, now, p.UserID, rules.IARole, a.Code, a.Name,
				a.Definition, rules.Saves.ProposedChangeReason); err != nil {
				return fmt.Errorf("iaframework: drafting %s: %w", a.Code, err)
			}
			if err := insertDomains(ctx, tx, id, a.Interventions, now); err != nil {
				return err
			}
			if err := frameworkAudit(ctx, tx, "ia.framework.area_drafted", "OutcomeArea", id, p, 1, statusDraft,
				map[string]any{"code": a.Code, "domains": anyStrings(a.Interventions)}, "", now); err != nil {
				return err
			}
			created++
		}
		return nil
	})
	return created, err
}

// cleanInterventions is _clean_interventions.
func cleanInterventions(raw string) []string {
	var out []string
	for _, v := range strings.Split(raw, ",") {
		if _, ok := rules.InterventionLabels[v]; ok && !slices.Contains(out, v) {
			out = append(out, v)
		}
	}
	return out
}

// SaveArea is save_outcome_area; id "" creates one. The saved name and
// version.
func (f Framework) SaveArea(ctx context.Context, p auth.Principal, id string, data map[string]string) (string, int, error) {
	if !mayAuthor(p) {
		return "", 0, refuse(notAuthor)
	}
	name, definition := strings.TrimSpace(data["name"]), strings.TrimSpace(data["definition"])
	interventions := cleanInterventions(data["interventions"])
	if name == "" || definition == "" {
		return "", 0, refuse("An outcome area needs a name and a definition.")
	}
	if len(interventions) == 0 {
		return "", 0, refuse("Name at least one SSA domain the area is read through, or say in the definition why no SSA proxy exists.")
	}
	reason := strings.TrimSpace(data["change_reason"])
	now := f.now()
	var savedVersion int
	err := f.write(ctx, func(tx pgx.Tx) error {
		var recordID, code, action, status string
		version := 1
		if id == "" {
			var err error
			from := data["code"]
			if from == "" {
				from = name
			}
			if code, err = slugOf(from); err != nil {
				return err
			}
			var exists bool
			if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM impact_outcome_area WHERE code = $1)`, code).Scan(&exists); err != nil {
				return fmt.Errorf("iaframework: reading the area codes: %w", err)
			}
			if exists {
				return refuse("An outcome area with that code already exists.")
			}
			recordID, action, status = cuid.New(), "ia.framework.area_drafted", statusDraft
			if _, err := tx.Exec(ctx, `INSERT INTO impact_outcome_area (id, created_at, updated_at, author_id, author_role, submitted_at,
  reviewed_by_id, reviewed_at, review_basis, review_note, code, name, definition, status, version, change_reason)
VALUES ($1, $2, $2, $3, $4, NULL, NULL, NULL, '', '', $5, $6, $7, 'draft', 1, $8)`, recordID, now, p.UserID, rules.IARole, code, name,
				definition, reason); err != nil {
				return fmt.Errorf("iaframework: drafting the area: %w", err)
			}
		} else {
			area, err := f.load(ctx, tx, kindArea, id, true)
			if err != nil {
				return err
			}
			code, version, status = area.code, area.version, area.status
			switch {
			case pending(area.status):
				if area.author != p.UserID {
					return refuse(notTheirDraft)
				}
				recordID, action = area.id, "ia.framework.area_updated"
				changeReason := area.changeReason
				if data["change_reason"] != "" {
					changeReason = reason
				}
				if _, err := tx.Exec(ctx, `UPDATE impact_outcome_area SET name = $2, definition = $3, change_reason = $4, updated_at = $5
WHERE id = $1`, area.id, name, definition, changeReason, now); err != nil {
					return fmt.Errorf("iaframework: saving the area: %w", err)
				}
				if _, err := tx.Exec(ctx, `SELECT gateway_ia_framework.clear_area_domains($1)`, area.id); err != nil {
					return fmt.Errorf("iaframework: clearing the area's domains: %w", err)
				}
			case area.status == statusInReview:
				return refuse("This area is with a reviewer.")
			default:
				var busy bool
				if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM impact_outcome_area WHERE code = $1 AND status = ANY($2))`,
					area.code, []string{statusDraft, statusReturned, statusInReview}).Scan(&busy); err != nil {
					return fmt.Errorf("iaframework: reading the area's versions: %w", err)
				}
				if busy {
					return refuse("A new version of this area is already being drafted or reviewed.")
				}
				var last int
				if err := tx.QueryRow(ctx, `SELECT COALESCE(MAX(version), 0) FROM impact_outcome_area WHERE code = $1`, area.code).Scan(&last); err != nil {
					return fmt.Errorf("iaframework: reading the area's versions: %w", err)
				}
				recordID, action, version, status = cuid.New(), "ia.framework.area_version_drafted", last+1, statusDraft
				if _, err := tx.Exec(ctx, `INSERT INTO impact_outcome_area (id, created_at, updated_at, author_id, author_role, submitted_at,
  reviewed_by_id, reviewed_at, review_basis, review_note, code, name, definition, status, version, change_reason)
VALUES ($1, $2, $2, $3, $4, NULL, NULL, NULL, '', '', $5, $6, $7, 'draft', $8, $9)`, recordID, now, p.UserID, rules.IARole, area.code,
					name, definition, version, reason); err != nil {
					return fmt.Errorf("iaframework: drafting the area's version: %w", err)
				}
			}
		}
		if err := insertDomains(ctx, tx, recordID, interventions, now); err != nil {
			return err
		}
		savedVersion = version
		return frameworkAudit(ctx, tx, action, "OutcomeArea", recordID, p, version, status,
			map[string]any{"code": code, "domains": anyStrings(interventions)}, "", now)
	})
	return name, savedVersion, err
}

// snapshot is indicator_snapshot.
func snapshot(fields map[string]string, areaID *string) map[string]any {
	out := map[string]any{}
	for _, k := range indicatorFields {
		out[k] = fields[k]
	}
	if areaID != nil {
		out["outcome_area"] = *areaID
	} else {
		out["outcome_area"] = nil
	}
	return out
}

// SaveIndicator is save_indicator; id "" creates one.
func (f Framework) SaveIndicator(ctx context.Context, p auth.Principal, id string, data map[string]string) (string, int, error) {
	var name string
	var version int
	err := f.write(ctx, func(tx pgx.Tx) error {
		var err error
		name, version, err = f.saveIndicator(ctx, tx, p, id, data)
		return err
	})
	return name, version, err
}

func (f Framework) saveIndicator(ctx context.Context, tx pgx.Tx, p auth.Principal, id string, data map[string]string) (string, int, error) {
	if !mayAuthor(p) {
		return "", 0, refuse(notAuthor)
	}
	fields := map[string]string{"name": strings.TrimSpace(data["name"]), "level": data["level"], "unit": strings.TrimSpace(data["unit"]),
		"source": data["source"], "calculation": strings.TrimSpace(data["calculation"])}
	var missing []string
	for _, k := range []string{"name", "unit", "calculation"} {
		if fields[k] == "" {
			missing = append(missing, k)
		}
	}
	if len(missing) > 0 {
		return "", 0, refuse("An indicator needs its " + strings.Join(missing, ", ") + ".")
	}
	if _, ok := rules.Levels[fields["level"]]; !ok {
		return "", 0, refuse("Choose whether the indicator is an output or an outcome.")
	}
	if _, ok := rules.Sources[fields["source"]]; !ok {
		return "", 0, refuse("Choose the evidence source the indicator is calculated from.")
	}
	if fields["level"] == "outcome" && fields["source"] == "activity" {
		return "", 0, refuse("An outcome indicator cannot be calculated from activity records alone — counting delivered work is an output.")
	}
	for _, k := range rules.Saves.IndicatorTextFields {
		fields[k] = strings.TrimSpace(data[k])
	}
	var areaID *string
	if raw := strings.TrimSpace(data["outcome_area"]); raw != "" {
		var found string
		err := tx.QueryRow(ctx, `SELECT id FROM impact_outcome_area WHERE id = $1`, raw).Scan(&found)
		if errors.Is(err, pgx.ErrNoRows) {
			return "", 0, refuse("That outcome area does not exist.")
		}
		if err != nil {
			return "", 0, fmt.Errorf("iaframework: reading the outcome area: %w", err)
		}
		areaID = &found
	}
	var effective any
	if v := data["effective_from"]; v != "" {
		effective = v
	}
	r, err := f.readerOf(ctx, p)
	if err != nil {
		return "", 0, err
	}
	reason := strings.TrimSpace(data["change_reason"])
	now := f.now()
	values := func() []any {
		out := make([]any, 0, len(indicatorFields))
		for _, k := range indicatorFields {
			out = append(out, fields[k])
		}
		return out
	}
	insert := func(key string, version int, country string) (string, error) {
		recordID := cuid.New()
		args := append([]any{recordID, now, p.UserID, rules.IARole, key, version, country, reason, areaID, effective}, values()...)
		_, err := tx.Exec(ctx, `INSERT INTO impact_indicator_definition (id, created_at, updated_at, author_id, author_role, submitted_at,
  reviewed_by_id, reviewed_at, review_basis, review_note, key, version, country, status, change_reason, outcome_area_id, effective_from,
  name, level, unit, source, calculation, population, denominator, baseline_rule, frequency, disaggregation, limitations, data_owner_role)
VALUES ($1, $2, $2, $3, $4, NULL, NULL, NULL, '', '', $5, $6, $7, 'draft', $8, $9, $10::date, $11, $12, $13, $14, $15, $16, $17, $18,
  $19, $20, $21, $22)`, args...)
		if err != nil {
			return "", fmt.Errorf("iaframework: drafting the indicator: %w", err)
		}
		return recordID, nil
	}
	var recordID, key, action, status string
	version := 1
	var before any
	if id == "" {
		from := data["key"]
		if from == "" {
			from = fields["name"]
		}
		if key, err = slugOf(from); err != nil {
			return "", 0, err
		}
		var exists bool
		if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM impact_indicator_definition WHERE key = $1)`, key).Scan(&exists); err != nil {
			return "", 0, fmt.Errorf("iaframework: reading the indicator keys: %w", err)
		}
		if exists {
			return "", 0, refuse("An indicator with that key already exists.")
		}
		if recordID, err = insert(key, 1, r.country); err != nil {
			return "", 0, err
		}
		action, status = "ia.framework.indicator_drafted", statusDraft
	} else {
		ind, err := f.load(ctx, tx, kindIndicator, id, true)
		if err != nil {
			return "", 0, err
		}
		key, version, status = ind.key, ind.version, ind.status
		before = snapshot(ind.fields, ind.areaID)
		switch {
		case pending(ind.status):
			if ind.author != p.UserID {
				return "", 0, refuse(notTheirDraft)
			}
			recordID, action = ind.id, "ia.framework.indicator_updated"
			changeReason := ind.changeReason
			if data["change_reason"] != "" {
				changeReason = reason
			}
			args := append([]any{ind.id, now, areaID, effective, changeReason}, values()...)
			if _, err := tx.Exec(ctx, `UPDATE impact_indicator_definition SET updated_at = $2, outcome_area_id = $3, effective_from = $4::date,
  change_reason = $5, name = $6, level = $7, unit = $8, source = $9, calculation = $10, population = $11, denominator = $12,
  baseline_rule = $13, frequency = $14, disaggregation = $15, limitations = $16, data_owner_role = $17 WHERE id = $1`, args...); err != nil {
				return "", 0, fmt.Errorf("iaframework: saving the indicator: %w", err)
			}
		case ind.status == statusInReview:
			return "", 0, refuse("This indicator is with a reviewer.")
		default:
			var busy bool
			if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM impact_indicator_definition WHERE key = $1 AND status = ANY($2))`,
				ind.key, []string{statusDraft, statusReturned, statusInReview}).Scan(&busy); err != nil {
				return "", 0, fmt.Errorf("iaframework: reading the indicator's versions: %w", err)
			}
			if busy {
				return "", 0, refuse("A new version of this indicator is already being drafted or reviewed.")
			}
			var last int
			if err := tx.QueryRow(ctx, `SELECT COALESCE(MAX(version), 0) FROM impact_indicator_definition WHERE key = $1`, ind.key).Scan(&last); err != nil {
				return "", 0, fmt.Errorf("iaframework: reading the indicator's versions: %w", err)
			}
			country := ind.country
			if country == "" {
				country = r.country
			}
			version, status = last+1, statusDraft
			if recordID, err = insert(ind.key, version, country); err != nil {
				return "", 0, err
			}
			action = "ia.framework.indicator_version_drafted"
		}
	}
	err = frameworkAudit(ctx, tx, action, "IndicatorDefinition", recordID, p, version, status,
		map[string]any{"key": key, "before": before, "after": snapshot(fields, areaID)}, "", now)
	return fields["name"], version, err
}

// lines is _lines.
func lines(value string) []string {
	var out []string
	for _, l := range strings.Split(strings.ReplaceAll(value, "\r\n", "\n"), "\n") {
		if t := strings.Trim(l, " -•\t"); t != "" {
			out = append(out, t)
		}
	}
	return out
}

// purpose is one active LoanPurpose.
type purpose struct {
	id, code, label, unit, verification string
	followUp, version                   int
	countries, indicators, evidence     []string
}

func (f Framework) purposeOf(ctx context.Context, q pgx.Tx, id string) (*purpose, error) {
	var p purpose
	var countries, indicators, evidence []byte
	var row pgx.Row
	sql := `SELECT id, code, label, unit_of_measure, verification_method, follow_up_days, version, applicable_countries,
  impact_indicators, required_evidence FROM bt_loan_purpose WHERE id = $1 AND active`
	if q != nil {
		row = q.QueryRow(ctx, sql, id)
	} else {
		row = f.DB.QueryRow(ctx, sql, id)
	}
	err := row.Scan(&p.id, &p.code, &p.label, &p.unit, &p.verification, &p.followUp, &p.version, &countries, &indicators, &evidence)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, &Refusal{Message: "That loan purpose does not exist.", NotFound: true}
	}
	if err != nil {
		return nil, fmt.Errorf("iaframework: reading the loan purpose: %w", err)
	}
	for _, pair := range []struct {
		raw []byte
		to  *[]string
	}{{countries, &p.countries}, {indicators, &p.indicators}, {evidence, &p.evidence}} {
		var items []any
		if err := json.Unmarshal(pair.raw, &items); err == nil {
			for _, v := range items {
				*pair.to = append(*pair.to, fmt.Sprint(v))
			}
		}
	}
	return &p, nil
}

// purposeKey is loan_purpose_key.
func purposeKey(code string) string {
	return slug(rules.LoanPurposeKeyPrefix + code)
}

// SavePurpose is save_loan_purpose_measurement: the purpose's label and the
// draft's version.
func (f Framework) SavePurpose(ctx context.Context, p auth.Principal, purposeID string, data map[string]string) (string, int, error) {
	if !mayAuthor(p) {
		return "", 0, refuse(notAuthor)
	}
	lp, err := f.purposeOf(ctx, nil, purposeID)
	if err != nil {
		return "", 0, err
	}
	r, err := f.readerOf(ctx, p)
	if err != nil {
		return "", 0, err
	}
	var applicable []string
	for _, c := range lp.countries {
		if c != "" {
			applicable = append(applicable, c)
		}
	}
	if len(applicable) > 0 && r.country != "" && !slices.Contains(applicable, r.country) {
		return "", 0, refuse("That loan purpose is not offered in your country.")
	}
	indicators, evidence := lines(data["impact_indicators"]), lines(data["required_evidence"])
	method := strings.TrimSpace(data["verification_method"])
	rawDays := data["follow_up_days"]
	if rawDays == "" {
		rawDays = strconv.Itoa(lp.followUp)
	}
	days, convErr := strconv.Atoi(strings.TrimSpace(rawDays))
	if convErr != nil {
		return "", 0, refuse("The follow-up is a number of days.")
	}
	if len(indicators) == 0 || len(evidence) == 0 || method == "" {
		return "", 0, refuse("Impact indicators, required evidence and the verification method are all required.")
	}
	if days <= 0 {
		return "", 0, refuse("The follow-up must be at least one day after disbursement.")
	}
	unit := lp.unit
	if unit == "" {
		unit = "count"
	}
	key := purposeKey(lp.code)
	payload := map[string]string{"name": lp.label + " — lending measurement", "level": "outcome", "unit": unit, "source": "lending",
		"calculation": strings.Join(indicators, "\n"), "baseline_rule": method, "disaggregation": strings.Join(evidence, "\n"),
		"frequency": fmt.Sprintf("%d days", days), "population": "Schools financed for this purpose",
		"limitations": strings.TrimSpace(data["limitations"]), "data_owner_role": rules.IARole,
		"change_reason": strings.TrimSpace(data["change_reason"])}
	var latest string
	err = f.DB.QueryRow(ctx, `SELECT id FROM impact_indicator_definition WHERE key = $1 ORDER BY version DESC LIMIT 1`, key).Scan(&latest)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", 0, fmt.Errorf("iaframework: reading the purpose's measurement: %w", err)
	}
	if latest == "" {
		payload["key"] = key
	}
	_, version, err := f.SaveIndicator(ctx, p, latest, payload)
	return lp.label, version, err
}

// reviewerIDs is intervention_mapping.reviewer_ids.
func (f Framework) reviewerIDs(ctx context.Context, country, author string) ([]string, error) {
	var peers []string
	if country != "" {
		rows, err := f.DB.Query(ctx, `SELECT u.id FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE u.roles @> ARRAY[$1]::varchar[] AND u.is_active AND u.deleted_at IS NULL AND sp.country = $2 AND sp.deleted_at IS NULL`,
			rules.IARole, country)
		if err != nil {
			return nil, fmt.Errorf("iaframework: reading the country's officers: %w", err)
		}
		ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
		if err != nil {
			return nil, err
		}
		for _, id := range ids {
			if id != author {
				peers = append(peers, id)
			}
		}
	}
	if len(peers) > 0 || country == "" {
		return peers, nil
	}
	rows, err := f.DB.Query(ctx, `SELECT u.id FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE u.roles @> ARRAY[$1]::varchar[] AND u.is_active AND u.deleted_at IS NULL AND sp.country = $2`, rules.CDRole, country)
	if err != nil {
		return nil, fmt.Errorf("iaframework: reading the country's directors: %w", err)
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}

// authorCountry is _author_country.
func (f Framework) authorCountry(ctx context.Context, r *record) (string, error) {
	if c := strings.TrimSpace(r.country); c != "" {
		return c, nil
	}
	var country string
	err := f.DB.QueryRow(ctx, `SELECT COALESCE(country, '') FROM staff_profile WHERE user_id = $1 LIMIT 1`, r.author).Scan(&country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("iaframework: reading the author's country: %w", err)
	}
	return strings.TrimSpace(country), nil
}

// Submit is framework.submit: the record's name.
func (f Framework) Submit(ctx context.Context, p auth.Principal, kind, id, changeReason string) (string, error) {
	if !mayAuthor(p) {
		return "", refuse(notAuthor)
	}
	now := f.now()
	var row *record
	err := f.write(ctx, func(tx pgx.Tx) error {
		var err error
		if row, err = f.load(ctx, tx, kind, id, true); err != nil {
			return err
		}
		if !pending(row.status) {
			return refuse("Only a draft or a returned definition can be submitted.")
		}
		if row.author != p.UserID {
			return refuse("The officer who wrote this definition submits it.")
		}
		reason := strings.TrimSpace(changeReason)
		if reason == "" {
			reason = strings.TrimSpace(row.changeReason)
		}
		if reason == "" {
			return refuse("Say what this definition establishes or changes, and why.")
		}
		row.changeReason, row.status = reason, statusInReview
		if _, err := tx.Exec(ctx, pick(kind, `UPDATE impact_outcome_area SET change_reason = $2, status = 'in_review', submitted_at = $3, updated_at = $3
WHERE id = $1`, `UPDATE impact_indicator_definition SET change_reason = $2, status = 'in_review', submitted_at = $3, updated_at = $3
WHERE id = $1`), id, reason, now); err != nil {
			return fmt.Errorf("iaframework: submitting the %s: %w", kind, err)
		}
		return frameworkAudit(ctx, tx, "ia.framework."+kind+"_submitted", modelName(kind), id, p, row.version, statusInReview,
			map[string]any{"reason": reason}, reason, now)
	})
	if err != nil {
		return "", err
	}
	country, err := f.authorCountry(ctx, row)
	if err == nil {
		var to []string
		if to, err = f.reviewerIDs(ctx, country, row.author); err == nil {
			body := []rune(row.title() + ": " + row.changeReason)
			if len(body) > noticeMax {
				body = body[:noticeMax]
			}
			f.notice(ctx, kind, row.id, eventRequested, "Framework definition to review", string(body), "high", "Review Definition", now, to...)
		}
	}
	if err != nil && f.Logger != nil {
		f.Logger.WarnContext(ctx, "iaframework: the reviewers were not told", "record", id, "err", err)
	}
	return row.name, nil
}

// notice is the framework's notices, each opening the record's tab and drawer
// for those who may read the framework, the dashboard for anyone else.
func (f Framework) notice(ctx context.Context, kind, id, event, title, body, priority, label string, now time.Time, to ...string) {
	if len(to) == 0 {
		return
	}
	rows, err := f.DB.Query(ctx, `SELECT id, COALESCE(active_role, '') FROM "user" WHERE id = ANY($1)`, to)
	if err != nil {
		if f.Logger != nil {
			f.Logger.WarnContext(ctx, "iaframework: the recipients were not read", "record", id, "err", err)
		}
		return
	}
	roles := map[string]string{}
	for rows.Next() {
		var uid, role string
		if rows.Scan(&uid, &role) == nil {
			roles[uid] = role
		}
	}
	rows.Close()
	var recipients []activities.NoticeTo
	for _, uid := range to {
		route, button := "/dashboard", "View Dashboard"
		switch roles[uid] {
		case rules.IARole, rules.CDRole, "Admin":
			route, button = fmt.Sprintf("%s?tab=%ss&open=%s-%s", Path, kind, kind, id), label
		}
		if _, ok := roles[uid]; ok {
			recipients = append(recipients, activities.NoticeTo{UserID: uid, Route: route, Label: button})
		}
	}
	err = activities.SendNotices(ctx, f.DB, f.Push, nil, f.Logger, now, id, "", activities.Origin{}, activities.Notice{
		Title: title, Body: body, Event: event, Category: "ia", ContextType: modelName(kind), Priority: priority,
	}, recipients)
	if err != nil && f.Logger != nil {
		f.Logger.WarnContext(ctx, "iaframework: a framework notice was not sent", "record", id, "err", err)
	}
}

// Review is framework.review: the record's name.
func (f Framework) Review(ctx context.Context, p auth.Principal, kind, id, decision, note string) (string, error) {
	note = strings.TrimSpace(note)
	if decision != "approve" && decision != "return" {
		return "", refuse("Approve the definition or return it with a note.")
	}
	now := f.now()
	var row *record
	err := f.write(ctx, func(tx pgx.Tx) error {
		var err error
		if row, err = f.load(ctx, tx, kind, id, true); err != nil {
			return err
		}
		if row.status != statusInReview {
			return refuse("Only a submitted definition can be reviewed.")
		}
		country, err := f.authorCountry(ctx, row)
		if err != nil {
			return err
		}
		basis, err := f.canReview(ctx, p, row.author, country)
		if err != nil {
			return err
		}
		table := "impact_outcome_area"
		if kind == kindIndicator {
			table = "impact_indicator_definition"
		}
		if decision == "return" {
			if note == "" {
				return refuse("Say what has to change before it can be approved.")
			}
			row.status, row.note = statusReturned, note
			if _, err := tx.Exec(ctx, pick(kind, `UPDATE impact_outcome_area SET status = 'returned', reviewed_by_id = $2, reviewed_at = $3, review_basis = $4,
  review_note = $5, updated_at = $3 WHERE id = $1`, `UPDATE impact_indicator_definition SET status = 'returned', reviewed_by_id = $2, reviewed_at = $3, review_basis = $4,
  review_note = $5, updated_at = $3 WHERE id = $1`), id, p.UserID, now, basis, note); err != nil {
				return fmt.Errorf("iaframework: returning the %s: %w", kind, err)
			}
			return frameworkAudit(ctx, tx, "ia.framework."+kind+"_returned", modelName(kind), id, p, row.version, statusReturned,
				map[string]any{"reason": note}, note, now)
		}
		identity, value := "code", row.code
		if kind == kindIndicator {
			identity, value = "key", row.key
		}
		priors, err := tx.Query(ctx, `SELECT id, version FROM `+table+` WHERE status = 'approved' AND `+identity+` = $1 AND id <> $2
FOR UPDATE`, value, id)
		if err != nil {
			return fmt.Errorf("iaframework: reading the approved version: %w", err)
		}
		type prior struct {
			id      string
			version int
		}
		var before []prior
		for priors.Next() {
			var pr prior
			if err := priors.Scan(&pr.id, &pr.version); err != nil {
				priors.Close()
				return err
			}
			before = append(before, pr)
		}
		priors.Close()
		for _, pr := range before {
			if _, err := tx.Exec(ctx, pick(kind, `UPDATE impact_outcome_area SET status = 'superseded', updated_at = $2 WHERE id = $1`, `UPDATE impact_indicator_definition SET status = 'superseded', updated_at = $2 WHERE id = $1`), pr.id, now); err != nil {
				return fmt.Errorf("iaframework: superseding the approved version: %w", err)
			}
			if err := frameworkAudit(ctx, tx, "ia.framework."+kind+"_superseded", modelName(kind), pr.id, p, pr.version, statusSuperseded,
				map[string]any{"superseded_by": id}, "", now); err != nil {
				return err
			}
		}
		row.status, row.note = statusApproved, note
		if kind == kindIndicator && row.effective == nil {
			day := f.localDay()
			row.effective = &day
		}
		sql := pick(kind, `UPDATE impact_outcome_area SET status = 'approved', reviewed_by_id = $2, reviewed_at = $3, review_basis = $4, review_note = $5,
  updated_at = $3 WHERE id = $1`, `UPDATE impact_indicator_definition SET status = 'approved', reviewed_by_id = $2, reviewed_at = $3, review_basis = $4, review_note = $5,
  updated_at = $3 WHERE id = $1`)
		args := []any{id, p.UserID, now, basis, note}
		if kind == kindIndicator {
			sql = `UPDATE impact_indicator_definition SET status = 'approved', reviewed_by_id = $2, reviewed_at = $3, review_basis = $4,
  review_note = $5, updated_at = $3, effective_from = $6 WHERE id = $1`
			args = append(args, *row.effective)
		}
		if _, err := tx.Exec(ctx, sql, args...); err != nil {
			return fmt.Errorf("iaframework: approving the %s: %w", kind, err)
		}
		if err := frameworkAudit(ctx, tx, "ia.framework."+kind+"_approved", modelName(kind), id, p, row.version, statusApproved,
			map[string]any{"basis": basis}, "", now); err != nil {
			return err
		}
		if kind == kindIndicator && strings.HasPrefix(row.key, rules.LoanPurposeKeyPrefix) {
			return f.applyPurpose(ctx, tx, p, row, now)
		}
		return nil
	})
	if err != nil {
		return "", err
	}
	f.tellAuthor(ctx, kind, row, decision, now)
	return row.name, nil
}

// canReview is assert_can_review: the reader's basis, or the refusal.
func (f Framework) canReview(ctx context.Context, p auth.Principal, author, country string) (string, error) {
	r, err := f.readerOf(ctx, p)
	if err != nil {
		return "", err
	}
	res := &resolver{db: f.DB, r: r, officers: map[string][]string{}}
	ok, err := res.may(ctx, author, country)
	if err != nil {
		return "", err
	}
	if ok {
		if p.ActiveRole == rules.IARole {
			return "peer_ia", nil
		}
		return "cd_fallback", nil
	}
	switch {
	case p.UserID == author:
		return "", refuse("You wrote this, so a second reviewer has to review it.")
	case p.ActiveRole == rules.CDRole:
		return "", refuse("Another Impact Assessment officer in this country reviews it; the Country Director acknowledges only where there is no second officer.")
	}
	return "", refuse("Only a second Impact Assessment officer in this country may review it.")
}

// tellAuthor is _notify_author: the request's notices closed, the author told.
func (f Framework) tellAuthor(ctx context.Context, kind string, row *record, decision string, now time.Time) {
	err := f.write(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition($1, $2, $3, $4)`, eventRequested, modelName(kind), row.id, now)
		return err
	})
	if err != nil && f.Logger != nil {
		f.Logger.WarnContext(ctx, "iaframework: the review request was not closed", "record", row.id, "err", err)
	}
	title, priority := "Framework definition approved", "normal"
	if decision != "approve" {
		title, priority = "Framework definition returned", "high"
	}
	body := row.title()
	if row.note != "" {
		body += ": " + row.note
	}
	if b := []rune(body); len(b) > noticeMax {
		body = string(b[:noticeMax])
	}
	f.notice(ctx, kind, row.id, eventDecided, title, body, priority, "Open Framework", now, row.author)
}

var leadingDigits = regexp.MustCompile(`^\d+`)

// applyPurpose is _apply_loan_purpose: the approved measurement written onto
// its loan purpose.
func (f Framework) applyPurpose(ctx context.Context, tx pgx.Tx, p auth.Principal, row *record, now time.Time) error {
	code := strings.TrimPrefix(row.key, rules.LoanPurposeKeyPrefix)
	rows, err := tx.Query(ctx, `SELECT id, code FROM bt_loan_purpose ORDER BY code FOR UPDATE`)
	if err != nil {
		return fmt.Errorf("iaframework: reading the loan purposes: %w", err)
	}
	var match string
	for rows.Next() {
		var id, c string
		if err := rows.Scan(&id, &c); err != nil {
			rows.Close()
			return err
		}
		if match == "" && (purposeKey(c) == row.key || strings.ToLower(c) == code) {
			match = id
		}
	}
	rows.Close()
	if match == "" {
		return nil
	}
	var indicators, evidence []byte
	var method string
	var days, version int
	if err := tx.QueryRow(ctx, `SELECT impact_indicators, required_evidence, verification_method, follow_up_days, version
FROM bt_loan_purpose WHERE id = $1`, match).Scan(&indicators, &evidence, &method, &days, &version); err != nil {
		return fmt.Errorf("iaframework: reading the loan purpose: %w", err)
	}
	var beforeIndicators, beforeEvidence any
	_ = json.Unmarshal(indicators, &beforeIndicators)
	_ = json.Unmarshal(evidence, &beforeEvidence)
	newIndicators, err := json.Marshal(orEmpty(lines(row.fields["calculation"])))
	if err != nil {
		return err
	}
	newEvidence, err := json.Marshal(orEmpty(lines(row.fields["disaggregation"])))
	if err != nil {
		return err
	}
	newDays := days
	if d := leadingDigits.FindString(row.fields["frequency"]); d != "" {
		newDays, _ = strconv.Atoi(d)
	}
	if version == 0 {
		version = 1
	}
	if _, err := tx.Exec(ctx, `UPDATE bt_loan_purpose SET impact_indicators = $2::jsonb, required_evidence = $3::jsonb,
  verification_method = $4, follow_up_days = $5, measurement_profile_complete = TRUE, version = $6, updated_at = $7 WHERE id = $1`,
		match, string(newIndicators), string(newEvidence), row.fields["baseline_rule"], newDays, version+1, now); err != nil {
		return fmt.Errorf("iaframework: writing the loan purpose's measurement: %w", err)
	}
	return frameworkAudit(ctx, tx, "bt.loan.purpose_measurement_defined", "LoanPurpose", match, p, version+1, nil,
		map[string]any{"indicator": row.id, "before": map[string]any{"impact_indicators": beforeIndicators,
			"required_evidence": beforeEvidence, "verification_method": method, "follow_up_days": days}}, "", now)
}

func orEmpty(s []string) []string {
	if s == nil {
		return []string{}
	}
	return s
}

// pick is the statement for the record's own table.
func pick(kind, area, indicator string) string {
	if kind == kindIndicator {
		return indicator
	}
	return area
}
