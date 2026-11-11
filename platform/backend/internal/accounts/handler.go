package accounts

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"connectrpc.com/connect"

	commonv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/common/v1"
	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

const (
	defaultPageSize = 50
	maxPageSize     = 200
)

// Handler serves AccountService and AccountAdminService.
type Handler struct {
	service *Service
	logger  *slog.Logger
}

// NewHandler returns the Connect handler for both services.
func NewHandler(service *Service, logger *slog.Logger) *Handler {
	return &Handler{service: service, logger: logger}
}

func (h *Handler) fail(ctx context.Context, err error) error {
	var refused *Refused
	if errors.As(err, &refused) {
		code := connect.CodeInvalidArgument
		reason := apierr.ReasonInvalidArgument
		switch {
		case refused.Conflict:
			code = connect.CodeAlreadyExists
		case refused.Message == msgNotFound:
			code, reason = connect.CodeNotFound, apierr.ReasonNotFound
		case refused.Message == msgOnlyAdminModifiesAdmin || refused.Message == msgOnlyAdminGrantsAdmin ||
			refused.Message == "Access restricted: Invalid role request." || refused.Message == "Only an Admin can delete users.":
			code, reason = connect.CodePermissionDenied, apierr.ReasonPermissionDenied
		}
		return apierr.New(ctx, code, reason, refused.Message)
	}
	var connectErr *connect.Error
	if errors.As(err, &connectErr) {
		return connectErr
	}
	return apierr.Internal(ctx, h.logger, err)
}

// ── AccountService ────────────────────────────────────────────────────────

// SwitchRole implements AccountService.
func (h *Handler) SwitchRole(ctx context.Context, req *connect.Request[identityv1.SwitchRoleRequest]) (*connect.Response[identityv1.SwitchRoleResponse], error) {
	principal, err := signedIn(ctx)
	if err != nil {
		return nil, err
	}
	token, err := h.service.SwitchRole(ctx, principal, req.Msg.GetRole())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.SwitchRoleResponse{AccessToken: token, ActiveRole: req.Msg.GetRole()}), nil
}

// SetNewPassword implements AccountService.
func (h *Handler) SetNewPassword(ctx context.Context, req *connect.Request[identityv1.SetNewPasswordRequest]) (*connect.Response[identityv1.SetNewPasswordResponse], error) {
	principal, err := signedIn(ctx)
	if err != nil {
		return nil, err
	}
	if err := h.service.SetNewPassword(ctx, principal, req.Msg.GetPassword(), req.Msg.GetConfirm()); err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.SetNewPasswordResponse{}), nil
}

// ── AccountAdminService ───────────────────────────────────────────────────

// ListAccounts implements AccountAdminService.
func (h *Handler) ListAccounts(ctx context.Context, req *connect.Request[identityv1.ListAccountsRequest]) (*connect.Response[identityv1.ListAccountsResponse], error) {
	if _, err := administrator(ctx); err != nil {
		return nil, err
	}
	page, size := pageOf(req.Msg.GetPage())
	accounts, total, err := h.service.List(ctx, req.Msg.GetSearch(), req.Msg.GetStatus(), page, size)
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	now := h.service.deps.Now()
	out := make([]*identityv1.ManagedAccount, len(accounts))
	for i, account := range accounts {
		out[i] = managed(account, now)
	}
	pages := int32((total + int64(size) - 1) / int64(size))
	return connect.NewResponse(&identityv1.ListAccountsResponse{
		Accounts: out,
		Page:     &commonv1.PageInfo{Page: int32(page), PageSize: int32(size), Total: total, TotalPages: pages},
	}), nil
}

// GetAccount implements AccountAdminService.
func (h *Handler) GetAccount(ctx context.Context, req *connect.Request[identityv1.GetAccountRequest]) (*connect.Response[identityv1.GetAccountResponse], error) {
	if _, err := administrator(ctx); err != nil {
		return nil, err
	}
	account, err := h.service.Get(ctx, req.Msg.GetUserId())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.GetAccountResponse{Account: managed(account, h.service.deps.Now())}), nil
}

// CreateAccount implements AccountAdminService.
func (h *Handler) CreateAccount(ctx context.Context, req *connect.Request[identityv1.CreateAccountRequest]) (*connect.Response[identityv1.CreateAccountResponse], error) {
	principal, err := administrator(ctx)
	if err != nil {
		return nil, err
	}
	m := req.Msg
	created, err := h.service.Create(ctx, principal, NewAccount{
		Name: m.GetName(), Email: m.GetEmail(), Phone: m.GetPhone(), Role: m.GetRole(), Password: m.GetPassword(),
		AdditionalRoles: m.GetAdditionalRoles(), PrimaryDistrictID: m.GetPrimaryDistrictId(),
		AdditionalDistrictIDs: m.GetAdditionalDistrictIds(), Country: m.GetCountry(), Department: m.GetDepartment(),
	})
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.CreateAccountResponse{
		Account: managed(created.Account, h.service.deps.Now()), InvitationLink: created.InvitationLink,
	}), nil
}

// UpdateAccount implements AccountAdminService.
func (h *Handler) UpdateAccount(ctx context.Context, req *connect.Request[identityv1.UpdateAccountRequest]) (*connect.Response[identityv1.UpdateAccountResponse], error) {
	principal, err := administrator(ctx)
	if err != nil {
		return nil, err
	}
	m := req.Msg
	account, err := h.service.Update(ctx, principal, m.GetUserId(), Changes{
		Name: m.GetName(), Email: m.GetEmail(), Phone: m.Phone, Role: m.GetRole(), AdditionalRoles: m.GetAdditionalRoles(),
	})
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.UpdateAccountResponse{Account: managed(account, h.service.deps.Now())}), nil
}

// ResendInvitation implements AccountAdminService.
func (h *Handler) ResendInvitation(ctx context.Context, req *connect.Request[identityv1.ResendInvitationRequest]) (*connect.Response[identityv1.ResendInvitationResponse], error) {
	principal, err := administrator(ctx)
	if err != nil {
		return nil, err
	}
	link, err := h.service.ResendInvitation(ctx, principal, req.Msg.GetUserId())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.ResendInvitationResponse{InvitationLink: link}), nil
}

// RevokeInvitation implements AccountAdminService.
func (h *Handler) RevokeInvitation(ctx context.Context, req *connect.Request[identityv1.RevokeInvitationRequest]) (*connect.Response[identityv1.RevokeInvitationResponse], error) {
	principal, err := administrator(ctx)
	if err != nil {
		return nil, err
	}
	if err := h.service.RevokeInvitation(ctx, principal, req.Msg.GetUserId()); err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.RevokeInvitationResponse{}), nil
}

// SetAccountStatus implements AccountAdminService.
func (h *Handler) SetAccountStatus(ctx context.Context, req *connect.Request[identityv1.SetAccountStatusRequest]) (*connect.Response[identityv1.SetAccountStatusResponse], error) {
	principal, err := administrator(ctx)
	if err != nil {
		return nil, err
	}
	account, err := h.service.SetStatus(ctx, principal, req.Msg.GetUserId(), req.Msg.GetStatus())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.SetAccountStatusResponse{Account: managed(account, h.service.deps.Now())}), nil
}

// SendPasswordReset implements AccountAdminService.
func (h *Handler) SendPasswordReset(ctx context.Context, req *connect.Request[identityv1.SendPasswordResetRequest]) (*connect.Response[identityv1.SendPasswordResetResponse], error) {
	principal, err := administrator(ctx)
	if err != nil {
		return nil, err
	}
	if err := h.service.SendPasswordReset(ctx, principal, req.Msg.GetUserId()); err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.SendPasswordResetResponse{}), nil
}

// SetTemporaryPassword implements AccountAdminService.
func (h *Handler) SetTemporaryPassword(ctx context.Context, req *connect.Request[identityv1.SetTemporaryPasswordRequest]) (*connect.Response[identityv1.SetTemporaryPasswordResponse], error) {
	principal, err := administrator(ctx)
	if err != nil {
		return nil, err
	}
	if err := h.service.SetTemporaryPassword(ctx, principal, req.Msg.GetUserId(), req.Msg.GetPassword()); err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.SetTemporaryPasswordResponse{}), nil
}

// UnlockAccount implements AccountAdminService.
func (h *Handler) UnlockAccount(ctx context.Context, req *connect.Request[identityv1.UnlockAccountRequest]) (*connect.Response[identityv1.UnlockAccountResponse], error) {
	principal, err := administrator(ctx)
	if err != nil {
		return nil, err
	}
	if err := h.service.Unlock(ctx, principal, req.Msg.GetUserId()); err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.UnlockAccountResponse{}), nil
}

// DeleteAccount implements AccountAdminService.
func (h *Handler) DeleteAccount(ctx context.Context, req *connect.Request[identityv1.DeleteAccountRequest]) (*connect.Response[identityv1.DeleteAccountResponse], error) {
	principal, err := administrator(ctx)
	if err != nil {
		return nil, err
	}
	if err := h.service.Delete(ctx, principal, req.Msg.GetUserId()); err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.DeleteAccountResponse{}), nil
}

func pageOf(page *commonv1.PageRequest) (number, size int) {
	number, size = int(page.GetPage()), int(page.GetPageSize())
	if number < 1 {
		number = 1
	}
	if size < 1 {
		size = defaultPageSize
	}
	return number, min(size, maxPageSize)
}

func managed(a Account, now time.Time) *identityv1.ManagedAccount {
	out := &identityv1.ManagedAccount{
		UserId: a.ID, Name: a.Name, Email: a.Email, Phone: a.Phone, Roles: a.Roles, ActiveRole: a.ActiveRole,
		Status: a.Status, IsActive: a.IsActive, PasswordSet: a.PasswordSet, InvitationStatus: a.InvitationStatus,
		Locked: a.Locked(now), LockedUntilAdmin: a.LockedUntilAdmin, MustChangePassword: a.MustChangePassword,
	}
	if a.LastSignInAt != nil {
		out.LastSignInAt = a.LastSignInAt.UTC().Format(time.RFC3339)
	}
	if a.InvitationExpiresAt != nil {
		out.InvitationExpiresAt = a.InvitationExpiresAt.UTC().Format(time.RFC3339)
	}
	return out
}
