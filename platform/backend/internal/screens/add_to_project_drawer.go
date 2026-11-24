package screens

import (
	"context"
	"regexp"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The Add to Project drawer a page links to by its path (the Core Schools
// list's row action, /schools/<id>/assign-to-project), drawn from the same
// form the school actions read, as assign_to_project_drawer.html reads. Its
// save is the path's own SaveDrawer. The feed never served this drawer, so the
// link was a dead end on the web with or without Django.

var addToProjectDrawerPath = regexp.MustCompile(`^/schools/([A-Za-z0-9]{1,30})/assign-to-project/?$`)

func (s *Service) addToProjectDrawerInGo(ctx context.Context, p auth.Principal, path string) (*screensv1.GetDrawerResponse, bool, error) {
	m := addToProjectDrawerPath.FindStringSubmatch(path)
	if m == nil {
		return nil, false, nil
	}
	answer, served, err := s.getAddToProjectInGo(ctx, p, m[1])
	if !served || err != nil {
		return nil, served, err
	}
	form := answer.GetForm()
	if form.GetRefused() != "" {
		return &screensv1.GetDrawerResponse{Refusal: form.GetRefused()}, true, nil
	}
	return &screensv1.GetDrawerResponse{Drawer: addToProjectPageDrawer(form)}, true, nil
}

func actionChoiceOptions(empty string, choices []*screensv1.ActionChoice) []*screensv1.DrawerOption {
	out := []*screensv1.DrawerOption{{Value: "", Label: empty}}
	for _, c := range choices {
		out = append(out, &screensv1.DrawerOption{Value: c.GetValue(), Label: c.GetLabel(), Disabled: c.GetDisabled()})
	}
	return out
}

// addToProjectPageDrawer is assign_to_project_drawer.html.
func addToProjectPageDrawer(form *screensv1.AddToProjectForm) *screensv1.PageDrawer {
	d := &screensv1.PageDrawer{Title: form.GetTitle(), HasRequired: true, CancelLabel: "Cancel"}
	if notice := form.GetEmptyNotice(); notice != "" {
		d.Items = []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: notice, Tone: "info"}}}}
		return d
	}
	d.Items = []*screensv1.DrawerItem{
		drawerField(&screensv1.DrawerField{Name: "project_id", Label: "Project", Kind: "select", Required: true,
			Options: actionChoiceOptions("Select a project", form.GetProjects())}),
		drawerField(&screensv1.DrawerField{Name: "project_type", Label: "Project type", Kind: "text", Placeholder: "e.g. Curriculum support"}),
		drawerField(&screensv1.DrawerField{Name: "participation_type", Label: "Expected support type", Kind: "select",
			Options: actionChoiceOptions("Select a support type", form.GetSupportTypes())}),
		drawerField(&screensv1.DrawerField{Name: "coordinator_id", Label: "Project coordinator", Kind: "select",
			Options: actionChoiceOptions("Project default", form.GetCoordinators())}),
		drawerField(&screensv1.DrawerField{Name: "support_area", Label: "Focus area", Kind: "select",
			Options: actionChoiceOptions("Select a focus area", form.GetFocusAreas())}),
		drawerField(&screensv1.DrawerField{Name: "start_date", Label: "Start date", Kind: "date"}),
		drawerField(&screensv1.DrawerField{Name: "notes", Label: "Notes", Kind: "textarea", Placeholder: "Objectives for this school"}),
	}
	d.SubmitLabel, d.CanSubmit = "Assign to project", true
	return d
}

// addToProjectSaveInGo is the drawer's save: the same Add to Project the
// school actions make (assign_to_project_flow).
func (s *Service) addToProjectSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	m := addToProjectDrawerPath.FindStringSubmatch(strings.SplitN(message.GetPath(), "?", 2)[0])
	p, ok := auth.PrincipalFrom(ctx)
	if m == nil || !ok {
		return nil, false, nil
	}
	v := message.GetValues()
	answer, served, err := s.addToProjectInGo(ctx, p, &screensv1.AddToProjectRequest{SchoolId: m[1], ProjectId: v["project_id"],
		ProjectType: v["project_type"], ParticipationType: v["participation_type"], StartDate: v["start_date"],
		SupportArea: v["support_area"], CoordinatorId: v["coordinator_id"], Notes: v["notes"]})
	if !served || err != nil {
		return nil, served, err
	}
	r := answer.GetResult()
	if r.GetSaved() {
		return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(r.GetMessage())}, true, nil
	}
	why := r.GetRefused()
	if why == "" {
		why = r.GetError()
	}
	return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(why)}, true, nil
}
