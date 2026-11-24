package projectcapacity

import (
	"reflect"
	"testing"
)

func TestSelectionRefusalIsAssertBatchFits(t *testing.T) {
	cases := []struct {
		count int
		a     allocationRow
		want  string
	}{
		{2, allocationRow{maximum: 5, assigned: 3}, ""},
		{3, allocationRow{maximum: 5, assigned: 3}, "Capacity exceeded. You can add a maximum of 2 more schools to this project."},
		{2, allocationRow{maximum: 5, assigned: 4}, "Capacity exceeded. You can add a maximum of 1 more school to this project."},
		{1, allocationRow{maximum: 5, assigned: 5}, "Project capacity reached. You have reached your allocation of 5 schools for Numeracy. No additional schools can be added unless the Project Coordinator increases your allocation."},
		{1, allocationRow{maximum: 5, assigned: 7}, "Project capacity reached. You have reached your allocation of 5 schools for Numeracy. No additional schools can be added unless the Project Coordinator increases your allocation."},
	}
	for _, c := range cases {
		got := selectionRefusal("Numeracy", c.a, c.count)
		if got != c.want {
			t.Errorf("selectionRefusal(%d, %+v) = %q, want %q", c.count, c.a, got, c.want)
		}
	}
}

func TestBulkMessagesAreTheViewsInItsOrder(t *testing.T) {
	got := bulkMessages("Numeracy", 2, 1, []skipped{{"Alpha", "No."}, {"Beta", "Nope."}, {"Gamma", "x"}, {"Delta", "y"}})
	want := []Said{
		{Warning, "Skipped 1 school(s) already assigned to this project."},
		{Error, "Skipped 4 school(s): Alpha: No.; Beta: Nope.; Gamma: x and 1 more."},
		{Success, "Successfully assigned 2 school(s) to project 'Numeracy'."},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("got %+v\nwant %+v", got, want)
	}
	if got := bulkMessages("Numeracy", 0, 0, nil); !reflect.DeepEqual(got, []Said{{Error, "No new project assignments were made."}}) {
		t.Errorf("nothing added = %+v", got)
	}
	if got := bulkMessages("Numeracy", 0, 0, []skipped{{"Alpha", "No."}}); !reflect.DeepEqual(got, []Said{{Error, "Skipped 1 school(s): Alpha: No.."}}) {
		t.Errorf("only refusals = %+v", got)
	}
}

func TestTickedCodesAreRepeatedOrJoinedAndDistinct(t *testing.T) {
	if got := TickedCodes([]string{"1442, 1338", " 1442 ", "", "x"}); !reflect.DeepEqual(got, []string{"1442", "1338", "x"}) {
		t.Errorf("TickedCodes = %v", got)
	}
}

func TestOutcomesReadAsTheFeedReadsThem(t *testing.T) {
	said := []Said{{Warning, "W."}, {Success, "S."}}
	if r := AsDirectory(said); !r.Saved || r.Message != "S." || !reflect.DeepEqual(r.Warnings, []string{"W."}) || r.Error != "" {
		t.Errorf("directory = %+v", r)
	}
	if r := AsDirectory([]Said{{Error, "E."}, {Warning, "W."}, {Success, "S."}}); r.Saved || r.Error != "E." || !reflect.DeepEqual(r.Warnings, []string{"W."}) {
		t.Errorf("an error wins = %+v", r)
	}
	if r := AsDirectory([]Said{{Warning, "W."}}); r.Saved || r.Error != "W." || len(r.Warnings) != 0 {
		t.Errorf("warnings alone = %+v", r)
	}
	if saved, text := AsDrawer(said); !saved || text != "S." {
		t.Errorf("drawer saved = %v %q", saved, text)
	}
	if saved, text := AsDrawer([]Said{{Warning, "W."}, {Error, "E."}}); saved || text != "W. E." {
		t.Errorf("drawer refused = %v %q", saved, text)
	}
}
