package clustercreate

import (
	"net/url"
	"reflect"
	"testing"
)

func TestReadFormIsWhatTheViewReads(t *testing.T) {
	f := readForm(map[string]string{
		"name": "  Goma Cluster ", "district_id": " d1 ", "sub_county_ids": "s2,s1,s2",
		"cluster_leader_name": "  ", "cluster_leader_phone": " 0772 ", "responsible_staff_id": " u9 ",
	}, url.Values{"assign_school_id": {" sch1 "}})
	if f.Name != "Goma Cluster" || f.District != "d1" || f.Type != "mixed" || f.Owner != "u9" || f.AssignSchool != "sch1" {
		t.Errorf("form = %+v", f)
	}
	if !reflect.DeepEqual(f.SubCounties, []string{"s2", "s1", "s2"}) {
		t.Errorf("sub-counties = %v", f.SubCounties)
	}
	if f.LeaderName != nil || f.LeaderPhone == nil || *f.LeaderPhone != "0772" {
		t.Errorf("leader = %v %v", f.LeaderName, f.LeaderPhone)
	}
	if g := readForm(map[string]string{"cluster_type": " ", "sub_county_id": "s5"}, nil); g.Type != "" || !reflect.DeepEqual(g.SubCounties, []string{"s5"}) {
		t.Errorf("a posted blank type stays blank and the single sub-county is read: %+v", g)
	}
}

func TestMissingFieldsAreRefusedInTheViewsWords(t *testing.T) {
	cases := []struct {
		f    Form
		want string
	}{
		{Form{Name: "A", District: "d", SubCounties: []string{"s"}}, ""},
		{Form{Name: "A", District: "d"}, "Failed to create cluster: select at least one sub-county."},
		{Form{District: "d", SubCounties: []string{"s"}}, "Failed to create cluster: missing fields."},
	}
	for _, c := range cases {
		if got := missing(c.f); got != c.want {
			t.Errorf("missing(%+v) = %q, want %q", c.f, got, c.want)
		}
	}
}

func TestCreatedMessageNamesTheSchoolWhenOneJoined(t *testing.T) {
	if got := createdMessage("Goma Cluster", "", ""); got != "Successfully created cluster 'Goma Cluster'." {
		t.Errorf("got %q", got)
	}
	want := "Successfully created cluster 'Goma Cluster'. School 'Alpha' has been assigned to the new cluster 'Goma Cluster'."
	if got := createdMessage("Goma Cluster", "Alpha", "Goma Cluster"); got != want {
		t.Errorf("got %q", got)
	}
}

func TestDistinctSubCountiesKeepTheirOrder(t *testing.T) {
	if got := distinct([]string{"s2", "s1", "s2"}); !reflect.DeepEqual(got, []string{"s2", "s1"}) {
		t.Errorf("distinct = %v", got)
	}
}

func TestDrawerIsTheCreateForm(t *testing.T) {
	d := drawerFor([]District{{"d1", "Mukono"}}, []SubCounty{{"s1", "Central Division", "d1", "Cluster A"}, {"s2", "Kasawo", "d1", ""}},
		"d1", []Staff{{"u1", "Paul N.", "CCEO"}})
	if d.GetTitle() != "Create cluster" || d.GetSubmitLabel() != "Create cluster" || d.GetCancelLabel() != "Cancel" || !d.GetCanSubmit() || !d.GetHasRequired() {
		t.Fatalf("head = %+v", d)
	}
	items := d.GetItems()
	if len(items) != 8 {
		t.Fatalf("items = %d", len(items))
	}
	district := items[0].GetField()
	if district.GetValue() != "d1" || district.GetReloadsPath() != "/clusters/eligible-staff" || district.GetReloadsTarget() != "responsible_staff_id" ||
		len(district.GetOptions()) != 2 || district.GetOptions()[0].GetLabel() != "Select a district" || !district.GetRequired() {
		t.Errorf("district = %+v", district)
	}
	staff := items[1].GetField()
	if staff.GetLabel() != "Assigned staff (optional)" || staff.GetOptions()[0].GetLabel() != "No assigned staff" || staff.GetOptions()[1].GetLabel() != "Paul N. (CCEO)" || staff.GetOptions()[1].GetValue() != "u1" {
		t.Errorf("staff = %+v", staff)
	}
	subs := items[2].GetField()
	if subs.GetKind() != "checklist" || subs.GetGroupBy() != "district_id" || subs.GetOptions()[0].GetDetail() != "Also in Cluster A" ||
		subs.GetOptions()[0].GetGroup() != "d1" || subs.GetOptions()[1].GetDetail() != "" {
		t.Errorf("sub-counties = %+v", subs)
	}
	if name := items[3].GetField(); name.GetName() != "name" || name.GetMaxLength() != 255 || name.GetPlaceholder() != "e.g. Mukono Central Cluster" {
		t.Errorf("name = %+v", name)
	}
	if items[4].GetHeading() != "Cluster leader" || items[7].GetField().GetKind() != "tel" || items[7].GetField().GetMaxLength() != 64 {
		t.Errorf("leader = %+v %+v", items[4], items[7])
	}
}
