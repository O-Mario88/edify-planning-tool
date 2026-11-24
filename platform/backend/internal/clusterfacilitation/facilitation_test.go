package clusterfacilitation

import "testing"

func TestTheDrawerReadsAsTheFeedReadsIt(t *testing.T) {
	d := drawerFor(Cluster{Name: "Cluster A"}, "", []Partner{{ID: "p1", Name: "Build Africa"}}, 2)
	if d.GetTitle() != "Partner to facilitate Cluster A" || d.GetSubmitLabel() != "Save" || d.GetCancelLabel() != "Cancel" || !d.GetCanSubmit() {
		t.Fatalf("head %v", d)
	}
	items := d.GetItems()
	if items[0].GetText() != "Now facilitated by Staff." {
		t.Fatalf("now: %q", items[0].GetText())
	}
	f := items[1].GetField()
	if f.GetName() != "facilitating_partner_id" || f.GetLabel() != "Facilitated by" || f.GetKind() != "select" ||
		len(f.GetOptions()) != 2 || f.GetOptions()[0].GetLabel() != "Staff" || f.GetOptions()[1].GetValue() != "p1" {
		t.Fatalf("field %v", f)
	}
	if items[2].GetNote().GetTone() != "info" || items[2].GetNote().GetText()[:18] != "What this assigns " {
		t.Fatalf("note %v", items[2])
	}
	if got, want := items[3].GetText(), "2 sessions already planned for this cluster keep the facilitator they have. Change one from its own Edit."; got != want {
		t.Fatalf("sessions %q", got)
	}
	one := drawerFor(Cluster{Name: "B"}, "p1", []Partner{{ID: "p1", Name: "Build Africa"}}, 1)
	if one.GetItems()[0].GetText() != "Now facilitated by Build Africa." || one.GetItems()[1].GetField().GetValue() != "p1" {
		t.Fatalf("current %v", one.GetItems()[:2])
	}
	if got, want := one.GetItems()[3].GetText(), "1 session already planned for this cluster keeps the facilitator it has. Change one from its own Edit."; got != want {
		t.Fatalf("one session %q", got)
	}
	if len(drawerFor(Cluster{Name: "C"}, "", nil, 0).GetItems()) != 3 {
		t.Fatal("no planned sessions, no line")
	}
}

func TestTheSaveSaysWhatItDid(t *testing.T) {
	if got := assignedMessage(); got != "Saved. Press Refresh to see it on the page." {
		t.Fatalf("got %q", got)
	}
	if got := notActivePartner; got != "Cluster not assigned: Select an active Partner organisation to facilitate." {
		t.Fatalf("got %q", got)
	}
}
