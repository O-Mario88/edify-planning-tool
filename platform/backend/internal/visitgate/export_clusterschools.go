package visitgate

// What a list's Visit Lock column (internal/clusterpage) reads: the state of
// an open school's staff support visit and its words, "Unlocked" included
// (VisitGate.lock_state and lock_state_label).

// LockState is VisitGate.lock_state for an open school.
func (g Gate) LockState(r Rules) string { return g.lockState(r) }

// LockStateLabel is VisitGate.lock_state_label: the column's words for the
// state, "" where it does not apply.
func (g Gate) LockStateLabel(r Rules) string { return r.LockLabels[g.lockState(r)] }
