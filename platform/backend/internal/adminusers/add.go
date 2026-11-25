package adminusers

// The Add User drawer (admin_users_view ?drawer=add,
// partials/admin/add_user_drawer.html) as the feed reads it. Its save is
// accounts.CreateInTx with the supervisor and the managed people, through
// screens.

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// supervisorRoles are the roles the create form offers as supervisors.
var supervisorRoles = []string{"Program Lead", "CountryDirector", "RegionalVicePresident"}

// managementExcluded are the roles never offered as people to manage.
var managementExcluded = []string{"Admin", "PartnerAdmin", "PartnerFieldOfficer"}

func field(f *screensv1.DrawerField) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: f}}
}

// AddUserDrawer draws the Add User drawer for the Admin.
func AddUserDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal) (*screensv1.PageDrawer, error) {
	if p.ActiveRole != "Admin" {
		return nil, ErrHandOn
	}
	supervisors, err := options(ctx, db, `SELECT sp.id, COALESCE(u.name, '') || ' — ' || COALESCE(u.active_role, ''), ''
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL AND u.active_role = ANY($1) ORDER BY u.name`, supervisorRoles)
	if err != nil {
		return nil, err
	}
	districts, err := options(ctx, db, `SELECT id, COALESCE(name, ''), '' FROM district ORDER BY name`)
	if err != nil {
		return nil, err
	}
	people, err := options(ctx, db, `SELECT sp.id, COALESCE(u.name, ''), COALESCE(u.active_role, '') || ' · ' || COALESCE(u.email, '')
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL AND sp.country = 'Uganda' AND NOT (COALESCE(u.active_role, '') = ANY($1))
ORDER BY u.name`, managementExcluded)
	if err != nil {
		return nil, err
	}
	roles := []*screensv1.DrawerOption{}
	for _, r := range rules.FilterRoles {
		roles = append(roles, &screensv1.DrawerOption{Value: r, Label: r})
	}
	items := []*screensv1.DrawerItem{
		field(&screensv1.DrawerField{Name: "name", Label: "Full Name", Kind: "text", Required: true, Placeholder: "e.g. John Doe"}),
		field(&screensv1.DrawerField{Name: "email", Label: "Email Address", Kind: "email", Required: true, Placeholder: "johndoe@edify.org"}),
		field(&screensv1.DrawerField{Name: "phone", Label: "Phone Number", Kind: "text", Placeholder: "+256..."}),
		field(&screensv1.DrawerField{Name: "password", Label: "Password — optional", Kind: "password",
			Help:        "Leave blank and the new user sets their own password from a one-time invitation link — nobody else ever knows it.",
			Placeholder: "Leave blank to send an invitation instead"}),
		field(&screensv1.DrawerField{Name: "supervisor_staff_id", Label: "Supervisor", Kind: "select",
			Help:    "Without a supervisor this person has no leave approver, no team scope, and no development-request routing.",
			Options: append([]*screensv1.DrawerOption{{Label: "No supervisor yet"}}, supervisors...)}),
		field(&screensv1.DrawerField{Name: "role", Label: "Primary Role", Kind: "select", Required: true, Value: roles[0].GetValue(),
			Options: roles}),
		field(&screensv1.DrawerField{Name: "primary_district", Label: "Primary District Assignment", Kind: "select",
			Help: "Staff visits here share daily transport and lunch.", Options: append([]*screensv1.DrawerOption{{Label: "None (HQ / Regional)"}}, districts...)}),
	}
	if len(people) > 0 {
		items = append(items, field(&screensv1.DrawerField{Name: "managed_staff_ids", Label: "People this user will manage", Kind: "checklist",
			Options: people}))
	} else {
		items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: "No eligible Uganda staff profiles are available yet."}})
	}
	items = append(items,
		field(&screensv1.DrawerField{Name: "additional_districts", Label: "Secondary District Assignments", Kind: "checklist",
			Help: "Staff visits here share transport, breakfast, lunch, dinner and accommodation.", Options: withDetail(districts)}),
		field(&screensv1.DrawerField{Name: "additional_roles", Label: "Additional/Secondary Roles", Kind: "checklist", Options: withDetail(roles)}),
	)
	return &screensv1.PageDrawer{Title: "Add user", Subtitle: "A sign-in account for a member of staff", HasRequired: true,
		SubmitLabel: "Add user", CancelLabel: "Cancel", CanSubmit: true, Items: items}, nil
}

// withDetail is the options as a checklist carries them (each with its
// detail, empty here).
func withDetail(in []*screensv1.DrawerOption) []*screensv1.DrawerOption {
	out := make([]*screensv1.DrawerOption, 0, len(in))
	for _, o := range in {
		out = append(out, &screensv1.DrawerOption{Value: o.GetValue(), Label: o.GetLabel()})
	}
	return out
}

func options(ctx context.Context, db schooldirectory.Querier, sql string, args ...any) ([]*screensv1.DrawerOption, error) {
	rows, err := db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("adminusers: the drawer's choices: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (*screensv1.DrawerOption, error) {
		o := &screensv1.DrawerOption{}
		err := row.Scan(&o.Value, &o.Label, &o.Detail)
		return o, err
	})
}
