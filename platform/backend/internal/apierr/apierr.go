// Package apierr builds the structured errors the gateway returns. Every
// error carries a Connect/gRPC status code, a message safe to show a person,
// and an edify.common.v1.ErrorDetail with a stable reason code and the ids
// support needs to find the request.
package apierr

import (
	"context"
	"errors"
	"log/slog"

	"connectrpc.com/connect"

	commonv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/common/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
)

// Stable reason codes. Clients branch on these, never on message text.
const (
	ReasonAuthMissing        = "AUTH_TOKEN_MISSING"
	ReasonAuthInvalid        = "AUTH_TOKEN_INVALID"
	ReasonAuthExpired        = "AUTH_TOKEN_EXPIRED"
	ReasonAccountInactive    = "AUTH_ACCOUNT_NOT_ACTIVE"
	ReasonRoleNotMigrated    = "ROLE_NOT_MIGRATED"
	ReasonActingNotSupported = "ACTING_APPOINTMENT_NOT_SUPPORTED"
	ReasonSchoolNotFound     = "SCHOOL_NOT_FOUND"
	ReasonInvalidArgument    = "INVALID_ARGUMENT"
	ReasonPermissionDenied   = "PERMISSION_DENIED"
	ReasonScreenUnavailable  = "SCREEN_UNAVAILABLE"
	ReasonNotFound           = "NOT_FOUND"
	ReasonInternal           = "INTERNAL"
	// ReasonPasswordChangeRequired: the account's password was set by an
	// administrator and must be replaced first.
	ReasonPasswordChangeRequired = "PASSWORD_CHANGE_REQUIRED"
)

const internalMessage = "Something went wrong on our side. Please try again."

// New returns a Connect error with the structured detail attached.
func New(ctx context.Context, code connect.Code, reason, message string) *connect.Error {
	connectErr := connect.NewError(code, errors.New(message))
	span := trace.FromContext(ctx)
	detail, err := connect.NewErrorDetail(&commonv1.ErrorDetail{
		Code:      reason,
		RequestId: span.RequestID,
		TraceId:   span.TraceID,
	})
	if err == nil {
		connectErr.AddDetail(detail)
	}
	return connectErr
}

// Internal logs cause with the request's ids and returns an error that
// reveals nothing about it.
func Internal(ctx context.Context, logger *slog.Logger, cause error) *connect.Error {
	span := trace.FromContext(ctx)
	logger.ErrorContext(ctx, "request failed",
		slog.String("error", cause.Error()),
		slog.String("request_id", span.RequestID),
		slog.String("trace_id", span.TraceID),
	)
	return New(ctx, connect.CodeInternal, ReasonInternal, internalMessage)
}

// Interceptor guarantees that no handler error leaves the gateway without
// structure: anything that is not already a Connect error is logged and
// replaced by Internal.
func Interceptor(logger *slog.Logger) connect.UnaryInterceptorFunc {
	return func(next connect.UnaryFunc) connect.UnaryFunc {
		return func(ctx context.Context, request connect.AnyRequest) (connect.AnyResponse, error) {
			response, err := next(ctx, request)
			if err == nil {
				return response, nil
			}
			var connectErr *connect.Error
			if errors.As(err, &connectErr) {
				return nil, err
			}
			return nil, Internal(ctx, logger, err)
		}
	}
}

// Reason extracts the stable reason code from an error built by this package.
func Reason(err error) string {
	var connectErr *connect.Error
	if !errors.As(err, &connectErr) {
		return ""
	}
	for _, detail := range connectErr.Details() {
		value, valueErr := detail.Value()
		if valueErr != nil {
			continue
		}
		if errorDetail, ok := value.(*commonv1.ErrorDetail); ok {
			return errorDetail.GetCode()
		}
	}
	return ""
}
