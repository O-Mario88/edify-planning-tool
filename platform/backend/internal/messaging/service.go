package messaging

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"connectrpc.com/connect"

	messagingv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/messaging/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/messaging/v1/messagingv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Service answers MessagingService.
type Service struct {
	db     schooldirectory.Querier
	now    func() time.Time
	logger *slog.Logger
}

var _ messagingv1connect.MessagingServiceHandler = (*Service)(nil)

// NewService returns the inbox over db.
func NewService(db schooldirectory.Querier, now func() time.Time, logger *slog.Logger) *Service {
	if now == nil {
		now = time.Now
	}
	return &Service{db: db, now: now, logger: logger}
}

// ListThreads is the inbox's list for the signed-in reader.
func (s *Service) ListThreads(ctx context.Context, request *connect.Request[messagingv1.ListThreadsRequest]) (*connect.Response[messagingv1.ListThreadsResponse], error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return nil, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "Sign in to continue.")
	}
	m := request.Msg
	answer, err := Inbox(ctx, s.db, p, Query{Tab: m.GetTab(), Q: m.GetQ(), Sort: m.GetSort(), Page: m.GetPage(), Thread: m.GetThread()}, s.now())
	if err != nil {
		return nil, s.refusal(ctx, err)
	}
	return connect.NewResponse(answer), nil
}

// GetUnreadCount is the top bar's Messages badge.
func (s *Service) GetUnreadCount(ctx context.Context, _ *connect.Request[messagingv1.GetUnreadCountRequest]) (*connect.Response[messagingv1.GetUnreadCountResponse], error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return nil, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "Sign in to continue.")
	}
	n, err := UnreadCount(ctx, s.db, p)
	if err != nil {
		return nil, s.refusal(ctx, err)
	}
	return connect.NewResponse(&messagingv1.GetUnreadCountResponse{Unread: int32(n)}), nil
}

// refusal is the error the web reads: not the reader's page (the existing
// page's 404), handed on to the existing application, or a failure.
func (s *Service) refusal(ctx context.Context, err error) error {
	switch {
	case errors.Is(err, pagegate.ErrNotAvailable):
		return apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "This was not found, or it is not yours to view.")
	case errors.Is(err, ErrHandOn):
		return apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable, "Messages open in the existing application for now.")
	}
	return apierr.Internal(ctx, s.logger, err)
}
