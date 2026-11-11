package acting

import (
	"context"
	"errors"
	"log/slog"

	"connectrpc.com/connect"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Handler serves ActingLeadershipService. Every procedure is open to
// whoever is signed in, including someone working in an acting capacity:
// the rules decide what each may read and do, and an acting capacity
// appoints, changes and cancels nothing.
type Handler struct {
	service *Service
	logger  *slog.Logger
}

// NewHandler returns the Connect handler.
func NewHandler(service *Service, logger *slog.Logger) *Handler {
	return &Handler{service: service, logger: logger}
}

func caller(ctx context.Context) (auth.Principal, error) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return auth.Principal{}, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "Sign in to continue.")
	}
	return principal, nil
}

func (h *Handler) fail(ctx context.Context, err error) error {
	var refused *Refused
	if errors.As(err, &refused) {
		switch {
		case refused.NotFound:
			return apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, refused.Message)
		case refused.Forbidden:
			return apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied, refused.Message)
		case refused.Conflict:
			return apierr.New(ctx, connect.CodeAlreadyExists, apierr.ReasonInvalidArgument, refused.Message)
		}
		return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, refused.Message)
	}
	return apierr.Internal(ctx, h.logger, err)
}

// GetActingBoard implements ActingLeadershipService.
func (h *Handler) GetActingBoard(ctx context.Context, _ *connect.Request[identityv1.GetActingBoardRequest]) (*connect.Response[identityv1.GetActingBoardResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	board, err := h.service.Board(ctx, principal)
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.GetActingBoardResponse{
		Current: board.Current, Upcoming: board.Upcoming, History: board.History, CanAppointLabel: board.CanAppointLabel,
	}), nil
}

// GetAppointOptions implements ActingLeadershipService.
func (h *Handler) GetAppointOptions(ctx context.Context, _ *connect.Request[identityv1.GetAppointOptionsRequest]) (*connect.Response[identityv1.GetAppointOptionsResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	options, err := h.service.Options(ctx, principal)
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	response := &identityv1.GetAppointOptionsResponse{Label: options.Entry.Label, AppointeeRole: options.Entry.AppointeeRole}
	for _, c := range options.Candidates {
		response.Candidates = append(response.Candidates, &identityv1.ActingCandidate{StaffProfileId: c.StaffID, Name: c.Name, Email: c.Email})
	}
	for _, m := range options.Months {
		response.Months = append(response.Months, &identityv1.MonthChoice{Value: m.Value, Label: m.Label, EffectiveLabel: m.Effective})
	}
	return connect.NewResponse(response), nil
}

// PreviewAppointment implements ActingLeadershipService.
func (h *Handler) PreviewAppointment(ctx context.Context, req *connect.Request[identityv1.PreviewAppointmentRequest]) (*connect.Response[identityv1.PreviewAppointmentResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	preview, err := h.service.Preview(ctx, principal, req.Msg.GetAppointeeStaffId(), req.Msg.GetMonth())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.PreviewAppointmentResponse{
		AppointeeName: preview.AppointeeName, Label: preview.Entry.Label, MonthLabel: preview.MonthLabel,
		EffectiveLabel: preview.Effective, Statement: preview.Statement,
	}), nil
}

// Appoint implements ActingLeadershipService.
func (h *Handler) Appoint(ctx context.Context, req *connect.Request[identityv1.AppointRequest]) (*connect.Response[identityv1.AppointResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	appointment, err := h.service.Appoint(ctx, principal, req.Msg.GetAppointeeStaffId(), req.Msg.GetMonth())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.AppointResponse{Appointment: appointment}), nil
}

// ChangeMonth implements ActingLeadershipService.
func (h *Handler) ChangeMonth(ctx context.Context, req *connect.Request[identityv1.ChangeMonthRequest]) (*connect.Response[identityv1.ChangeMonthResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	appointment, err := h.service.ChangeMonth(ctx, principal, req.Msg.GetAppointmentId(), req.Msg.GetMonth())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.ChangeMonthResponse{Appointment: appointment}), nil
}

// CancelAppointment implements ActingLeadershipService.
func (h *Handler) CancelAppointment(ctx context.Context, req *connect.Request[identityv1.CancelAppointmentRequest]) (*connect.Response[identityv1.CancelAppointmentResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	appointment, err := h.service.Cancel(ctx, principal, req.Msg.GetAppointmentId(), req.Msg.GetReason())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.CancelAppointmentResponse{Appointment: appointment}), nil
}

// GetAppointment implements ActingLeadershipService.
func (h *Handler) GetAppointment(ctx context.Context, req *connect.Request[identityv1.GetAppointmentRequest]) (*connect.Response[identityv1.GetAppointmentResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	appointment, err := h.service.Get(ctx, principal, req.Msg.GetAppointmentId())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.GetAppointmentResponse{Appointment: appointment}), nil
}

// SetActingCapacity implements ActingLeadershipService.
func (h *Handler) SetActingCapacity(ctx context.Context, req *connect.Request[identityv1.SetActingCapacityRequest]) (*connect.Response[identityv1.SetActingCapacityResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	capacity, token, err := h.service.SetCapacity(ctx, principal, req.Msg.GetActing())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.SetActingCapacityResponse{Capacity: capacity, AccessToken: token}), nil
}
