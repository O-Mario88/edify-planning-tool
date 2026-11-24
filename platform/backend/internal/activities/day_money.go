package activities

import (
	"cmp"
	"context"
	"encoding/json"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing/daypool"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// What follows a priced day with Django absent: the transport company's
// obligation and the staff advances are written with the day's costs, and
// each owner's weekly request and monthly draft are rebuilt once when the
// costs-to-follow row ends (apps.fund_requests.follow). Every write is made
// by the narrow functions in deploy/db/day_money_roles.sql.

// transportGoneStatuses are vendor_channel.TRANSPORT_GONE_STATUSES: a day's
// members whose share of its transport the provider is not owed.
var transportGoneStatuses = []string{"cancelled", "deferred", "rejected"}

// weekBucket is one owner's week, by its Monday.
type weekBucket struct {
	owner string
	start time.Time
}

// monthBucket is one owner's month of a fiscal year.
type monthBucket struct {
	owner, fy string
	month     int
}

// dayMoney is what a costs-to-follow row has to refile when it ends.
type dayMoney struct {
	weeks  map[weekBucket]struct{}
	months map[monthBucket]struct{}
	notes  []followNote
}

// followNote is what a save asked to be written on its lines once they are
// priced (costs_follow.NOTES).
type followNote struct {
	Kind     string `json:"kind"`
	Activity string `json:"activity"`
	Old      string `json:"old"`
	New      string `json:"new"`
	Reason   string `json:"reason"`
}

// trail is handle_reschedule's text; write is false when the move moved
// nothing. The weeks are of each date as the row wrote it.
func (n followNote) trail() (text string, write bool, err error) {
	if n.Kind != "reschedule_note" {
		return "", false, fmt.Errorf("activities: a costs-to-follow note of kind %q", n.Kind)
	}
	const layout = "2006-01-02T15:04:05-07:00"
	before, err := time.Parse(layout, n.Old)
	if err != nil {
		return "", false, fmt.Errorf("activities: a reschedule note's old date: %w", err)
	}
	after, err := time.Parse(layout, n.New)
	if err != nil {
		return "", false, fmt.Errorf("activities: a reschedule note's new date: %w", err)
	}
	if before.Equal(after) {
		return "", false, nil
	}
	_, oldWeek := before.ISOWeek()
	_, newWeek := after.ISOWeek()
	return fmt.Sprintf(" [Audit: Rescheduled due to %s. Old period: Week %d, New period: Week %d]", n.Reason, oldWeek, newWeek), true, nil
}

func newDayMoney() *dayMoney {
	return &dayMoney{weeks: map[weekBucket]struct{}{}, months: map[monthBucket]struct{}{}}
}

// addWeek files day under its owner's Monday. A week with no owner is nobody's.
func (m *dayMoney) addWeek(owner string, day time.Time) {
	if owner == "" {
		return
	}
	sinceMonday := (int(day.Weekday()) + 6) % 7
	monday := time.Date(day.Year(), day.Month(), day.Day()-sinceMonday, 0, 0, 0, 0, time.UTC)
	m.weeks[weekBucket{owner: owner, start: monday}] = struct{}{}
}

func (m *dayMoney) addMonth(owner, fy string, month int) {
	if owner == "" || fy == "" || month == 0 {
		return
	}
	m.months[monthBucket{owner: owner, fy: fy, month: month}] = struct{}{}
}

// addSteps takes the weeks and months the save wrote on its row: where the
// activity's lines sat before it moved or was cancelled.
func (m *dayMoney) addSteps(steps costsFollowSteps) error {
	for _, week := range steps.Weeks {
		if len(week) != 2 {
			return fmt.Errorf("activities: a costs-to-follow week is not an owner and a date: %v", week)
		}
		day, err := time.Parse(time.DateOnly, week[1])
		if err != nil {
			return fmt.Errorf("activities: a costs-to-follow week: %w", err)
		}
		m.addWeek(week[0], day)
	}
	for _, month := range steps.Months {
		if len(month) != 3 {
			return fmt.Errorf("activities: a costs-to-follow month is not an owner, a year and a month: %v", month)
		}
		number, err := monthNumber(month[2])
		if err != nil {
			return err
		}
		m.addMonth(fmt.Sprint(month[0]), fmt.Sprint(month[1]), number)
	}
	m.notes = append(m.notes, steps.Notes...)
	return nil
}

// monthNumber reads a month from a row's JSON, as a number or as digits.
func monthNumber(raw any) (int, error) {
	switch value := raw.(type) {
	case float64:
		return int(value), nil
	case json.Number:
		number, err := value.Int64()
		return int(number), err
	case string:
		return strconv.Atoi(value)
	}
	return 0, fmt.Errorf("activities: a costs-to-follow month is %T", raw)
}

func (m *dayMoney) sortedWeeks() []weekBucket {
	weeks := make([]weekBucket, 0, len(m.weeks))
	for week := range m.weeks {
		weeks = append(weeks, week)
	}
	slices.SortFunc(weeks, func(a, b weekBucket) int {
		return cmp.Or(cmp.Compare(a.owner, b.owner), a.start.Compare(b.start))
	})
	return weeks
}

func (m *dayMoney) sortedMonths() []monthBucket {
	months := make([]monthBucket, 0, len(m.months))
	for month := range m.months {
		months = append(months, month)
	}
	slices.SortFunc(months, func(a, b monthBucket) int {
		return cmp.Or(cmp.Compare(a.owner, b.owner), cmp.Compare(a.fy, b.fy), cmp.Compare(a.month, b.month))
	})
	return months
}

// schoolTransportAmount is vendor_channel._school_transport: the shares of the
// day's transport held by the members at a school.
func schoolTransportAmount(pool map[string]int64, atSchool []bool) int64 {
	if len(atSchool) == 0 {
		return 0
	}
	var transport int64
	for key, amount := range pool {
		if strings.Contains(key, "transport") {
			transport += amount
		}
	}
	var owed int64
	for index, share := range daypool.AllocateComponent(transport, len(atSchool)) {
		if atSchool[index] {
			owed += share
		}
	}
	return owed
}

// ensureDayTransport keeps the transport company's obligation in step with
// the day. A day already paid at another amount fails the settlement.
func ensureDayTransport(ctx context.Context, tx pgx.Tx, batchID string, pool map[string]int64, now time.Time) error {
	rows, err := tx.Query(ctx, `SELECT COALESCE(school_id, '') <> '' FROM activity
WHERE daily_visit_batch_id = $1 AND deleted_at IS NULL AND NOT (status = ANY($2)) ORDER BY id`, batchID, transportGoneStatuses)
	if err != nil {
		return fmt.Errorf("activities: reading the day's transport members: %w", err)
	}
	atSchool, err := pgx.CollectRows(rows, pgx.RowTo[bool])
	if err != nil {
		return fmt.Errorf("activities: reading a transport member: %w", err)
	}
	amount := schoolTransportAmount(pool, atSchool)
	if _, err := tx.Exec(ctx, `SELECT gateway_day_money.ensure_transport($1, $2, $3)`, batchID, amount, now); err != nil {
		return fmt.Errorf("activities: keeping the day's transport obligation: %w", err)
	}
	return nil
}

// clearDayMoney is the guard and the cascade of the existing cost writer: it
// refuses a day whose money has moved, then lifts the advances and weekly
// lines off the lines about to be rewritten.
func clearDayMoney(ctx context.Context, tx pgx.Tx, activityIDs []string, money *dayMoney) error {
	var refusal *string
	if err := tx.QueryRow(ctx, `SELECT gateway_day_money.money_guard($1)`, activityIDs).Scan(&refusal); err != nil {
		return fmt.Errorf("activities: checking the day's money: %w", err)
	}
	if refusal != nil {
		return fmt.Errorf("activities: the day cannot be priced: %s", *refusal)
	}
	rows, err := tx.Query(ctx, `SELECT bucket_owner, bucket_week FROM gateway_day_money.clear_day($1)`, activityIDs)
	if err != nil {
		return fmt.Errorf("activities: clearing the day's advances: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var owner string
		var week time.Time
		if err := rows.Scan(&owner, &week); err != nil {
			return fmt.Errorf("activities: reading a cleared week: %w", err)
		}
		money.addWeek(owner, week)
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("activities: clearing the day's advances: %w", err)
	}
	return nil
}

// openDayMoney opens the advances of the lines just written and notes the
// owner's week and month for the row's end.
func openDayMoney(ctx context.Context, tx pgx.Tx, activityIDs []string, owner string, day, now time.Time, money *dayMoney) error {
	var opened int
	if err := tx.QueryRow(ctx, `SELECT gateway_day_money.open_advances($1, $2, $3)`, activityIDs, owner, now).Scan(&opened); err != nil {
		return fmt.Errorf("activities: opening the day's advances: %w", err)
	}
	money.addWeek(owner, day)
	rows, err := tx.Query(ctx, `SELECT DISTINCT responsible_user, fiscal_year, month FROM activity_schedule_cost_line
WHERE activity_id = ANY($1) AND responsible_user IS NOT NULL AND fiscal_year IS NOT NULL AND month IS NOT NULL`, activityIDs)
	if err != nil {
		return fmt.Errorf("activities: reading the day's months: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var lineOwner, fy string
		var month int
		if err := rows.Scan(&lineOwner, &fy, &month); err != nil {
			return fmt.Errorf("activities: reading a month: %w", err)
		}
		money.addMonth(lineOwner, fy, month)
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("activities: reading the day's months: %w", err)
	}
	return nil
}

// refileDayMoney rebuilds each owner-week and owner-month once, from the
// lines as they stand.
func refileDayMoney(ctx context.Context, tx pgx.Tx, money *dayMoney, now time.Time) error {
	for _, week := range money.sortedWeeks() {
		if _, err := tx.Exec(ctx, `SELECT gateway_day_money.refile_week($1, $2::date, $3, $4)`,
			week.owner, week.start.Format(time.DateOnly), schooldirectory.OperationalFY(week.start), now); err != nil {
			return fmt.Errorf("activities: rebuilding the weekly request: %w", err)
		}
	}
	for _, month := range money.sortedMonths() {
		if _, err := tx.Exec(ctx, `SELECT gateway_day_money.refile_month($1, $2, $3, $4)`,
			month.owner, month.fy, month.month, now); err != nil {
			return fmt.Errorf("activities: rebuilding the monthly draft: %w", err)
		}
	}
	for _, note := range money.notes {
		trail, write, err := note.trail()
		if err != nil {
			return err
		}
		if !write {
			continue
		}
		if _, err := tx.Exec(ctx, `SELECT gateway_day_money.note_lines($1, $2, $3)`, note.Activity, trail, now); err != nil {
			return fmt.Errorf("activities: writing the move's trail: %w", err)
		}
	}
	return nil
}

// handOnFiledMonth hands on a save whose day is carried by a request other
// than the owner's own monthly draft. The existing application carries such a
// request along with the change; Go does not yet.
func (n *NativePricing) handOnFiledMonth(ctx context.Context, owner string, days ...time.Time) error {
	dates := make([]string, 0, len(days))
	for _, day := range days {
		dates = append(dates, day.Format(time.DateOnly))
	}
	var filed bool
	if err := n.pool.QueryRow(ctx, `SELECT gateway_day_money.day_month_filed($1, $2::date[])`, owner, dates).Scan(&filed); err != nil {
		return fmt.Errorf("activities: checking the day's monthly request: %w", err)
	}
	if filed {
		return handOn("a filed monthly request carries this day")
	}
	return nil
}
