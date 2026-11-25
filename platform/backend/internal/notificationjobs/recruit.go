package notificationjobs

// recruit_notice.sweep: a Programme Lead or CCEO whose schools cannot take
// their year's visit target gets one notice (opening My Plan) for as long as
// that holds; the notice of anybody who holds enough again, or is no longer
// a Lead or a CCEO, is closed.

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningmonitor"
)

const (
	recruitEvent   = "planning_recruit_schools"
	recruitContext = "visit_target"
	recruitTitle   = "Recruit more schools to meet your visit target"
)

// RecruitSweep is the sweep; it says how many notices it opened.
func RecruitSweep(ctx context.Context, tx pgx.Tx, now time.Time, n Notices) (int, error) {
	everyone, err := planningmonitor.RecruitPortfolios(ctx, tx)
	if err != nil {
		return 0, err
	}
	told := map[string]bool{}
	rows, err := tx.Query(ctx, `SELECT context_id FROM notification WHERE source_event_type = $1 AND context_type = $2
  AND resolved_at IS NULL`, recruitEvent, recruitContext)
	if err != nil {
		return 0, fmt.Errorf("notificationjobs: reading who was told to recruit: %w", err)
	}
	for rows.Next() {
		var key *string
		if err := rows.Scan(&key); err != nil {
			rows.Close()
			return 0, err
		}
		if key != nil {
			told[*key] = true
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	short := map[string]bool{}
	for _, p := range everyone {
		if p.Short > 0 {
			short[p.Key] = true
		}
	}
	opened := 0
	for _, p := range everyone {
		if !short[p.Key] || told[p.Key] {
			continue
		}
		to := p.UserID
		if to == "" {
			to = p.Key
		}
		people, err := activities.NotifyInTx(ctx, tx, n.Push, n.Logger, now, p.Key, activities.Notice{
			Title: recruitTitle,
			Body: "You plan " + thousands(p.Target) + " visits a year, and the schools you hold take fewer than that. " +
				"Recruit more schools to meet your target. My Plan shows how many you still need.",
			Event: recruitEvent, Category: "planning", ContextType: recruitContext, Priority: "normal",
		}, []activities.NoticeTo{{UserID: to, Route: "/my-plan", Label: "Open My Plan"}})
		if err != nil {
			return opened, err
		}
		if len(people) > 0 {
			opened++
		}
	}
	for key := range told {
		if short[key] {
			continue
		}
		if _, err := tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition($1, $2, $3, $4)`,
			recruitEvent, recruitContext, key, now); err != nil {
			return opened, fmt.Errorf("notificationjobs: closing a recruit notice: %w", err)
		}
	}
	return opened, nil
}

// thousands is f"{n:,}".
func thousands(n int) string {
	s := strconv.Itoa(n)
	sign := ""
	if n < 0 {
		sign, s = "-", s[1:]
	}
	var out []byte
	for i := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			out = append(out, ',')
		}
		out = append(out, s[i])
	}
	return sign + string(out)
}
