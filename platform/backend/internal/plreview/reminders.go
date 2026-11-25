package plreview

// The verification_reminders job (apps.pl_review.reminders.
// send_verification_reminders): each evening every Programme Lead with
// completions waiting on them is told how many and from whom; one notice a
// lead a day, the evening's taking the place of the day before's, and a lead
// whose queue is empty has theirs closed.

import (
	"context"
	"fmt"
	"log/slog"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

const (
	verifyReminderEvent = "completions_awaiting_verification"
	verifyNamed         = 3 // _NAMED
)

// VerificationReminders is send_verification_reminders for today in Kampala.
func VerificationReminders(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location,
	push activities.NoticePush, logger *slog.Logger) (int, error) {
	key := "verify-" + now.In(kampala).Format(time.DateOnly)
	rows, err := tx.Query(ctx, `SELECT u.id, COALESCE(u.active_role, ''), COALESCE(u.roles, '{}'), COALESCE(sp.id, '')
FROM "user" u LEFT JOIN staff_profile sp ON sp.user_id = u.id
WHERE $1 = ANY(u.roles) AND u.is_active ORDER BY u.created_at DESC`, rules.LeadRole)
	if err != nil {
		return 0, fmt.Errorf("plreview: reading the Programme Leads: %w", err)
	}
	var leads []auth.Principal
	for rows.Next() {
		var p auth.Principal
		if err := rows.Scan(&p.UserID, &p.ActiveRole, &p.Roles, &p.StaffProfileID); err != nil {
			rows.Close()
			return 0, err
		}
		leads = append(leads, p)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	s := &Service{db: tx, now: func() time.Time { return now }}
	sent := 0
	for _, lead := range leads {
		waiting, err := s.queue(ctx, lead)
		if err != nil {
			return sent, err
		}
		if _, err := tx.Exec(ctx, `SELECT gateway_notifications.close_stale_notices_for($1, $2, $3, $4)`,
			lead.UserID, verifyReminderEvent, key, now); err != nil {
			return sent, fmt.Errorf("plreview: closing the earlier reminder: %w", err)
		}
		if len(waiting) == 0 {
			continue
		}
		var told bool
		if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM notification WHERE recipient_id = $1 AND source_event_type = $2
  AND context_id = $3)`, lead.UserID, verifyReminderEvent, key).Scan(&told); err != nil {
			return sent, fmt.Errorf("plreview: reading whether tonight's reminder was sent: %w", err)
		}
		if told {
			continue
		}
		owners := make([]string, 0, len(waiting))
		for _, c := range waiting {
			owners = append(owners, c.Owner)
		}
		body, err := reminderBody(ctx, s, owners)
		if err != nil {
			return sent, err
		}
		count := len(owners)
		noun := "activities"
		if count == 1 {
			noun = "activity"
		}
		if _, err := activities.NotifyInTx(ctx, tx, push, logger, now, key, activities.Notice{
			Title: fmt.Sprintf("Verify %d completed %s before the day ends", count, noun), Body: body,
			Event: verifyReminderEvent, Category: "activity", ContextType: "completion_reviews", Priority: "high",
		}, []activities.NoticeTo{{UserID: lead.UserID, Route: "/pl/review-queue", Label: "Verify Completions"}}); err != nil {
			return sent, err
		}
		sent++
	}
	return sent, nil
}

// reminderBody is _body: the count, and the officers it is from, most first.
func reminderBody(ctx context.Context, s *Service, owners []string) (string, error) {
	names, profileOf, err := s.people(ctx, owners)
	if err != nil {
		return "", err
	}
	type tally struct {
		name string
		n    int
	}
	var order []string
	counts := map[string]int{}
	for _, owner := range owners {
		who := owner
		if p, ok := profileOf[owner]; ok {
			who = p
		}
		if _, seen := counts[who]; !seen {
			order = append(order, who)
		}
		counts[who]++
	}
	var byOfficer []tally
	for _, who := range order {
		name := names[who]
		if name == "" {
			name = "an unnamed officer"
		}
		byOfficer = append(byOfficer, tally{name: name, n: counts[who]})
	}
	sort.SliceStable(byOfficer, func(i, j int) bool {
		if byOfficer[i].n != byOfficer[j].n {
			return byOfficer[i].n > byOfficer[j].n
		}
		return strings.ToLower(byOfficer[i].name) < strings.ToLower(byOfficer[j].name)
	})
	parts := make([]string, 0, verifyNamed)
	for i, t := range byOfficer {
		if i == verifyNamed {
			break
		}
		parts = append(parts, fmt.Sprintf("%d from %s", t.n, t.name))
	}
	named := strings.Join(parts, ", ")
	if more := len(byOfficer) - verifyNamed; more > 0 {
		plural := "s"
		if more == 1 {
			plural = ""
		}
		named += fmt.Sprintf(" and %d more officer%s", more, plural)
	}
	count := len(owners)
	verb := "activities are"
	if count == 1 {
		verb = "activity is"
	}
	return fmt.Sprintf("%d completed %s waiting for you to verify (%s). Check each visit ID or training ID, "+
		"then mark it Verified or Return it with the reason.", count, verb, named), nil
}
