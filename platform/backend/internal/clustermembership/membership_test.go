package clustermembership

import (
	"encoding/json"
	"testing"
)

func TestAddedMessageSaysHowManyAndWhichWereSkipped(t *testing.T) {
	cases := []struct {
		n       int
		skipped []string
		want    string
	}{
		{2, nil, "Successfully assigned 2 schools to Cluster N."},
		{1, nil, "Successfully assigned 1 schools to Cluster N."},
		{0, []string{"Alpha", "Beta"}, "Successfully assigned 0 schools to Cluster N. Skipped 2 already-clustered: Alpha, Beta."},
	}
	for _, c := range cases {
		if got := addedMessage(c.n, "Cluster N", c.skipped); got != c.want {
			t.Errorf("addedMessage(%d, %v) = %q, want %q", c.n, c.skipped, got, c.want)
		}
	}
}

func TestRefusalsAreTheServiceWords(t *testing.T) {
	cases := map[string]string{
		"inactive":    "A school can only be assigned to an active cluster.",
		"country":     "A school can only join a cluster in its own country.",
		"other_owner": "That cluster belongs to another staff member. A school joins a cluster owned by the person responsible for the school; moving it across portfolios needs a transfer.",
		"joined":      "",
		"same":        "",
	}
	for answer, want := range cases {
		if got := refusalOf(answer); got != want {
			t.Errorf("refusalOf(%q) = %q, want %q", answer, got, want)
		}
	}
}

func TestAuditPayloadIsTheServiceShape(t *testing.T) {
	district, clusterDistrict := "d1", "d2"
	rel := "neighbouring"
	got, _ := json.Marshal(auditPayload(Joined{NewCluster: "c1", Relationship: &rel, SchoolDistrict: &district, ClusterDistrict: &clusterDistrict}))
	want := `{"new":{"clusterDistrictId":"d2","clusterId":"c1","crossDistrict":true,"relationship":"neighbouring","schoolDistrictId":"d1"},"newClusterId":"c1","oldClusterId":null,"previous":{"clusterId":null}}`
	if string(got) != want {
		t.Errorf("payload\n got %s\nwant %s", got, want)
	}
	old := "c0"
	got, _ = json.Marshal(auditPayload(Joined{OldCluster: &old, NewCluster: "c1"}))
	want = `{"new":{"clusterDistrictId":null,"clusterId":"c1","crossDistrict":false,"relationship":null,"schoolDistrictId":null},"newClusterId":"c1","oldClusterId":"c0","previous":{"clusterId":"c0"}}`
	if string(got) != want {
		t.Errorf("payload\n got %s\nwant %s", got, want)
	}
}

func TestDrawerListsTheUnclusteredSchools(t *testing.T) {
	d := drawerFor(Cluster{Name: "Cluster N", DistrictName: "Mukono"}, []Candidate{
		{ID: "s1", Code: "1234", Name: "Alpha Primary"}, {ID: "s2", Code: "", Name: "Beta Primary"},
	})
	if d.GetTitle() != "Add schools to Cluster N" || d.GetSubmitLabel() != "Save schools to cluster" || !d.GetCanSubmit() || !d.GetHasRequired() {
		t.Fatalf("drawer head = %+v", d)
	}
	items := d.GetItems()
	if len(items) != 4 {
		t.Fatalf("items = %d, want 4", len(items))
	}
	search := items[0].GetField()
	if search.GetLabel() != "Search schools" || search.GetKind() != "text" || search.GetPlaceholder() != "Search by name or ID" || search.GetName() != "" {
		t.Errorf("search = %+v", search)
	}
	if all := items[1].GetField(); all.GetLabel() != "Select all visible schools" || all.GetKind() != "checkbox" {
		t.Errorf("select all = %+v", all)
	}
	list := items[2].GetField()
	if list.GetName() != "school_ids" || list.GetKind() != "checklist" || len(list.GetOptions()) != 2 {
		t.Fatalf("checklist = %+v", list)
	}
	if o := list.GetOptions()[0]; o.GetValue() != "s1" || o.GetLabel() != "Alpha Primary" || o.GetDetail() != "1234" {
		t.Errorf("first option = %+v", o)
	}
	if items[3].GetText() != "Tick the schools to add, then save." {
		t.Errorf("closing line = %q", items[3].GetText())
	}
}

func TestDrawerWithNothingToAddSaysSo(t *testing.T) {
	d := drawerFor(Cluster{Name: "Cluster N", DistrictName: "Mukono"}, nil)
	if d.GetCanSubmit() || d.GetSubmitLabel() != "" || d.GetCancelLabel() != "Cancel" || len(d.GetItems()) != 1 {
		t.Fatalf("drawer = %+v", d)
	}
	note := d.GetItems()[0].GetNote()
	if note.GetText() != "All schools are clustered Every candidate school in Mukono district already belongs to a cluster." || note.GetTone() != "info" {
		t.Errorf("note = %+v", note)
	}
}
