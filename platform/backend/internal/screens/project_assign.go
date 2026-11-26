package screens

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"slices"
	"strings"
	"time"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The coordinator's hand-over of project schools to a partner
// (planning_views.special_projects_bulk_partner_view), drawn and saved in
// Go with Django absent.

const (
	projectAssignPath       = "/projects/planning/bulk-partner"
	projectAssignPageDenied = "Access Denied: Your active role does not have permission to view Projects."
	projectAssignDenied     = "You do not have permission to assign to a partner."
	projectAssignEvery      = "Every school listed is handed over for this purpose. The activity, final cost and budget lines are created when the partner schedules it."
	projectAssignNoListed   = "None of the projects' partners can take new work"
	projectAssignWhy        = "They are not one of this project's partners"
)

// ProjectAssigner is the project hand-over's read and save
// (internal/activities.Service).
type ProjectAssigner interface {
	ProjectAssignSelectionFor(ctx context.Context, p auth.Principal, raw string) (activities.ProjectAssignSelection, error)
	AssignProjectPartner(ctx context.Context, p auth.Principal, req activities.ProjectAssignRequest, origin activities.Origin) (activities.Answer, error)
}

// WithProjectAssign makes the project hand-over Go's with Django absent.
func (s *Service) WithProjectAssign(saver ProjectAssigner) *Service {
	s.projectAssign = saver
	return s
}

func (s *Service) projectAssignTaken(path string) (url.Values, bool) {
	if s.projectAssign == nil || s.existingApp != nil {
		return nil, false
	}
	pathOnly, rawQuery, _ := strings.Cut(path, "?")
	if strings.TrimSuffix(pathOnly, "/") != projectAssignPath {
		return nil, false
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return nil, false
	}
	return query, true
}

// projectAssignRefusal is the view's doors: the Projects page, then
// can_assign_to_partner.
func projectAssignRefusal(p auth.Principal) string {
	switch {
	case !pageaccess.CanOpen(p.ActiveRole, false, projectAssignPath):
		return projectAssignPageDenied
	case !coreforms.MayAssign(p.ActiveRole):
		return projectAssignDenied
	}
	return ""
}

// projectAssignDrawerInGo is the view's GET.
func (s *Service) projectAssignDrawerInGo(ctx context.Context, p auth.Principal, path string) (*screensv1.GetDrawerResponse, bool, error) {
	query, ok := s.projectAssignTaken(path)
	if !ok || p.InActingAppointment || p.StaffProfileID == "" {
		return nil, false, nil
	}
	if refusal := projectAssignRefusal(p); refusal != "" {
		return &screensv1.GetDrawerResponse{Refusal: refusal}, true, nil
	}
	sel, err := s.projectAssign.ProjectAssignSelectionFor(ctx, p, query.Get("assignments"))
	if errors.Is(err, activities.ErrHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	if len(sel.Rows) == 0 {
		return &screensv1.GetDrawerResponse{Refusal: "No in-scope project schools were selected."}, true, nil
	}
	if len(sel.Included()) == 0 {
		return &screensv1.GetDrawerResponse{Drawer: drawerNotAvailable(projectAssignNothing(sel))}, true, nil
	}
	partners, err := coreforms.NewService(s.db, s.clock).AssignablePartners(ctx)
	if err != nil {
		return nil, true, fmt.Errorf("screens: reading the assignable partners: %w", err)
	}
	followUpNamed, err := activities.FollowUpNeedsTraining(ctx, s.db, p.Country, schooldirectory.OperationalFY(time.Now()))
	if err != nil {
		return nil, true, fmt.Errorf("screens: reading the year's follow-up rule: %w", err)
	}
	return &screensv1.GetDrawerResponse{Drawer: projectAssignDrawer(sel, partners, followUpNamed)}, true, nil
}

// projectAssignNothing is the view's words when no selected school may go
// to a partner.
func projectAssignNothing(sel activities.ProjectAssignSelection) string {
	if len(sel.Rows) == 1 {
		return sel.Rows[0].Reason
	}
	return "None of the selected schools can be assigned to a partner: each is a Champion school, which staff deliver themselves, or is closed."
}

// drawerNotAvailable is drawer_error.html as the feed reads it.
func drawerNotAvailable(message string) *screensv1.PageDrawer {
	return &screensv1.PageDrawer{Title: "Not available", HasRequired: true, CancelLabel: "Close",
		Items: []*screensv1.DrawerItem{note(message, "warning")}}
}

// projectAssignDrawer is partials/projects/bulk_partner_drawer.html as the
// feed reads it: the training choice is drawn only once In-school Training
// is chosen, which the feed does not see.
func projectAssignDrawer(sel activities.ProjectAssignSelection, partners []coreforms.Partner, followUpNamed bool) *screensv1.PageDrawer {
	included := len(sel.Included())
	items := []*screensv1.DrawerItem{drawerText("Selected project schools")}
	for _, r := range sel.Rows {
		line := r.SchoolName + " · " + r.ProjectName
		if r.Reason != "" {
			line += " · Not included: " + r.Reason
		}
		items = append(items, drawerText(line))
	}
	partner := &screensv1.DrawerField{Name: "partner_id", Label: "Partner organization", Kind: "select", Required: true,
		Options: []*screensv1.DrawerOption{{Value: "", Label: "Select partner…"}}}
	listed, others := partners, []coreforms.Partner(nil)
	if sel.Listed {
		listed, others = nil, nil
		for _, p := range partners {
			if slices.Contains(sel.ProjectPartners, p.ID) {
				listed = append(listed, p)
			} else {
				others = append(others, p)
			}
		}
		if len(listed) == 0 {
			partner.Options = append(partner.Options, &screensv1.DrawerOption{Label: projectAssignNoListed, Disabled: true})
		}
	}
	for _, p := range append(listed, others...) {
		partner.Options = append(partner.Options, &screensv1.DrawerOption{Value: p.ID, Label: p.Name})
	}
	why := &screensv1.DrawerField{Name: "override_reason", Label: "Why this partner", Kind: "textarea", Placeholder: projectAssignWhy}
	purpose := &screensv1.DrawerField{Name: "purpose_of_visit", Label: "Purpose of assignment", Kind: "select", Required: true,
		Options: []*screensv1.DrawerOption{{Value: "", Label: "Select purpose…"}}}
	for _, choice := range activities.PartnerPurposes() {
		if choice[0] == "training_follow_up" && followUpNamed {
			continue
		}
		purpose.Options = append(purpose.Options, &screensv1.DrawerOption{Value: choice[0], Label: choice[1]})
	}
	items = append(items, drawerField(partner), drawerField(why), drawerField(purpose), drawerText(bulkAssignDay), drawerText(projectAssignEvery))
	return &screensv1.PageDrawer{
		Title:       fmt.Sprintf("Assign %d %s to a partner", included, pluralWord(included, "project school", "project schools")),
		HasRequired: true, CancelLabel: "Cancel", Items: items,
		SubmitLabel: fmt.Sprintf("Assign %d %s", included, pluralWord(included, "school", "schools")), CanSubmit: true,
	}
}

// projectAssignInGo is the view's POST.
func (s *Service) projectAssignInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	query, ok := s.projectAssignTaken(message.GetPath())
	p, signed := auth.PrincipalFrom(ctx)
	if !ok || !signed {
		return nil, false, nil
	}
	if refusal := projectAssignRefusal(p); refusal != "" {
		return &screensv1.SaveDrawerResponse{Saved: false, Error: refusal}, true, nil
	}
	values := message.GetValues()
	assignments := query.Get("assignments")
	if v, posted := values["assignments"]; posted {
		assignments = v
	}
	saved, err := s.projectAssign.AssignProjectPartner(ctx, p, activities.ProjectAssignRequest{Assignments: assignments,
		PartnerID: values["partner_id"], Purpose: values["purpose_of_visit"], CourseID: values["training_course_id"],
		Focus: values["focus_intervention"], OverrideReason: values["override_reason"]}, from)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go project hand-over failed", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(saved.Message)}, true, nil
}
