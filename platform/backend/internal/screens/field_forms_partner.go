package screens

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnercapabilities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
)

const maxPartnerName = 255

// partnerRoleChoices is PartnerRole.choices.
var partnerRoleChoices = [][2]string{{"delivery", "Delivery Partner"}, {"loan", "Loan Partner"}}

// partnerCreateForm is create_partner_view opened: the organisation record
// only. Nothing here creates a sign-in account.
func partnerCreateForm(ctx context.Context, s *Service, p auth.Principal, _ fieldFormRequest) (*screensv1.PageDrawer, error) {
	rows, err := s.db.Query(ctx, `SELECT name FROM region ORDER BY name`)
	if err != nil {
		return nil, fmt.Errorf("screens: reading the regions: %w", err)
	}
	regions, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("screens: reading a region: %w", err)
	}
	groups, err := partnercapabilities.Groups(ctx, s.db, ssaInterventionChoices)
	if err != nil {
		return nil, err
	}
	managesLogins := rbac.Grants(p.ActiveRole, rbac.PartnerUserManage) && rbac.Grants(p.ActiveRole, rbac.UserManage)
	return partnerCreateDrawer(regions, groups, managesLogins), nil
}

// partnerCreateDrawer is create_partner_drawer.html. Its tick lists are one
// field each, so every box keeps its words on the phone and the web: an
// activity names its interventions on its second line.
func partnerCreateDrawer(regions []string, groups []partnercapabilities.Group, managesLogins bool) *screensv1.PageDrawer {
	text := func(name, label, kind, placeholder string) *screensv1.DrawerItem {
		return formField(&screensv1.DrawerField{Name: name, Label: label, Kind: kind, Placeholder: placeholder})
	}
	items := []*screensv1.DrawerItem{
		textLine("The organisation starts inactive and receives no work until it is activated."),
		formField(&screensv1.DrawerField{Name: "name", Label: "Organisation name", Kind: "text", Required: true,
			Placeholder: "e.g. Hope Education Initiative", MaxLength: proto.Int32(maxPartnerName)}),
		formField(&screensv1.DrawerField{Name: "partner_role", Label: "Partner role", Kind: "select", Required: true, Value: partnerRoleChoices[0][0],
			Help: "A Loan Partner lends through the loan workflow and is not handed school visits or trainings.", Options: choiceOptions(partnerRoleChoices)}),
		partnerRegionsItem(regions),
		headingLine("Interventions and activities"),
		textLine("Tick everything it delivers. An intervention on its own is enough."),
	}
	items = append(items, partnerCapabilityItems(groups)...)
	login := "No sign-in account is created here. A user administrator is told the organisation is waiting and sets up its logins."
	if managesLogins {
		login = "No sign-in account is created here. Set up the organisation's login from the Partner Organisations directory once it is saved."
	}
	items = append(items,
		text("contact_person", "Contact person", "text", "e.g. Jane Doe"),
		text("email", "Organisation email", "email", "contact@partner.org"),
		text("phone", "Phone number", "tel", "+256 700 000 000"),
		text("expertise", "Expertise", "text", "e.g. Literacy, leadership training"),
		text("notes", "Notes", "textarea", "Anything the team should know"),
		reviewNote(login, "info"),
	)
	return &screensv1.PageDrawer{
		Title:       "Add partner organisation",
		HasRequired: true,
		SubmitLabel: "Add organisation",
		CancelLabel: "Cancel",
		CanSubmit:   true,
		Items:       items,
	}
}

func partnerRegionsItem(regions []string) *screensv1.DrawerItem {
	if len(regions) == 0 {
		return reviewNote("No regions are set up yet. Add the organisation now and record its regions once they are.", "info")
	}
	options := make([]*screensv1.DrawerOption, len(regions))
	for i, region := range regions {
		options[i] = &screensv1.DrawerOption{Value: region, Label: region}
	}
	return formField(&screensv1.DrawerField{Name: "region_names", Label: "Regions", Kind: "checklist",
		Help: "Tick every region it works in.", Options: options})
}

// partnerCapabilityItems draws one list of interventions and one of
// activities. An activity under two interventions is one box.
func partnerCapabilityItems(groups []partnercapabilities.Group) []*screensv1.DrawerItem {
	interventions := make([]*screensv1.DrawerOption, 0, len(groups))
	var activities []*screensv1.DrawerOption
	under := map[string][]string{}
	for _, group := range groups {
		interventions = append(interventions, &screensv1.DrawerOption{Value: group.Key, Label: group.Label, Detail: activityCount(len(group.Activities))})
		for _, activity := range group.Activities {
			if _, seen := under[activity.Code]; !seen {
				activities = append(activities, &screensv1.DrawerOption{Value: activity.Code, Label: activity.Name})
			}
			under[activity.Code] = append(under[activity.Code], group.Label)
		}
	}
	for _, activity := range activities {
		activity.Detail = strings.Join(under[activity.GetValue()], " · ")
	}
	var items []*screensv1.DrawerItem
	if len(interventions) > 0 {
		items = append(items, formField(&screensv1.DrawerField{Name: "ssa_interventions", Label: "Interventions", Kind: "checklist", Options: interventions}))
	}
	if len(activities) == 0 {
		return append(items, reviewNote("The activity catalogue has nothing a partner may deliver yet. Add the organisation now and record what it does once the catalogue does.", "info"))
	}
	return append(items, formField(&screensv1.DrawerField{Name: "activity_codes", Label: "Activities", Kind: "checklist", Options: activities}))
}

func activityCount(n int) string {
	switch n {
	case 0:
		return ""
	case 1:
		return "1 activity"
	}
	return fmt.Sprintf("%d activities", n)
}
