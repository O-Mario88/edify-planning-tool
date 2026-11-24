package screens

import (
	"context"
	"fmt"
	"log/slog"
	"net/url"
	"regexp"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/origin"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectcapacity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
)

// Bulk Add to Project, with Django absent: the drawer the Core Schools list
// and a cluster's roster open (/schools/bulk-assign-project-drawer, which
// the feed never served, so the button was a dead end with or without
// Django) and its save, and the School Directory dialog's save
// (BulkAssignProject), both bulk_assign_project_view.

var bulkProjectDrawerPath = regexp.MustCompile(`^/schools/bulk-assign-project-drawer/?$`)

// BulkEnroller reads and saves bulk Add to Project (projectcapacity.Service).
type BulkEnroller interface {
	BulkEnrol(ctx context.Context, p auth.Principal, codes []string, projectID, reason string, origin activities.Origin) ([]projectcapacity.Said, error)
	BulkChoices(ctx context.Context, p auth.Principal, codes []string) ([]projectcapacity.BulkSchool, int, string, error)
}

// WithBulkEnroller makes bulk Add to Project Go's with Django absent.
func (s *Service) WithBulkEnroller(b BulkEnroller) *Service {
	s.bulkEnroller = b
	return s
}

func (s *Service) bulkProjectQuery(raw string) (url.Values, bool) {
	if s.bulkEnroller == nil || s.existingApp != nil {
		return nil, false
	}
	parsed, err := url.Parse(raw)
	if err != nil || !bulkProjectDrawerPath.MatchString(parsed.Path) {
		return nil, false
	}
	return parsed.Query(), true
}

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// bulkProjectDrawer is partials/schools/bulk_assign_project_drawer.html.
func bulkProjectDrawer(schools []projectcapacity.BulkSchool, outside int, projects []*screensv1.BulkProjectChoice) *screensv1.PageDrawer {
	d := &screensv1.PageDrawer{Title: fmt.Sprintf("Add %d school%s to a project", len(schools), plural(len(schools))), CancelLabel: "Close"}
	d.Items = append(d.Items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: "Selected schools"}})
	for _, sc := range schools {
		d.Items = append(d.Items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: sc.Name + " " + sc.Code}})
	}
	if outside > 0 {
		verb := "are"
		if outside == 1 {
			verb = "is"
		}
		d.Items = append(d.Items, note(fmt.Sprintf("%d selected school%s %s outside your reach and left out.", outside, plural(outside), verb), "warning"))
	}
	switch {
	case len(schools) == 0:
		d.Items = append(d.Items, note("None of the selected schools can be added to a project from here.", "info"))
		return d
	case len(projects) == 0:
		d.Items = append(d.Items, note("No active projects available. Create a project before assigning schools.", "info"))
		return d
	}
	options := []*screensv1.DrawerOption{{Value: "", Label: "Select a project"}}
	for _, pr := range projects {
		options = append(options, &screensv1.DrawerOption{Value: pr.GetValue(), Label: pr.GetLabel(), Detail: pr.GetBlock(), Disabled: pr.GetBlock() != ""})
	}
	d.Items = append(d.Items,
		&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: &screensv1.DrawerField{Name: "project_id", Label: "Project", Kind: "select", Required: true, Options: options}}},
		&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: fmt.Sprintf("Adds the %d selected school%s. Schools already in the project are skipped.", len(schools), plural(len(schools)))}},
	)
	d.HasRequired, d.CanSubmit, d.SubmitLabel, d.CancelLabel = true, true, "Add to project", "Cancel"
	return d
}

func note(text, tone string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: text, Tone: tone}}}
}

func (s *Service) bulkProjectDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	query, ok := s.bulkProjectQuery(rawPath)
	if !ok {
		return nil, false, nil
	}
	schools, outside, refused, err := s.bulkEnroller.BulkChoices(ctx, p, projectcapacity.TickedCodes(query["school_ids"]))
	switch {
	case err != nil:
		return nil, true, err
	case refused != "":
		return &screensv1.GetDrawerResponse{Refusal: refused}, true, nil
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.clock())
	if err != nil {
		return nil, true, err
	}
	projects, err := schooldirectory.BulkProjects(ctx, s.db, p, scope)
	if err != nil {
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: bulkProjectDrawer(schools, outside, projects)}, true, nil
}

func (s *Service) bulkProjectSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (*screensv1.SaveDrawerResponse, bool, error) {
	query, ok := s.bulkProjectQuery(message.GetPath())
	p, signed := auth.PrincipalFrom(ctx)
	if !ok || !signed {
		return nil, false, nil
	}
	said, err := s.bulkEnroller.BulkEnrol(ctx, p, projectcapacity.TickedCodes(query["school_ids"]), message.GetValues()["project_id"],
		message.GetValues()["override_reason"], from)
	if err != nil {
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go bulk Add to Project save failed", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	saved, text := projectcapacity.AsDrawer(said)
	if saved {
		return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(text)}, true, nil
	}
	return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(text)}, true, nil
}

// bulkProjectDialogInGo is the School Directory dialog's save with Django
// absent.
func (s *Service) bulkProjectDialogInGo(ctx context.Context, p auth.Principal, request *connect.Request[screensv1.BulkAssignProjectRequest]) (*screensv1.BulkAssignProjectResponse, bool, error) {
	if s.bulkEnroller == nil || s.existingApp != nil {
		return nil, false, nil
	}
	read := origin.Read(request.Peer().Addr, request.Header(), s.trustProxy, trace.FromContext(ctx).RequestID)
	from := activities.Origin{IP: read.IP, UserAgent: read.UserAgent, CorrelationID: read.CorrelationID}
	req := request.Msg
	said, err := s.bulkEnroller.BulkEnrol(ctx, p, projectcapacity.TickedCodes(req.GetSchoolIds()), req.GetProjectId(), "", from)
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.BulkAssignProjectResponse{Result: projectcapacity.AsDirectory(said)}, true, nil
}
