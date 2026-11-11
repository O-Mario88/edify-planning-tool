package clusterlead

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The Cluster Action Register's follow-up (owner brief, 2026-11-11, part 8):
// unanswered requests are reminded about, support that is recorded or
// verified is reported to the leader, and an action long past its target is
// escalated one step up the reporting line, by the configured policy. Every
// notice is written once per event and recipient (its dedup key), and a
// relay delivers it into Edify's own notifications, retrying; delivery never
// decides the business event.

const (
	followUpBatch     = 200
	noticeBatch       = 100
	maxNoticeAttempts = 8
)

// FollowUp runs one pass of the follow-up rules; it returns how many writes
// it made.
func (s *ActionService) FollowUp(ctx context.Context) (int, error) {
	actions, err := s.store.FollowUpCandidates(ctx, followUpBatch)
	if err != nil {
		return 0, err
	}
	today := s.ops.today()
	system := actionViewer{principal: auth.Principal{Account: auth.Account{ActiveRole: "system"}}}
	writes := 0
	for _, a := range actions {
		escalated := false
		for _, r := range a.Schools {
			p := s.progressOf(r)
			recipient := firstNonEmpty(r.ResponsibleUserID, r.SupervisorUserID)
			write := ActionWrite{ActorID: "system", ActorRole: "system"}
			// Unanswered: remind the person it is routed to.
			if r.Status == schoolAwaiting && recipient != "" && a.SubmittedAt != nil &&
				daysBetween(*a.SubmittedAt, s.ops.now()) >= s.config.RemindAfterDays &&
				(r.ReminderAt == nil || daysBetween(*r.ReminderAt, s.ops.now()) >= s.config.RemindAfterDays) {
				write.Events = append(write.Events, ActionEventRecord{Event: "reminded", School: r.SchoolID})
				write.Notices = append(write.Notices, NoticeRecord{RecipientUserID: recipient, Event: "cluster_action_reminder",
					Title: "Reminder: Cluster Support Request waiting", TargetRoute: "/clusters/" + a.ClusterID,
					Body: fmt.Sprintf("%s for %s (%s) has waited %d days for your review.", supportWords(a), r.Name, a.Ref,
						daysBetween(*a.SubmittedAt, s.ops.now())),
					DedupKey: fmt.Sprintf("remind:%s:%s:%s", a.ID, r.SchoolID, today.Format(isoDate))})
				if err := s.store.MarkReminded(ctx, a.ID, r.SchoolID, write); err != nil {
					return writes, err
				}
				writes++
				continue
			}
			// Results the leader should review.
			var notices []NoticeRecord
			switch p {
			case progressImplemented:
				notices, err = s.leaderNotices(ctx, a, "cluster_action_implemented", "Support recorded — awaiting verification",
					fmt.Sprintf("The support for %s (%s) has been recorded; verification is still to come.", r.Name, a.Ref),
					fmt.Sprintf("implemented:%s:%s:%s", a.ID, r.SchoolID, r.ActivityID), "")
			case progressVerified:
				notices, err = s.leaderNotices(ctx, a, "cluster_action_verified", "Support verified",
					fmt.Sprintf("The support for %s (%s) is verified. Review it at your next meeting.", r.Name, a.Ref),
					fmt.Sprintf("verified:%s:%s:%s", a.ID, r.SchoolID, r.ActivityID), "")
			}
			if err != nil {
				return writes, err
			}
			// Past its target: tell the owner once, and the leader.
			if a.TargetOn.Before(today) && !finished(p) && recipient != "" {
				notices = append(notices, NoticeRecord{RecipientUserID: recipient, Event: "cluster_action_overdue",
					Title: "Cluster Support Request overdue", TargetRoute: "/clusters/" + a.ClusterID,
					Body:     fmt.Sprintf("%s for %s (%s) passed its target date of %s.", supportWords(a), r.Name, a.Ref, a.TargetOn.Format("2 Jan 2006")),
					DedupKey: fmt.Sprintf("overdue:%s:%s", a.ID, r.SchoolID)})
			}
			if len(notices) > 0 {
				if err := s.store.QueueNotices(ctx, a.ID, ActionWrite{ActorID: "system", ActorRole: "system", Notices: notices}); err != nil {
					return writes, err
				}
				writes++
			}
			// Long past its target and never escalated: one step up, by policy.
			if !escalated && s.config.EscalateAfterDays > 0 && !finished(p) && r.EscalatedAt == nil &&
				daysBetween(a.TargetOn, today) >= s.config.EscalateAfterDays {
				err := s.escalate(ctx, a, system, "", fmt.Sprintf("%d days past its target date with support not yet verified.",
					daysBetween(a.TargetOn, today)), "policy")
				if err != nil && !strings.Contains(err.Error(), "No supervisor") {
					return writes, err
				}
				escalated = true
				writes++
			}
		}
	}
	return writes, nil
}

// NoticeSender delivers one notice into Edify's notifications.
type NoticeSender interface {
	Send(ctx context.Context, n NoticeRecord, contextRef string) error
}

// ErrNoticesNotConfigured: no internal key or existing application is set,
// so notices stay queued.
var ErrNoticesNotConfigured = errors.New("clusterlead: notice delivery is not configured")

// HTTPNoticeSender posts notices to the existing application's internal
// endpoint (apps/notifications/cluster_action_relay.py) with the shared key.
type HTTPNoticeSender struct {
	base, key string
	http      *http.Client
}

// NewHTTPNoticeSender returns a sender, or nil when it is not configured.
func NewHTTPNoticeSender(base, key string) NoticeSender {
	if strings.TrimSpace(base) == "" || strings.TrimSpace(key) == "" {
		return nil
	}
	return &HTTPNoticeSender{base: strings.TrimRight(base, "/"), key: key, http: &http.Client{Timeout: 15 * time.Second}}
}

// Send delivers one notice.
func (h *HTTPNoticeSender) Send(ctx context.Context, n NoticeRecord, contextRef string) error {
	payload, err := json.Marshal(map[string]string{
		"noticeId": n.ID, "recipientId": n.RecipientUserID, "senderId": n.SenderUserID, "event": n.Event,
		"title": n.Title, "body": n.Body, "targetRoute": n.TargetRoute, "contextRef": contextRef,
	})
	if err != nil {
		return err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, h.base+"/api/notifications/internal/cluster-action-notices", bytes.NewReader(payload))
	if err != nil {
		return err
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Edify-Internal-Key", h.key)
	response, err := h.http.Do(request)
	if err != nil {
		return err
	}
	defer func() { _ = response.Body.Close() }()
	raw, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
	if response.StatusCode >= 300 {
		return fmt.Errorf("status %d: %s", response.StatusCode, strings.TrimSpace(string(raw)))
	}
	return nil
}

// RelayNotices delivers pending notices; it returns how many were sent.
func (s *ActionService) RelayNotices(ctx context.Context, sender NoticeSender) (int, error) {
	if sender == nil {
		return 0, ErrNoticesNotConfigured
	}
	notices, err := s.store.PendingNotices(ctx, maxNoticeAttempts, noticeBatch)
	if err != nil {
		return 0, err
	}
	sent := 0
	refs := map[string]string{}
	for _, n := range notices {
		ref, ok := refs[n.ActionID]
		if !ok {
			a, err := s.store.Action(ctx, n.ActionID)
			if err != nil {
				return sent, err
			}
			ref, refs[n.ActionID] = a.Ref, a.Ref
		}
		deliveryErr := sender.Send(ctx, n, ref)
		if err := s.store.NoticeDelivered(ctx, n.ID, deliveryErr); err != nil {
			return sent, err
		}
		if deliveryErr == nil {
			sent++
		}
	}
	return sent, nil
}

// RunFollowUp relays notices every minute and runs the follow-up rules every
// interval, until ctx ends. ready says whether the schema is in place.
func (s *ActionService) RunFollowUp(ctx context.Context, sender NoticeSender, interval time.Duration,
	ready func(context.Context) error, logger *slog.Logger) {
	relay := time.NewTicker(time.Minute)
	rules := time.NewTicker(interval)
	defer relay.Stop()
	defer rules.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-rules.C:
			if ready != nil && ready(ctx) != nil {
				continue
			}
			if n, err := s.FollowUp(ctx); err != nil {
				logger.Error("cluster actions: follow-up failed", slog.String("error", err.Error()))
			} else if n > 0 {
				logger.Info("cluster actions: follow-up", slog.Int("writes", n))
			}
		case <-relay.C:
			if sender == nil || (ready != nil && ready(ctx) != nil) {
				continue
			}
			if n, err := s.RelayNotices(ctx, sender); err != nil {
				logger.Error("cluster actions: notice relay failed", slog.String("error", err.Error()))
			} else if n > 0 {
				logger.Info("cluster actions: notices delivered", slog.Int("sent", n))
			}
		}
	}
}
