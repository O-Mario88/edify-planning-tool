package plreview

import (
	"net/url"
	"testing"
	"time"
)

func str(s string) *string { return &s }

func TestTheLeadIsSentToTheDashboardTabWithTheOfficerAndCompletion(t *testing.T) {
	if got := dashboardURL("", ""); got != "/dashboard?pm=view%3Dexecution#planning-monitor" {
		t.Errorf("plain: %q", got)
	}
	if got := dashboardURL("x y", "a1"); got != "/dashboard?pm=view%3Dexecution%26cceo%3Dx%2By%26open%3Da1#planning-monitor" {
		t.Errorf("carried: %q", got)
	}
}

func TestTheRegisterWritesEachCompletionAsTheRowDoes(t *testing.T) {
	today := time.Date(2026, 11, 14, 0, 0, 0, 0, time.UTC)
	actual := time.Date(2026, 11, 2, 0, 0, 0, 0, time.UTC)
	list := []completion{
		{ID: "a2", Owner: "u2", Type: "partner_activity", Cluster: str("Cluster E"), Others: 3, AttendedSchools: 2,
			Since: time.Date(2026, 11, 9, 8, 0, 0, 0, time.UTC)},
		{ID: "a1", Owner: "sp1", Type: "partner_activity", School: str("Kasawo  Primary"), SchoolCode: str("1497"), Actual: &actual,
			Teachers: 4, Leaders: 1, SalesforceID: "SF-1", Intervention: "leadership", Since: time.Date(2026, 11, 5, 8, 0, 0, 0, time.UTC)},
		{ID: "a3", Owner: "", Type: "made_up", Venue: "", Intervention: "odd", Since: time.Date(2026, 11, 20, 8, 0, 0, 0, time.UTC)},
	}
	names := map[string]string{"sp1": "Sarah N.", "u1": "Sarah N.", "u2": "alex"}
	profiles := map[string]string{"sp1": "sp1", "u1": "sp1", "u2": "sp2"}
	rows, options := register(list, names, profiles, today)
	if rows[0].ID != "a1" || rows[0].Waited != 9 || rows[1].ID != "a2" || rows[1].Waited != 5 || rows[2].Waited != 0 {
		t.Fatalf("order: %+v", rows)
	}
	r := rows[0]
	if r.Officer != "Sarah N." || r.Code != "1497" || r.Where != "Kasawo Primary" || r.Date != "2 Nov 2026" || r.Intervention != "LSHIP" ||
		r.Attendance != "4 teachers · 1 leaders" || r.Salesforce != "SF-1" || r.Activity != rules.ActivityTypes["partner_activity"] {
		t.Errorf("school row: %+v", r)
	}
	if c := rows[1]; c.Code != "—" || c.Where != "Cluster E (cluster)" || c.Attendance != "3 others · 2 schools" || c.Salesforce != "Not entered" || c.Date != "—" {
		t.Errorf("cluster row: %+v", c)
	}
	if o := rows[2]; o.Officer != "Unnamed officer" || o.Where != "—" || o.Intervention != "odd" || o.Activity != "made_up" {
		t.Errorf("bare row: %+v", o)
	}
	if len(options) != 2 || options[0].Label != "alex" || options[1].Value != "sp1" {
		t.Errorf("options: %v", options)
	}
}

func TestTheRegisterPageReadsItsFilterTableAndEmptyState(t *testing.T) {
	r := page(nil, nil, "", url.Values{})
	if r.Blocks[0].GetPanel().Title != "Waiting on you" || len(r.Blocks) != 2 {
		t.Fatalf("blocks: %v", r.Blocks)
	}
	tb := r.Blocks[1].GetTable()
	if len(tb.Columns) != 10 || tb.EmptyMessage != "Nothing is waiting on you" || len(tb.Rows) != 1 {
		t.Errorf("empty table: %v", tb)
	}
	rows := []row{{ID: "a1", Officer: "Sarah N.", Waited: 9}}
	r = page(rows, []option{{"sp1", "Sarah N."}, {"sp2", "alex"}}, "sp9", url.Values{})
	f := r.Blocks[1].GetFilters().Filters[0]
	if f.Name != "cceo" || f.Value != "" || len(f.Options) != 3 || f.Options[0].Label != "Every officer" {
		t.Errorf("filter: %v", f)
	}
	cells := r.Blocks[2].GetTable().Rows[0].Cells
	if a := cells[9].Actions; len(a) != 2 || a[0].Label != "Verify" || a[0].Href != "/pl/review-queue/a1/drawer" || a[1].Href != "/pl/review-queue/a1/return-drawer" || !a[1].Drawer || a[0].Key != "menu" {
		t.Errorf("actions: %v", a)
	}
	if cells[8].Text != "9" {
		t.Errorf("wait: %q", cells[8].Text)
	}
	if one := page(rows, []option{{"sp1", "Sarah N."}}, "", url.Values{}); len(one.Blocks) != 2 {
		t.Errorf("one officer draws no filter: %v", one.Blocks)
	}
}
