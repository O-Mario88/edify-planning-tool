package teams

import (
	"context"
	"errors"
	"log/slog"

	"connectrpc.com/connect"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/accounts"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Handler serves StaffTeamService and PartnerTeamService.
type Handler struct {
	staff    *StaffService
	partners *PartnerService
	logger   *slog.Logger
}

// NewHandler returns the Connect handler for both services.
func NewHandler(staff *StaffService, partners *PartnerService, logger *slog.Logger) *Handler {
	return &Handler{staff: staff, partners: partners, logger: logger}
}

// caller is the signed-in person, refused while in an acting appointment,
// which swaps their permissions in the existing system.
func caller(ctx context.Context) (auth.Principal, error) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return auth.Principal{}, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "Sign in to continue.")
	}
	if principal.InActingAppointment {
		return auth.Principal{}, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonActingNotSupported,
			"Teams are not available here while you hold an acting appointment. Use the Edify web app.")
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
	var accountRefused *accounts.Refused
	if errors.As(err, &accountRefused) {
		return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, accountRefused.Message)
	}
	return apierr.Internal(ctx, h.logger, err)
}

func staffMessage(m StaffMember) *identityv1.StaffMember {
	return &identityv1.StaffMember{
		StaffId: m.StaffID, UserId: m.UserID, Name: m.Name, Email: m.Email, Role: m.ActiveRole, Title: m.Title,
		OnboardingState: m.Onboarding, SupervisorStaffId: m.SupervisorStaffID, SupervisorName: m.SupervisorName,
		AssignedSchoolCount: int32(m.AssignedSchools),
	}
}

// ── StaffTeamService ─────────────────────────────────────────────────────

// ListStaff implements StaffTeamService.
func (h *Handler) ListStaff(ctx context.Context, req *connect.Request[identityv1.ListStaffRequest]) (*connect.Response[identityv1.ListStaffResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	staff, err := h.staff.List(ctx, principal, req.Msg.GetSearch())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	out := make([]*identityv1.StaffMember, len(staff))
	for i, m := range staff {
		out[i] = staffMessage(m)
	}
	return connect.NewResponse(&identityv1.ListStaffResponse{Staff: out}), nil
}

// GetSupervisor implements StaffTeamService.
func (h *Handler) GetSupervisor(ctx context.Context, req *connect.Request[identityv1.GetSupervisorRequest]) (*connect.Response[identityv1.GetSupervisorResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	found, err := h.staff.Supervisor(ctx, principal, req.Msg.GetUserId())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	choices := make([]*identityv1.SupervisorChoice, len(found.Choices))
	for i, p := range found.Choices {
		choices[i] = &identityv1.SupervisorChoice{StaffId: p.StaffID, Name: p.Name, Role: p.ActiveRole}
	}
	return connect.NewResponse(&identityv1.GetSupervisorResponse{
		Staff: staffMessage(found.Staff), ExpectedRole: found.ExpectedRole, Choices: choices,
	}), nil
}

// AssignSupervisor implements StaffTeamService.
func (h *Handler) AssignSupervisor(ctx context.Context, req *connect.Request[identityv1.AssignSupervisorRequest]) (*connect.Response[identityv1.AssignSupervisorResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	done, err := h.staff.AssignSupervisor(ctx, principal, req.Msg.GetUserId(), req.Msg.GetSupervisorStaffId())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.AssignSupervisorResponse{
		OldSupervisorStaffId: done.OldSupervisorStaffID, NewSupervisorStaffId: done.NewSupervisorStaffID,
		NewSupervisorName: done.NewSupervisorName,
	}), nil
}

// GetManagedTeam implements StaffTeamService.
func (h *Handler) GetManagedTeam(ctx context.Context, req *connect.Request[identityv1.GetManagedTeamRequest]) (*connect.Response[identityv1.GetManagedTeamResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	team, err := h.staff.Team(ctx, principal, req.Msg.GetUserId())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	people := make([]*identityv1.ManagedPerson, len(team.People))
	for i, p := range team.People {
		people[i] = &identityv1.ManagedPerson{StaffId: p.StaffID, Name: p.Name, Email: p.Email, Role: p.ActiveRole,
			Status: p.Status, Assigned: p.Assigned, OtherManager: p.OtherManager}
	}
	return connect.NewResponse(&identityv1.GetManagedTeamResponse{
		Role: team.Role, Country: team.Country, Automatic: team.Automatic, People: people,
	}), nil
}

// ConfigureManagedTeam implements StaffTeamService.
func (h *Handler) ConfigureManagedTeam(ctx context.Context, req *connect.Request[identityv1.ConfigureManagedTeamRequest]) (*connect.Response[identityv1.ConfigureManagedTeamResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	done, err := h.staff.ConfigureTeam(ctx, principal, req.Msg.GetUserId(), req.Msg.GetStaffIds())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.ConfigureManagedTeamResponse{
		AssignedCount: int32(done.Assigned), AddedCount: int32(done.Added), RemovedCount: int32(done.Removed),
	}), nil
}

// ── PartnerTeamService ───────────────────────────────────────────────────

func memberMessage(m Member) *identityv1.PartnerMemberInfo {
	out := &identityv1.PartnerMemberInfo{MemberId: m.ID, Name: m.Name, Role: m.Role, Title: m.Title, Phone: m.Phone,
		Email: m.Email, SchoolCount: int32(m.Schools)}
	if m.Login != nil {
		out.Login = &identityv1.PartnerLogin{UserId: m.Login.UserID, Email: m.Login.Email, Status: m.Login.Status,
			IsActive: m.Login.IsActive}
	}
	return out
}

// GetPartnerTeam implements PartnerTeamService.
func (h *Handler) GetPartnerTeam(ctx context.Context, req *connect.Request[identityv1.GetPartnerTeamRequest]) (*connect.Response[identityv1.GetPartnerTeamResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	team, err := h.partners.Team(ctx, principal, req.Msg.GetPartnerId())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	out := &identityv1.GetPartnerTeamResponse{PartnerId: team.PartnerID, PartnerName: team.PartnerName,
		LeadsTeam: team.LeadsTeam, ManagesRoster: team.Roster}
	for _, m := range team.Members {
		out.Members = append(out.Members, memberMessage(m))
	}
	for _, s := range team.Schools {
		out.Schools = append(out.Schools, &identityv1.PartnerSchool{SchoolId: s.ID, Name: s.Name, District: s.District,
			MemberId: s.MemberID})
	}
	return connect.NewResponse(out), nil
}

// AddMember implements PartnerTeamService.
func (h *Handler) AddMember(ctx context.Context, req *connect.Request[identityv1.AddMemberRequest]) (*connect.Response[identityv1.AddMemberResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	m := req.Msg
	member, err := h.partners.AddMember(ctx, principal, m.GetPartnerId(), NewMember{
		Name: m.GetName(), Role: m.GetRole(), Title: m.GetTitle(), Phone: m.GetPhone(), Email: m.GetEmail(),
	})
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.AddMemberResponse{Member: memberMessage(member)}), nil
}

// RemoveMember implements PartnerTeamService.
func (h *Handler) RemoveMember(ctx context.Context, req *connect.Request[identityv1.RemoveMemberRequest]) (*connect.Response[identityv1.RemoveMemberResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := h.partners.RemoveMember(ctx, principal, req.Msg.GetPartnerId(), req.Msg.GetMemberId()); err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.RemoveMemberResponse{}), nil
}

// CreateMemberLogin implements PartnerTeamService.
func (h *Handler) CreateMemberLogin(ctx context.Context, req *connect.Request[identityv1.CreateMemberLoginRequest]) (*connect.Response[identityv1.CreateMemberLoginResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	m := req.Msg
	done, err := h.partners.CreateLogin(ctx, principal, m.GetPartnerId(), m.GetMemberId(), m.GetEmail(), m.GetPassword())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.CreateMemberLoginResponse{Invited: done.Invited, InvitationLink: done.InvitationLink}), nil
}

// ResetMemberPassword implements PartnerTeamService.
func (h *Handler) ResetMemberPassword(ctx context.Context, req *connect.Request[identityv1.ResetMemberPasswordRequest]) (*connect.Response[identityv1.ResetMemberPasswordResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	m := req.Msg
	if err := h.partners.ResetPassword(ctx, principal, m.GetPartnerId(), m.GetMemberId(), m.GetPassword()); err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.ResetMemberPasswordResponse{}), nil
}

// SetMemberLoginActive implements PartnerTeamService.
func (h *Handler) SetMemberLoginActive(ctx context.Context, req *connect.Request[identityv1.SetMemberLoginActiveRequest]) (*connect.Response[identityv1.SetMemberLoginActiveResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	m := req.Msg
	if err := h.partners.SetLoginActive(ctx, principal, m.GetPartnerId(), m.GetMemberId(), m.GetActive()); err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.SetMemberLoginActiveResponse{}), nil
}

// SetMemberSchools implements PartnerTeamService.
func (h *Handler) SetMemberSchools(ctx context.Context, req *connect.Request[identityv1.SetMemberSchoolsRequest]) (*connect.Response[identityv1.SetMemberSchoolsResponse], error) {
	principal, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	m := req.Msg
	done, err := h.partners.SetSchools(ctx, principal, m.GetPartnerId(), m.GetMemberId(), m.GetSchoolIds())
	if err != nil {
		return nil, h.fail(ctx, err)
	}
	return connect.NewResponse(&identityv1.SetMemberSchoolsResponse{
		Given: int32(done.Given), Moved: int32(done.Moved), Cleared: int32(done.Cleared), ActivitiesNamed: int32(done.Named),
	}), nil
}
