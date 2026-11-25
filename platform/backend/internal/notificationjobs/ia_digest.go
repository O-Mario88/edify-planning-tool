package notificationjobs

// The ia_verification_digest job (apps.realtime.jobs._do_ia_verification_digest):
// one morning line per Impact Assessment officer of the work waiting for
// verification in their country, never their own, with how much is past the
// 24-hour SLA and how much is a partner's; and one per Country Director of
// the work IA officers ran themselves, which the Director verifies as
// fallback. Each person's line is sent once a day.

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pyhash"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

const (
	iaDigestEvent   = "ia_verification_digest"
	iaRole          = "ImpactAssessment"
	awaitingIA      = "awaiting_ia_verification"
	iaDigestSLA     = 24 * time.Hour
	iaDigestBody    = "Your morning verification digest."
	iaFallbackBody  = "Work Impact Assessment officers ran themselves, which you verify as fallback verifier."
	iaDigestIDBytes = 7
)

// iaDigestID is _ia_digest_id: the day and a short hash of the recipient.
func iaDigestID(today time.Time, recipient string) string {
	return "iad-" + today.Format(time.DateOnly) + "-" + pyhash.Blake2sHex([]byte(recipient), iaDigestIDBytes)
}

// roleHolder is one role_recipients row, as a principal its scope is resolved for.
type roleHolder struct{ auth.Principal }

// roleHolders is role_recipients(role): every live account holding it.
func roleHolders(ctx context.Context, tx pgx.Tx, role string) ([]roleHolder, error) {
	rows, err := tx.Query(ctx, `SELECT u.id, u.roles, COALESCE(u.active_role, ''), COALESCE(
  (SELECT sp.id FROM staff_profile sp WHERE sp.user_id = u.id LIMIT 1), '')
FROM "user" u WHERE u.roles @> ARRAY[$1::varchar] AND u.is_active AND u.deleted_at IS NULL ORDER BY u.created_at DESC`, role)
	if err != nil {
		return nil, fmt.Errorf("notificationjobs: reading the %s holders: %w", role, err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (roleHolder, error) {
		var h roleHolder
		err := row.Scan(&h.UserID, &h.Roles, &h.ActiveRole, &h.StaffProfileID)
		return h, err
	})
}

// waitingCounts is _send's aggregate over the waiting work.
type waitingCounts struct{ n, overdue, partner int }

// countWaiting counts the work awaiting verification in the scope's country,
// with extra narrowing it to the reader's share.
func countWaiting(ctx context.Context, tx pgx.Tx, scope schooldirectory.Scope, cutoff time.Time, extra string,
	extraArgs ...any) (waitingCounts, error) {
	args := []any{awaitingIA, cutoff}
	where := `a.deleted_at IS NULL AND a.status = $1`
	if scope.CountryScope && scope.Country != "" {
		args = append(args, scope.CountryIDs())
		where += " AND " + schoolprofile.ActivityInCountry(len(args))
	}
	for _, arg := range extraArgs {
		args = append(args, arg)
	}
	if extra != "" {
		where += " AND " + fmt.Sprintf(extra, len(args))
	}
	var c waitingCounts
	err := tx.QueryRow(ctx, `SELECT count(*)::int, count(*) FILTER (WHERE a.submitted_to_ia_at <= $2)::int,
  count(*) FILTER (WHERE a.delivery_type = 'partner')::int
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE `+where, args...).Scan(&c.n, &c.overdue, &c.partner)
	if err != nil {
		return c, fmt.Errorf("notificationjobs: counting the work awaiting verification: %w", err)
	}
	return c, nil
}

// SendIADigest says how many digests it sent.
func SendIADigest(ctx context.Context, tx pgx.Tx, now time.Time, kampala *time.Location, push activities.NoticePush) (int, error) {
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	cutoff := now.Add(-iaDigestSLA)
	sent := 0
	officers, err := roleHolders(ctx, tx, iaRole)
	if err != nil {
		return 0, err
	}
	for _, h := range officers {
		scope, err := schooldirectory.ResolveScope(ctx, tx, h.Principal, now)
		if err != nil {
			return sent, fmt.Errorf("notificationjobs: resolving %s's scope: %w", h.UserID, err)
		}
		own := []string{}
		for _, id := range []string{h.UserID, h.StaffProfileID} {
			if id != "" {
				own = append(own, id)
			}
		}
		counts, err := countWaiting(ctx, tx, scope, cutoff,
			"NOT (a.responsible_staff_id = ANY($%d) AND a.responsible_staff_id IS NOT NULL)", own)
		if err != nil {
			return sent, err
		}
		ok, err := sendIADigest(ctx, tx, push, now, today, h.UserID, counts, iaDigestBody, false)
		if err != nil {
			return sent, err
		}
		if ok {
			sent++
		}
	}
	directors, err := roleHolders(ctx, tx, countryDirector)
	if err != nil {
		return sent, err
	}
	for _, h := range directors {
		scope, err := schooldirectory.ResolveScope(ctx, tx, h.Principal, now)
		if err != nil {
			return sent, fmt.Errorf("notificationjobs: resolving %s's scope: %w", h.UserID, err)
		}
		officerWork := `a.responsible_staff_id IN (SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
  WHERE u.roles @> ARRAY['ImpactAssessment']::varchar[] AND sp.deleted_at IS NULL AND ($%[1]d = '' OR sp.country = $%[1]d))`
		country := ""
		if scope.Country != schooldirectory.NoCountry {
			country = scope.Country
		}
		counts, err := countWaiting(ctx, tx, scope, cutoff, officerWork, country)
		if err != nil {
			return sent, err
		}
		ok, err := sendIADigest(ctx, tx, push, now, today, h.UserID, counts, iaFallbackBody, true)
		if err != nil {
			return sent, err
		}
		if ok {
			sent++
		}
	}
	return sent, nil
}

// sendIADigest is _send: nothing when nothing waits or the line went today.
func sendIADigest(ctx context.Context, tx pgx.Tx, push activities.NoticePush, now, today time.Time, recipient string,
	c waitingCounts, body string, fallback bool) (bool, error) {
	if c.n == 0 {
		return false, nil
	}
	id := iaDigestID(today, recipient)
	var already bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM notification WHERE recipient_id = $1 AND source_event_id = $2)`,
		recipient, id).Scan(&already); err != nil {
		return false, fmt.Errorf("notificationjobs: reading today's digest: %w", err)
	}
	if already {
		return false, nil
	}
	title := fmt.Sprintf("%d waiting for verification", c.n)
	if fallback {
		title = fmt.Sprintf("%d IA officers' submissions waiting for you", c.n)
	}
	if c.overdue > 0 {
		title += fmt.Sprintf(" · %d past 24h", c.overdue)
	}
	if c.partner > 0 {
		title += fmt.Sprintf(" · %d from partners", c.partner)
	}
	priority := "normal"
	if c.overdue > 0 {
		priority = "high"
	}
	if _, err := activities.NotifyInTx(ctx, tx, push, slog.Default(), now, id, activities.Notice{
		Title: title, Body: body, Event: iaDigestEvent, Category: "verification", Priority: priority,
	}, []activities.NoticeTo{{UserID: recipient, Route: "/ia/verification/", Label: "Open Verification Queue"}}); err != nil {
		return false, fmt.Errorf("notificationjobs: sending the verification digest: %w", err)
	}
	return true, nil
}
