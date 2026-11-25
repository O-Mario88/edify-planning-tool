package adminusers

// A partner organisation's login setup (partner_user_setup_drawer_view,
// partials/partners/user_setup_drawer.html) as the feed reads it, and its
// save (partners.services.configure_partner_user) inside the caller's
// transaction.

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrNoPartner is the view's 404: no such live organisation.
var ErrNoPartner = errors.New("adminusers: no such partner")

// PartnerLoginRefusal is may_manage_partner_users's refusal.
const PartnerLoginRefusal = "Only a user administrator can set up partner logins."

// partnerSetupLabels are PartnerUserSetupStatus's labels.
var partnerSetupLabels = map[string]string{
	"pending": "User setup pending", "not_required": "No login required yet", "configured": "Partner login configured",
}

// MayManagePartnerLogins is may_manage_partner_users.
func MayManagePartnerLogins(p auth.Principal) bool {
	return rbac.Grants(p.ActiveRole, rbac.PartnerUserManage) && rbac.Grants(p.ActiveRole, rbac.UserManage)
}

type partnerRow struct {
	name, status, email, contact string
	login                        string // the live linked account's email, or ""
}

func partnerFor(ctx context.Context, db schooldirectory.Querier, id string) (partnerRow, error) {
	var r partnerRow
	err := db.QueryRow(ctx, `SELECT p.name, COALESCE(p.user_setup_status, ''), COALESCE(p.email, ''),
  COALESCE(p.contact_person, ''), COALESCE(u.email, '')
FROM partner p LEFT JOIN "user" u ON u.id = p.user_id AND u.deleted_at IS NULL
WHERE p.id = $1 AND p.deleted_at IS NULL`, id).Scan(&r.name, &r.status, &r.email, &r.contact, &r.login)
	if errors.Is(err, pgx.ErrNoRows) {
		return r, ErrNoPartner
	}
	if err != nil {
		return r, fmt.Errorf("adminusers: the partner: %w", err)
	}
	return r, nil
}

// PartnerLoginDrawer draws the login setup drawer for a user administrator.
func PartnerLoginDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, partnerID string) (*screensv1.PageDrawer, error) {
	r, err := partnerFor(ctx, db, partnerID)
	if err != nil {
		return nil, err
	}
	title, current, mode := "Set up login for "+r.name, "None linked", "invite"
	if r.login != "" {
		title, current, mode = "Change the login of "+r.name, r.login, "link"
	}
	items := []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Text{Text: "Current login: " + current}}}
	if r.login != "" {
		items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Tone: "info",
			Text: "To reset its password, unlock it or change its details, configure this login. Use this form to give " +
				r.name + " a different one."}}})
	}
	email := r.login
	if email == "" {
		email = r.email
	}
	inviteOnly := []*screensv1.DrawerCondition{{Field: "mode", Values: []string{"invite"}}}
	items = append(items,
		field(&screensv1.DrawerField{Name: "mode", Label: "What to do *", Kind: "radio", Required: true, Value: mode,
			Options: []*screensv1.DrawerOption{
				{Value: "invite", Label: "Create a new Partner Admin login."},
				{Value: "link", Label: "Link an existing partner account."},
				{Value: "not_required", Label: "No login required yet."},
			}}),
		field(&screensv1.DrawerField{Name: "email", Label: "Login email", Kind: "email", Value: email}),
		field(&screensv1.DrawerField{Name: "login_name", Label: "Person's name", Kind: "text", Value: r.contact, ShowWhen: inviteOnly}),
		field(&screensv1.DrawerField{Name: "password",
			Label: "Password (optional)", Kind: "password",
			Help: "Leave blank to email an invitation and let the person set their own. A password set here must be changed at first sign-in.", ShowWhen: inviteOnly}),
	)
	return &screensv1.PageDrawer{Title: title, Subtitle: partnerSetupLabels[r.status], HasRequired: true,
		SubmitLabel: "Save login setup", CancelLabel: "Cancel", CanSubmit: true, Items: items}, nil
}

// PartnerLoginChoice is the drawer's post.
type PartnerLoginChoice struct {
	Mode, Email, Name, Password string
}

// LoginRefused is a choice configure_partner_user refuses, in its words.
type LoginRefused struct{ Message string }

func (r *LoginRefused) Error() string { return r.Message }

func refusedf(format string, args ...any) error {
	return &LoginRefused{Message: fmt.Sprintf(format, args...)}
}

// PartnerLoginCreate creates the Partner Admin account an invite makes
// (admin_users.services.create, through accounts.CreateInTx).
type PartnerLoginCreate func(ctx context.Context, tx pgx.Tx, email, name, password string) (userID string, err error)

// PartnerLoginSaved is what the save did.
type PartnerLoginSaved struct {
	PartnerName, Status string
}

// ConfigurePartnerLogin is configure_partner_user inside tx.
func ConfigurePartnerLogin(ctx context.Context, tx pgx.Tx, p auth.Principal, partnerID string, in PartnerLoginChoice,
	create PartnerLoginCreate, now time.Time) (PartnerLoginSaved, error) {
	if !MayManagePartnerLogins(p) {
		return PartnerLoginSaved{}, &LoginRefused{Message: PartnerLoginRefusal}
	}
	var name, contact, prevStatus string
	var prevUser *string
	err := tx.QueryRow(ctx, `SELECT name, COALESCE(contact_person, ''), COALESCE(user_setup_status, ''), user_id
FROM partner WHERE id = $1 FOR UPDATE`, partnerID).Scan(&name, &contact, &prevStatus, &prevUser)
	if errors.Is(err, pgx.ErrNoRows) {
		return PartnerLoginSaved{}, &LoginRefused{Message: "Partner organisation not found."}
	}
	if err != nil {
		return PartnerLoginSaved{}, fmt.Errorf("adminusers: the partner: %w", err)
	}
	mode := strings.TrimSpace(in.Mode)
	userID, status := prevUser, "configured"
	switch mode {
	case "not_required":
		status = "not_required"
	case "link", "invite":
		linked, err := loginFor(ctx, tx, mode, strings.ToLower(strings.TrimSpace(in.Email)), in, name, contact, create)
		if err != nil {
			return PartnerLoginSaved{}, err
		}
		var other string
		err = tx.QueryRow(ctx, `SELECT name FROM partner WHERE user_id = $1 AND deleted_at IS NULL AND id <> $2 LIMIT 1`,
			linked.id, partnerID).Scan(&other)
		if err == nil {
			return PartnerLoginSaved{}, refusedf("%s is already the login for %s.", linked.email, other)
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return PartnerLoginSaved{}, fmt.Errorf("adminusers: the account's other partner: %w", err)
		}
		userID = &linked.id
	default:
		return PartnerLoginSaved{}, &LoginRefused{Message: "Choose Link, Invite or No login required."}
	}
	if _, err := tx.Exec(ctx, `UPDATE partner SET user_id = $2, user_setup_status = $3, user_setup_updated_by = $4,
  user_setup_updated_at = $5, updated_at = $5 WHERE id = $1`, partnerID, userID, status, p.UserID, now); err != nil {
		return PartnerLoginSaved{}, fmt.Errorf("adminusers: saving the login setup: %w", err)
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "partner.user_setup_changed", SubjectKind: audit.Text("partner"), SubjectID: audit.Text(partnerID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
		Payload: map[string]any{"mode": mode,
			"previous": map[string]any{"userId": nullableText(prevUser), "userSetupStatus": prevStatus},
			"new":      map[string]any{"userId": nullableText(userID), "userSetupStatus": status}},
	}, now); err != nil {
		return PartnerLoginSaved{}, err
	}
	if _, err := tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition($1, 'partner', $2, $3)`,
		"partner_user_setup_required", partnerID, now); err != nil {
		return PartnerLoginSaved{}, fmt.Errorf("adminusers: closing the setup notices: %w", err)
	}
	return PartnerLoginSaved{PartnerName: name, Status: status}, nil
}

type linkedLogin struct{ id, email string }

// loginFor is the account a link or invite names.
func loginFor(ctx context.Context, tx pgx.Tx, mode, email string, in PartnerLoginChoice, partnerName, contact string,
	create PartnerLoginCreate) (linkedLogin, error) {
	if email == "" {
		return linkedLogin{}, &LoginRefused{Message: "Enter the email address of the partner login."}
	}
	var found linkedLogin
	var name string
	var roles []string
	err := tx.QueryRow(ctx, `SELECT id, email, COALESCE(name, ''), COALESCE(roles, '{}') FROM "user"
WHERE email = $1 AND deleted_at IS NULL LIMIT 1`, email).Scan(&found.id, &found.email, &name, &roles)
	exists := err == nil
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return linkedLogin{}, fmt.Errorf("adminusers: the account: %w", err)
	}
	if mode == "link" {
		if !exists {
			return linkedLogin{}, refusedf("No account uses %s. Choose Invite to create one.", email)
		}
		for _, r := range roles {
			if partnerLoginRoles[r] {
				return found, nil
			}
		}
		return linkedLogin{}, refusedf("%s is not a partner account. Only a Partner Admin or Partner Field Officer login can be linked.", name)
	}
	if exists {
		return linkedLogin{}, refusedf("An account already uses %s. Choose Link instead.", email)
	}
	person := strings.TrimSpace(in.Name)
	if person == "" {
		person = contact
	}
	if person == "" {
		person = partnerName
	}
	id, err := create(ctx, tx, email, person, strings.TrimSpace(in.Password))
	if err != nil {
		return linkedLogin{}, err
	}
	return linkedLogin{id: id, email: email}, nil
}

func nullableText(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}
