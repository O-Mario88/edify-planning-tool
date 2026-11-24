package clustermembership

import (
	"reflect"
	"testing"
)

func TestClusterChoiceIsLabelledAsTheDrawerOption(t *testing.T) {
	cases := []struct {
		c    ownerCluster
		want string
		off  bool
	}{
		{ownerCluster{Name: "Cluster A", District: "Mukono", Schools: 1}, "Cluster A · Mukono · 1 school", false},
		{ownerCluster{Name: "Cluster A", District: "Mukono", Schools: 3, Current: true, Cross: true}, "Cluster A · Mukono (current) · 3 schools", true},
		{ownerCluster{Name: "Cluster B", District: "Buikwe", Schools: 0, Cross: true}, "Cluster B · Buikwe · Cross-District Cluster · 0 schools", false},
		{ownerCluster{Name: "Cluster B", District: "Buikwe", Schools: 2, Cross: true, Serves: true}, "Cluster B · Buikwe · Cross-District Cluster (approved neighbouring district) · 2 schools", false},
	}
	for _, c := range cases {
		got := clusterChoiceOf(c.c)
		if got.GetLabel() != c.want || got.GetDisabled() != c.off {
			t.Errorf("choice(%+v) = %q %v, want %q %v", c.c, got.GetLabel(), got.GetDisabled(), c.want, c.off)
		}
	}
}

func TestOwnerClustersSortServedFirstThenOwnDistrict(t *testing.T) {
	clusters := []ownerCluster{
		{ID: "x", Name: "zeta", Cross: true},
		{ID: "a", Name: "Beta", Serves: true},
		{ID: "b", Name: "alpha", Serves: true, Current: true},
		{ID: "c", Name: "Gamma", Serves: true, Cross: true},
		{ID: "d", Name: "Alpha", Serves: true},
	}
	sortOwnerClusters(clusters)
	got := []string{}
	for _, c := range clusters {
		got = append(got, c.ID)
	}
	if want := []string{"d", "a", "b", "c", "x"}; !reflect.DeepEqual(got, want) {
		t.Errorf("order = %v, want %v", got, want)
	}
}

func TestSchoolFormWords(t *testing.T) {
	sc := schoolFacts{Name: "Alpha Primary", District: "Mukono", SubCounty: "Goma"}
	f := schoolForm(sc, "Paul N.", []ownerCluster{{ID: "c1", Name: "Cluster A", District: "Mukono", Schools: 2, Serves: true}}, formState{selectable: true})
	if f.GetTitle() != "Add Alpha Primary to cluster" || f.GetSubmitLabel() != "Add to cluster" || f.GetOwnerNote() != "Clusters of Paul N. (the school's owner)." ||
		f.GetClusterNotice() != "" || f.GetNewClusterPlaceholder() != "e.g. Goma Cluster" || f.GetNewClusterNote() != "A new cluster is created in Mukono, covering Goma." ||
		f.GetReasonPlaceholder() != "Why this school joins a cluster across the district border" || f.GetConfirmLabel() != "" || !f.GetHasSelectableCluster() {
		t.Errorf("add form = %+v", f)
	}
	change := schoolForm(schoolFacts{Name: "Alpha Primary"}, "", nil, formState{isChange: true, current: "Cluster A"})
	if change.GetTitle() != "Change cluster for Alpha Primary" || change.GetSubmitLabel() != "Change cluster" ||
		change.GetConfirmLabel() != "Move this school out of Cluster A." || change.GetReasonPlaceholder() != "Why this school moves to another cluster" ||
		change.GetClusterNotice() != "This school's owner has no active cluster yet — create one to add the school." ||
		change.GetNewClusterPlaceholder() != "e.g. the school's district Cluster" || change.GetNewClusterNote() != "A new cluster is created in the school's district, covering the district." {
		t.Errorf("change form = %+v", change)
	}
	none := schoolForm(sc, "Paul N.", []ownerCluster{{ID: "c1", Name: "Cluster A", Current: true}}, formState{})
	if none.GetClusterNotice() != "This school's owner has no active cluster to add it to." {
		t.Errorf("no selectable = %q", none.GetClusterNotice())
	}
	if got := schoolForm(sc, "", nil, formState{ineligible: "Assign an owner first."}).GetClusterNotice(); got != "Assign an owner first." {
		t.Errorf("ineligible = %q", got)
	}
}

func TestBulkAssignMessagesAreRunBulks(t *testing.T) {
	r := bulkAssignMessages(2, "Cluster N", []string{"Alpha", "Beta"})
	if !r.GetSaved() || r.GetMessage() != "Successfully assigned 2 schools to cluster 'Cluster N'." ||
		!reflect.DeepEqual(r.GetWarnings(), []string{"Skipped already-clustered schools: Alpha, Beta."}) {
		t.Errorf("saved = %+v", r)
	}
	if r := bulkAssignMessages(0, "Cluster N", nil); r.GetSaved() || r.GetError() != "No unclustered schools were selected." {
		t.Errorf("none = %+v", r)
	}
}
