package screens

import (
	"context"
	"errors"
	"regexp"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
)

// The Start, Salesforce ID and Submit drawers of a visit, drawn as the feed
// reads start_drawer.html, salesforce_id_drawer.html and submit_drawer.html,
// for the visits whose saves Go makes with Django absent.

// lifecycleDrawerPath names the visit and the drawer.
var lifecycleDrawerPath = regexp.MustCompile(`^/activities/([A-Za-z0-9]{1,30})/(start|salesforce-id|submit)/?$`)

const (
	missingWarning = "One or more required items are missing. Programme Lead review may return this activity for correction."
	salesforceHelp = "SV- or SVE- for a visit, TS- for a training, or the record's own Salesforce ID — any one of them."
	completedHelp  = "Today or an earlier day. Done before its planned day, it moves to this day with its cost, and the planned day is free for other work."
)

// LifecycleReader reads a visit for its drawers (internal/activities.Service).
type LifecycleReader interface {
	LifecycleFacts(ctx context.Context, p auth.Principal, activityID string) (activities.LifecycleFacts, error)
}

// lifecycleDrawerInGo serves the drawer when Go saves the visit's form.
func (s *Service) lifecycleDrawerInGo(ctx context.Context, p auth.Principal, path string) (*screensv1.GetDrawerResponse, bool, error) {
	reader, ok := s.starter.(LifecycleReader)
	m := lifecycleDrawerPath.FindStringSubmatch(path)
	if !ok || m == nil || s.existingApp != nil {
		return nil, false, nil
	}
	facts, err := reader.LifecycleFacts(ctx, p, m[1])
	if errors.Is(err, activities.ErrHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	if facts.Session && m[2] != "salesforce-id" {
		return nil, false, nil
	}
	var drawer *screensv1.PageDrawer
	switch m[2] {
	case "start":
		drawer = startDrawer(facts)
	case "salesforce-id":
		today := time.Now().In(schoolplanning.Nairobi)
		drawer = salesforceDrawer(facts, time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, time.UTC))
	default:
		drawer = submitDrawer(facts)
	}
	return &screensv1.GetDrawerResponse{Drawer: drawer}, true, nil
}

// spokenType is the replace_underscore filter.
func spokenType(activityType string) string { return strings.ReplaceAll(activityType, "_", " ") }

func drawerText(text string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: text}}
}

func drawerField(f *screensv1.DrawerField) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: f}}
}

func startDrawer(f activities.LifecycleFacts) *screensv1.PageDrawer {
	return &screensv1.PageDrawer{
		Title: "Start " + spokenType(f.ActivityType) + " at " + f.Place, HasRequired: true,
		Items: []*screensv1.DrawerItem{
			drawerText("The activity moves to Started and the team sees that execution has begun."),
			drawerField(&screensv1.DrawerField{Name: "notes", Label: "Execution or location notes (optional)", Kind: "textarea",
				Placeholder: "e.g. Arrived at the school"}),
		},
		SubmitLabel: "Start activity", CancelLabel: "Cancel", CanSubmit: true,
	}
}

func salesforceDrawer(f activities.LifecycleFacts, today time.Time) *screensv1.PageDrawer {
	items := []*screensv1.DrawerItem{
		drawerField(&screensv1.DrawerField{Name: "salesforce_id", Label: "Salesforce activity ID", Kind: "text", Value: f.SalesforceID,
			Required: true, Help: salesforceHelp, Placeholder: "e.g. SV-11223344, SVE-11223344 or TS-998877"}),
	}
	if f.HandsInWithID {
		day := today.Format(time.DateOnly)
		value := day
		if f.Delivered != nil {
			value = f.Delivered.Format(time.DateOnly)
		}
		items = append(items, drawerField(&screensv1.DrawerField{Name: "actual_delivery_date", Label: "Date completed", Kind: "date",
			Value: value, Required: true, Help: completedHelp, MaxDate: day}))
	}
	return &screensv1.PageDrawer{
		Title: "Enter Salesforce ID for " + f.Place, HasRequired: true, Items: items,
		SubmitLabel: "Save Salesforce ID", CancelLabel: "Cancel", CanSubmit: true,
	}
}

// submitDrawer is submit_drawer.html for a visit: its one readiness line,
// the Salesforce ID (no SSA or headcount line is asked of these visits).
func submitDrawer(f activities.LifecycleFacts) *screensv1.PageDrawer {
	linked := "Missing"
	if f.SalesforceID != "" {
		linked = "Completed"
	}
	items := []*screensv1.DrawerItem{
		drawerText("Readiness"),
		{Kind: &screensv1.DrawerItem_Lines{Lines: &screensv1.PageFacts{Facts: []*screensv1.PageFact{
			{Label: "Salesforce activity ID linked", Value: linked}}}}},
	}
	if f.SalesforceID == "" {
		items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{
			Text: missingWarning, Tone: "warning"}}})
	}
	return &screensv1.PageDrawer{
		Title: "Submit " + spokenType(f.ActivityType) + " for review", Subtitle: f.Place, HasRequired: true, Items: items,
		SubmitLabel: "Submit for review", CancelLabel: "Cancel", CanSubmit: true,
	}
}
