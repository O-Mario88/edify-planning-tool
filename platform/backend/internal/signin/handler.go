package signin

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"strings"
	"time"

	"connectrpc.com/connect"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

// Limiter bounds requests per key; loans.Limiter satisfies it.
type Limiter interface {
	Allow(key string, limit int, period time.Duration) bool
}

// The existing throttles: sign-in (and its code) 10 a minute per address
// (RATE_LIMIT_LOGIN_PER_MIN), reset requests 4 per 10 minutes.
const (
	signInLimit    = 10
	signInPeriod   = time.Minute
	resetLimit     = 4
	resetPeriod    = 10 * time.Minute
	tokenLimit     = 60
	tokenPeriod    = time.Minute
	maxAgentLength = 256
)

// Reasons the app can branch on.
const (
	ReasonSignInRejected = "SIGN_IN_REJECTED"
	ReasonCodeRejected   = "SIGN_IN_CODE_REJECTED"
	ReasonSessionEnded   = "SESSION_ENDED"
	ReasonRateLimited    = "RATE_LIMITED"
	ReasonPasswordPolicy = "PASSWORD_POLICY"
	ReasonLinkInvalid    = "LINK_INVALID"
)

// appDevice reads the form factor the native app declares. Its HTTP library
// names itself ("okhttp", "CFNetwork"), not the device, so the browser rule
// alone would label every app sign-in "desktop". Anything else is ignored.
func appDevice(declared string) string {
	switch declared {
	case "mobile", "tablet":
		return declared
	}
	return ""
}

// Handler serves SignInService.
type Handler struct {
	service    *Service
	limiter    Limiter
	trustProxy bool
	logger     *slog.Logger
}

// NewHandler returns the Connect handler. trustProxy reads the caller's
// address from X-Forwarded-For, for a gateway behind a proxy that sets it.
func NewHandler(service *Service, limiter Limiter, trustProxy bool, logger *slog.Logger) *Handler {
	return &Handler{service: service, limiter: limiter, trustProxy: trustProxy, logger: logger}
}

func (h *Handler) caller(peer connect.Peer, header http.Header) Caller {
	address := peer.Addr
	if host, _, err := net.SplitHostPort(address); err == nil {
		address = host
	}
	if h.trustProxy {
		if forwarded := header.Get("X-Forwarded-For"); forwarded != "" {
			address = strings.TrimSpace(strings.Split(forwarded, ",")[0])
		}
	}
	if net.ParseIP(address) == nil {
		address = ""
	}
	agent := header.Get("User-Agent")
	if len(agent) > maxAgentLength {
		agent = agent[:maxAgentLength]
	}
	return Caller{IP: address, UserAgent: agent, Device: appDevice(header.Get("X-Edify-Device"))}
}

func (h *Handler) allow(ctx context.Context, name string, caller Caller, limit int, period time.Duration) error {
	if h.limiter.Allow(name+"|"+caller.IP, limit, period) {
		return nil
	}
	return apierr.New(ctx, connect.CodeResourceExhausted, ReasonRateLimited,
		"Too many attempts. Wait a minute and try again.")
}

// SignIn implements SignInService.
func (h *Handler) SignIn(ctx context.Context, req *connect.Request[identityv1.SignInRequest]) (*connect.Response[identityv1.SignInResponse], error) {
	caller := h.caller(req.Peer(), req.Header())
	if err := h.allow(ctx, "sign-in", caller, signInLimit, signInPeriod); err != nil {
		return nil, err
	}
	outcome, err := h.service.SignIn(ctx, req.Msg.GetEmail(), req.Msg.GetPassword(), req.Msg.GetActiveRole(), caller)
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	if outcome.Challenge != nil {
		c := outcome.Challenge
		return connect.NewResponse(&identityv1.SignInResponse{Result: &identityv1.SignInResponse_CodeRequired{
			CodeRequired: &identityv1.CodeRequired{
				ChallengeToken: c.ClientToken, Channel: c.Channel, DestinationHint: c.Hint,
				ExpiresInSeconds: int32(c.ExpiresIn / time.Second),
			},
		}}), nil
	}
	return connect.NewResponse(&identityv1.SignInResponse{Result: &identityv1.SignInResponse_Session{
		Session: granted(*outcome.Session),
	}}), nil
}

// VerifySignInCode implements SignInService.
func (h *Handler) VerifySignInCode(ctx context.Context, req *connect.Request[identityv1.VerifySignInCodeRequest]) (*connect.Response[identityv1.VerifySignInCodeResponse], error) {
	caller := h.caller(req.Peer(), req.Header())
	if err := h.allow(ctx, "sign-in", caller, signInLimit, signInPeriod); err != nil {
		return nil, err
	}
	session, err := h.service.VerifyCode(ctx, req.Msg.GetChallengeToken(), req.Msg.GetCode(), req.Msg.GetActiveRole(), caller)
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.VerifySignInCodeResponse{Session: granted(session)}), nil
}

// RefreshSession implements SignInService.
func (h *Handler) RefreshSession(ctx context.Context, req *connect.Request[identityv1.RefreshSessionRequest]) (*connect.Response[identityv1.RefreshSessionResponse], error) {
	if err := h.allow(ctx, "refresh", h.caller(req.Peer(), req.Header()), tokenLimit, tokenPeriod); err != nil {
		return nil, err
	}
	tokens, err := h.service.Refresh(ctx, req.Msg.GetRefreshToken())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.RefreshSessionResponse{
		AccessToken: tokens.AccessToken, RefreshToken: tokens.RefreshToken,
	}), nil
}

// SignOut implements SignInService.
func (h *Handler) SignOut(ctx context.Context, req *connect.Request[identityv1.SignOutRequest]) (*connect.Response[identityv1.SignOutResponse], error) {
	if err := h.allow(ctx, "sign-out", h.caller(req.Peer(), req.Header()), tokenLimit, tokenPeriod); err != nil {
		return nil, err
	}
	if err := h.service.SignOut(ctx, req.Msg.GetRefreshToken()); err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.SignOutResponse{}), nil
}

// RequestPasswordReset implements SignInService.
func (h *Handler) RequestPasswordReset(ctx context.Context, req *connect.Request[identityv1.RequestPasswordResetRequest]) (*connect.Response[identityv1.RequestPasswordResetResponse], error) {
	if err := h.allow(ctx, "forgot-password", h.caller(req.Peer(), req.Header()), resetLimit, resetPeriod); err != nil {
		return nil, err
	}
	if err := h.service.RequestPasswordReset(ctx, req.Msg.GetEmail()); err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.RequestPasswordResetResponse{}), nil
}

// ResetPassword implements SignInService.
func (h *Handler) ResetPassword(ctx context.Context, req *connect.Request[identityv1.ResetPasswordRequest]) (*connect.Response[identityv1.ResetPasswordResponse], error) {
	if err := h.allow(ctx, "reset-password", h.caller(req.Peer(), req.Header()), signInLimit, signInPeriod); err != nil {
		return nil, err
	}
	if err := h.service.ResetPassword(ctx, req.Msg.GetToken(), req.Msg.GetPassword(), req.Msg.GetConfirm()); err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.ResetPasswordResponse{}), nil
}

// CheckInvitation implements SignInService.
func (h *Handler) CheckInvitation(ctx context.Context, req *connect.Request[identityv1.CheckInvitationRequest]) (*connect.Response[identityv1.CheckInvitationResponse], error) {
	if err := h.allow(ctx, "invitation", h.caller(req.Peer(), req.Header()), signInLimit, signInPeriod); err != nil {
		return nil, err
	}
	state, err := h.service.CheckInvitation(ctx, req.Msg.GetToken())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.CheckInvitationResponse{
		Valid: state.Valid, Reason: state.Reason, Email: state.Email, Name: state.Name,
	}), nil
}

// AcceptInvitation implements SignInService.
func (h *Handler) AcceptInvitation(ctx context.Context, req *connect.Request[identityv1.AcceptInvitationRequest]) (*connect.Response[identityv1.AcceptInvitationResponse], error) {
	if err := h.allow(ctx, "invitation", h.caller(req.Peer(), req.Header()), signInLimit, signInPeriod); err != nil {
		return nil, err
	}
	if err := h.service.AcceptInvitation(ctx, req.Msg.GetToken(), req.Msg.GetPassword(), req.Msg.GetConfirm()); err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.AcceptInvitationResponse{}), nil
}

// GetSignInFigures implements SignInService.
func (h *Handler) GetSignInFigures(ctx context.Context, _ *connect.Request[identityv1.GetSignInFiguresRequest]) (*connect.Response[identityv1.GetSignInFiguresResponse], error) {
	figures, err := h.service.SignInFigures(ctx)
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	response := connect.NewResponse(&identityv1.GetSignInFiguresResponse{
		Portfolio: figures.Portfolio, SchoolsReached: figures.SchoolsReached, SchoolsVisited: figures.SchoolsVisited,
		SchoolsTrained: figures.SchoolsTrained, SsaCompleted: figures.SSACompleted,
	})
	response.Header().Set("Cache-Control", "public, max-age=300")
	return response, nil
}

func granted(s Session) *identityv1.SessionGranted {
	return &identityv1.SessionGranted{
		AccessToken: s.Tokens.AccessToken, RefreshToken: s.Tokens.RefreshToken,
		Account: &identityv1.SignedInAccount{
			UserId: s.Account.UserID, Email: s.Account.Email, Name: s.Account.Name, Roles: s.Account.Roles,
			ActiveRole: s.Account.ActiveRole, StaffProfileId: s.Account.StaffProfileID,
		},
	}
}

// fail turns a service error into the public answer.
func (h *Handler) fail(ctx context.Context, err error) error {
	var policy PolicyError
	var refusal InvitationRefusal
	switch {
	case errors.Is(err, ErrRejected):
		return apierr.New(ctx, connect.CodeUnauthenticated, ReasonSignInRejected, ErrRejected.Error())
	case errors.Is(err, ErrCodeRejected):
		return apierr.New(ctx, connect.CodeUnauthenticated, ReasonCodeRejected, ErrCodeRejected.Error())
	case errors.Is(err, ErrSessionExpired):
		return apierr.New(ctx, connect.CodeUnauthenticated, ReasonSessionEnded, ErrSessionExpired.Error())
	case errors.Is(err, ErrResetLink):
		return apierr.New(ctx, connect.CodeInvalidArgument, ReasonLinkInvalid, ErrResetLink.Error())
	case errors.As(err, &policy):
		return apierr.New(ctx, connect.CodeInvalidArgument, ReasonPasswordPolicy, policy.Error())
	case errors.As(err, &refusal):
		return apierr.New(ctx, connect.CodeInvalidArgument, ReasonLinkInvalid, refusal.Error())
	}
	return apierr.Internal(ctx, h.logger, err)
}
