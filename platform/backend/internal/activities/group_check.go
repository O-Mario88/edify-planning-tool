package activities

// The group check (docs/migration/33 §33.9): before its transaction Go asks
// the existing application to play the whole group as group_actions makes it
// (POST /api/auth/internal/visit-group-check, rolled back, writing nothing)
// and makes what it answers: each activity done or left with its words, the
// group changed together or, when its pricing refused, one activity at a
// time. Go's own reading of the group must agree with that answer at every
// point where it has one; where it does not, the whole group is handed on.

import (
	"context"
	"errors"
	"fmt"
)

// GroupQuestion is what the group check plays: the drawer's ticks, date and
// reason, as the person working in their role.
type GroupQuestion struct {
	Kind         string // "reschedule" or "cancel"
	ActivityIDs  []string
	Date, Reason string
	UserID, Role string
}

// GroupVerdict is the existing application's answer: the group's own
// refusal, whether it was changed together, the refusal of its pricing that
// changed it one at a time, and each activity in the group's order.
type GroupVerdict struct {
	Refusal      string        `json:"refusal"`
	Together     bool          `json:"together"`
	GroupRefusal string        `json:"groupRefusal"`
	Picks        []VerdictPick `json:"picks"`
}

// VerdictPick is what became of one ticked activity.
type VerdictPick struct {
	ID      string `json:"id"`
	Done    bool   `json:"done"`
	Refusal string `json:"refusal"`
}

// GroupPricing asks the existing application what a group would do.
type GroupPricing interface {
	GroupCheck(ctx context.Context, q GroupQuestion) (GroupVerdict, error)
}

// groupUnexpected is _message's words for an error that was not a refusal
// (group_actions._UNEXPECTED).
const groupUnexpected = "Could not be changed. The error has been logged."

// askGroup asks the check and holds Go's reading to it: the same activities,
// put in the group's order; every pick Go has already left (on the day,
// called off, a closed school, a past date) left by the check in the same
// words; a group changed one at a time only because its pricing refused.
// It answers each activity's verdict by id.
func (s *Service) askGroup(ctx context.Context, q GroupQuestion, picks []groupPick, changing int) (
	map[string]VerdictPick, GroupVerdict, error) {
	asker, ok := s.pricing.(GroupPricing)
	if !ok {
		return nil, GroupVerdict{}, fmt.Errorf("activities: the pricing cannot check a group")
	}
	verdict, err := asker.GroupCheck(ctx, q)
	if err != nil {
		return nil, GroupVerdict{}, err
	}
	if verdict.Refusal != "" || len(verdict.Picks) != len(picks) {
		return nil, verdict, handOn("the group check reads the group otherwise")
	}
	if changing > 1 && !verdict.Together && verdict.GroupRefusal == "" {
		return nil, verdict, handOn("the group check changed the group otherwise")
	}
	byID := map[string]VerdictPick{}
	order := map[string]int{}
	for i, v := range verdict.Picks {
		byID[v.ID], order[v.ID] = v, i
	}
	ordered := make([]groupPick, len(picks))
	for _, pick := range picks {
		i, found := order[pick.ActivityID]
		if !found {
			return nil, verdict, handOn("the group check reads other activities")
		}
		if v := byID[pick.ActivityID]; pick.Refusal != "" && (v.Done || v.Refusal != pick.Refusal) {
			return nil, verdict, handOn("the group check leaves a pick otherwise")
		}
		ordered[i] = pick
	}
	copy(picks, ordered)
	if s.logger != nil {
		s.logger.Info("activities: the group check", "kind", q.Kind, "together", verdict.Together,
			"groupRefusal", verdict.GroupRefusal)
	}
	return byID, verdict, nil
}

// inOrder puts the plans in the picks' (the group's) order.
func inOrder[P any](picks []groupPick, plans map[string]P) []P {
	out := []P{}
	for _, pick := range picks {
		if pl, ok := plans[pick.ActivityID]; ok {
			out = append(out, pl)
		}
	}
	return out
}

// writeEachMove is the group changed one activity at a time after its
// pricing refused (`_apply`'s fall-back, `_one_at_a_time` outside any
// transaction): each activity the check moved is moved as it is moved alone,
// in its own transaction with its own costs row, the costs the one before it
// kept settled first (`_settle_what_this_request_asked`), its ledger marks on
// its own commit. It answers the last costs row and its activity, for the
// settle that follows the group.
func (s *Service) writeEachMove(ctx context.Context, picks []groupPick, plans []*movePlan,
	door map[string]VerdictPick) (int64, string) {
	var lastRow int64
	var lastActivity string
	for _, pl := range plans {
		pick := pickOf(picks, pl.a.id)
		if v := door[pl.a.id]; !v.Done {
			pick.Refusal = v.Refusal
			continue
		}
		s.settleBefore(ctx, lastRow, lastActivity)
		alone := *pl
		alone.verdict.Refusal = ""
		rowID, err := s.writeMove(ctx, &alone)
		if !s.keptAlone(pick, err) {
			continue
		}
		if in(rules.LedgerCreditedTypes, pl.a.activityType) {
			if err := s.markOwnerYears(ctx, pl.a.responsible, pl.a.plannedDate, pl.newDay); err != nil {
				s.logger.Warn("activities: the target ledger was not marked", "activity", pl.a.id, "err", err)
			}
		}
		lastRow, lastActivity = rowID, pl.a.id
	}
	return lastRow, lastActivity
}

// writeEachCancel is writeEachMove for a group cancel.
func (s *Service) writeEachCancel(ctx context.Context, picks []groupPick, plans []*cancelPlan,
	door map[string]VerdictPick) (int64, string) {
	var lastRow int64
	var lastActivity string
	for _, pl := range plans {
		pick := pickOf(picks, pl.a.id)
		if v := door[pl.a.id]; !v.Done {
			pick.Refusal = v.Refusal
			continue
		}
		s.settleBefore(ctx, lastRow, lastActivity)
		rowID, err := s.writeCancel(ctx, pl)
		if !s.keptAlone(pick, err) {
			continue
		}
		if in(rules.LedgerCreditedTypes, pl.a.activityType) {
			if err := s.markOwnerYears(ctx, pl.a.responsible, pl.a.plannedDate); err != nil {
				s.logger.Warn("activities: the target ledger was not marked", "activity", pl.a.id, "err", err)
			}
		}
		if rowID != 0 {
			lastRow, lastActivity = rowID, pl.a.id
		}
	}
	return lastRow, lastActivity
}

// keptAlone says whether an activity changed alone was kept. One the check
// said would be kept and Go's own save refused, or that failed, is left with
// those words (`_change`/`_message`): the ones before it are committed, as
// they are in the existing application, so the group goes on.
func (s *Service) keptAlone(pick *groupPick, err error) bool {
	var refusal *Refusal
	switch {
	case err == nil:
		return true
	case errors.As(err, &refusal):
		s.logger.Warn("activities: the group check said this one moves alone; Go's save refused it",
			"activity", pick.ActivityID, "words", refusal.Message)
		pick.Refusal = refusal.Message
	default:
		s.logger.Error("activities: a group's activity could not be changed alone", "activity", pick.ActivityID, "err", err)
		pick.Refusal = groupUnexpected
	}
	return false
}

// settleBefore settles the costs the last activity kept before the next is
// changed, as the next save in the same request settles them first.
func (s *Service) settleBefore(ctx context.Context, rowID int64, activityID string) {
	if rowID == 0 {
		return
	}
	if err := s.pricing.Settle(ctx, []int64{rowID}, activityID); err != nil {
		s.logger.Warn("activities: the costs to follow were not settled; the sweep takes them",
			"activity", activityID, "row", rowID, "err", err)
	}
}
