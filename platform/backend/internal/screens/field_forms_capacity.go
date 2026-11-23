package screens

import (
	"context"
	"strings"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectcapacity"
)

const (
	maxWithdrawalReason = 500
	minCapacitySchools  = 1
)

// capacitySetForm is project_capacity_set_view opened.
func capacitySetForm(ctx context.Context, s *Service, p auth.Principal, req fieldFormRequest) (*screensv1.PageDrawer, error) {
	form, err := projectcapacity.NewService(s.db, s.now).SetCapacityForm(ctx, p, strings.TrimSpace(req.query.Get("project")))
	if err != nil {
		return nil, err
	}
	return capacitySetDrawer(form), nil
}

// capacitySetDrawer is capacity_drawer.html for a new allocation. Someone who
// already holds one is listed but not selectable: theirs is edited from its row.
func capacitySetDrawer(form projectcapacity.SetForm) *screensv1.PageDrawer {
	projects := make([]*screensv1.DrawerOption, 0, len(form.Projects)+1)
	projects = append(projects, &screensv1.DrawerOption{Label: "Choose a project"})
	for _, choice := range form.Projects {
		projects = append(projects, &screensv1.DrawerOption{Value: choice.Value, Label: choice.Label})
	}
	first := "Choose the project first"
	if form.Project != "" {
		first = "Choose a staff member"
	}
	staff := make([]*screensv1.DrawerOption, 0, len(form.Staff)+1)
	staff = append(staff, &screensv1.DrawerOption{Label: first})
	for _, choice := range form.Staff {
		option := &screensv1.DrawerOption{Value: choice.Value, Label: choice.Label}
		if choice.Taken {
			option.Disabled = true
			option.Label += " — already allocated, edit from the table"
		}
		staff = append(staff, option)
	}
	staffField := &screensv1.DrawerField{Name: "staff_id", Label: "Staff member", Kind: "select", Required: true,
		ReadOnly: form.Project == "", Options: staff}
	if form.Project != "" && len(form.Staff) == 0 {
		staffField.Help = "No active CCEO or Programme Lead works in this project's country."
	}
	return &screensv1.PageDrawer{
		Title:       "Set staff capacity",
		HasRequired: true,
		SubmitLabel: "Save Capacity",
		CancelLabel: "Cancel",
		CanSubmit:   true,
		Items: []*screensv1.DrawerItem{
			formField(&screensv1.DrawerField{Name: "project_id", Label: "Project", Kind: "select", Value: form.Project,
				Required: true, Options: projects}),
			formField(staffField),
			formField(&screensv1.DrawerField{Name: "max_schools", Label: "Maximum schools", Kind: "number", Required: true,
				Help: "The most schools this staff member can add to this project. Assigned and remaining are counted for you.",
				Min:  proto.Float64(minCapacitySchools), Step: proto.Float64(1)}),
		},
	}
}

// capacityWithdrawForm is project_withdraw_school_view opened. An enrolment
// this reader may not take out is not there for them.
func capacityWithdrawForm(ctx context.Context, s *Service, p auth.Principal, req fieldFormRequest) (*screensv1.PageDrawer, error) {
	form, err := projectcapacity.NewService(s.db, s.now).WithdrawSchoolForm(ctx, p, strings.TrimSpace(req.query.Get("enrolment")))
	if err != nil {
		return nil, err
	}
	if form == nil {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "This was not found, or it is not yours to view.")
	}
	return withdrawSchoolDrawer(*form), nil
}

// withdrawSchoolDrawer is withdraw_school_drawer.html: the block and its
// reason, or the confirmation with a required reason.
func withdrawSchoolDrawer(form projectcapacity.WithdrawForm) *screensv1.PageDrawer {
	facts := &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: []*screensv1.PageFact{
		{Label: "School", Value: form.School},
		{Label: "Project", Value: form.Project},
		{Label: "Assigned", Value: form.Assigned},
	}}}}
	if form.Block != nil {
		return &screensv1.PageDrawer{
			Title: "Withdraw school", HasRequired: true, CancelLabel: "Close",
			Items: []*screensv1.DrawerItem{facts, reviewNote(form.Block.Title+" "+form.Block.Message, "warning")},
		}
	}
	note := "This school has not entered project execution and can be withdrawn."
	if form.Holder != "" {
		note += " Its place returns to " + form.Holder + "'s allocation."
	}
	reasons := []*screensv1.DrawerOption{{Label: "Choose a reason"}}
	reasons = append(reasons, choiceOptions(projectcapacity.WithdrawalReasons())...)
	return &screensv1.PageDrawer{
		Title:       "Withdraw school",
		HasRequired: true,
		SubmitLabel: "Withdraw School",
		CancelLabel: "Cancel",
		CanSubmit:   true,
		Items: []*screensv1.DrawerItem{
			facts,
			reviewNote(note, "info"),
			formField(&screensv1.DrawerField{Name: "reason_code", Label: "Reason", Kind: "select", Required: true, Options: reasons}),
			formField(&screensv1.DrawerField{Name: "reason_other", Label: "Say why", Kind: "textarea", Required: true,
				MaxLength: proto.Int32(maxWithdrawalReason),
				ShowWhen:  []*screensv1.DrawerCondition{{Field: "reason_code", Values: []string{"other"}}}}),
		},
	}
}
