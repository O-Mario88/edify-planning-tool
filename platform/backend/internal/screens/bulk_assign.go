package screens

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"strings"
	"time"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The bulk hand-over a list's tick bar opens (planning_views.
// bulk_assign_partner_drawer_view and bulk_action_view's "partner"), drawn
// and saved in Go with Django absent.

const (
	bulkAssignDrawerPath = "/planning/bulk-assign-partner-drawer"
	bulkAssignEvery      = "Every selected school is handed over for this reason. No activity, cost or budget line is created until it is scheduled."
	bulkAssignDay        = "The day this assignment is made. The partner chooses the date of the work."
)

// BulkAssigner is the bulk hand-over's read and save (internal/activities.Service).
type BulkAssigner interface {
	BulkAssignRows(ctx context.Context, p auth.Principal, values []string) ([]activities.BulkAssignRow, int, error)
	BulkAssignPartner(ctx context.Context, p auth.Principal, req activities.BulkAssignRequest, origin activities.Origin) (activities.Answer, error)
}

// WithBulkAssign makes the tick bar's Assign to partner Go's with Django absent.
func (s *Service) WithBulkAssign(saver BulkAssigner) *Service {
	s.bulkAssign = saver
	return s
}

func (s *Service) bulkAssignTaken(path string) (url.Values, bool) {
	if s.bulkAssign == nil || s.existingApp != nil {
		return nil, false
	}
	pathOnly, rawQuery, _ := strings.Cut(path, "?")
	if strings.TrimSuffix(pathOnly, "/") != bulkAssignDrawerPath {
		return nil, false
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return nil, false
	}
	return query, true
}

// bulkAssignDrawerInGo is bulk_assign_partner_drawer_view.
func (s *Service) bulkAssignDrawerInGo(ctx context.Context, p auth.Principal, path string) (*screensv1.GetDrawerResponse, bool, error) {
	query, ok := s.bulkAssignTaken(path)
	if !ok || p.InActingAppointment || p.StaffProfileID == "" {
		return nil, false, nil
	}
	if !coreforms.MayAssign(p.ActiveRole) {
		return &screensv1.GetDrawerResponse{Refusal: coreforms.AssignPartnerRefused}, true, nil
	}
	rows, outside, err := s.bulkAssign.BulkAssignRows(ctx, p, query["school_ids"])
	if errors.Is(err, activities.ErrHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	partners, err := coreforms.NewService(s.db, s.clock).AssignablePartners(ctx)
	if err != nil {
		return nil, true, fmt.Errorf("screens: reading the assignable partners: %w", err)
	}
	followUpNamed, err := activities.FollowUpNeedsTraining(ctx, s.db, p.Country, schooldirectory.OperationalFY(time.Now()))
	if err != nil {
		return nil, true, fmt.Errorf("screens: reading the year's follow-up rule: %w", err)
	}
	return &screensv1.GetDrawerResponse{Drawer: bulkAssignDrawer(rows, outside, partners, followUpNamed)}, true, nil
}

// bulkAssignDrawer is bulk_assign_partner_drawer.html. Each school is its
// name and code, its notes beside it (the feed ran them together, and read a
// lone school as a fact without its name).
func bulkAssignDrawer(rows []activities.BulkAssignRow, outside int, partners []coreforms.Partner, followUpNamed bool) *screensv1.PageDrawer {
	assignable := 0
	var items []*screensv1.DrawerItem
	for _, row := range rows {
		items = append(items, drawerText(row.School.Name+" "+row.School.Code))
		if row.OK {
			assignable++
		} else {
			items = append(items, drawerText("Not included: "+row.Reason))
		}
		for _, note := range row.ClosedTo {
			items = append(items, drawerText(note))
		}
	}
	if outside > 0 {
		items = append(items, drawerText(fmt.Sprintf("%d selected %s %s outside your planning portfolio and left out.",
			outside, pluralWord(outside, "school", "schools"), pluralWord(outside, "is", "are"))))
	}
	count := fmt.Sprintf("%d %s", assignable, pluralWord(assignable, "school", "schools"))
	d := &screensv1.PageDrawer{Title: "Assign to partner", Subtitle: count, HasRequired: true, CancelLabel: "Cancel", Items: items}
	if assignable == 0 {
		return d
	}
	partner := &screensv1.DrawerField{Name: "partner_id", Label: "Partner", Kind: "select", Required: true,
		Options: []*screensv1.DrawerOption{{Value: "", Label: "Select a partner…"}}}
	for _, p := range partners {
		partner.Options = append(partner.Options, &screensv1.DrawerOption{Value: p.ID, Label: p.Name})
	}
	purpose := &screensv1.DrawerField{Name: "purpose_of_visit", Label: "Reason for assigning", Kind: "select", Required: true,
		Options: []*screensv1.DrawerOption{{Value: "", Label: "Select a reason…"}}}
	for _, choice := range activities.PartnerPurposes() {
		if choice[0] == "training_follow_up" && followUpNamed {
			continue
		}
		purpose.Options = append(purpose.Options, &screensv1.DrawerOption{Value: choice[0], Label: choice[1]})
	}
	if followUpNamed {
		purpose.Help = "A Training Follow Up names the training it follows, so it is assigned from each school's own Assign."
	}
	d.Items = append(d.Items, drawerField(partner), drawerField(purpose), drawerText(bulkAssignEvery), drawerText(bulkAssignDay))
	d.SubmitLabel, d.CanSubmit = "Assign "+count, true
	return d
}

// bulkAssignInGo is bulk_action_view's "partner", posted from the drawer.
func (s *Service) bulkAssignInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	query, ok := s.bulkAssignTaken(message.GetPath())
	p, signed := auth.PrincipalFrom(ctx)
	if !ok || !signed {
		return nil, false, nil
	}
	if !coreforms.MayAssign(p.ActiveRole) {
		return &screensv1.SaveDrawerResponse{Saved: false, Error: coreforms.AssignPartnerRefused}, true, nil
	}
	values := message.GetValues()
	saved, err := s.bulkAssign.BulkAssignPartner(ctx, p, activities.BulkAssignRequest{Codes: query["school_ids"],
		PartnerID: values["partner_id"], Purpose: values["purpose_of_visit"], Course: values["training_course_id"],
		Focus: values["focus_intervention"]}, from)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go bulk hand-over failed", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(saved.Message)}, true, nil
}
