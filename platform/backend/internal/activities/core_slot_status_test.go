package activities

import "testing"

// core_slot_status: a slot's "Planned" means open, so work still "planned"
// must not read as an open slot. Every other status is the activity's own.
func TestASlotTakesItsActivitysStatus(t *testing.T) {
	for activity, want := range map[string]string{
		"scheduled": "scheduled", "planned": "Scheduled", " Planned ": "Scheduled",
		"awaiting_owner_approval": "awaiting_owner_approval", "completed": "completed", "": "",
	} {
		if got := coreSlotStatus(activity); got != want {
			t.Fatalf("%q = %q, want %q", activity, got, want)
		}
	}
}
