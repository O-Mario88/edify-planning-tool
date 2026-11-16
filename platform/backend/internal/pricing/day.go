package pricing

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
)

// DayRefusal is a day the existing pricing refuses: its card lacks a rate
// the day needs (compute_daily_pool), for a day of DistrictType.
type DayRefusal struct {
	DistrictType string
	Missing      []string
}

func (e *DayRefusal) Error() string {
	return "pricing: the day's rate card is missing " + strings.Join(e.Missing, ", ")
}

// Message is compute_daily_pool's refusal, in its own words.
func (e *DayRefusal) Message() string {
	return fmt.Sprintf("Cost Catalogue is missing required rate(s) for %s district visits: %s. "+
		"Ask the CD to add them in Cost Settings.", e.DistrictType, strings.Join(e.Missing, ", "))
}

// Share is one rate of the day's pool.
type Share struct {
	Key    string
	Amount int64
}

// Member is one activity of the day and what it costs: its share of every
// rate of the pool, then its own lines that are not the day's.
type Member struct {
	ActivityID string
	Cost       costing.Cost
}

// Day is _plan_day and the member costs _write_day_lines writes, worked out
// without writing: the day's members, Primary, Secondary or Mixed, the
// rates it fetches, whether it is the day the traveller comes home, the
// pool, and each member's cost.
type Day struct {
	Card         *Card
	Mark         string
	DistrictType string
	ReturnDay    bool
	Pool         []Share
	Members      []Member
}

type dayRow struct {
	user, storedType string
	date             time.Time
	schoolCount      int
}

// The day's own price needs only whether it is away now: the existing
// pricing also reads the neighbours of a day that was away when last priced,
// to settle them, which is a write Go does not make.

// PlanDay plans the stored day batchID as the existing pricing would.
func PlanDay(ctx context.Context, db Querier, batchID string) (Day, error) {
	var b dayRow
	err := db.QueryRow(ctx, `
		SELECT COALESCE(responsible_user, ''), COALESCE(district_type, ''), visit_date, COALESCE(school_count, 0)
		FROM daily_visit_batch WHERE id = $1`, batchID).Scan(&b.user, &b.storedType, &b.date, &b.schoolCount)
	if err != nil {
		return Day{}, fmt.Errorf("pricing: reading day %s: %w", batchID, err)
	}
	members, err := dayMembers(ctx, db, batchID)
	if err != nil {
		return Day{}, err
	}
	return planDay(ctx, db, b, members)
}

// planDay plans the day b with these members (by id).
func planDay(ctx context.Context, db Querier, b dayRow, members []dayMember) (Day, error) {
	d, err := dayPool(ctx, db, b, members)
	if err != nil {
		return d, err
	}
	return withMemberCosts(ctx, db, d, members)
}

// dayPool is _plan_day with_recipes=False: the day's kind, whether it is the
// trip home, and its pool, or the day's refusal.
func dayPool(ctx context.Context, db Querier, b dayRow, members []dayMember) (Day, error) {
	card, err := ReadCard(ctx, db, rules.OperationalKind, &b.date)
	if err != nil {
		return Day{}, err
	}
	traveller, err := readTraveller(ctx, db, b.user)
	if err != nil {
		return Day{}, err
	}
	types := map[string]bool{}
	for _, m := range members {
		t := "primary"
		if m.district != "" {
			found, err := traveller.districtType(ctx, db, m.district)
			if err != nil {
				return Day{}, err
			}
			if found != "" {
				t = found
			}
		}
		types[t] = true
	}
	d := Day{Card: card, Mark: "primary", DistrictType: b.storedType}
	if types["secondary"] {
		d.Mark = "secondary"
		if types["primary"] {
			d.Mark = "mixed"
		}
	}
	if len(types) > 0 {
		d.DistrictType = "secondary"
		if d.Mark == "primary" {
			d.DistrictType = "primary"
		}
	}
	isAway := d.DistrictType == "secondary" && len(members) > 0
	if isAway {
		before, after := b.date.AddDate(0, 0, -1), b.date.AddDate(0, 0, 1)
		away, err := awayOn(ctx, db, b.user, before, after)
		if err != nil {
			return Day{}, err
		}
		d.ReturnDay = away[before.Format(time.DateOnly)] && !away[after.Format(time.DateOnly)]
	}
	rates := map[string]int64{}
	if card != nil {
		rates = card.Rates
	}
	required, optional := costing.DayKeys(d.DistrictType, traveller.accommodationKey(), d.ReturnDay)
	var missing []string
	for _, k := range required {
		if _, ok := rates[k]; !ok {
			missing = append(missing, k)
		}
	}
	if len(missing) > 0 {
		return d, &DayRefusal{DistrictType: d.DistrictType, Missing: missing}
	}
	for _, k := range required {
		d.Pool = append(d.Pool, Share{Key: k, Amount: rates[k]})
	}
	for _, k := range optional {
		if v, ok := rates[k]; ok {
			d.Pool = append(d.Pool, Share{Key: k, Amount: v})
		}
	}
	return d, nil
}

// withMemberCosts is what _write_day_lines writes each member of the day d:
// its share of every rate of the pool, then its own lines that are not the
// day's.
func withMemberCosts(ctx context.Context, db Querier, d Day, members []dayMember) (Day, error) {
	card := d.Card
	rates := ratesOf(card)
	n := len(members)
	for i, m := range members {
		in, err := StoredInput(ctx, db, m.id)
		if err != nil {
			return Day{}, err
		}
		in.DistrictType, in.ReturnDay = d.DistrictType, d.ReturnDay
		a, err := Profiled(in)
		if err != nil {
			return Day{}, err
		}
		a.LinkedRates = card.LinkedRates(in.CatalogueItemID)
		own := costing.CostForActivity(a, rates)
		cost := costing.Cost{MissingItems: []string{}}
		for _, share := range d.Pool {
			amount := split(share.Amount, n, i)
			label := dayLineLabel(share.Key, d.Mark)
			u := amount
			cost.Lines = append(cost.Lines, costing.Line{Label: label, Key: share.Key, Unit: &u, Qty: 1, Amount: amount})
		}
		for _, line := range own.Lines {
			if _, dayRate := costing.DayLabel(line.Key); !dayRate {
				cost.Lines = append(cost.Lines, line)
			}
		}
		for _, key := range own.MissingItems {
			if _, dayRate := costing.DayLabel(key); !dayRate {
				cost.MissingItems = append(cost.MissingItems, key)
			}
		}
		for _, line := range cost.Lines {
			cost.Amount += line.Amount
		}
		cost.CostMissing = len(cost.MissingItems) > 0
		d.Members = append(d.Members, Member{ActivityID: m.id, Cost: cost})
	}
	return d, nil
}

// split is allocate_component's i-th part of total across n: the remainder
// shillings to the first members.
func split(total int64, n, i int) int64 {
	base, remainder := total/int64(n), total%int64(n)
	if int64(i) < remainder {
		return base + 1
	}
	return base
}

func dayLineLabel(key, mark string) string {
	if mark == "mixed" && key == "secondary_transport_per_day" {
		return rules.MixedTransportLabel
	}
	if l, ok := costing.DayLabel(key); ok {
		return l
	}
	return pyTitle(strings.ReplaceAll(key, "_", " "))
}

type dayMember struct{ id, district string }

// dayMembers is the day's live fundable members by id, with the district
// each happens in (member_district: the school's, else the cluster's, else
// the event's).
func dayMembers(ctx context.Context, db Querier, batchID string) ([]dayMember, error) {
	rows, err := db.Query(ctx, `
		SELECT a.id, COALESCE(sc.district_id, cl.district_id, a.event_district_id, '')
		FROM activity a
		LEFT JOIN school sc ON sc.id = a.school_id
		LEFT JOIN cluster cl ON cl.id = a.cluster_id
		WHERE a.daily_visit_batch_id = $1 AND a.deleted_at IS NULL
		  AND (a.status IS NULL OR NOT (a.status = ANY($2)))
		ORDER BY a.id`, batchID, rules.NonFundableStatuses)
	if err != nil {
		return nil, fmt.Errorf("pricing: reading the day's members: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (dayMember, error) {
		var m dayMember
		err := row.Scan(&m.id, &m.district)
		return m, err
	})
}

// awayOn is return_day.away_on over the stored days: which of the two days
// the traveller spends in a secondary district.
func awayOn(ctx context.Context, db Querier, user string, days ...time.Time) (map[string]bool, error) {
	out := map[string]bool{}
	if user == "" {
		return out, nil
	}
	rows, err := db.Query(ctx, `
		SELECT visit_date FROM daily_visit_batch
		WHERE responsible_user = $1 AND visit_date = ANY($2) AND district_type = 'secondary' AND school_count > 0`,
		user, days)
	if err != nil {
		return nil, fmt.Errorf("pricing: reading the neighbouring days: %w", err)
	}
	dates, err := pgx.CollectRows(rows, pgx.RowTo[time.Time])
	if err != nil {
		return nil, fmt.Errorf("pricing: reading the neighbouring days: %w", err)
	}
	for _, d := range dates {
		out[d.Format(time.DateOnly)] = true
	}
	return out, nil
}

// pyTitle is Python's str.title().
func pyTitle(s string) string {
	out := []rune(strings.ToLower(s))
	start := true
	for i, r := range out {
		letter := r >= 'a' && r <= 'z'
		if letter && start {
			out[i] = r - 'a' + 'A'
		}
		start = !letter
	}
	return string(out)
}
