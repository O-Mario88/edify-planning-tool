package pushdelivery

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerassigned"
)

const (
	// freshFor is FRESH_FOR: a notice older than a day is history.
	freshFor = 24 * time.Hour
	// maxAttempts is MAX_ATTEMPTS: tries before a copy is given up.
	maxAttempts = 6

	statusSending   = "sending"
	statusRetry     = "retry_scheduled"
	statusAccepted  = "accepted"
	statusFailed    = "failed"
	statusSkipped   = "skipped"
	statusSupressed = "suppressed"
)

// sendable are _SENDABLE.
var sendable = []string{"queued", statusRetry, statusSending}

// Senders are the services this deployment can push through; a nil one is
// not set up here.
type Senders struct {
	Web  *Web
	FCM  *FCM
	APNs *APNs
}

// SendersFrom reads the existing application's settings from the
// environment. WEBPUSH_EXTRA_HOSTS is no setting there, so no extra push
// service is allowed.
func SendersFrom(getenv func(string) string, readFile func(string) ([]byte, error)) Senders {
	client := &http.Client{Timeout: 10 * time.Second, CheckRedirect: NoRedirects}
	subject := getenv("WEBPUSH_SUBJECT")
	if subject == "" {
		subject = "mailto:admin@edifyplanning.app"
	}
	account := strings.TrimSpace(getenv("FCM_SERVICE_ACCOUNT_JSON"))
	if path := strings.TrimSpace(getenv("FCM_SERVICE_ACCOUNT_FILE")); account == "" && path != "" {
		if raw, err := readFile(path); err == nil {
			account = string(raw)
		}
	}
	topic := strings.TrimSpace(getenv("APNS_TOPIC"))
	if topic == "" {
		topic = "app.edifyplanning.mobile"
	}
	environment := strings.TrimSpace(getenv("APNS_ENVIRONMENT"))
	if environment == "" {
		environment = "production"
	}
	return Senders{
		Web: NewWeb(WebConfig{PublicKey: strings.TrimSpace(getenv("WEBPUSH_VAPID_PUBLIC_KEY")),
			PrivateKey: strings.TrimSpace(getenv("WEBPUSH_VAPID_PRIVATE_KEY")), Subject: subject}, client),
		FCM: NewFCM(account, client),
		APNs: NewAPNs(strings.TrimSpace(getenv("APNS_KEY_ID")), strings.TrimSpace(getenv("APNS_TEAM_ID")),
			strings.TrimSpace(getenv("APNS_PRIVATE_KEY")), topic, environment, client),
	}
}

// SendersFromEnv is SendersFrom over the process environment.
func SendersFromEnv() Senders { return SendersFrom(os.Getenv, os.ReadFile) }

// throughApple is _through_apple: an iPhone that gave Apple's own token.
func throughApple(kind, endpoint string) bool { return kind == "ios" && validAPNsToken(endpoint) }

// ready is ready(): this kind of device can be sent to here, and for an
// iPhone, through the service its token belongs to.
func (s Senders) ready(kind, endpoint string) bool {
	switch kind {
	case "web":
		return s.Web != nil
	case "android":
		return s.FCM != nil
	case "ios":
		if throughApple(kind, endpoint) {
			return s.APNs != nil
		}
		return s.FCM != nil
	}
	return false
}

type pushNotice struct {
	notice
	recipient, status, route string
	resolved                 bool
	reminders                int
}

type subscription struct {
	id, user, kind, endpoint, p256dh, auth string
	revoked                                bool
	failures                               int
}

type delivery struct {
	id, status string
	attempts   int
}

// Handler is handle_push.
type Handler struct {
	Senders Senders
}

// Handle is one notification.push event, outside any transaction.
func (h Handler) Handle(ctx context.Context, pool *pgxpool.Pool, payload map[string]any, now time.Time) error {
	notificationID, _ := payload["notificationId"].(string)
	subscriptionID, _ := payload["subscriptionId"].(string)
	n, found, err := readNotice(ctx, pool, notificationID)
	if err != nil || !found {
		return err
	}
	s, found, err := readSubscription(ctx, pool, subscriptionID)
	if err != nil || !found {
		return err
	}
	round := n.reminders
	if raw, ok := payload["round"]; ok {
		if v, ok := raw.(float64); ok {
			round = int(v)
		}
	}
	d, err := readDelivery(ctx, pool, n.id, round, s.id)
	if err != nil {
		return err
	}
	if d != nil && !contains(sendable, d.status) {
		return nil
	}
	status, why, err := h.whyNot(ctx, pool, n, s, now)
	if err != nil {
		return err
	}
	if status != "" {
		return record(ctx, pool, d, status, now, fields{lastError: &why})
	}
	attempts := 1
	if d != nil {
		attempts = d.attempts + 1
	}
	if err := record(ctx, pool, d, statusSending, now, fields{attempts: &attempts}); err != nil {
		return err
	}
	messageID, err := h.send(ctx, n, s, now)
	return h.outcome(ctx, pool, d, s, attempts, messageID, err, now)
}

// outcome is handle_push's except clauses and else.
func (h Handler) outcome(ctx context.Context, pool *pgxpool.Pool, d *delivery, s subscription, attempts int, messageID string,
	sendErr error, now time.Time) error {
	detail := ""
	if sendErr != nil {
		detail = sendErr.Error()
	}
	switch {
	case sendErr == nil:
		if _, err := write(ctx, pool, `UPDATE notification_push_subscription SET last_success_at = $2, failure_count = 0,
  last_error = '' WHERE id = $1`, s.id, now); err != nil {
			return fmt.Errorf("pushdelivery: recording the device's success: %w", err)
		}
		empty := ""
		id := cut(messageID, 128)
		return record(ctx, pool, d, statusAccepted, now, fields{providerID: &id, sentAt: &now, lastError: &empty})
	case errors.Is(sendErr, ErrGone):
		if _, err := write(ctx, pool, `UPDATE notification_push_subscription SET revoked_at = $2, revoked_reason = 'gone',
  last_error = $3 WHERE id = $1`, s.id, now, cut(detail, 255)); err != nil {
			return fmt.Errorf("pushdelivery: forgetting the device: %w", err)
		}
		why := "Device gone: " + detail
		return record(ctx, pool, d, statusFailed, now, fields{lastError: &why})
	case errors.Is(sendErr, ErrRejected):
		if _, err := write(ctx, pool, `UPDATE notification_push_subscription SET failure_count = $2, last_error = $3 WHERE id = $1`,
			s.id, s.failures+1, cut(detail, 255)); err != nil {
			return fmt.Errorf("pushdelivery: recording the refusal: %w", err)
		}
		return record(ctx, pool, d, statusFailed, now, fields{lastError: &detail})
	case errors.Is(sendErr, ErrUnavailable):
		if attempts < maxAttempts {
			if err := record(ctx, pool, d, statusRetry, now, fields{lastError: &detail}); err != nil {
				return err
			}
			return sendErr // the outbox tries again with backoff
		}
		return record(ctx, pool, d, statusFailed, now, fields{lastError: &detail})
	}
	return sendErr
}

// send is _send: one message to one device; the provider's message id.
func (h Handler) send(ctx context.Context, n pushNotice, s subscription, now time.Time) (string, error) {
	urgent := n.priority == "high" || n.priority == "urgent"
	payload := payloadFor(n.notice)
	if s.kind == "web" {
		urgency := "normal"
		if urgent {
			urgency = "high"
		}
		if h.Senders.Web == nil {
			return "", rejected("Web Push is not configured on this deployment.")
		}
		return "", h.Senders.Web.Send(ctx, s.endpoint, s.p256dh, s.auth, payload, freshFor, urgency, n.id, now)
	}
	if throughApple(s.kind, s.endpoint) {
		if h.Senders.APNs == nil {
			return "", rejected("APNs is not configured on this deployment.")
		}
		return "", h.Senders.APNs.Send(ctx, s.endpoint, payload, n.priority, n.id, freshFor, now)
	}
	if h.Senders.FCM == nil {
		return "", rejected("App push is not configured on this deployment.")
	}
	return h.Senders.FCM.Send(ctx, s.endpoint, payload, freshFor, urgent, n.id, now)
}

// whyNot is _why_not: the status and sentence of a copy that must not be
// sent now, or "" when it may be.
func (h Handler) whyNot(ctx context.Context, pool *pgxpool.Pool, n pushNotice, s subscription, now time.Time) (string, string, error) {
	switch {
	case s.revoked:
		return statusSkipped, "The device was turned off before it was sent.", nil
	case s.user != n.recipient:
		return statusSkipped, "Someone else has since signed in on the device.", nil
	case n.status != "unread" || n.resolved:
		return statusSkipped, "Read in the app, or the work was done, before it was sent.", nil
	case n.told.Before(now.Add(-freshFor)):
		return statusSkipped, "More than a day old by the time it could be sent.", nil
	case !h.Senders.ready(s.kind, s.endpoint):
		return statusSkipped, "Push to this kind of device is not set up here.", nil
	}
	var active bool
	var p auth.Principal
	err := pool.QueryRow(ctx, `SELECT is_active AND deleted_at IS NULL, COALESCE(active_role, ''), roles FROM "user" WHERE id = $1`,
		n.recipient).Scan(&active, &p.ActiveRole, &p.Roles)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && !active) {
		return statusSkipped, "The recipient's account is no longer active.", nil
	}
	if err != nil {
		return "", "", fmt.Errorf("pushdelivery: reading the recipient: %w", err)
	}
	p.UserID = n.recipient
	if n.route != "" {
		member := false
		if p.ActiveRole == "PartnerAdmin" || p.ActiveRole == "PartnerFieldOfficer" {
			if member, err = partnerassigned.IsTeamMember(ctx, pool, p); err != nil {
				return "", "", fmt.Errorf("pushdelivery: reading whether the recipient is a team member: %w", err)
			}
		}
		if !pageaccess.CanOpen(p.ActiveRole, member, n.route) {
			return statusSkipped, "The recipient's role cannot open what it is about.", nil
		}
	}
	if n.priority != "urgent" {
		var off bool
		if err := pool.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM notification_preference WHERE user_id = $1 AND NOT push_enabled)`,
			n.recipient).Scan(&off); err != nil {
			return "", "", fmt.Errorf("pushdelivery: reading the recipient's push setting: %w", err)
		}
		if off {
			return statusSupressed, "Turned off by the recipient.", nil
		}
	}
	return "", "", nil
}

func readNotice(ctx context.Context, pool *pgxpool.Pool, id string) (pushNotice, bool, error) {
	var n pushNotice
	var created time.Time
	var reminded *time.Time
	err := pool.QueryRow(ctx, `SELECT id, recipient_id, COALESCE(status, ''), resolved_at IS NOT NULL, created_at, last_reminded_at,
  COALESCE(priority, ''), COALESCE(title, ''), COALESCE(body, ''), COALESCE(category, ''), COALESCE(target_route, ''),
  COALESCE(reminder_count, 0)
FROM notification WHERE id = $1`, id).Scan(&n.id, &n.recipient, &n.status, &n.resolved, &created, &reminded, &n.priority,
		&n.title, &n.body, &n.category, &n.route, &n.reminders)
	if errors.Is(err, pgx.ErrNoRows) {
		return n, false, nil
	}
	if err != nil {
		return n, false, fmt.Errorf("pushdelivery: reading the notification: %w", err)
	}
	n.told = created
	if reminded != nil {
		n.told = *reminded
	}
	return n, true, nil
}

func readSubscription(ctx context.Context, pool *pgxpool.Pool, id string) (subscription, bool, error) {
	var s subscription
	err := pool.QueryRow(ctx, `SELECT id, user_id, COALESCE(kind, ''), COALESCE(endpoint, ''), COALESCE(p256dh, ''),
  COALESCE(auth, ''), revoked_at IS NOT NULL, COALESCE(failure_count, 0)
FROM notification_push_subscription WHERE id = $1`, id).Scan(&s.id, &s.user, &s.kind, &s.endpoint, &s.p256dh, &s.auth,
		&s.revoked, &s.failures)
	if errors.Is(err, pgx.ErrNoRows) {
		return s, false, nil
	}
	if err != nil {
		return s, false, fmt.Errorf("pushdelivery: reading the device: %w", err)
	}
	return s, true, nil
}

func readDelivery(ctx context.Context, pool *pgxpool.Pool, notificationID string, round int, target string) (*delivery, error) {
	var d delivery
	err := pool.QueryRow(ctx, `SELECT id, status, attempts FROM notification_delivery
WHERE notification_id = $1 AND channel = 'push' AND round = $2 AND target = $3`,
		notificationID, round, target).Scan(&d.id, &d.status, &d.attempts)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("pushdelivery: reading the copy: %w", err)
	}
	return &d, nil
}

// fields are what _record moves on besides the status.
type fields struct {
	attempts   *int
	lastError  *string
	providerID *string
	sentAt     *time.Time
}

// record is _record: a copy's status, nothing for an event queued before
// copies were kept.
func record(ctx context.Context, pool *pgxpool.Pool, d *delivery, status string, now time.Time, f fields) error {
	if d == nil {
		return nil
	}
	var failedAt *time.Time
	if status == statusFailed {
		failedAt = &now
	}
	var lastError *string
	if f.lastError != nil {
		trimmed := cut(*f.lastError, 255)
		lastError = &trimmed
	}
	if _, err := write(ctx, pool, `UPDATE notification_delivery SET status = $2, updated_at = $3,
  attempts = COALESCE($4, attempts), last_error = COALESCE($5, last_error),
  provider_message_id = COALESCE($6, provider_message_id), sent_at = COALESCE($7, sent_at),
  failed_at = COALESCE($8, failed_at)
WHERE id = $1`, d.id, status, now, f.attempts, lastError, f.providerID, f.sentAt, failedAt); err != nil {
		return fmt.Errorf("pushdelivery: recording the copy: %w", err)
	}
	return nil
}

// cut is Python's [:n] of a string.
func cut(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n])
	}
	return s
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

// write is one statement in a read-write transaction of its own: the
// gateway's sessions are read-only unless a transaction says otherwise.
func write(ctx context.Context, pool *pgxpool.Pool, sql string, args ...any) (struct{}, error) {
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return struct{}{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, sql, args...); err != nil {
		return struct{}{}, err
	}
	return struct{}{}, tx.Commit(ctx)
}
