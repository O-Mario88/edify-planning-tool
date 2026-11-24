package screens

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The group reschedule and cancel drawers the selection bar opens
// (activity_group_views._drawer), drawn as the feed reads
// group_reschedule_drawer.html and group_cancel_drawer.html, for the
// selections whose saves Go makes with Django absent.

const (
	groupMoveHelp   = "Every activity above moves to this date. An activity of several days keeps its length."
	groupCancelText = "Each stays on the record as Cancelled and leaves the plan. Its cost and any undisbursed advance are withdrawn."
)

// GroupSelector reads a selection for its drawer (internal/activities.Service).
type GroupSelector interface {
	GroupSelection(ctx context.Context, p auth.Principal, raw []string, cancel bool) (ready, left []activities.GroupPick, moneyMoved int, err error)
}

// groupSelector is the saver that reads the selection: the group's own.
func (s *Service) groupSelector(cancel bool) (GroupSelector, bool) {
	var saver any = s.groupMoves
	if cancel {
		saver = s.groupCancels
	}
	selector, ok := saver.(GroupSelector)
	return selector, ok && saver != nil
}

// groupReadyIDs is the drawer's hidden activity_ids: the ticked activities
// the action changes, for a save posted from the drawer without them.
func (s *Service) groupReadyIDs(ctx context.Context, p auth.Principal, ids string, cancel bool) []string {
	selector, ok := s.groupSelector(cancel)
	if !ok {
		return nil
	}
	ready, _, _, err := selector.GroupSelection(ctx, p, strings.Split(ids, ","), cancel)
	if err != nil {
		return nil
	}
	out := make([]string, len(ready))
	for i, pick := range ready {
		out[i] = pick.ActivityID
	}
	return out
}

// groupDrawerInGo serves the drawer when Go saves the selection.
func (s *Service) groupDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	pathOnly, rawQuery, _ := strings.Cut(rawPath, "?")
	pathOnly = strings.TrimSuffix(pathOnly, "/")
	selector, ok := s.groupSelector(pathOnly == groupCancelPath)
	if !ok || s.existingApp != nil || (pathOnly != groupReschedulePath && pathOnly != groupCancelPath) {
		return nil, false, nil
	}
	query, err := url.ParseQuery(rawQuery)
	if err != nil {
		return nil, false, nil
	}
	cancel := pathOnly == groupCancelPath
	ready, left, moneyMoved, err := selector.GroupSelection(ctx, p, strings.Split(query.Get("ids"), ","), cancel)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.GetDrawerResponse{Drawer: groupRefusedDrawer(cancel, refusal.Message)}, true, nil
	case err != nil:
		return nil, true, err
	}
	if cancel {
		return &screensv1.GetDrawerResponse{Drawer: cancelSelectionDrawer(ready, left, moneyMoved)}, true, nil
	}
	return &screensv1.GetDrawerResponse{Drawer: moveSelectionDrawer(ready, left)}, true, nil
}

func groupTitle(cancel bool) string {
	if cancel {
		return "Cancel selected activities"
	}
	return "Reschedule selected activities"
}

// groupRefusedDrawer is the drawer's {% if error %} branch.
func groupRefusedDrawer(cancel bool, message string) *screensv1.PageDrawer {
	return &screensv1.PageDrawer{Title: groupTitle(cancel), HasRequired: true, CancelLabel: "Close",
		Items: []*screensv1.DrawerItem{drawerText(message)}}
}

// groupPicksItems is group_picks.html as the feed reads it: each list's
// heading, then its lines.
func groupPicksItems(ready, left []activities.GroupPick, readyHeading, leftHeading string) []*screensv1.DrawerItem {
	var items []*screensv1.DrawerItem
	if len(ready) > 0 {
		facts := make([]*screensv1.PageFact, len(ready))
		for i, pick := range ready {
			facts[i] = &screensv1.PageFact{Label: pick.Title + " · " + pick.Where, Value: pick.Day.Format("2 Jan 2006")}
		}
		items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: fmt.Sprintf("%s (%d)", readyHeading, len(ready))}},
			&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Lines{Lines: &screensv1.PageFacts{Facts: facts}}})
	}
	if len(left) > 0 {
		facts := make([]*screensv1.PageFact, len(left))
		for i, pick := range left {
			facts[i] = &screensv1.PageFact{Label: pick.Title + " · " + pick.Where + " · " + pick.Day.Format("2 Jan 2006"), Value: pick.Refusal}
		}
		items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: fmt.Sprintf("%s (%d)", leftHeading, len(left))}},
			&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Lines{Lines: &screensv1.PageFacts{Facts: facts}}})
	}
	return items
}

func activitiesWord(n int) string {
	if n == 1 {
		return "activity"
	}
	return "activities"
}

// selectedCount is the drawer's subtitle: how many it lists, and none when
// it lists nothing.
func selectedCount(ready, left []activities.GroupPick) string {
	if n := len(ready) + len(left); n > 0 {
		return fmt.Sprintf("%d selected", n)
	}
	return ""
}

func groupNone(verb string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{
		Text: "None of the selected activities can be " + verb + ".", Tone: "warning"}}}
}

func moveSelectionDrawer(ready, left []activities.GroupPick) *screensv1.PageDrawer {
	d := &screensv1.PageDrawer{Title: groupTitle(false), Subtitle: selectedCount(ready, left), HasRequired: true,
		Items: groupPicksItems(ready, left, "Moving", "Staying where they are")}
	if len(ready) == 0 {
		d.Items, d.CancelLabel = append(d.Items, groupNone("rescheduled")), "Close"
		return d
	}
	d.Items = append(d.Items,
		drawerField(&screensv1.DrawerField{Name: "scheduled_date", Label: "New date", Kind: "date", Required: true, Help: groupMoveHelp}),
		drawerField(&screensv1.DrawerField{Name: "reason", Label: "Reason for changing the date", Kind: "textarea", Required: true,
			Help: "One reason, recorded on each activity.", Placeholder: "Why the date is changing"}))
	d.SubmitLabel = fmt.Sprintf("Reschedule %d %s", len(ready), activitiesWord(len(ready)))
	d.CancelLabel, d.CanSubmit = "Keep dates", true
	return d
}

func cancelSelectionDrawer(ready, left []activities.GroupPick, moneyMoved int) *screensv1.PageDrawer {
	d := &screensv1.PageDrawer{Title: groupTitle(true), Subtitle: selectedCount(ready, left), HasRequired: true,
		Items: groupPicksItems(ready, left, "Being cancelled", "Staying on the plan")}
	if len(ready) == 0 {
		d.Items, d.CancelLabel = append(d.Items, groupNone("cancelled")), "Close"
		return d
	}
	if moneyMoved > 0 {
		d.Items = append(d.Items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Tone: "warning",
			Text: fmt.Sprintf("An advance has already been disbursed for %d of these. Cancelling does not remove that money: what was spent still has to be accounted for and the rest returned.", moneyMoved)}}})
	}
	d.Items = append(d.Items, drawerText(groupCancelText),
		drawerField(&screensv1.DrawerField{Name: "reason", Label: "Reason", Kind: "textarea", Required: true,
			Help: "One reason, recorded on each activity. Reviewers later see only this line.", Placeholder: "e.g. Schools closed for the term"}))
	d.SubmitLabel = fmt.Sprintf("Cancel %d %s", len(ready), activitiesWord(len(ready)))
	d.CancelLabel, d.CanSubmit = "Keep activities", true
	return d
}
