package planningmonitor

import (
	"context"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// cexTargets is target_position: the selection's planned output, validated
// actual and gap, read as CD Analytics reads them (_weighted_achievement).
type cexTargets struct {
	status                       string // ok, week, people_only or none
	target, achieved, gap, share int
}

// targetPosition reads the people's targets through the same series and
// ledger as My Targets (targets.Prepare, which never writes). A year with
// an approved priority contract is answered from the contract for the
// selected people (allocation_priorities with recipient_ids), which Go does
// not read yet, so such a year is handed on.
func (s *cexSnapshot) targetPosition(ctx context.Context, db schooldirectory.Querier) (cexTargets, error) {
	f, w := s.filters, s.data.window
	if w.period == "week" {
		return cexTargets{status: "week"}, nil
	}
	if f.region != "" || f.channel != "" || f.partner != "" || f.activType != "" {
		return cexTargets{status: "people_only"}, nil
	}
	none := cexTargets{status: "none"}
	staff := s.targetPeople()
	if len(staff) == 0 {
		return none, nil
	}
	if contract, err := allocations.Exist(ctx, db, w.fy); err != nil || contract {
		if err == nil {
			err = targets.ErrHandOn
		}
		return none, err
	}
	people, err := cexTargetUsers(ctx, db, staff)
	if err != nil || len(people) == 0 {
		return none, err
	}
	roster, err := targets.Prepare(ctx, db, people, w.fy, nil)
	if err != nil {
		return none, err
	}
	areas := roster.AgreedAreas(people)
	if len(areas) == 0 {
		return none, nil
	}
	months := w.monthsOfFY
	if w.period == "fy" {
		months = []int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}
	}
	pct, achieved, target := roster.TeamWeightedPct(people, areas, months)
	if target == 0 {
		return none, nil
	}
	return cexTargets{status: "ok", target: target, achieved: achieved, gap: max(0, target-achieved), share: pct}, nil
}

// cexTargetUsers is _staff_user_ids then _users_by_id: the live profiles'
// users (a removed user is still read, as User.objects reads it).
func cexTargetUsers(ctx context.Context, db schooldirectory.Querier, staff []string) ([]targets.Person, error) {
	rows, err := db.Query(ctx, `SELECT sp.id, u.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
		WHERE sp.id = ANY($1) AND sp.deleted_at IS NULL ORDER BY sp.id`, staff)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the selection's people: %w", err)
	}
	defer rows.Close()
	people := []targets.Person{}
	for rows.Next() {
		var p targets.Person
		if err := rows.Scan(&p.StaffID, &p.UserID); err != nil {
			return nil, err
		}
		people = append(people, p)
	}
	return people, rows.Err()
}

// targetNote is the workspace's target note for the position.
func (s *cexSnapshot) targetNote(t cexTargets) *node {
	switch t.status {
	case "ok":
		return el("p", "cpo-info", el("strong", "", "Targets"), fmt.Sprintf(" for the people in this selection, %s: planned output %d · validated actual %d · remaining gap %d · %d%% achieved. ",
			s.data.window.label(), t.target, t.achieved, t.gap, t.share),
			"The same figures My Targets, Team Targets and CD Analytics read from the canonical target ledger; only verified work earns credit, and nothing here recalculates performance.")
	case "week":
		return el("p", "cpo-info", el("strong", "", "Targets"), " are set by month: a week has none of its own. Choose the month to read planned output against validated actual.")
	case "people_only":
		return el("p", "cpo-info", el("strong", "", "Targets"), " are held by people, not by region, delivery channel, Partner or activity type, so they are not shown for this filter. Clear it, or choose a Programme Lead or CCEO, to read planned output against validated actual.")
	}
	return el("p", "cpo-info", el("strong", "", "Targets:"), " none are set in My Targets for the people in this selection for "+s.data.window.label()+
		", so there is no planned output to read against. Validated credits still count in the canonical target ledger.")
}
