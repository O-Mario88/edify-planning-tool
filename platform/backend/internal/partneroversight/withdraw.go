package partneroversight

// The withdrawal drawer (oversight_views.partner_withdrawal_preview_view,
// partials/oversight/withdrawal_drawer.html): what taking the work back from
// its Partner would do, computed as withdrawal_service.preview computes it,
// and the form that does it, as the feed reads them. Its save stays the
// existing application's.

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// WithdrawPath is the drawer's path.
const WithdrawPath = "/partner-oversight/withdraw"

// replacementLimit is _eligible_replacements' first hundred partners.
const replacementLimit = 100

// preview is withdrawal_service._preview_of's answer.
type preview struct {
	kind, kindLabel                   string
	available, dated, locked          bool
	school, partner                   string
	activityType, slot                string
	assignmentStatus, activityStatus  string
	plannedDate                       *time.Time
	plannedCost, budgetRemoved        int64
	cancelled, amendment, slotReopens bool
}

// Withdraw draws the drawer for the hand-over assignmentID, or the Partner
// work activityID when no hand-over is named. ErrDetailHandOn is a drawer Go
// does not draw.
func (s *Service) Withdraw(ctx context.Context, p auth.Principal, assignmentID, activityID string) (*screensv1.PageDrawer, string, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, WithdrawPath) {
		return nil, DetailRefusal, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || p.Acting != nil || p.InActingAppointment || (p.Country != nil && p.Country.FromRegistry()) ||
		p.ActiveRole == "ProjectCoordinator" {
		return nil, "", ErrDetailHandOn
	}
	now := s.now()
	it, err := s.workInScope(ctx, p, role, strings.TrimSpace(assignmentID), strings.TrimSpace(activityID), now)
	if err != nil {
		return nil, "", err
	}
	if it == nil {
		return &screensv1.PageDrawer{Title: "Not available", HasRequired: true, CancelLabel: "Cancel",
			Items: []*screensv1.DrawerItem{dText(notInScope)}}, "", nil
	}
	if it.projectID != "" && it.targetIntervention == "" {
		return nil, "", ErrDetailHandOn
	}
	pv, err := s.previewOf(ctx, it)
	if err != nil {
		return nil, "", err
	}
	d := &screensv1.PageDrawer{Title: pv.kindLabel, Subtitle: strings.TrimSpace(pv.school + " · " + pv.partner), HasRequired: true, CancelLabel: "Cancel"}
	directs := p.ActiveRole == "Admin" || p.ActiveRole == "ImpactAssessment"
	switch {
	case it.projectID != "" && !directs:
		name := it.projectName
		if name == "" {
			if err := s.db.QueryRow(ctx, `SELECT COALESCE(name, '') FROM project WHERE id = $1`, it.projectID).Scan(&name); err != nil &&
				!errors.Is(err, pgx.ErrNoRows) {
				return nil, "", fmt.Errorf("partneroversight: the project's name: %w", err)
			}
		}
		d.Items = []*screensv1.DrawerItem{
			dText("This school's work belongs to " + first(name, "a Special Project") + "."),
			dText("Only its Project Coordinator can withdraw it from " + pv.partner +
				" or reassign it to another partner. Follow it on Project Monitoring."),
		}
	case !pv.available:
		d.Items = []*screensv1.DrawerItem{
			dText("This work can no longer be withdrawn."),
			dText("It has been paid or closed. A concern about work already settled goes through a dispute, a reopening or a " +
				"corrective follow-up, each of which keeps the original record intact."),
		}
	default:
		partners, err := s.replacements(ctx, it.partnerID)
		if err != nil {
			return nil, "", err
		}
		request := mustRequest(p.ActiveRole, pv)
		d.Items = withdrawForm(pv, request, partners)
		d.CanSubmit, d.SubmitLabel = true, pv.kindLabel
		if request {
			d.SubmitLabel = "Send request to Program Lead"
		}
	}
	return d, "", nil
}

// workInScope is _partner_work_in_scope: the named hand-over, the hand-over
// the activity is paired with, or the Partner work with none, each only if
// the reader's lens reads it.
func (s *Service) workInScope(ctx context.Context, p auth.Principal, role Role, assignmentID, activityID string,
	now time.Time) (*item, error) {
	if assignmentID != "" {
		return s.itemInScope(ctx, p, role.Lens, assignmentID, now)
	}
	if activityID == "" {
		return nil, nil
	}
	var paired string
	err := s.db.QueryRow(ctx, `SELECT id FROM partner_assignment WHERE scheduled_activity_id = $1 ORDER BY id LIMIT 1`, activityID).
		Scan(&paired)
	switch {
	case err == nil:
		return s.itemInScope(ctx, p, role.Lens, paired, now)
	case !errors.Is(err, pgx.ErrNoRows):
		return nil, fmt.Errorf("partneroversight: the activity's hand-over: %w", err)
	}
	return s.activityInScope(ctx, p, role, activityID, now)
}

// activityInScope is build_item_by_activity: Partner work with no hand-over,
// as the page's own list of it for the reader holds it.
func (s *Service) activityInScope(ctx context.Context, p auth.Principal, role Role, activityID string, now time.Time) (*item, error) {
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, err
	}
	var team, regions []string
	switch role.Lens {
	case "team":
		own, err := bothIDSpaces(ctx, s.db, []string{p.UserID, p.StaffProfileID})
		if err != nil {
			return nil, err
		}
		team = own
		if !role.OwnWorkOnly {
			if team, err = bothIDSpaces(ctx, s.db, append(append([]string{}, own...), scope.SupervisedStaffIDs...)); err != nil {
				return nil, err
			}
		}
		if len(team) == 0 {
			return nil, nil
		}
	case "region":
		regions = nonNil(scope.RegionIDs)
	case "country":
	default:
		return nil, ErrDetailHandOn
	}
	acts, err := readActivities(ctx, s.db, unassignedPartnerWhere+` AND a.id = $3
  AND ($4::text[] IS NULL OR a.monitored_by_staff_id = ANY($4) OR a.responsible_staff_id = ANY($4)
    OR s.account_owner_id = ANY($4) OR c.responsible_staff_id = ANY($4))
  AND ($5::text[] IS NULL OR s.region_id = ANY($5) OR c.region_id = ANY($5))`,
		rules.PartnerDelivery, []string{"cancelled", "rejected", "deferred"}, activityID, team, regions)
	if err != nil || len(acts) == 0 {
		return nil, err
	}
	a := acts[0]
	dir, err := readDirectory(ctx, s.db, nonEmpty([]string{a.monitor, a.responsible, a.owner, a.clusterOwner}))
	if err != nil {
		return nil, err
	}
	costs, err := readCosts(ctx, s.db, []string{a.id})
	if err != nil {
		return nil, err
	}
	it := unassignedItem(a, officerFrom(dir), costs)
	// The hand-over this work never had (_handover_shape): scheduled by the
	// Partner, its slot the activity's own.
	it.assignmentStatus = "partner_scheduled"
	return it, nil
}

// previewOf is _preview_of over the item.
func (s *Service) previewOf(ctx context.Context, it *item) (preview, error) {
	w := rules.Work.Withdrawal
	pv := preview{kind: it.withdrawalKind(), school: it.schoolName, partner: it.partnerName,
		assignmentStatus: it.assignmentStatus, activityStatus: it.activityStatus}
	a := it.act
	if a != nil {
		pv.dated = a.hasDated()
		pv.plannedDate = a.plannedDate
		pv.activityType = a.activityType
		if it.plannedCost != nil {
			pv.plannedCost = *it.plannedCost
		}
		locked, err := s.moneyMoved(ctx, a)
		if err != nil {
			return pv, err
		}
		pv.locked = locked
	}
	slot, expected, err := s.slotOf(ctx, it)
	if err != nil {
		return pv, err
	}
	pv.slot = slot
	if pv.activityType == "" {
		pv.activityType = expected
	}
	pv.kindLabel = withdrawalLabelOf(pv.kind, pv.dated)
	if pv.kindLabel == "" {
		pv.kindLabel = first(w.Labels[pv.kind], pv.kind)
	}
	pv.available = pv.kind != "blocked"
	pv.cancelled = pv.kind == "recall_scheduled"
	pv.amendment = pv.locked && pv.kind == "recall_scheduled"
	if !pv.locked && pv.kind != "withdraw_unscheduled" {
		pv.budgetRemoved = pv.plannedCost
	}
	pv.slotReopens = pv.kind == "withdraw_unscheduled" || pv.kind == "recall_scheduled"
	return pv, nil
}

// moneyMoved is is_financially_locked: a payment past pending, or an
// advance whose money has moved.
func (s *Service) moneyMoved(ctx context.Context, a *activity) (bool, error) {
	switch first(a.payment, "none") {
	case "none", "pending", "pending_ia":
	default:
		return true, nil
	}
	var moved bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM advance_request WHERE activity_id = $1 AND status = ANY($2))`,
		a.id, rules.Work.Withdrawal.MoneyMovedAdvanceStatuses).Scan(&moved); err != nil {
		return false, fmt.Errorf("partneroversight: the activity's advances: %w", err)
	}
	return moved, nil
}

// slotOf is _slot_label (the hand-over's support requirement in words) and
// the hand-over's expected kind of work; for work with no hand-over, the
// activity's own kind.
func (s *Service) slotOf(ctx context.Context, it *item) (string, string, error) {
	if it.assignmentID == "" {
		kind := ""
		if it.act != nil {
			kind = it.act.activityType
		}
		return first(kind, "Support"), kind, nil
	}
	var support, expected string
	var visit, training *string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(support_type, ''), COALESCE(expected_activity_type, ''), visit_number, training_number
FROM partner_assignment WHERE id = $1`, it.assignmentID).Scan(&support, &expected, &visit, &training); err != nil {
		return "", "", fmt.Errorf("partneroversight: the hand-over's slot: %w", err)
	}
	bits := []string{first(support, expected, "Support")}
	if visit != nil && *visit != "" {
		bits = append(bits, "Visit "+*visit)
	}
	if training != nil && *training != "" {
		bits = append(bits, "Training "+*training)
	}
	return strings.Join(bits, " · "), expected, nil
}

// mustRequest is _must_request: a CCEO may only ask their Lead, unless the
// work is unscheduled or only staff have dated it.
func mustRequest(role string, pv preview) bool {
	if role != "CCEO" || pv.kind == "withdraw_unscheduled" {
		return false
	}
	return !(pv.kind == "recall_scheduled" && !pv.dated)
}

// replacements is _eligible_replacements: active partners other than the
// one the work is being taken from, by name.
func (s *Service) replacements(ctx context.Context, partnerID string) ([]*screensv1.DrawerOption, error) {
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM partner WHERE active_status AND deleted_at IS NULL AND id <> $1
ORDER BY name LIMIT $2`, partnerID, replacementLimit)
	if err != nil {
		return nil, fmt.Errorf("partneroversight: the replacement partners: %w", err)
	}
	defer rows.Close()
	out := []*screensv1.DrawerOption{{Label: "Choose the partner taking this on…"}}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("partneroversight: the replacement partners: %w", err)
		}
		out = append(out, &screensv1.DrawerOption{Value: id, Label: name})
	}
	return out, rows.Err()
}

// withdrawForm is the drawer's form as the feed reads it.
func withdrawForm(pv preview, request bool, partners []*screensv1.DrawerOption) []*screensv1.DrawerItem {
	w := rules.Work.Withdrawal
	items := []*screensv1.DrawerItem{}
	if request {
		items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Tone: "info",
			Text: pv.partner + " has already scheduled this, so your Program Lead decides. This sends them the request."}}})
	}
	scheduled := "Not scheduled"
	if pv.plannedDate != nil {
		scheduled = pv.plannedDate.Format("2 Jan 2006")
		if !pv.dated {
			scheduled += " (a date staff set; the partner has not scheduled it)"
		}
	}
	items = append(items, dHeading("The assignment"), dFacts(
		[2]string{"Support slot", djangoTitle(strings.ReplaceAll(pv.slot, "_", " "))},
		[2]string{"Activity", titleWords(pv.activityType)},
		[2]string{"Scheduled for", scheduled},
		[2]string{"Current state", djangoTitle(strings.ReplaceAll(first(pv.activityStatus, pv.assignmentStatus), "_", " "))},
	), dHeading("Impact"),
		dText("Planned cost on this work UGX "+intcomma(pv.plannedCost)),
		dText("Leaves the live budget UGX "+intcomma(pv.budgetRemoved)))
	if pv.cancelled {
		whose := "The partner's scheduled activity"
		if !pv.dated {
			whose = "The activity dated for the partner"
		}
		items = append(items, dText(whose+" is cancelled, not deleted. Its cost lines stay as the record of what was planned; "+
			"every total excludes them."))
	}
	if pv.amendment {
		items = append(items, dText("Budget amendment required Money has already moved or been committed against this activity, "+
			"so the approved amount is not rewritten. A formal amendment records the change and somebody has to approve it."))
	}
	if pv.slotReopens {
		items = append(items, dText("The school's support slot reopens — the same one, not a second entitlement."))
	} else {
		items = append(items, dText("The support slot stays with this assignment while the review runs, so a replacement cannot "+
			"duplicate work that may still be finished."))
	}
	reasons := []*screensv1.DrawerOption{{Label: "Choose a reason…"}}
	for _, c := range w.ReasonChoices {
		reasons = append(reasons, &screensv1.DrawerOption{Value: c[0], Label: c[1]})
	}
	dispositions := []*screensv1.DrawerOption{}
	for _, c := range w.DispositionChoices {
		dispositions = append(dispositions, &screensv1.DrawerOption{Value: c[0], Label: c[1]})
	}
	limit := func(n int32) *int32 { return &n }
	return append(items,
		dField(&screensv1.DrawerField{Name: "reason_category", Label: "Reason", Kind: "select", Required: true,
			Help: "Decides whether this counts against the partner's performance.", Options: reasons}),
		dField(&screensv1.DrawerField{Name: "partner_facing_reason", Label: "Explanation for the partner", Kind: "textarea",
			Required: true, Placeholder: "Why this work is being withdrawn and what happens next", MaxLength: limit(600),
			Help: "The partner sees this, except for a safeguarding or conduct concern, which shows a neutral notice. " +
				"Put that detail in the internal note."}),
		dField(&screensv1.DrawerField{Name: "internal_note", Label: "Internal note (optional)", Kind: "textarea",
			Placeholder: "Staff only, never shown to the partner", MaxLength: limit(2000)}),
		dField(&screensv1.DrawerField{Name: "disposition", Label: "What happens next", Kind: "select", Required: true,
			Value: "return_to_planning", Help: "Where the school's support goes after this.", Options: dispositions}),
		dField(&screensv1.DrawerField{Name: "replacement_partner_id", Label: "Replacement partner", Kind: "select",
			Help:     "They start with no date and no cost, priced from their own rate when they schedule.",
			ShowWhen: []*screensv1.DrawerCondition{{Field: "disposition", Values: []string{"reassign_partner"}}}, Options: partners}),
	)
}

func dField(f *screensv1.DrawerField) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: f}}
}
