package activities

import "testing"

func TestAPartnersDateIsTheirsUnlessStaffPutItThereOrTheWorkStillWaits(t *testing.T) {
	cases := []struct {
		status, datedBy string
		want            bool
	}{
		{"partner_scheduled", "partner", true},
		{"partner_scheduled", "", true},
		{"partner_scheduled", "staff", false},
		{"assigned_to_partner", "partner", false},
	}
	for _, c := range cases {
		w := &partnerWork{moved: moved{status: c.status}, datedBy: c.datedBy}
		if got := w.partnerDated(); got != c.want {
			t.Fatalf("%s dated by %q: %v", c.status, c.datedBy, got)
		}
	}
}
