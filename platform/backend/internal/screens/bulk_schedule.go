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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The bulk Schedule a list's tick bar opens (planning_views.
// bulk_schedule_drawer_view and bulk_schedule_action_view), drawn and saved
// in Go with Django absent.

const (
	bulkScheduleDrawerPath = "/planning/bulk-schedule-drawer"
	bulkScheduleNote       = "Each school gets its own costed activity on your plan; a visit at a Core School takes its package slot. A school the scheduling rules refuse is named and left out."
)

// BulkScheduler is the bulk Schedule's read and save (internal/activities.Service).
type BulkScheduler interface {
	TickedSchools(ctx context.Context, p auth.Principal, values []string) ([]activities.TickedSchool, int, error)
	BulkSchedule(ctx context.Context, p auth.Principal, req activities.BulkScheduleRequest, origin activities.Origin) (activities.Answer, error)
}

// WithBulkSchedule makes the tick bar's Schedule Go's with Django absent.
func (s *Service) WithBulkSchedule(saver BulkScheduler) *Service {
	s.bulkSchedule = saver
	return s
}

func (s *Service) bulkScheduleTaken(path string) (url.Values, bool) {
	if s.bulkSchedule == nil || s.existingApp != nil {
		return nil, false
	}
	pathOnly, rawQuery, _ := strings.Cut(path, "?")
	if strings.TrimSuffix(pathOnly, "/") != bulkScheduleDrawerPath {
		return nil, false
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return nil, false
	}
	return query, true
}

// bulkScheduleDrawerInGo is bulk_schedule_drawer_view.
func (s *Service) bulkScheduleDrawerInGo(ctx context.Context, p auth.Principal, path string) (*screensv1.GetDrawerResponse, bool, error) {
	query, ok := s.bulkScheduleTaken(path)
	if !ok || p.InActingAppointment || p.StaffProfileID == "" {
		return nil, false, nil
	}
	if refusal := activities.ScheduleRefusal(p.ActiveRole); refusal != "" {
		return &screensv1.GetDrawerResponse{Refusal: refusal}, true, nil
	}
	schools, posted, err := s.bulkSchedule.TickedSchools(ctx, p, query["school_ids"])
	if errors.Is(err, activities.ErrHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	followUpNamed, err := activities.FollowUpNeedsTraining(ctx, s.db, p.Country, schooldirectory.OperationalFY(time.Now()))
	if err != nil {
		return nil, true, fmt.Errorf("screens: reading the year's follow-up rule: %w", err)
	}
	return &screensv1.GetDrawerResponse{Drawer: bulkScheduleDrawer(schools, posted-len(schools), followUpNamed,
		coreforms.SchedulesVisitsOnly(p.ActiveRole))}, true, nil
}

// bulkScheduleDrawer is bulk_schedule_drawer.html as the feed reads it.
func bulkScheduleDrawer(schools []activities.TickedSchool, outside int, followUpNamed, visitsOnly bool) *screensv1.PageDrawer {
	n := len(schools)
	label := fmt.Sprintf("Schedule %d %s", n, pluralWord(n, "school", "schools"))
	d := &screensv1.PageDrawer{Title: label, HasRequired: true, CancelLabel: "Cancel",
		Items: []*screensv1.DrawerItem{drawerText("Selected schools")}}
	for _, school := range schools {
		d.Items = append(d.Items, drawerText(school.Name+" "+school.Code))
	}
	if outside > 0 {
		d.Items = append(d.Items, drawerText(fmt.Sprintf("%d selected %s %s outside your planning portfolio and left out.",
			outside, pluralWord(outside, "school", "schools"), pluralWord(outside, "is", "are"))))
	}
	if n == 0 {
		return d
	}
	purpose := &screensv1.DrawerField{Name: "purpose_of_visit", Label: "Purpose of visit", Kind: "select", Required: true,
		Options: []*screensv1.DrawerOption{{Value: "", Label: "Select purpose…"}}}
	for _, choice := range activities.StaffPurposes() {
		if (choice[0] == "training_follow_up" && followUpNamed) || (visitsOnly && slices.Contains(coreforms.TrainingPurposes, choice[0])) {
			continue
		}
		purpose.Options = append(purpose.Options, &screensv1.DrawerOption{Value: choice[0], Label: choice[1]})
	}
	if followUpNamed {
		purpose.Help = "A Training Follow Up names the training it follows, so it is scheduled from each school's own Schedule."
	}
	d.Items = append(d.Items, drawerField(purpose),
		drawerField(&screensv1.DrawerField{Name: "scheduled_date", Label: "Delivery date", Kind: "date", Required: true}),
		&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: bulkScheduleNote, Tone: "warning"}}})
	d.SubmitLabel, d.CanSubmit = label, true
	return d
}

func pluralWord(n int, one, many string) string {
	if n == 1 {
		return one
	}
	return many
}

// bulkScheduleInGo is bulk_schedule_action_view, posted from the drawer.
func (s *Service) bulkScheduleInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	query, ok := s.bulkScheduleTaken(message.GetPath())
	p, signed := auth.PrincipalFrom(ctx)
	if !ok || !signed {
		return nil, false, nil
	}
	values := message.GetValues()
	codes := query["school_ids"]
	if posted := values["school_ids"]; posted != "" {
		codes = append(codes, posted)
	}
	saved, err := s.bulkSchedule.BulkSchedule(ctx, p, activities.BulkScheduleRequest{Codes: codes,
		Purpose: values["purpose_of_visit"], Course: values["training_course_id"], Date: values["scheduled_date"],
		Focus: values["focus_intervention"]}, from)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go bulk schedule failed", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	words := collapse(saved.Message)
	if notice := collapse(saved.Notice); notice != "" {
		words += " " + notice
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: words}, true, nil
}
