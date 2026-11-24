package myplan

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The budget of one activity as its detail drawer shows it
// (apps.budget.breakdown.activity_budget_breakdown and the view's
// activity_cost), for a member of staff: a partner reader is handed on.

// costSnapshot is the activity's current ActivityCostSnapshot.
type costSnapshot struct {
	found            bool
	status           string
	spent, disbursed *int64
	limit            *int64
	breakdown        []byte
	card             string
	missingConfig    []byte
	calculated       *time.Time
	cardLabel        string
	cardFY           *string
	cardVersion      *int64
}

func readCostSnapshot(ctx context.Context, db schooldirectory.Querier, id string) (costSnapshot, error) {
	s := costSnapshot{found: true}
	err := db.QueryRow(ctx, `
SELECT COALESCE(s.cost_status, ''), trunc(s.actual_accounted_spend)::bigint, trunc(s.amount_disbursed)::bigint,
  trunc(s.approved_operating_limit)::bigint, s.operational_breakdown, COALESCE(s.operational_rate_card_id, ''),
  s.missing_configuration, s.calculated_at, COALESCE(c.label, ''), c.fy, c.version
FROM activity_cost_snapshot s LEFT JOIN cost_catalogue c ON c.id = s.operational_rate_card_id
WHERE s.activity_id = $1 AND s.is_current ORDER BY s.sequence DESC LIMIT 1`, id).Scan(
		&s.status, &s.spent, &s.disbursed, &s.limit, &s.breakdown, &s.card,
		&s.missingConfig, &s.calculated, &s.cardLabel, &s.cardFY, &s.cardVersion)
	if errors.Is(err, pgx.ErrNoRows) {
		return costSnapshot{}, nil
	}
	if err != nil {
		return costSnapshot{}, fmt.Errorf("myplan: reading the cost snapshot: %w", err)
	}
	return s, nil
}

// activityCost is the view's activity_cost: the figure the Finance tab's
// strip shows and the words under it.
type activityCost struct {
	label  string
	amount *int64
	note   string
}

func (s *Service) activityCost(ctx context.Context, a *detailActivity, snap costSnapshot) (activityCost, error) {
	if snap.found && in(rules.Detail.SpentCostStatuses, snap.status) {
		if snap.spent == nil || snap.disbursed == nil {
			return activityCost{}, handOn("spent money with no amount")
		}
		return activityCost{"Actual Accounted Spend", snap.spent, withDisbursed("Recorded after approved accountability", *snap.disbursed)}, nil
	}
	if snap.found && snap.limit != nil {
		if snap.disbursed == nil {
			return activityCost{}, handOn("an approved limit with no disbursement")
		}
		return activityCost{"Approved Operating Limit", snap.limit, withDisbursed("Maximum authorized activity spend", *snap.disbursed)}, nil
	}
	amounts, err := minimumAmounts(ctx, s.db, []string{a.id})
	if errors.Is(err, ErrUnported) {
		return activityCost{}, handOn("a minimum estimate Go does not price")
	}
	if err != nil {
		return activityCost{}, err
	}
	missing, err := missingKeys(snap)
	if err != nil {
		return activityCost{}, err
	}
	amount := amounts[a.id]
	note := "Minimum viable cost not configured. Ask the Country Director to set the missing rates."
	participants := in(missing, "expectedParticipants")
	switch {
	case amount != nil:
		note = "Staff planning estimate. Funding is calculated at country operational rates."
	case participants && len(uniq(missing)) == 1:
		note = "No participant count is planned, so the participants' meals are not priced and this activity cannot be requested. Edit it and enter the number of participants."
	case participants:
		note = "No participant count is planned and a rate is missing: enter the number of participants, and ask the Country Director to set the missing rates."
	}
	return activityCost{"Minimum Viable Cost", amount, note}, nil
}

// withDisbursed is the strip's helper: the note, and the amount disbursed
// when there is one.
func withDisbursed(note string, disbursed int64) string {
	if disbursed != 0 {
		return note + " · Amount disbursed: " + money(disbursed)
	}
	return note
}

func uniq(values []string) []string {
	var out []string
	for _, v := range values {
		if !in(out, v) {
			out = append(out, v)
		}
	}
	return out
}

// missingKeys is the snapshot's missing_configuration as a list of keys.
func missingKeys(snap costSnapshot) ([]string, error) {
	if !snap.found {
		return nil, nil
	}
	v, err := decode(snap.missingConfig)
	if err != nil {
		return nil, err
	}
	if !truthy(v) {
		return nil, nil
	}
	list, ok := v.([]any)
	if !ok {
		return nil, handOn("missing configuration that is not a list")
	}
	var out []string
	for _, item := range list {
		key, isText := item.(string)
		if !isText {
			return nil, handOn("a missing key that is not text")
		}
		out = append(out, key)
	}
	return out, nil
}

// costLine is one stored ActivityScheduleCostLine.
type costLine struct {
	id, key, label, lineType, card string
	amount, quantity, unit         int64
	vendorPaid                     bool
}

func readDetailLines(ctx context.Context, db schooldirectory.Querier, id string) ([]costLine, error) {
	rows, err := db.Query(ctx, `
SELECT id, COALESCE(cost_setting_key, ''), COALESCE(label, ''), COALESCE(line_item_type, ''), COALESCE(catalogue_id, ''),
  COALESCE(trunc(amount), 0)::bigint, COALESCE(trunc(quantity), 0)::bigint, COALESCE(trunc(unit_cost), 0)::bigint,
  COALESCE(vendor_paid, false)
FROM activity_schedule_cost_line WHERE activity_id = $1 ORDER BY created_at ASC, id ASC`, id)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the cost lines: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (costLine, error) {
		var l costLine
		err := row.Scan(&l.id, &l.key, &l.label, &l.lineType, &l.card, &l.amount, &l.quantity, &l.unit, &l.vendorPaid)
		return l, err
	})
}

// rateSetting is one CostSetting of the rate card the lines were priced
// from.
type rateSetting struct {
	label, unit     string
	unitCost        int64
	approvedMinimum *int64
}

func readRateSettings(ctx context.Context, db schooldirectory.Querier, card string) (map[rateKey]rateSetting, error) {
	rows, err := db.Query(ctx, `SELECT key, COALESCE(label, ''), COALESCE(unit, ''), COALESCE(trunc(unit_cost), 0)::bigint, trunc(approved_minimum)::bigint
FROM cost_setting WHERE catalogue_id = $1`, card)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the rate card: %w", err)
	}
	defer rows.Close()
	out := map[rateKey]rateSetting{}
	for rows.Next() {
		var key string
		var s rateSetting
		if err := rows.Scan(&key, &s.label, &s.unit, &s.unitCost, &s.approvedMinimum); err != nil {
			return nil, err
		}
		out[rateKey{card, key}] = s
	}
	return out, rows.Err()
}

// rateFor is setting_for_line over the rate card's settings.
func rateFor(rates map[rateKey]rateSetting, card, key string) (rateSetting, bool) {
	if s, ok := rates[rateKey{card, key}]; ok {
		return s, true
	}
	for _, old := range rules.Rows.RateAliases[key] {
		if s, ok := rates[rateKey{card, old}]; ok {
			return s, true
		}
	}
	return rateSetting{}, false
}

// visitBatch is the DailyVisitBatch the activity's day was priced in.
type visitBatch struct {
	schoolCount   *int64
	rateSnapshot  map[string]any
	day           time.Time
	districtType  string
	transportPaid bool
}

func readVisitBatch(ctx context.Context, db schooldirectory.Querier, id string) (*visitBatch, error) {
	b := &visitBatch{}
	var raw []byte
	err := db.QueryRow(ctx, `
SELECT b.school_count, b.rate_snapshot, b.visit_date, COALESCE(b.district_type, ''),
  EXISTS (SELECT 1 FROM transport_payment t WHERE t.batch_id = b.id AND t.status = 'paid')
FROM daily_visit_batch b WHERE b.id = $1`, id).Scan(&b.schoolCount, &raw, &b.day, &b.districtType, &b.transportPaid)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, handOn("no day batch")
	}
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the day's batch: %w", err)
	}
	v, err := decode(raw)
	if err != nil {
		return nil, err
	}
	if v != nil {
		m, ok := v.(map[string]any)
		if !ok {
			return nil, handOn("a day's rates that are not an object")
		}
		b.rateSnapshot = m
	}
	return b, nil
}

// pricedLines are the snapshot's operational breakdown by key, in the
// order the keys were first priced (a later line under a key replaces the
// first, as the dict comprehension does).
func pricedLines(snap costSnapshot) ([]string, map[string]map[string]any, error) {
	if !snap.found {
		return nil, map[string]map[string]any{}, nil
	}
	v, err := decode(snap.breakdown)
	if err != nil {
		return nil, nil, err
	}
	out := map[string]map[string]any{}
	if !truthy(v) {
		return nil, out, nil
	}
	list, ok := v.([]any)
	if !ok {
		return nil, nil, handOn("a breakdown that is not a list")
	}
	var order []string
	for _, item := range list {
		line, isMap := item.(map[string]any)
		if !isMap {
			return nil, nil, handOn("a breakdown line that is not an object")
		}
		key, isText := line["key"].(string)
		if !isText {
			return nil, nil, handOn("a breakdown line without a key")
		}
		if _, seen := out[key]; !seen {
			order = append(order, key)
		}
		out[key] = line
	}
	return order, out, nil
}

// pyInt is int(value) of a stored rate: a whole number or its digits.
func pyInt(v any) (*int64, bool) {
	switch x := v.(type) {
	case nil:
		return nil, true
	case json.Number:
		n, ok := whole(x)
		if !ok {
			return nil, false
		}
		return &n, true
	case string:
		n, err := strconv.ParseInt(strings.TrimSpace(x), 10, 64)
		if err != nil {
			return nil, false
		}
		return &n, true
	}
	return nil, false
}

// baseKey is breakdown._base_key: a component stored once per month of a
// run of days keeps its key before the suffix.
func baseKey(key string) string {
	if i := strings.Index(key, rules.Detail.PeriodSuffix); i >= 0 {
		return key[:i]
	}
	return key
}

// readLineMoney is each line's finance_status, by line id.
func readLineMoney(ctx context.Context, db schooldirectory.Querier, a *detailActivity, lines []costLine, batch *visitBatch) (map[string]string, error) {
	out := map[string]string{}
	if len(lines) == 0 {
		return out, nil
	}
	ids := make([]string, 0, len(lines))
	for _, l := range lines {
		ids = append(ids, l.id)
	}
	type advance struct{ status, netsuite string }
	advances := map[string]advance{}
	rows, err := db.Query(ctx, `SELECT DISTINCT ON (budget_line_id) budget_line_id, COALESCE(status, ''), COALESCE(accountability_netsuite_id, '')
FROM advance_request WHERE budget_line_id = ANY($1) ORDER BY budget_line_id, created_at DESC`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the lines' advances: %w", err)
	}
	for rows.Next() {
		var line string
		var adv advance
		if err := rows.Scan(&line, &adv.status, &adv.netsuite); err != nil {
			rows.Close()
			return nil, err
		}
		advances[line] = adv
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	weekly, err := firstRequests(ctx, db, costLines{a.id: ids})
	if err != nil {
		return nil, err
	}
	var advanced, cleared bool
	if err := db.QueryRow(ctx, `SELECT COALESCE(bool_or(payment_type = 'advance'), false), COALESCE(bool_or(payment_type = 'clearance'), false)
FROM partner_payment WHERE activity_id = $1`, a.id).Scan(&advanced, &cleared); err != nil {
		return nil, fmt.Errorf("myplan: reading the partner's payments: %w", err)
	}
	severalDays := a.end != nil && a.planned != nil && a.end.After(*a.planned)
	for _, l := range lines {
		adv := advances[l.id]
		m := lineMoney{
			advance: adv.status, netsuite: adv.netsuite, weekly: str(weekly[l.id]),
			status: a.status, lineType: l.lineType, scheduled: a.scheduled != nil,
			partner:         a.delivery == "partner" || (l.lineType == rules.Detail.FeeLineType && a.facilitator != ""),
			vendorTransport: l.lineType == "transport" && a.schoolID != "" && !severalDays,
			transportPaid:   batch != nil && batch.transportPaid,
			vendorPaid:      l.vendorPaid, costMissing: a.costMissing, amount: l.amount,
			partnerAdvance: advanced, partnerCleared: cleared,
		}
		words, ok := financeStatus(m)
		if !ok {
			return nil, handOn("a line Go cannot word")
		}
		out[l.id] = words
	}
	return out, nil
}
