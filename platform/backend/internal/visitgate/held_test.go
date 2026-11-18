package visitgate

import "testing"

func TestAHandOverHoldsTheSlotItNamesOrTheNextOneAssigned(t *testing.T) {
	r := coreRules()
	slots := []slot{
		// Newest plan first, then by number (order_by("-core_plan__fy", "sequence_number")).
		{kind: "visit", sequence: 1, partner: "p1", open: false, status: "Assigned"},
		{kind: "visit", sequence: 2, partner: "p1", open: true, status: "Assigned"},
		{kind: "visit", sequence: 3, partner: "p1", open: true, status: " assigned "},
		{kind: "visit", sequence: 4, partner: "p2", open: true, status: "Assigned"},
		{kind: "training", sequence: 1, partner: "p1", open: true, status: "Planned"},
	}
	named := func(number string) heldHandover {
		return heldHandover{handover: handover{support: "Visit", visitNumber: number != ""}, partner: "p1", visitNo: number}
	}
	other := func(id, number string) heldHandover {
		o := named(number)
		o.id = id
		return o
	}
	for _, c := range []struct {
		name   string
		h      heldHandover
		others []heldHandover
		want   int
	}{
		{"a named slot this partner holds", named("1"), nil, 1},
		{"a named slot another partner holds", heldHandover{handover: handover{support: "Visit", visitNumber: true}, partner: "p1", visitNo: "4"}, nil, 0},
		{"a named number that is not one", named("x"), nil, 0},
		{"unnamed: the first open Assigned slot", heldHandover{handover: handover{expected: "core_visit"}, partner: "p1"}, nil, 2},
		{"unnamed: past a slot another hand-over names",
			heldHandover{handover: handover{expected: "core_visit"}, id: "h1", partner: "p1"}, []heldHandover{other("h2", "2")}, 3},
		{"unnamed training: no Assigned slot", heldHandover{handover: handover{expected: "in_school_training"}, partner: "p1"}, nil, 0},
		{"not package work", heldHandover{handover: handover{purpose: "ssa_support"}, partner: "p1"}, nil, 0},
	} {
		got, ok := heldSlot(r, c.h, slots, c.others, nil)
		if (c.want == 0) == ok || (ok && got.Sequence != c.want) {
			t.Errorf("%s: %+v %v, want slot %d", c.name, got, ok, c.want)
		}
	}
}
