package notificationcenter

import "context"

// UnreadCount is the bell's figure (apps.core.context_processors.sidebar_counts):
// the reader's notifications still unread, less the resolved ones, which are
// history and the drawer does not show.
func (s *Service) UnreadCount(ctx context.Context, userID string) (int32, error) {
	var unread int32
	err := s.db.QueryRow(ctx, `
SELECT COUNT(*) FROM notification
 WHERE recipient_id = $1 AND status = 'unread' AND resolved_at IS NULL`, userID).Scan(&unread)
	return unread, err
}
