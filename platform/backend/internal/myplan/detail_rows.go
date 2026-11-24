package myplan

import (
	"context"
	"fmt"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// budgetOf is activity_budget_breakdown for a staff reader. staff is the
// responsible officer's name ("" when the view found nobody); pairNote is
// pair_costing's note for the activity.
func budgetOf(ctx context.Context, db schooldirectory.Querier, a *detailActivity, snap costSnapshot, staff, pairNote string) (budgetBreakdown, error) {
	lines, err := readDetailLines(ctx, db, a.id)
	if err != nil {
		return budgetBreakdown{}, err
	}
	order, priced, err := pricedLines(snap)
	if err != nil {
		return budgetBreakdown{}, err
	}
	card := snap.card
	if card == "" {
		for _, l := range lines {
			if l.card != "" {
				card = l.card
				break
			}
		}
	}
	rates := map[rateKey]rateSetting{}
	if card != "" && len(lines) > 0 {
		if rates, err = readRateSettings(ctx, db, card); err != nil {
			return budgetBreakdown{}, err
		}
	}
	var batch *visitBatch
	if a.batchID != "" {
		if batch, err = readVisitBatch(ctx, db, a.batchID); err != nil {
			return budgetBreakdown{}, err
		}
	}
	money, err := readLineMoney(ctx, db, a, lines, batch)
	if err != nil {
		return budgetBreakdown{}, err
	}

	groups := map[string][]costLine{}
	var seen []string
	for _, l := range lines {
		key := baseKey(l.key)
		if _, ok := groups[key]; !ok {
			seen = append(seen, key)
		}
		groups[key] = append(groups[key], l)
	}
	var keys []string
	for _, key := range order {
		if _, ok := groups[key]; ok {
			keys = append(keys, key)
		}
	}
	for _, key := range seen {
		if _, ok := priced[key]; !ok {
			keys = append(keys, key)
		}
	}

	var b budgetBreakdown
	counts := map[int]bool{}
	var labels []string
	minimums := true
	for _, key := range keys {
		row, count, label, err := budgetRowOf(key, groups[key], priced[key], rates, card, batch, money)
		if err != nil {
			return budgetBreakdown{}, err
		}
		if count != nil {
			counts[*count] = true
		}
		if label != "" {
			labels = append(labels, label)
		}
		if row.minimumUnknown {
			minimums = false
		}
		b.rows = append(b.rows, row.budgetRow)
	}
	for _, r := range b.rows {
		b.total += r.amount
		b.minimumTotal += r.minimum
	}
	minimums = minimums && len(b.rows) > 0
	if minimums {
		for _, r := range b.rows {
			if r.minimum != r.amount {
				b.showMinimum = true
			}
		}
	}
	if batch != nil && len(labels) > 0 && len(counts) == 1 {
		if err := b.sayDay(ctx, db, a, batch, counts, labels, staff); err != nil {
			return budgetBreakdown{}, err
		}
	}
	return b, b.finish(ctx, db, a, snap, pairNote)
}

// pricedRow is one row and whether its minimum viable share is known.
type pricedRow struct {
	budgetRow
	minimumUnknown bool
}

// budgetRowOf is one cost item's row: count is the day's activity count it
// was shared by, label the day's cost it names ("transport", "lunch"), for
// the day's sentence.
func budgetRowOf(key string, members []costLine, priced map[string]any, rates map[rateKey]rateSetting, card string, batch *visitBatch, money map[string]string) (pricedRow, *int, string, error) {
	d := rules.Detail
	var amount, quantity int64
	for _, m := range members {
		amount += m.amount
		quantity += m.quantity
	}
	unit := members[0].unit
	st, found := rateFor(rates, card, key)
	if priced != nil {
		// int(priced_line.get("amount") or 0)
		n, ok := pyInt(orZero(priced["amount"]))
		if !ok {
			return pricedRow{}, nil, "", handOn("a priced amount that is not whole")
		}
		if n == nil {
			n = new(int64)
		}
		if *n != amount {
			priced = nil
		}
	}
	unitLabel := ""
	if found && st.unit != "unit" {
		unitLabel = st.unit
	}
	if unitLabel == "" {
		unitLabel = d.RateUnits[key]
	}
	unitLabel = strings.TrimSpace(unitLabel)
	label := ""
	if found {
		label = strings.TrimSpace(st.label)
	}
	if label == "" {
		label, _, _ = strings.Cut(members[0].label, " [Rate basis:")
	}
	for _, m := range members {
		if m.label == d.MixedTransportLabel {
			label = d.MixedTransportLabel
		}
	}
	if priced != nil && truthy(priced["missing"]) {
		// "Not set" and the warning beside it: parts Go does not draw yet.
		return pricedRow{}, nil, "", handOn("a rate missing from the Cost Catalogue")
	}

	var count *int
	dayLabel := ""
	basis := "As priced"
	allocation := priced["dailyAllocation"]
	_, daily := d.KeyLabels[key]
	switch {
	case daily && (truthy(allocation) || batch != nil):
		n, index, err := shareOf(allocation, batch)
		if err != nil {
			return pricedRow{}, nil, "", err
		}
		var candidates []*int64
		if batch != nil {
			rate, ok := pyInt(batch.rateSnapshot[key])
			if !ok {
				return pricedRow{}, nil, "", handOn("a day rate that is not whole")
			}
			candidates = append(candidates, rate)
		} else {
			candidates = append(candidates, nil)
		}
		if found {
			c := st.unitCost
			candidates = append(candidates, &c)
		}
		rate := dayRate(amount, max(n, 1), index, candidates)
		if rate == nil {
			basis = "Share of the day's cost"
		} else {
			shared := max(n, 1)
			basis = dayBasis(*rate, shared, unitLabel)
			count = &shared
		}
		first, _, _ := strings.Cut(d.KeyLabels[key], " ")
		dayLabel = strings.ToLower(first)
	case quantity*unit == amount:
		basis = quantityBasis(quantity, unit, unitLabel)
	}

	row := pricedRow{budgetRow: budgetRow{label: label, basis: basis, amount: amount, status: money[members[0].id]}}
	if priced == nil {
		row.minimumUnknown = true
		return row, count, dayLabel, nil
	}
	share, ok := minimumShare(priced, setting{approvedMinimum: st.approvedMinimum, unitCost: st.unitCost}, found)
	if !ok {
		return pricedRow{}, nil, "", handOn("a minimum share Go does not price")
	}
	if share == nil {
		row.minimumUnknown = true
	} else {
		row.minimum = *share
	}
	return row, count, dayLabel, nil
}

func orZero(v any) any {
	if !truthy(v) {
		return nil
	}
	return v
}

// shareOf is how many activities shared the day and which share this is:
// the snapshot line's dailyAllocation, else the batch's school count.
func shareOf(allocation any, batch *visitBatch) (int, *int64, error) {
	if truthy(allocation) {
		m, ok := allocation.(map[string]any)
		if !ok {
			return 0, nil, handOn("a daily allocation that is not an object")
		}
		count, okCount := whole(m["count"])
		index, okIndex := whole(m["index"])
		if !okCount || !okIndex {
			return 0, nil, handOn("a daily allocation without a whole count")
		}
		return int(count), &index, nil
	}
	if batch.schoolCount == nil || *batch.schoolCount == 0 {
		return 1, nil, nil
	}
	return int(*batch.schoolCount), nil, nil
}

// sayDay is the breakdown's day: who shares the day's transport and meals.
func (b *budgetBreakdown) sayDay(ctx context.Context, db schooldirectory.Querier, a *detailActivity, batch *visitBatch, counts map[int]bool, labels []string, staff string) error {
	count := 0
	for c := range counts {
		count = c
	}
	b.day = daySentence(staff, batch.day, count, uniq(labels))
	if count > 1 {
		others, err := dayOthers(ctx, db, a, count)
		if err != nil {
			return err
		}
		if len(others) > 0 {
			b.day += " Shared with: " + strings.Join(others, "; ")
		}
	}
	if batch.districtType == "secondary" && !anyKey(batch.rateSnapshot, rules.Detail.AccommodationKeys) {
		b.notes = append(b.notes, "This is the day home from a run of days in a secondary district, so it carries no accommodation and no dinner.")
	}
	return nil
}

func anyKey(m map[string]any, keys []string) bool {
	for _, k := range keys {
		if _, ok := m[k]; ok {
			return true
		}
	}
	return false
}

// dayOthers names the day's other activities, "Name at Place", while the
// day still holds the activities it was priced for.
func dayOthers(ctx context.Context, db schooldirectory.Querier, a *detailActivity, count int) ([]string, error) {
	rows, err := db.Query(ctx, `
SELECT o.id, o.activity_type, COALESCE(o.activity_name_snapshot, ''), o.school_id IS NOT NULL, COALESCE(s.name, ''),
  o.cluster_id IS NOT NULL, COALESCE(c.name, '')
FROM activity o LEFT JOIN school s ON s.id = o.school_id LEFT JOIN cluster c ON c.id = o.cluster_id
WHERE o.daily_visit_batch_id = $1 AND o.deleted_at IS NULL AND NOT COALESCE(o.status = ANY($2), false)
ORDER BY o.planned_date ASC, o.id ASC`, a.batchID, rules.Detail.NonFundableStatuses)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the day's activities: %w", err)
	}
	defer rows.Close()
	var names []string
	total := 0
	for rows.Next() {
		var id, kind, name, schoolName, clusterName string
		var hasSchool, hasCluster bool
		if err := rows.Scan(&id, &kind, &name, &hasSchool, &schoolName, &hasCluster, &clusterName); err != nil {
			return nil, err
		}
		total++
		if id == a.id {
			continue
		}
		if name == "" {
			name = rules.Detail.TypeLabels[kind]
			if name == "" {
				name = kind
			}
		}
		place := ""
		switch {
		case hasSchool:
			place = schoolName
		case hasCluster:
			place = clusterName
		}
		if place != "" {
			name += " at " + place
		}
		names = append(names, name)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if total != count {
		return nil, nil
	}
	return names, nil
}

// finish adds what the breakdown says about missing rates, an in-school
// training paired with the visit, an empty budget and the rate card.
func (b *budgetBreakdown) finish(ctx context.Context, db schooldirectory.Querier, a *detailActivity, snap costSnapshot, pairNote string) error {
	keys, err := missingKeys(snap)
	if err != nil {
		return err
	}
	var missing []string
	for _, key := range keys {
		switch label, ok := rules.Detail.MissingLabels[key]; {
		case key == "expectedParticipants":
			missing = append(missing, "the planned participant count")
		case ok:
			missing = append(missing, label)
		default:
			missing = append(missing, pyTitle(strings.ReplaceAll(key, "_", " ")))
		}
	}
	if pairNote != "" && len(b.rows) == 0 {
		// "UGX 0 (captured …)" and the link to the other half: Go hands on.
		return handOn("the UGX 0 half of a training and visit pair")
	}
	if len(b.rows) > 0 && a.kind == "school_visit" && !in(rules.Rows.CompanionGoneStatuses, a.status) {
		var paired bool
		if err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity WHERE paired_school_visit_id = $1
AND activity_type = 'in_school_training' AND deleted_at IS NULL AND NOT COALESCE(status = ANY($2), false))`,
			a.id, rules.Rows.CompanionGoneStatuses).Scan(&paired); err != nil {
			return fmt.Errorf("myplan: reading the visit's training: %w", err)
		}
		if paired {
			b.notes = append(b.notes, "This visit carries the in-school training done during it; the training itself is kept at UGX 0.")
		}
	}
	note := ""
	if len(missing) > 0 {
		verb := "are"
		if len(missing) == 1 {
			verb = "is"
		}
		note = fmt.Sprintf("Cost setup required: %s %s not set", andJoined(missing), verb)
	}
	switch {
	case len(b.rows) > 0 && note != "":
		b.missingNote = note + ", so this total is incomplete."
	case len(b.rows) == 0 && note != "":
		b.emptyNote = note + ", so this activity has no budget yet."
	case len(b.rows) == 0:
		b.emptyNote = "No budget has been worked out for this activity yet."
	}
	if len(b.rows) > 0 && snap.found && snap.card != "" && snap.cardVersion != nil {
		label := snap.cardLabel
		if label == "" {
			label = fmt.Sprintf("FY%s Cost Catalogue", pyNone(snap.cardFY))
		}
		b.source = fmt.Sprintf("Rates from the %s, version %d.", label, *snap.cardVersion)
		if snap.calculated != nil {
			day := snap.calculated.In(kampala)
			b.workedOut = fmt.Sprintf("%d %s %d", day.Day(), day.Format("Jan"), day.Year())
		}
	}
	return nil
}

// pyTitle is str.title for the words of a key.
func pyTitle(s string) string { return detailTitle(s) }
