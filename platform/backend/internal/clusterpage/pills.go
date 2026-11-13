package clusterpage

import (
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// The chips a school's list row draws side by side, as the feed reads them
// (page_blocks._planning_pills): the Visit and Training plan statuses
// (components/school_planning_badges.html) and the Visit Lock
// (partials/planning/visit_lock_cell.html). Shared by this page's cluster
// school lists and the Planning list (internal/planningpage).

const (
	lockToneOpen   = "open"
	lockToneClosed = "closed"
	unlockedState  = "unlocked"
)

// ChipPills is one pill a chip, in the page's own planning tone, across the
// lists a cell joins in order; nil when there are none.
func ChipPills(chips ...[]schoolplanning.Chip) []*screensv1.PageBadge {
	var pills []*screensv1.PageBadge
	for _, list := range chips {
		for _, c := range list {
			pills = append(pills, &screensv1.PageBadge{Text: collapse(c.Label), Tone: c.Tone})
		}
	}
	return pills
}

// LockPills is the Visit Lock cell's chip: outlined with an open padlock
// where the staff support visit is unlocked, grey with a shut one and the
// gate's sentence on hover where it is held, and none where the lock does
// not apply (a Champion school).
func LockPills(g visitgate.Gate, r visitgate.Rules) []*screensv1.PageBadge {
	label := g.LockStateLabel(r)
	if label == "" {
		return nil
	}
	if g.LockState(r) == unlockedState {
		return []*screensv1.PageBadge{{Text: collapse(label), Tone: lockToneOpen, Icon: "unlock"}}
	}
	return []*screensv1.PageBadge{{Text: collapse(label), Tone: lockToneClosed, Title: g.StaffReason, Icon: "lock"}}
}
