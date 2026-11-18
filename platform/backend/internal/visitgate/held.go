package visitgate

import (
	"context"
	"fmt"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pynum"
)

// HeldSlot is a Core package slot a hand-over holds: its kind ("visit" or
// "training") and its number.
type HeldSlot struct {
	Kind     string
	Sequence int
}

// slot is one core_activity_slot row of a school's package.
type slot struct {
	kind, partner, status string
	sequence              int
	// open is whether no activity fills the slot yet.
	open bool
}

// heldHandover is a hand-over as slot_held_by_assignment reads it.
type heldHandover struct {
	handover
	id, school, code, schoolType, partner string
	visitNo, trainingNo                   string
}

// namesItsSlot is package_credit._names_its_slot.
func (h heldHandover) namesItsSlot() bool {
	return strings.TrimSpace(h.support) != "" || h.visitNo != "" || h.trainingNo != ""
}

// number is the slot number a hand-over names for kind, int(number or 0).
func (h heldHandover) number(kind string) (int, bool) {
	text := h.trainingNo
	if kind == kindVisit {
		text = h.visitNo
	}
	if text == "" {
		return 0, true
	}
	return pynum.Int(text)
}

// heldSlot is package_credit.slot_held_by_assignment over the school's
// slots (newest plan first, then by number) and the partner's other
// unscheduled hand-overs at the school.
func heldSlot(r Rules, h heldHandover, slots []slot, others []heldHandover, outside []string) (HeldSlot, bool) {
	kind := assignmentKind(r, h.handover, outside)
	if kind == "" {
		return HeldSlot{}, false
	}
	if h.namesItsSlot() {
		// A number that is not one names slot 0, which no package has.
		sequence, _ := h.number(kind)
		for _, s := range slots {
			if s.kind == kind && s.sequence == sequence && s.partner == h.partner {
				return HeldSlot{kind, s.sequence}, true
			}
		}
		return HeldSlot{}, false
	}
	// Unnamed: an Assigned slot this partner holds that no named hand-over
	// of theirs at the school accounts for.
	named := map[int]bool{}
	for _, o := range others {
		if o.id == h.id || o.partner != h.partner || !o.namesItsSlot() || assignmentKind(r, o.handover, outside) != kind {
			continue
		}
		if n, ok := o.number(kind); ok {
			named[n] = true
		}
	}
	for _, s := range slots {
		if s.kind == kind && s.partner == h.partner && s.open &&
			strings.ToLower(strings.TrimSpace(s.status)) == "assigned" && !named[s.sequence] {
			return HeldSlot{kind, s.sequence}, true
		}
	}
	return HeldSlot{}, false
}

const heldHandoverColumns = `pa.id, COALESCE(pa.school_id, ''), COALESCE(s.school_id, ''), COALESCE(s.school_type, ''),
  COALESCE(pa.partner_id, ''), COALESCE(pa.project_id, ''), COALESCE(pa.support_type, ''),
  COALESCE(pa.visit_number, ''), COALESCE(pa.training_number, ''), COALESCE(pa.purpose_of_visit, ''),
  COALESCE(pa.expected_activity_type, ''), COALESCE(ci.is_training_course AND ci.universal_training, false)
FROM partner_assignment pa
LEFT JOIN school s ON s.id = pa.school_id
LEFT JOIN activity_catalogue_item ci ON ci.id = pa.training_course_id`

func readHeldHandovers(ctx context.Context, q Querier, where string, args ...any) ([]heldHandover, error) {
	rows, err := q.Query(ctx, "SELECT "+heldHandoverColumns+" WHERE "+where, args...)
	if err != nil {
		return nil, fmt.Errorf("visitgate: reading the hand-overs' slots: %w", err)
	}
	defer rows.Close()
	out := []heldHandover{}
	for rows.Next() {
		var h heldHandover
		if err := rows.Scan(&h.id, &h.school, &h.code, &h.schoolType, &h.partner, &h.project, &h.support,
			&h.visitNo, &h.trainingNo, &h.purpose, &h.expected, &h.universal); err != nil {
			return nil, fmt.Errorf("visitgate: reading the hand-overs' slots: %w", err)
		}
		h.visitNumber, h.trainingNumber = h.visitNo != "", h.trainingNo != ""
		out = append(out, h)
	}
	return out, rows.Err()
}

// HeldSlots is slot_held_by_assignment for each hand-over in ids: the
// package slot each holds at its Core school, by hand-over id; one with
// none is left out.
func HeldSlots(ctx context.Context, q Querier, r Rules, ids []string) (map[string]HeldSlot, error) {
	out := map[string]HeldSlot{}
	if len(ids) == 0 {
		return out, nil
	}
	handovers, err := readHeldHandovers(ctx, q, "pa.id = ANY($1)", ids)
	if err != nil {
		return nil, err
	}
	codes, schools := []string{}, []string{}
	for _, h := range handovers {
		if h.schoolType == "core" && h.code != "" {
			codes, schools = append(codes, h.code), append(schools, h.school)
		}
	}
	if len(codes) == 0 {
		return out, nil
	}
	outside, err := projectsOutsideSSA(ctx, q, r)
	if err != nil {
		return nil, err
	}
	slots, err := readSlots(ctx, q, codes)
	if err != nil {
		return nil, err
	}
	others, err := readHeldHandovers(ctx, q, "pa.school_id = ANY($1) AND pa.status = ANY($2)", schools, r.UnscheduledHandoverStatuses)
	if err != nil {
		return nil, err
	}
	bySchool := map[string][]heldHandover{}
	for _, o := range others {
		bySchool[o.school] = append(bySchool[o.school], o)
	}
	for _, h := range handovers {
		if h.schoolType != "core" || h.code == "" {
			continue
		}
		if held, ok := heldSlot(r, h, slots[h.code], bySchool[h.school], outside); ok {
			out[h.id] = held
		}
	}
	return out, nil
}

// readSlots is each school's package slots by its School ID, newest plan
// first, then by number.
func readSlots(ctx context.Context, q Querier, codes []string) (map[string][]slot, error) {
	rows, err := q.Query(ctx, `
SELECT cas.school_id, cas.activity_type, cas.sequence_number, COALESCE(cas.assigned_partner_id, ''),
  cas.activity_id IS NULL, COALESCE(cas.status, '')
FROM core_activity_slot cas JOIN core_plan cp ON cp.id = cas.core_plan_id
WHERE cas.school_id = ANY($1)
ORDER BY cp.fy DESC, cas.sequence_number, cas.id`, codes)
	if err != nil {
		return nil, fmt.Errorf("visitgate: reading the package slots: %w", err)
	}
	defer rows.Close()
	out := map[string][]slot{}
	for rows.Next() {
		var code string
		var s slot
		if err := rows.Scan(&code, &s.kind, &s.sequence, &s.partner, &s.open, &s.status); err != nil {
			return nil, fmt.Errorf("visitgate: reading the package slots: %w", err)
		}
		out[code] = append(out[code], s)
	}
	return out, rows.Err()
}
