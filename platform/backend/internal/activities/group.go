package activities

// The sixth save Go owns: rescheduling or cancelling the ticked activities
// together, from the bar for ticked rows (/activity-selection/reschedule and
// /activity-selection/cancel; docs/migration/33). The rules are the view
// (apps/frontend/views/activity_group_views.py) and the group
// (apps/activities/group_actions.py), in their order (33.3). Each activity
// goes through Go's single move or cancel (reschedule.go, cancel.go), as each
// goes through `services.reschedule` or `services.cancel` there.
//
// Go takes a group only when every ticked activity is one its single save
// takes and nothing in the group needs what Go has not ported (33.1);
// otherwise the whole group is handed on (ErrHandOn) and nothing is written.
// A group is never split between the two applications.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The group's own words and limit (group_actions.py: MAX_SELECTION, reschedule
// 196–198, the moves already on the day 216, cancel 235, _refusal 407, _pick
// 445; activity_group_views.py _names, _finish, the views' audit actions and
// verbs; group_outcome.html). Held to the Python source by
// TestTheGroupWordsAreTheExistingApplications.
const (
	maxGroupSelection    = 100
	groupChooseDate      = "Choose the date these activities move to."
	groupMoveReason      = "Give the reason these activities are moving."
	groupCancelReason    = "Give the reason these activities are being cancelled."
	groupAlreadyOnDay    = "Already on this date."
	groupAlreadyOff      = "Already cancelled."
	groupProgrammeWork   = "Programme work"
	groupNamesShown      = 3
	groupMovedVerb       = "moved"
	groupCancelledVerb   = "cancelled"
	groupMoveAuditName   = "reschedule_activity"
	groupCancelAuditName = "cancel_activity"
)

// GroupRequest is the group drawer's form: the ticked activities (one
// `activity_ids` per tick, in the order the drawer lists them), the new date
// for a reschedule, and the one reason.
type GroupRequest struct {
	ActivityIDs  []string
	Date, Reason string
}

// GroupPick is one ticked activity and what became of it (group_actions.Pick).
type GroupPick struct {
	ActivityID, Title, Where string
	Day                      time.Time
	// Refusal is why it was left as it is; empty when it was changed.
	Refusal string
}

// GroupAnswer is what a group did: the activities changed and left, in the
// order the existing view reports them, and the words it answers with.
type GroupAnswer struct {
	Done, Refused []GroupPick
	// Message is the page's flash message when anything changed
	// ("3 activities moved to 19 November 2026. Not moved: …").
	Message string
	// Outcome is the drawer's words when nothing changed (group_outcome.html,
	// read as text): "Nothing was moved. {title} · {where}: {why} …".
	Outcome string
}

// groupPick is a ticked activity as read before the group.
type groupPick struct {
	GroupPick
	a       moved
	ownerID string
}

// GroupReschedule moves every ticked activity that can move to the posted
// date, or refuses the group in the existing words, or hands the whole group
// on (ErrHandOn).
func (s *Service) GroupReschedule(ctx context.Context, p auth.Principal, req GroupRequest, origin Origin) (GroupAnswer, error) {
	ids, err := groupIDs(req.ActivityIDs)
	if err != nil {
		return GroupAnswer{}, err
	}
	if p.InActingAppointment || p.StaffProfileID == "" || in(rules.Doors.Requesters, p.ActiveRole) ||
		rules.CalendarBlocksRefuse {
		return GroupAnswer{}, handOn("not the owner moving their own visits")
	}
	picks, err := s.groupPicks(ctx, p, ids, movableStatuses, true)
	if err != nil {
		return GroupAnswer{}, err
	}
	// group_actions.reschedule: the date, then the reason, before anything
	// is read for the activities.
	posted := strings.TrimSpace(req.Date)
	reason := strings.TrimSpace(req.Reason)
	if posted != "" && !isoDate.MatchString(posted) {
		return GroupAnswer{}, handOn("a date in another form")
	}
	day, err := time.ParseInLocation(time.DateOnly, posted, s.kampala)
	if err != nil {
		return GroupAnswer{}, refuse("%s", groupChooseDate)
	}
	if reason == "" {
		return GroupAnswer{}, refuse("%s", groupMoveReason)
	}
	for i := range picks {
		if sameDay(picks[i].Day, day) {
			picks[i].Refusal = groupAlreadyOnDay
		}
	}
	plans, changing, err := s.groupMovePlans(ctx, p, picks, posted, reason, origin)
	if err != nil {
		return GroupAnswer{}, err
	}
	// The group as the existing application plays it (33.9): the second
	// visit meeting the day the first made, and its pricing once over all.
	door, verdict, err := s.askGroup(ctx, GroupQuestion{Kind: "reschedule", ActivityIDs: ids, Date: posted,
		Reason: reason, UserID: p.UserID, Role: p.ActiveRole}, picks, changing)
	if err != nil {
		return GroupAnswer{}, err
	}
	byID := map[string]*movePlan{}
	for _, pl := range plans {
		byID[pl.a.id] = pl
	}
	plans = inOrder(picks, byID)
	var rowID int64
	var settled string
	var marked []time.Time
	switch {
	case changing > 1 && verdict.Together:
		rowID, marked, err = s.writeGroupMove(ctx, p, picks, plans, changing, origin, door)
	case changing > 1:
		rowID, settled = s.writeEachMove(ctx, picks, plans, door)
	default:
		rowID, marked, err = s.writeOneMove(ctx, picks, plans, door)
	}
	if err != nil {
		return GroupAnswer{}, err
	}
	answer := groupOutcome(picks)
	s.afterGroup(ctx, p, origin, groupMoveAuditName, answer,
		map[string]any{"new_date": posted, "reason": reason, "group": true}, marked, rowID, settled)
	count := len(answer.Done)
	answer.Message = fmt.Sprintf("%d %s moved to %s.", count, activityWord(count), longDate(day))
	finishAnswer(&answer, groupMovedVerb)
	return answer, nil
}

// GroupCancel cancels every ticked activity that is still live, or refuses
// the group in the existing words, or hands the whole group on (ErrHandOn).
func (s *Service) GroupCancel(ctx context.Context, p auth.Principal, req GroupRequest, origin Origin) (GroupAnswer, error) {
	ids, err := groupIDs(req.ActivityIDs)
	if err != nil {
		return GroupAnswer{}, err
	}
	if p.InActingAppointment || p.StaffProfileID == "" || in(rules.Doors.Requesters, p.ActiveRole) {
		return GroupAnswer{}, handOn("not the owner cancelling their own visits")
	}
	picks, err := s.groupPicks(ctx, p, ids, cancellableStatuses, false)
	if err != nil {
		return GroupAnswer{}, err
	}
	// group_actions.cancel: the reason, before anything is read.
	reason := strings.TrimSpace(req.Reason)
	if reason == "" {
		return GroupAnswer{}, refuse("%s", groupCancelReason)
	}
	if utf8.RuneCountInString(reason) > maxCancelReason {
		return GroupAnswer{}, handOn("a reason longer than the activity keeps")
	}
	for i := range picks {
		if in(offPlanStatuses, picks[i].a.status) {
			// _refusal: called off already (the drawer lists it as left).
			picks[i].Refusal = groupAlreadyOff
		}
	}
	changing := 0
	plans := map[string]*cancelPlan{}
	for i := range picks {
		if picks[i].Refusal != "" {
			continue
		}
		changing++
		// A refusal of the pricing on this one alone is the check's to
		// place (33.9): left alone it is the visit's, priced together the
		// group's.
		pl, err := s.prepareCancel(ctx, p, CancelRequest{ActivityID: picks[i].ActivityID, Reason: reason}, origin)
		var refusal *Refusal
		if err != nil && !(errors.As(err, &refusal) && pl != nil) {
			return GroupAnswer{}, err
		}
		plans[picks[i].ActivityID] = pl
	}
	door, verdict, err := s.askGroup(ctx, GroupQuestion{Kind: "cancel", ActivityIDs: ids, Reason: reason,
		UserID: p.UserID, Role: p.ActiveRole}, picks, changing)
	if err != nil {
		return GroupAnswer{}, err
	}
	ordered := inOrder(picks, plans)
	var rowID int64
	var settled string
	marked := []time.Time{}
	switch {
	case changing > 1 && verdict.Together:
		for _, pl := range ordered {
			if !door[pl.a.id].Done {
				// Nothing a cancel of 30.1's case meets refuses it inside a
				// group: not ported.
				return GroupAnswer{}, handOn("the group check leaves a cancel Go would make")
			}
			if in(rules.LedgerCreditedTypes, pl.a.activityType) {
				marked = append(marked, pl.a.plannedDate)
			}
		}
		rowID, err = s.writeGroupCancel(ctx, p, ordered, origin)
	case changing > 1:
		rowID, settled = s.writeEachCancel(ctx, picks, ordered, door)
	case changing == 1:
		pl := ordered[0]
		v := door[pl.a.id]
		switch {
		case !v.Done:
			pickOf(picks, pl.a.id).Refusal = v.Refusal
		case pl.verdict.Refusal != "":
			return GroupAnswer{}, handOn("the group check cancels one Go's check refuses")
		default:
			rowID, err = s.writeCancel(ctx, pl)
			if in(rules.LedgerCreditedTypes, pl.a.activityType) {
				marked = append(marked, pl.a.plannedDate)
			}
		}
	}
	if err != nil {
		return GroupAnswer{}, err
	}
	answer := groupOutcome(picks)
	s.afterGroup(ctx, p, origin, groupCancelAuditName, answer, map[string]any{"reason": reason, "group": true},
		marked, rowID, settled)
	count := len(answer.Done)
	answer.Message = fmt.Sprintf("%d %s cancelled.", count, activityWord(count))
	finishAnswer(&answer, groupCancelledVerb)
	return answer, nil
}

// groupIDs is clean_ids: the ticked ids, once each, in the order ticked. No
// id, or more than the group takes, is handed on (the existing words then).
func groupIDs(raw []string) ([]string, error) {
	ids := []string{}
	for _, value := range raw {
		value = strings.TrimSpace(value)
		if value != "" && !slices.Contains(ids, value) {
			ids = append(ids, value)
		}
	}
	if len(ids) == 0 || len(ids) > maxGroupSelection {
		return nil, handOn("no activity ticked, or more than a group takes")
	}
	return ids, nil
}

// groupPicks reads every ticked activity and hands the group on unless each
// is one Go's single save takes (prepareMove's and prepareCancel's doors
// that do not turn on the date or the reason). The group check puts them in
// `selection`'s order (askGroup).
func (s *Service) groupPicks(ctx context.Context, p auth.Principal, ids []string, statuses []string, move bool) ([]groupPick, error) {
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, handOn("no scope: " + err.Error())
	}
	picks := make([]groupPick, 0, len(ids))
	for _, id := range ids {
		a, err := movedVisit(ctx, s.db, id)
		if err != nil {
			return nil, err
		}
		if a == nil || a.responsible != p.StaffProfileID || !in(statuses, a.status) ||
			!in(inScopePurposes, a.purpose) || rules.Purposes.ActivityTypes[a.purpose] != a.activityType ||
			a.nameSnapshot == "" || (move && a.batchID == "") {
			return nil, handOn("a ticked activity is not a visit of the first save's kind, owned by the person")
		}
		sc, err := schoolByIDOrCode(ctx, s.db, a.schoolID)
		if err != nil {
			return nil, err
		}
		if sc == nil || sc.ID != a.schoolID || in(rules.Gate.CoreRuleTypes, sc.Type) {
			return nil, handOn("a ticked activity is at a Core school, or no school")
		}
		owner, err := schoolOwner(ctx, s.db, sc.ID)
		if err != nil {
			return nil, err
		}
		if !slices.Contains(scope.OwnSchoolIDs, sc.ID) || owner != p.StaffProfileID {
			return nil, handOn("a ticked activity is outside the person's own portfolio")
		}
		ownerUID, err := fundingOwner(ctx, s.db, a.responsible, p.UserID)
		if err != nil {
			return nil, err
		}
		if why, err := moveNotices(ctx, s.db, a.id, ownerUID); err != nil || why != "" {
			if err != nil {
				return nil, err
			}
			return nil, handOn(why)
		}
		where := sc.Name
		if where == "" {
			where = groupProgrammeWork
		}
		picks = append(picks, groupPick{
			GroupPick: GroupPick{ActivityID: a.id, Title: a.nameSnapshot, Where: where, Day: a.plannedDate},
			a:         *a, ownerID: ownerUID,
		})
	}
	return picks, nil
}

// groupMovePlans prepares each pick that is to move through the single
// move's own preparation (prepareMove), in the group's order. A pick it
// refuses is left with those words, as `_change` leaves it; anything it
// hands on hands the whole group on. changing is `_apply`'s count: the picks
// the group itself did not leave.
func (s *Service) groupMovePlans(ctx context.Context, p auth.Principal, picks []groupPick, posted, reason string,
	origin Origin) ([]*movePlan, int, error) {
	changing := 0
	for _, pick := range picks {
		if pick.Refusal == "" {
			changing++
		}
	}
	plans := []*movePlan{}
	for i := range picks {
		if picks[i].Refusal != "" {
			continue
		}
		pl, err := s.prepareMove(ctx, p, MoveRequest{ActivityID: picks[i].ActivityID, Date: posted, Reason: reason}, origin)
		var refusal *Refusal
		switch {
		case errors.As(err, &refusal):
			picks[i].Refusal = refusal.Message
			continue
		case err != nil:
			return nil, 0, err
		}
		plans = append(plans, pl)
	}
	return plans, changing, nil
}

// pickOf finds a plan's pick.
func pickOf(picks []groupPick, id string) *groupPick {
	for i := range picks {
		if picks[i].ActivityID == id {
			return &picks[i]
		}
	}
	return nil
}

// writeOneMove is `_one_at_a_time` when one pick is left to move: the single
// move as it is made alone, its own transaction and costs row. The check's
// answer decides it: left with its words, or moved; Go's own check refusing
// a move the check makes hands the group on, as does Go's save refusing it
// (nothing has been written).
func (s *Service) writeOneMove(ctx context.Context, picks []groupPick, plans []*movePlan,
	door map[string]VerdictPick) (int64, []time.Time, error) {
	if len(plans) == 0 {
		return 0, nil, nil
	}
	pl := plans[0]
	if v := door[pl.a.id]; !v.Done {
		pickOf(picks, pl.a.id).Refusal = v.Refusal
		return 0, nil, nil
	}
	if pl.verdict.Refusal != "" {
		return 0, nil, handOn("the group check moves one Go's check refuses")
	}
	rowID, err := s.writeMove(ctx, pl)
	var refusal *Refusal
	if errors.As(err, &refusal) {
		return 0, nil, handOn("the group check moves one Go's save refuses")
	}
	if err != nil {
		return 0, nil, err
	}
	marked := []time.Time{}
	if in(rules.LedgerCreditedTypes, pl.a.activityType) {
		marked = append(marked, pl.a.plannedDate, pl.newDay)
	}
	return rowID, marked, nil
}

// keptCosts is what a group's costs_follow block keeps: the days in the
// order last asked for (`_price_when_the_save_ends` moves a day asked again
// to the end), the owner-weeks and owner-months once each in the order
// asked, and the notes.
type keptCosts struct {
	days   [][]string
	weeks  [][]string
	months [][]any
	notes  []any
}

func (k *keptCosts) day(batchID, owner string) {
	k.days = slices.DeleteFunc(k.days, func(d []string) bool { return d[0] == batchID })
	k.days = append(k.days, []string{batchID, owner})
}

func (k *keptCosts) week(w []string) {
	if !slices.ContainsFunc(k.weeks, func(x []string) bool { return slices.Equal(x, w) }) {
		k.weeks = append(k.weeks, w)
	}
}

func (k *keptCosts) month(m []any) {
	if !slices.ContainsFunc(k.months, func(x []any) bool { return fmt.Sprint(x) == fmt.Sprint(m) }) {
		k.months = append(k.months, m)
	}
}

func (k *keptCosts) empty() bool {
	return len(k.days) == 0 && len(k.weeks) == 0 && len(k.months) == 0 && len(k.notes) == 0
}

// writeGroupMove is `_together`: the group in one transaction, each pick in
// a savepoint of its own and undone to it when refused, the days, weeks and
// months it touched kept once in one costs row (`together`), named as the
// change the group is ("3 activities", planner_change's `what`). It answers
// the row's id and the days whose years the ledger marks on commit.
func (s *Service) writeGroupMove(ctx context.Context, p auth.Principal, picks []groupPick, plans []*movePlan,
	changing int, origin Origin, door map[string]VerdictPick) (int64, []time.Time, error) {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return 0, nil, fmt.Errorf("activities: opening the group: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	kept := &keptCosts{days: [][]string{}, weeks: [][]string{}, months: [][]any{}, notes: []any{}}
	marks := groupMarks{}
	for _, pl := range plans {
		point, err := tx.Begin(ctx)
		if err != nil {
			return 0, nil, fmt.Errorf("activities: opening the visit's savepoint: %w", err)
		}
		// The check's answer for this one, met where the existing save
		// meets it: a refusal Go reads itself (the duplicate test) before the
		// row, any other (the day the one before it made) after it.
		v := door[pl.a.id]
		played := *pl
		played.verdict.Refusal = v.Refusal
		stored, err := s.moveInTx(ctx, point, &played)
		pl.newBatch = played.newBatch
		var refusal *Refusal
		if errors.As(err, &refusal) {
			if v.Done || refusal.Message != v.Refusal {
				return 0, nil, handOn("the group check and Go's save leave a visit otherwise")
			}
			if err := point.Rollback(ctx); err != nil {
				return 0, nil, fmt.Errorf("activities: undoing the visit: %w", err)
			}
			pickOf(picks, pl.a.id).Refusal = refusal.Message
			if stored && in(rules.LedgerCreditedTypes, pl.a.activityType) {
				marks.undone(pl.a.plannedDate, pl.newDay)
			}
			continue
		}
		if err != nil {
			return 0, nil, err
		}
		if err := point.Commit(ctx); err != nil {
			return 0, nil, fmt.Errorf("activities: keeping the visit: %w", err)
		}
		if in(rules.LedgerCreditedTypes, pl.a.activityType) {
			marks.kept(pl.a.plannedDate, pl.newDay)
		}
		if pl.a.batchID != pl.newBatch {
			kept.day(pl.a.batchID, pl.ownerUID)
		}
		kept.day(pl.newBatch, pl.ownerUID)
		for _, w := range pl.weeks {
			kept.week(w)
		}
		for _, m := range pl.months {
			kept.month(m)
		}
		if !pl.a.scheduled.Equal(pl.scheduled) {
			kept.notes = append(kept.notes, map[string]any{
				"kind": "reschedule_note", "activity": pl.a.id, "old": pyISO(pl.a.scheduled.UTC()),
				"new": pyISO(pl.scheduled), "reason": pl.reason,
			})
		}
	}
	var rowID int64
	if !kept.empty() {
		change := fmt.Sprintf("%d activities", changing)
		if rowID, err = keepGroupCosts(ctx, tx, p, origin, s.now(), kept, change); err != nil {
			return 0, nil, err
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, nil, fmt.Errorf("activities: committing the group: %w", err)
	}
	return rowID, marks.days, nil
}

// groupMarks is ledger_sync's marks for a transaction of savepoints: the
// first mark puts one callback on the commit (`mark_when_committed`); a
// savepoint that rolls back takes the callback with it when it was put there
// inside it, and keeps a later pick's marks when it was put there before.
type groupMarks struct {
	registered bool
	days       []time.Time
}

func (m *groupMarks) kept(days ...time.Time) {
	m.registered = true
	m.days = append(m.days, days...)
}

func (m *groupMarks) undone(days ...time.Time) {
	if m.registered {
		m.days = append(m.days, days...)
	}
}

// writeGroupCancel is `_together` for a cancel: one transaction, a savepoint
// for each, the days, weeks and months the existing application says each
// keeps (its cancel check) kept once in one costs row (`together`, no change
// named: a group cancel is not a planner's change).
func (s *Service) writeGroupCancel(ctx context.Context, p auth.Principal, plans []*cancelPlan, origin Origin) (int64, error) {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return 0, fmt.Errorf("activities: opening the group: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	kept := &keptCosts{days: [][]string{}, weeks: [][]string{}, months: [][]any{}, notes: []any{}}
	for _, pl := range plans {
		point, err := tx.Begin(ctx)
		if err != nil {
			return 0, fmt.Errorf("activities: opening the visit's savepoint: %w", err)
		}
		if err := s.cancelInTx(ctx, point, pl); err != nil {
			return 0, err
		}
		if err := point.Commit(ctx); err != nil {
			return 0, fmt.Errorf("activities: keeping the visit: %w", err)
		}
		for _, d := range pl.verdict.Days {
			kept.day(d[0], d[1])
		}
		for _, w := range pl.verdict.Weeks {
			kept.week(w)
		}
		for _, m := range pl.verdict.Months {
			kept.month(m)
		}
	}
	var rowID int64
	if !kept.empty() {
		if rowID, err = keepGroupCosts(ctx, tx, p, origin, s.now(), kept, ""); err != nil {
			return 0, err
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("activities: committing the group: %w", err)
	}
	return rowID, nil
}

// keepGroupCosts is costs_follow._hand_over's row for a group: `together`
// true, every owner the days, weeks and months name, sorted.
func keepGroupCosts(ctx context.Context, tx pgx.Tx, p auth.Principal, origin Origin, now time.Time,
	kept *keptCosts, change string) (int64, error) {
	var named any
	if change != "" {
		named = change
	}
	steps, err := json.Marshal(map[string]any{
		"days": kept.days, "together": true, "weeks": kept.weeks, "months": kept.months, "notes": kept.notes,
		"change": named,
	})
	if err != nil {
		return 0, err
	}
	owners := []string{}
	for _, d := range kept.days {
		owners = append(owners, d[1])
	}
	for _, w := range kept.weeks {
		owners = append(owners, w[0])
	}
	for _, m := range kept.months {
		if owner, ok := m[0].(string); ok {
			owners = append(owners, owner)
		}
	}
	owners = slices.DeleteFunc(owners, func(o string) bool { return o == "" })
	sort.Strings(owners)
	owners = slices.Compact(owners)
	ownersJSON, _ := json.Marshal(owners)
	provenance, _ := json.Marshal(map[string]any{
		"ip": nilIfEmpty(origin.IP), "agent": nilIfEmpty(origin.UserAgent),
		"correlation": nilIfEmpty(origin.CorrelationID), "acting": nil,
	})
	var id int64
	err = tx.QueryRow(ctx, `
INSERT INTO daily_visit_costs_to_follow (created_at, updated_at, owners, asked_by, asked_by_role, steps,
  provenance, attempts, held_reason)
VALUES ($1, $1, $2, $3, $4, $5, $6, 0, '') RETURNING id`,
		now, ownersJSON, p.UserID, p.ActiveRole, steps, provenance).Scan(&id)
	if err != nil {
		return 0, fmt.Errorf("activities: keeping the group's costs to follow: %w", err)
	}
	return id, nil
}

// groupOutcome is `_one_at_a_time`'s answer: the picks changed and the picks
// left, each in the group's order.
func groupOutcome(picks []groupPick) GroupAnswer {
	answer := GroupAnswer{Done: []GroupPick{}, Refused: []GroupPick{}}
	for _, pick := range picks {
		if pick.Refusal == "" {
			answer.Done = append(answer.Done, pick.GroupPick)
		} else {
			answer.Refused = append(answer.Refused, pick.GroupPick)
		}
	}
	return answer
}

// afterGroup is what follows the commit, in the existing order: the ledger's
// marks (on commit), the view's audit rows (`_audit`: every pick changed,
// then every pick left with its reason), then the pricing.
func (s *Service) afterGroup(ctx context.Context, p auth.Principal, origin Origin, action string, answer GroupAnswer,
	payload map[string]any, marked []time.Time, rowID int64, settled string) {
	if len(marked) > 0 {
		if err := s.markOwnerYears(ctx, p.StaffProfileID, marked...); err != nil {
			s.logger.Warn("activities: the target ledger was not marked", "group", action, "err", err)
		}
	}
	for _, pick := range answer.Done {
		s.auditGroupRow(ctx, p, origin, action, pick.ActivityID, true, "", payload)
	}
	for _, pick := range answer.Refused {
		s.auditGroupRow(ctx, p, origin, action, pick.ActivityID, false, pick.Refusal, payload)
	}
	if rowID == 0 || len(answer.Done) == 0 {
		return
	}
	if settled == "" {
		settled = answer.Done[0].ActivityID
	}
	if err := s.pricing.Settle(ctx, []int64{rowID}, settled); err != nil {
		s.logger.Warn("activities: the group's costs to follow were not settled; the sweep takes them",
			"row", rowID, "err", err)
	}
}

func (s *Service) auditGroupRow(ctx context.Context, p auth.Principal, origin Origin, action, activityID string,
	success bool, reason string, payload map[string]any) {
	if err := s.appendGroupRow(ctx, p, origin, action, activityID, success, reason, payload); err != nil {
		s.logger.Warn("activities: a group audit row was not written", "activity", activityID, "err", err)
	}
}

func (s *Service) appendGroupRow(ctx context.Context, p auth.Principal, origin Origin, action, activityID string,
	success bool, reason string, payload map[string]any) error {
	role := p.ActiveRole
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, p.UserID, s.now())
	if err != nil {
		return err
	}
	row := copyPayload(payload)
	var why *string
	if !success {
		why = audit.Text(reason)
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: action, SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(activityID),
		ActorID: audit.Text(p.UserID), ActorRole: &role, Success: success, Reason: why,
		Payload: withStamps(row, cover), IPAddress: nilIfEmpty(origin.IP), UserAgent: nilIfEmpty(origin.UserAgent),
		CorrelationID: nilIfEmpty(origin.CorrelationID),
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// copyPayload copies a payload so each row's stamps are its own.
func copyPayload(payload map[string]any) map[string]any {
	out := make(map[string]any, len(payload))
	for k, v := range payload {
		out[k] = v
	}
	return out
}

func activityWord(count int) string {
	if count == 1 {
		return "activity"
	}
	return "activities"
}

// finishAnswer is the view's `_finish`: the flash message with the picks
// left ("Not moved: A at X (why); …"), or, when nothing changed, the
// drawer's words for each pick left.
func finishAnswer(answer *GroupAnswer, verb string) {
	if len(answer.Done) > 0 {
		if len(answer.Refused) > 0 {
			answer.Message += " Not " + verb + ": " + groupNames(answer.Refused) + "."
		}
		return
	}
	answer.Message = ""
	parts := []string{"Nothing was " + verb + "."}
	for _, pick := range answer.Refused {
		parts = append(parts, pick.Title+" · "+pick.Where+": "+pick.Refusal)
	}
	answer.Outcome = strings.Join(parts, " ")
}

// groupNames is `_names`: the first three picks left, "; "-joined, and how
// many more.
func groupNames(picks []GroupPick) string {
	shown := []string{}
	for i, pick := range picks {
		if i == groupNamesShown {
			break
		}
		shown = append(shown, fmt.Sprintf("%s at %s (%s)", pick.Title, pick.Where, strings.TrimRight(pick.Refusal, ".")))
	}
	names := strings.Join(shown, "; ")
	if more := len(picks) - groupNamesShown; more > 0 {
		names += fmt.Sprintf(" and %d more", more)
	}
	return names
}
