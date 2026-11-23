package plreview

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// appleToken is apps.notifications.apns._TOKEN: a raw APNs device token.
var appleToken = regexp.MustCompile(`^[0-9a-fA-F]{64,200}$`)

// PushReadiness is which push services this deployment holds keys for
// (apps.notifications.push.ready_kinds), read from the same settings.
type PushReadiness struct {
	Web, FCM, APNS bool
}

// reaches is push.ready for one device.
func (r PushReadiness) reaches(kind, endpoint string) bool {
	switch kind {
	case "web":
		return r.Web
	case "android":
		return r.FCM
	case "ios":
		if appleToken.MatchString(endpoint) {
			return r.APNS
		}
		return r.FCM
	}
	return false
}

// PushReadinessFrom reads the settings the existing application reads. Only
// whether each key is usable is kept; no key is held.
func PushReadinessFrom(getenv func(string) string, readFile func(string) ([]byte, error)) PushReadiness {
	present := func(names ...string) bool {
		for _, name := range names {
			if strings.TrimSpace(getenv(name)) == "" {
				return false
			}
		}
		return true
	}
	account := strings.TrimSpace(getenv("FCM_SERVICE_ACCOUNT_JSON"))
	if path := strings.TrimSpace(getenv("FCM_SERVICE_ACCOUNT_FILE")); account == "" && path != "" {
		if raw, err := readFile(path); err == nil {
			account = string(raw)
		}
	}
	return PushReadiness{
		Web:  present("WEBPUSH_VAPID_PUBLIC_KEY", "WEBPUSH_VAPID_PRIVATE_KEY"),
		FCM:  usableFirebaseAccount(account),
		APNS: present("APNS_KEY_ID", "APNS_TEAM_ID", "APNS_PRIVATE_KEY"),
	}
}

// usableFirebaseAccount is fcm._parse: JSON, or base64 of it, naming the
// project, the client and the key.
func usableFirebaseAccount(raw string) bool {
	text := strings.TrimSpace(raw)
	if text == "" {
		return false
	}
	if !strings.HasPrefix(text, "{") {
		decoded, err := base64.StdEncoding.DecodeString(text)
		if err != nil {
			return false
		}
		text = string(decoded)
	}
	var account map[string]any
	if err := json.Unmarshal([]byte(text), &account); err != nil {
		return false
	}
	for _, field := range []string{"project_id", "client_email", "private_key"} {
		value, ok := account[field].(string)
		if !ok || strings.TrimSpace(value) == "" {
			return false
		}
	}
	return true
}

// queuePush is push.enqueue for a notice raised or brought back: a delivery
// row and a durable event per device. It runs in a savepoint of its own, so a
// phone copy never undoes the notice.
func (s *ReviewService) queuePush(ctx context.Context, tx pgx.Tx, notificationID, recipient string, now time.Time) error {
	return s.push.QueueCopy(ctx, tx, notificationID, recipient, now)
}

// QueueCopy queues a notice's phone copy for each of the recipient's devices
// this deployment can reach.
func (r PushReadiness) QueueCopy(ctx context.Context, tx pgx.Tx, notificationID, recipient string, now time.Time) error {
	if r == (PushReadiness{}) {
		return nil
	}
	savepoint, err := tx.Begin(ctx)
	if err != nil {
		return fmt.Errorf("opening the phone copy's savepoint: %w", err)
	}
	defer func() { _ = savepoint.Rollback(ctx) }()
	rows, err := savepoint.Query(ctx, `SELECT id, kind, endpoint FROM notification_push_subscription
 WHERE user_id = $1 AND revoked_at IS NULL ORDER BY id`, recipient)
	if err != nil {
		return fmt.Errorf("reading the officer's devices: %w", err)
	}
	type device struct{ id, kind, endpoint string }
	devices, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (device, error) {
		var d device
		err := row.Scan(&d.id, &d.kind, &d.endpoint)
		return d, err
	})
	if err != nil {
		return fmt.Errorf("reading a device: %w", err)
	}
	for _, d := range devices {
		if !r.reaches(d.kind, d.endpoint) {
			continue
		}
		if _, err := savepoint.Exec(ctx, `SELECT gateway_notifications.queue_push_copy($1, $2, $3, $4, $5)`,
			cuid.New(), cuid.New(), notificationID, d.id, now); err != nil {
			return fmt.Errorf("queueing the phone copy: %w", err)
		}
	}
	return savepoint.Commit(ctx)
}
