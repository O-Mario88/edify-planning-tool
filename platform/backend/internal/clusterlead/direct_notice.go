package clusterlead

import (
	"context"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
)

// DirectNoticeSender delivers Cluster Action notices directly to
// public.notification via gateway_notifications.deliver (M11), eliminating
// the Django HTTP relay (apps/notifications/cluster_action_relay.py).
type DirectNoticeSender struct {
	writer *notificationcenter.Writer
}

// NewDirectNoticeSender returns a NoticeSender backed directly by Postgres.
func NewDirectNoticeSender(pool *pgxpool.Pool) *DirectNoticeSender {
	return &DirectNoticeSender{writer: notificationcenter.NewWriter(pool, time.Now)}
}

// Send writes one Cluster Action notice idempotently without calling Django.
func (s *DirectNoticeSender) Send(ctx context.Context, n NoticeRecord, contextRef string) error {
	sourceID := strings.ReplaceAll(n.ID, "-", "")
	if len(sourceID) > 30 {
		sourceID = sourceID[:30]
	}
	_, err := s.writer.Deliver(ctx, notificationcenter.Delivery{
		RecipientID:     n.RecipientUserID,
		SenderID:        n.SenderUserID,
		Title:           n.Title,
		Body:            n.Body,
		Category:        "cluster_support",
		ContextType:     "cluster_action",
		ContextID:       contextRef,
		TargetRoute:     n.TargetRoute,
		ActionLabel:     "Open cluster",
		ActionRequired:  true,
		Priority:        "normal",
		SourceEventType: n.Event,
		SourceEventID:   sourceID,
	})
	return err
}
