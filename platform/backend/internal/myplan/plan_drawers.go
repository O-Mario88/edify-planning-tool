package myplan

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// My Plan's Reschedule and Cancel drawers (my_plan_views.reschedule_drawer_view
// and cancel_activity_drawer_view, as the feed reads partials/planning/
// schedule_drawer.html in its reschedule mode and partials/my_plan/
// cancel_drawer.html) for a reader who may change the work. Their parts Go
// does not draw yet hand the drawer on: the other half of a pair moving or
// cancelled with it, a week's request sent and taken back, a partner's own
// work to date, and a training's form.

// TeamReadOnlyMessage is scoping.TEAM_READ_ONLY_MESSAGE.
const TeamReadOnlyMessage = "You can see this activity but not change it: a team member's scheduled work is edited, rescheduled or cancelled by the person responsible for it."

// rescheduleFYHelp is the date field's help in the reschedule mode.
const rescheduleFYHelp = "This date's financial year has already had this visit at the school. Choose a date in another financial year, or another purpose."

// changedWork is what the two drawers read of the activity.
type changedWork struct {
	id, kind, status, delivery, partnerID, datedBy, partnerName string
	planned, scheduled                                          *time.Time
	schoolName, clusterName                                     string
	hasSchool, hasCluster                                       bool
	meetingKind                                                 string
	paired                                                      bool
}

func readChangedWork(ctx context.Context, db schooldirectory.Querier, id string) (*changedWork, error) {
	a := &changedWork{}
	err := db.QueryRow(ctx, `
SELECT a.id, a.activity_type, COALESCE(a.status, ''), COALESCE(a.delivery_type, ''), COALESCE(a.assigned_partner_id, ''),
  COALESCE(a.partner_date_set_by, ''), COALESCE(pa.name, ''), a.planned_date, a.scheduled_date,
  COALESCE(s.name, ''), COALESCE(c.name, ''), s.id IS NOT NULL, c.id IS NOT NULL, COALESCE(a.meeting_kind, ''),
  a.paired_school_visit_id IS NOT NULL
    OR EXISTS (SELECT 1 FROM activity o WHERE o.paired_school_visit_id = a.id AND o.deleted_at IS NULL)
FROM activity a
LEFT JOIN partner pa ON pa.id = a.assigned_partner_id
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE a.id = $1 AND a.deleted_at IS NULL`, id).Scan(
		&a.id, &a.kind, &a.status, &a.delivery, &a.partnerID, &a.datedBy, &a.partnerName, &a.planned, &a.scheduled,
		&a.schoolName, &a.clusterName, &a.hasSchool, &a.hasCluster, &a.meetingKind, &a.paired)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the work to change: %w", err)
	}
	return a, nil
}

// PlanDrawer draws My Plan's Reschedule or Cancel drawer (kind
// "reschedule" or "cancel") for p, or ErrDetailHandOn.
func (s *Service) PlanDrawer(ctx context.Context, p auth.Principal, id, kind string) (*screensv1.PageDrawer, error) {
	access, err := ReadActivityAccess(ctx, s.db, p, id, s.now())
	if err != nil {
		return nil, err
	}
	if !access.Decided || !access.Found || !access.Visible {
		return nil, handOn("a drawer the existing application refuses")
	}
	if !access.Runnable {
		return noteDrawer("Read only", TeamReadOnlyMessage), nil
	}
	a, err := readChangedWork(ctx, s.db, id)
	if err != nil {
		return nil, err
	}
	if a == nil {
		return nil, handOn("no such activity")
	}
	if kind == "cancel" {
		return s.cancelDrawer(ctx, a)
	}
	return s.rescheduleDrawer(ctx, a)
}

// noteDrawer is refusal_drawer: a title and one note, closed.
func noteDrawer(title, note string) *screensv1.PageDrawer {
	return &screensv1.PageDrawer{
		Title: title, HasRequired: true, CancelLabel: "Close",
		Items: []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: note, Tone: "info"}}}},
	}
}

func drawerNote(text, tone string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: text, Tone: tone}}}
}

func drawerText(text string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: text}}
}

func drawerField(f *screensv1.DrawerField) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: f}}
}

// cancelDrawer is cancel_drawer.html for work the reader may cancel.
func (s *Service) cancelDrawer(ctx context.Context, a *changedWork) (*screensv1.PageDrawer, error) {
	if a.paired {
		return nil, handOn("the other half of a pair is cancelled with it")
	}
	d := rules.Detail
	var moneyMoved, keepsSchool bool
	if err := s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM advance_request WHERE activity_id = $1 AND status = ANY($2)),
       EXISTS (SELECT 1 FROM partner_assignment WHERE scheduled_activity_id = $1 AND status = ANY($3))`,
		a.id, d.MoneyMovedAdvanceStatuses, d.PartnerScheduledAssignmentStatuses).Scan(&moneyMoved, &keepsSchool); err != nil {
		return nil, fmt.Errorf("myplan: reading the work's money and hand-over: %w", err)
	}
	title := "Cancel " + strings.ReplaceAll(a.kind, "_", " ")
	if a.hasSchool {
		title += " at " + a.schoolName
	}
	var items []*screensv1.DrawerItem
	if moneyMoved {
		items = append(items, drawerNote("An advance for this activity has already been disbursed. Cancelling does not remove that money — you still have to account for what was spent and return the rest.", "warning"))
	}
	if a.delivery == "partner" && a.partnerHasDated() && keepsSchool {
		name := a.partnerName
		if name == "" {
			name = "the partner"
		}
		items = append(items, drawerNote("The school stays assigned to "+name+": only this date is cancelled, and the partner schedules the school again. To take the school back from the partner, withdraw it instead.", "info"))
	}
	words := "It stays on the record as Cancelled, leaves your plan and is no longer counted anywhere. Its cost and any undisbursed advance are withdrawn."
	if a.partnerID != "" {
		words += " The assigned partner is notified."
	}
	items = append(items, drawerText(words), drawerField(&screensv1.DrawerField{
		Name: "reason", Label: "Reason", Kind: "textarea", Required: true,
		Help: "Reviewers later see only this line.", Placeholder: "e.g. School closed for the term",
	}))
	return &screensv1.PageDrawer{
		Title: title, HasRequired: true, Items: items,
		SubmitLabel: "Cancel activity", CancelLabel: "Keep activity", CanSubmit: true,
	}, nil
}

// partnerHasDated is dating_policy.partner_has_dated.
func (a *changedWork) partnerHasDated() bool {
	if a.status == "assigned_to_partner" || a.datedBy == rules.Detail.DatedByStaff {
		return false
	}
	return a.planned != nil || a.scheduled != nil
}

// rescheduleDrawer is the schedule drawer's reschedule mode for work the
// reader may move.
func (s *Service) rescheduleDrawer(ctx context.Context, a *changedWork) (*screensv1.PageDrawer, error) {
	if in(rules.Detail.ExecutedStatuses, a.status) {
		return noteDrawer("Cannot reschedule", "This activity has already been carried out, so it can no longer be rescheduled. Only an activity that is still scheduled can be."), nil
	}
	isTraining := in(rules.Detail.TrainingTypes, a.kind) ||
		(in(rules.Detail.MeetingTypes, a.kind) && a.meetingKind == rules.Detail.TrainingMeetingKind)
	switch {
	case a.paired:
		return nil, handOn("the other half of a pair moves with it")
	case a.delivery == "partner":
		return nil, handOn("a partner's work, its assigning officer named")
	case isTraining:
		return nil, handOn("a training's reschedule form")
	case a.planned == nil:
		return nil, handOn("work with no planned day")
	}
	var sent bool
	if err := s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM weekly_fund_request_line l
  JOIN weekly_fund_request r ON r.id = l.weekly_fund_request_id
  JOIN activity_schedule_cost_line c ON c.id = l.activity_budget_line_id
  WHERE c.activity_id = $1 AND r.status NOT IN ('pending_responsible_confirmation', 'not_requested'))`, a.id).Scan(&sent); err != nil {
		return nil, fmt.Errorf("myplan: reading the work's weekly requests: %w", err)
	}
	if sent {
		return nil, handOn("a week's request sent, taken back by the move")
	}
	subject := "this activity"
	switch {
	case a.hasSchool:
		subject = a.schoolName
	case a.hasCluster:
		subject = a.clusterName
	}
	return &screensv1.PageDrawer{
		Title: "Reschedule " + TypeLabel(a.kind) + " for " + subject, HasRequired: true,
		Items: []*screensv1.DrawerItem{
			drawerField(&screensv1.DrawerField{
				Name: "scheduled_date", Label: "Scheduled date", Kind: "date", Value: a.planned.Format(time.DateOnly),
				Required: true, Help: rescheduleFYHelp,
			}),
			drawerField(&screensv1.DrawerField{
				Name: "reason", Label: "Reason for changing the date", Kind: "textarea", Required: true,
				Placeholder: "Why the date is changing",
			}),
		},
		SubmitLabel: "Save new date", CancelLabel: "Cancel", CanSubmit: true,
	}, nil
}
