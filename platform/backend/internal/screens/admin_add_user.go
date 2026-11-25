package screens

// The Users page's Add User drawer and its save (admin_users_view
// ?drawer=add, action create → admin_users.services.create): the account,
// its staff profile and districts, its supervisor and the people it
// manages, in one transaction, then its invitation or password email.

import (
	"context"
	"errors"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/accounts"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/adminusers"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/teams"
)

const addUserPath = "/admin-panel/users"

// managingRoles are the primary roles whose managed people create() sets.
var managingRoles = map[string]bool{"Program Lead": true, "ImpactAssessment": true, "RegionalVicePresident": true}

// AccountCreation is the accounts.Service part the Add User save uses.
type AccountCreation interface {
	CreateInTx(ctx context.Context, tx pgx.Tx, principal auth.Principal, in accounts.NewAccount) (string, string, error)
	NotifyCreated(principal auth.Principal, name, email, invitation string) string
	StaffChanged()
}

// TeamAssignment is the teams.StaffService part the Add User save uses.
type TeamAssignment interface {
	AssignSupervisorInTx(ctx context.Context, tx pgx.Tx, principal auth.Principal, userID, supervisorStaffID string,
		now time.Time) (teams.Reassigned, error)
	ConfigureTeamInTx(ctx context.Context, tx pgx.Tx, principal auth.Principal, userID string, staffIDs []string,
		now time.Time) (teams.Configured, error)
}

// WithAccountCreation makes the Add User drawer's save Go's.
func (s *Service) WithAccountCreation(a AccountCreation, t TeamAssignment) *Service {
	s.accountCreation, s.teamAssignment = a, t
	return s
}

func isAddUserPath(rawPath string) bool {
	path, query, _ := strings.Cut(rawPath, "?")
	return strings.TrimSuffix(path, "/") == addUserPath && query == "drawer=add"
}

func (s *Service) addUserDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	if !isAddUserPath(rawPath) || s.db == nil || p.InActingAppointment {
		return nil, false, nil
	}
	if !pageaccess.CanOpen(p.ActiveRole, false, addUserPath) {
		return &screensv1.GetDrawerResponse{Refusal: usersRefusal}, true, nil
	}
	d, err := adminusers.AddUserDrawer(ctx, s.db, p)
	switch {
	case errors.Is(err, adminusers.ErrHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

// newAccountFrom is the create form's post as create() reads it.
func newAccountFrom(values map[string]string, lists map[string][]string) accounts.NewAccount {
	var districts []string
	for _, d := range lists["additional_districts"] {
		if d != "" {
			districts = append(districts, d)
		}
	}
	return accounts.NewAccount{
		Name: strings.TrimSpace(values["name"]), Email: strings.ToLower(strings.TrimSpace(values["email"])),
		Phone: strings.TrimSpace(values["phone"]), Role: values["role"], Password: strings.TrimSpace(values["password"]),
		AdditionalRoles: lists["additional_roles"], PrimaryDistrictID: values["primary_district"],
		AdditionalDistrictIDs: districts, Country: strings.TrimSpace(values["country"]),
		Department: strings.TrimSpace(values["department"]),
	}
}

func (s *Service) addUserSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok || !isAddUserPath(message.GetPath()) || !s.nativeForms() || s.accountCreation == nil || s.teamAssignment == nil ||
		p.InActingAppointment {
		return nil, false, nil
	}
	if !pageaccess.CanOpen(p.ActiveRole, false, addUserPath) || p.ActiveRole != "Admin" {
		return &screensv1.SaveDrawerResponse{Error: "This drawer is not available."}, true, nil
	}
	lists := map[string][]string{}
	for _, name := range []string{"additional_roles", "additional_districts", "managed_staff_ids"} {
		lists[name] = tickedIDs(message.GetValues()[name])
	}
	in := newAccountFrom(message.GetValues(), lists)
	if in.Email == "" || in.Name == "" || in.Role == "" {
		return &screensv1.SaveDrawerResponse{Error: "Name, email, and primary role are required."}, true, nil
	}
	supervisor := strings.TrimSpace(message.GetValues()["supervisor_staff_id"])
	var userID, invitation string
	err := pgx.BeginTxFunc(ctx, s.db, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		var err error
		if userID, invitation, err = s.accountCreation.CreateInTx(ctx, tx, p, in); err != nil {
			return err
		}
		now := time.Now()
		if s.now != nil {
			now = s.now()
		}
		if supervisor != "" {
			if _, err = s.teamAssignment.AssignSupervisorInTx(ctx, tx, p, userID, supervisor, now); err != nil {
				return err
			}
		}
		if managed := lists["managed_staff_ids"]; len(managed) > 0 && managingRoles[in.Role] {
			_, err = s.teamAssignment.ConfigureTeamInTx(ctx, tx, p, userID, managed, now)
		}
		return err
	})
	var accountRefused *accounts.Refused
	var teamRefused *teams.Refused
	switch {
	case errors.As(err, &accountRefused):
		return &screensv1.SaveDrawerResponse{Error: accountRefused.Message}, true, nil
	case errors.As(err, &teamRefused):
		return &screensv1.SaveDrawerResponse{Error: teamRefused.Message}, true, nil
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	s.accountCreation.StaffChanged()
	s.accountCreation.NotifyCreated(p, in.Name, in.Email, invitation)
	sent := "An invitation to set their own password was sent."
	if in.Password != "" {
		sent = "A temporary password notification was sent."
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: "User '" + in.Name + "' created. " + sent}, true, nil
}
