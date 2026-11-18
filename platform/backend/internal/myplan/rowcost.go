package myplan

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"slices"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// costLines are each activity's schedule cost lines in the order the
// prefetch reads them (no ordering: the table's), and the activities with
// any (has_lines).
type costLines map[string][]string

func readCostLines(ctx context.Context, db schooldirectory.Querier, ids []string) (costLines, error) {
	out := costLines{}
	rows, err := db.Query(ctx, `SELECT id, activity_id FROM activity_schedule_cost_line WHERE activity_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: cost lines: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, activityID string
		if err := rows.Scan(&id, &activityID); err != nil {
			return nil, err
		}
		out[activityID] = append(out[activityID], id)
	}
	return out, rows.Err()
}

// firstRequests is money_chain's first_request_by_line: the weekly
// request's status the first weekly request line of each cost line
// belongs to ("" for a line whose request is not there).
func firstRequests(ctx context.Context, db schooldirectory.Querier, lines costLines) (map[string]*string, error) {
	var ids []string
	for _, ls := range lines {
		ids = append(ids, ls...)
	}
	out := map[string]*string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT l.activity_budget_line_id, r.status FROM weekly_fund_request_line l
LEFT OUTER JOIN weekly_fund_request r ON r.id = l.weekly_fund_request_id
WHERE l.activity_budget_line_id IN (SELECT unnest($1::varchar[]))`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: weekly requests: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var line, status *string
		if err := rows.Scan(&line, &status); err != nil {
			return nil, err
		}
		if line == nil {
			continue
		}
		if _, seen := out[*line]; !seen {
			if status == nil {
				empty := "\x00"
				status = &empty
			}
			out[*line] = status
		}
	}
	return out, rows.Err()
}

// budgetStatus is the loop's Budget status: the first cost line's weekly
// request, the in-school pair's other half, or none.
func budgetStatus(a *activity, lines costLines, requests map[string]*string, notes map[string]string) string {
	first := ""
	if ls := lines[a.id]; len(ls) > 0 {
		first = ls[0]
	}
	switch {
	case first != "" && a.costMissing:
		return "Cost Setup Required"
	case first != "":
		status, ok := requests[first]
		if !ok || *status == "\x00" {
			return "Budget Created"
		}
		switch *status {
		case "pending_responsible_confirmation":
			return "In Weekly Request"
		case "submitted_to_pl":
			return "Awaiting PL Approval"
		case "submitted_to_cd":
			return "Awaiting CD Approval"
		case "returned_by_pl", "returned_by_cd", "returned_by_accountant":
			return "Request Returned"
		case "confirmed_for_advance":
			return "Approved"
		case "disbursed":
			return "Disbursed"
		}
		return "Included in Request"
	}
	if _, ok := notes[a.id]; ok {
		if a.activityType == "in_school_training" {
			return "In School Visit"
		}
		return "In Training"
	}
	return "No Budget"
}

// setting is a CostSetting row a stored component was priced from.
type setting struct {
	approvedMinimum *int64
	unitCost        int64
}

type rateKey struct{ card, key string }

func readSettings(ctx context.Context, db schooldirectory.Querier, cards []string) (map[rateKey]setting, error) {
	out := map[rateKey]setting{}
	if len(cards) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT catalogue_id, key, approved_minimum, unit_cost FROM cost_setting WHERE catalogue_id = ANY($1)`, cards)
	if err != nil {
		return nil, fmt.Errorf("myplan: cost settings: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var card *string
		var key string
		var s setting
		if err := rows.Scan(&card, &key, &s.approvedMinimum, &s.unitCost); err != nil {
			return nil, err
		}
		out[rateKey{str(card), key}] = s
	}
	return out, rows.Err()
}

// settingForLine is costing_service.setting_for_line.
func settingForLine(rates map[rateKey]setting, card, key string) (setting, bool) {
	if s, ok := rates[rateKey{card, key}]; ok {
		return s, true
	}
	for _, old := range rules.Rows.RateAliases[key] {
		if s, ok := rates[rateKey{card, old}]; ok {
			return s, true
		}
	}
	return setting{}, false
}

// truthy is Python's truth of a decoded JSON value.
func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case json.Number:
		f, err := x.Float64()
		return err != nil || f != 0
	case []any:
		return len(x) > 0
	case map[string]any:
		return len(x) > 0
	}
	return true
}

// whole is a JSON number the existing code reads as a Python int; ok is
// false for anything else (a float, which Go does not price yet).
func whole(v any) (int64, bool) {
	n, isNumber := v.(json.Number)
	if !isNumber {
		return 0, false
	}
	i, err := n.Int64()
	if err != nil || i > 1e15 || i < -1e15 {
		return 0, false
	}
	return i, true
}

// minimumShare is costing_service.minimum_share. ok is false where the
// existing code would fail or reads a float; the share is nil where it
// answers None.
func minimumShare(line map[string]any, s setting, found bool) (share *int64, ok bool) {
	key, _ := line["key"].(string)
	if !found && in(rules.Rows.RetiredCostSettingKeys, key) && !truthy(line["missing"]) {
		amount := line["amount"]
		if !truthy(amount) {
			zero := int64(0)
			return &zero, true
		}
		n, isWhole := whole(amount)
		if !isWhole {
			return nil, false
		}
		return &n, true
	}
	var rate *int64
	if found {
		rate = s.approvedMinimum
	}
	unitValue, hasUnit := line["unit"]
	if rate == nil || !hasUnit || unitValue == nil || truthy(line["missing"]) {
		return nil, true
	}
	if alloc := line["dailyAllocation"]; truthy(alloc) {
		m, isMap := alloc.(map[string]any)
		if !isMap {
			return nil, false
		}
		count, okCount := whole(m["count"])
		index, okIndex := whole(m["index"])
		if !okCount || !okIndex || count <= 0 || index < 0 || index >= count {
			return nil, false
		}
		base, remainder := *rate/count, *rate%count
		if index < remainder {
			base++
		}
		return &base, true
	}
	unit, isWhole := whole(unitValue)
	if !isWhole {
		return nil, false
	}
	label := ""
	if raw, has := line["label"]; has {
		text, isText := raw.(string)
		if !isText {
			return nil, false
		}
		label = text
	}
	if unit != 0 && bytes.Contains([]byte(label), []byte("(shared,")) {
		unit = s.unitCost
	}
	if unit == 0 {
		if *rate == 0 {
			zero := int64(0)
			return &zero, true
		}
		return nil, true
	}
	amount, isWholeAmount := whole(line["amount"])
	if !isWholeAmount {
		return nil, false
	}
	// Decimal(amount) * Decimal(rate) / Decimal(unit), quantized half up.
	q := new(big.Rat).SetFrac(new(big.Int).Mul(big.NewInt(amount), big.NewInt(*rate)), big.NewInt(unit))
	v := roundHalfUp(q)
	return &v, true
}

// roundHalfUp is Decimal.quantize(Decimal("1"), ROUND_HALF_UP): halves away
// from zero.
func roundHalfUp(q *big.Rat) int64 {
	num, den := new(big.Int).Abs(q.Num()), q.Denom()
	twice := new(big.Int).Add(new(big.Int).Mul(num, big.NewInt(2)), den)
	r := new(big.Int).Quo(twice, new(big.Int).Mul(den, big.NewInt(2)))
	if q.Sign() < 0 {
		r.Neg(r)
	}
	return r.Int64()
}

// snapshot is a current cost snapshot's priced components.
type snapshot struct {
	activityID    string
	card          *string
	breakdown     []byte
	operational   *int64
	missingConfig []byte
}

func readSnapshots(ctx context.Context, db schooldirectory.Querier, ids []string) ([]snapshot, error) {
	rows, err := db.Query(ctx, `SELECT activity_id, operational_rate_card_id, operational_breakdown, operational_cost, missing_configuration
FROM activity_cost_snapshot WHERE activity_id = ANY($1) AND is_current`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: cost snapshots: %w", err)
	}
	defer rows.Close()
	var out []snapshot
	for rows.Next() {
		var s snapshot
		if err := rows.Scan(&s.activityID, &s.card, &s.breakdown, &s.operational, &s.missingConfig); err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

func decode(raw []byte) (any, error) {
	if raw == nil {
		return nil, nil
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	var v any
	err := d.Decode(&v)
	return v, err
}

func cardsOf(snaps []snapshot) []string {
	var cards []string
	for _, s := range snaps {
		if s.card != nil && !in(cards, *s.card) {
			cards = append(cards, *s.card)
		}
	}
	return cards
}

// minimumAmounts is costing_service.planned_minimum_amounts: each
// activity's staff estimate from its current snapshot's components, nil
// where a component cannot be re-priced.
func minimumAmounts(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]*int64, error) {
	snaps, err := readSnapshots(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	rates, err := readSettings(ctx, db, cardsOf(snaps))
	if err != nil {
		return nil, err
	}
	out := map[string]*int64{}
	for _, s := range snaps {
		breakdown, err := decode(s.breakdown)
		if err != nil {
			return nil, err
		}
		missingConfig, err := decode(s.missingConfig)
		if err != nil {
			return nil, err
		}
		lines, isList := breakdown.([]any)
		if !isList {
			// None or another shape: `for line in breakdown` fails there.
			return nil, fmt.Errorf("%w: a breakdown that is not a list", ErrUnported)
		}
		total := int64(0)
		missing := !isSet(s.card) || (len(lines) == 0 && (s.operational == nil || *s.operational != 0)) || truthy(missingConfig)
		for _, l := range lines {
			line, isMap := l.(map[string]any)
			if !isMap {
				return nil, fmt.Errorf("%w: a component that is not an object", ErrUnported)
			}
			key, _ := line["key"].(string)
			st, found := settingForLine(rates, str(s.card), key)
			share, ok := minimumShare(line, st, found)
			if !ok {
				return nil, fmt.Errorf("%w: a component Go does not price", ErrUnported)
			}
			if share == nil {
				missing = true
				break
			}
			total += *share
		}
		if missing {
			out[s.activityID] = nil
		} else {
			v := total
			out[s.activityID] = &v
		}
	}
	return out, nil
}

// mealRates is costing_service.planned_meal_rates without its fallback:
// one participant's meal at each session, from its own snapshot's meals
// line. A session it does not find would read the live catalogue's rate,
// which Go does not read yet (the caller passes the page then).
func mealRates(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]int64, error) {
	out := map[string]int64{}
	if len(ids) == 0 {
		return out, nil
	}
	snaps, err := readSnapshots(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	rates, err := readSettings(ctx, db, cardsOf(snaps))
	if err != nil {
		return nil, err
	}
	for _, s := range snaps {
		breakdown, err := decode(s.breakdown)
		if err != nil {
			return nil, err
		}
		lines, _ := breakdown.([]any)
		if breakdown != nil && lines == nil && truthy(breakdown) {
			return nil, fmt.Errorf("%w: a breakdown that is not a list", ErrUnported)
		}
		for _, l := range lines {
			line, isMap := l.(map[string]any)
			if !isMap {
				return nil, fmt.Errorf("%w: a component that is not an object", ErrUnported)
			}
			key, _ := line["key"].(string)
			if !in(rules.Rows.MealsRateKeys, key) {
				continue
			}
			qty := int64(0)
			if truthy(line["qty"]) {
				n, isWhole := whole(line["qty"])
				if !isWhole {
					return nil, fmt.Errorf("%w: a meals line's quantity that is not whole", ErrUnported)
				}
				qty = n
			}
			st, found := settingForLine(rates, str(s.card), key)
			share, ok := minimumShare(line, st, found)
			if !ok {
				return nil, fmt.Errorf("%w: a meals component Go does not price", ErrUnported)
			}
			if share == nil || qty == 0 {
				continue
			}
			out[s.activityID] = int64(math.RoundToEven(float64(*share) / float64(qty)))
			break
		}
	}
	return out, nil
}

// catalogueRate is costing_service.catalogue_rate: the live published card's
// rate for key as staff planning reads one (the approved minimum, else the
// operational rate), nil when the card does not carry it.
func catalogueRate(ctx context.Context, db schooldirectory.Querier, place *registry.Work, key string) (*int64, error) {
	r := rules.Rows
	var card string
	err := db.QueryRow(ctx, `SELECT id FROM cost_catalogue WHERE country = $1 AND kind = $2 AND status = $3 AND is_active
ORDER BY fy DESC, version DESC LIMIT 1`, registry.SettingsName(place, r.CatalogueCountry), r.CatalogueKind, r.CatalogueStatus).Scan(&card)
	if isNoRows(err) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("myplan: live rate card: %w", err)
	}
	keys := slices.Clone(r.CanonicalRateKeys)
	for _, olds := range r.RateAliases {
		keys = append(keys, olds...)
	}
	rows, err := db.Query(ctx, `SELECT key, approved_minimum, unit_cost, catalogue_item_id IS NOT NULL FROM cost_setting
WHERE catalogue_id = $1 AND (key = ANY($2) OR catalogue_item_id IS NOT NULL)`, card, keys)
	if err != nil {
		return nil, fmt.Errorf("myplan: live rates: %w", err)
	}
	defer rows.Close()
	type priced struct {
		minimum *int64
		unit    int64
		item    bool
	}
	held := map[string]priced{}
	for rows.Next() {
		var k string
		var p priced
		if err := rows.Scan(&k, &p.minimum, &p.unit, &p.item); err != nil {
			return nil, err
		}
		held[k] = p
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	p, ok := held[key]
	if !ok {
		for _, old := range r.RateAliases[key] {
			if p, ok = held[old]; ok {
				break
			}
		}
	}
	if !ok || !(in(r.CanonicalRateKeys, key) || p.item) {
		return nil, nil
	}
	if p.minimum != nil {
		v := *p.minimum
		return &v, nil
	}
	v := p.unit
	return &v, nil
}
