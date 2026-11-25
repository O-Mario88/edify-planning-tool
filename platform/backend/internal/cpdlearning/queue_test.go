package cpdlearning

import "testing"

// supervisor_queue.html as the feed reads it: the count, each row's officer
// (and whether the reader covers them), course with its type and year, the
// money with "over allocation", how long it has waited or its conflict, and
// the Return drawer as the one action.
func TestQueueBlocksReadAsTheFeedReadsThem(t *testing.T) {
	nine := 9
	queue := []queueRow{
		{id: "r1", staffName: "Deo M.", course: "Data for Schools", courseType: "Online", fy: "2027",
			dates: "11 Jan 2027 – 19 Feb 2027", amount: "USD 450", exception: true, waited: &nine},
		{id: "r2", staffName: "Ann K.", course: "Mentoring", courseType: "In Person", fy: "2026", dates: "—",
			amount: "USD 150", conflict: "major_conflict", covering: true},
	}
	blocks := queueBlocks(queue, false)
	if len(blocks) != 2 || blocks[0].GetPanel().GetItems()[0].GetText() != "2 requests" {
		t.Fatalf("blocks %v", blocks)
	}
	rows := blocks[1].GetTable().GetRows()
	got := []string{}
	for _, c := range rows[0].GetCells()[:5] {
		got = append(got, c.GetText())
	}
	want := []string{"Deo M.", "Data for Schools Online · FY 2027", "11 Jan 2027 – 19 Feb 2027", "USD 450 · over allocation", "9 days"}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("cell %d %q, want %q", i, got[i], want[i])
		}
	}
	if c := rows[1].GetCells(); c[0].GetText() != "Ann K. · you are covering" || c[4].GetText() != "Schedule conflict" {
		t.Errorf("second row %v", c)
	}
	if a := rows[0].GetCells()[5].GetActions(); len(a) != 1 || a[0].GetHref() != "/cpd-learning/return?request_id=r1" || !a[0].GetDrawer() {
		t.Errorf("actions %v", a)
	}
	if queueBlocks(nil, false) != nil || len(queueBlocks(nil, true)) != 1 {
		t.Error("the empty queue: HR draws nothing, the team view its empty state")
	}
}
