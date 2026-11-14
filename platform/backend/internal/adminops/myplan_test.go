package adminops

import (
	"net/url"
	"slices"
	"strings"
	"testing"
	"time"
)

func date(y int, m time.Month, d int) *time.Time {
	t := time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
	return &t
}

func TestMyPlanSortsWorkIntoItsSections(t *testing.T) {
	now := time.Date(2026, 11, 14, 9, 0, 0, 0, zone) // a Saturday: the week ends tomorrow
	inc := "i1"
	active := []workItem{
		{Reference: "crit", Severity: "critical", Status: "scheduled", Scheduled: date(2026, 12, 14)},
		{Reference: "late", Severity: "medium", Status: "in_progress", Due: date(2026, 11, 12)},
		{Reference: "today", Severity: "high", Status: "scheduled", Scheduled: date(2026, 11, 14), Incident: &inc},
		{Reference: "sunday", Severity: "low", Status: "waiting", Scheduled: date(2026, 11, 15)},
		{Reference: "monday", Severity: "low", Status: "scheduled", Scheduled: date(2026, 11, 16)},
		{Reference: "undated", Severity: "low", Status: "scheduled"},
		{Reference: "watch", Severity: "critical", Status: "monitoring", Scheduled: date(2026, 11, 14)},
	}
	got := [][]string{}
	for _, s := range sectionWork(active, now) {
		refs := []string{}
		for _, w := range s.items {
			refs = append(refs, w.Reference)
		}
		got = append(got, refs)
	}
	want := [][]string{{"crit"}, {"today"}, {"late"}, {"sunday"}, {"monday", "undated"}, {"watch"}}
	for i := range want {
		if !slices.Equal(got[i], want[i]) {
			t.Errorf("section %d = %v, want %v", i, got[i], want[i])
		}
	}
}

func TestMyPlanRowsReadAsTheFeedReadsThem(t *testing.T) {
	inc := "i1"
	if got := rowWords(workItem{Severity: "high", Reference: "OPS-1", Category: "preventive_maintenance", Scheduled: date(2026, 11, 14),
		Title: "Item  3", Status: "scheduled", Route: "/planning", Incident: &inc}); !slices.Equal(got,
		[]string{"High", "OPS-1", "Preventive Maintenance", "14 Nov", "Item 3", "/planning · Scheduled · Incident"}) {
		t.Errorf("scheduled: %v", got)
	}
	if got := rowWords(workItem{Severity: "low", Reference: "OPS-4", Category: "preventive_maintenance", Title: "Item 4", Status: "waiting"}); !slices.Equal(got,
		[]string{"Low", "OPS-4", "Preventive Maintenance", "Item 4", "Waiting", "Waiting"}) {
		t.Errorf("waiting: %v", got)
	}
	if got := rowWords(workItem{Severity: "low", Reference: "OPS-2", Category: "x", Title: "Item 2", Status: "in_progress"}); got[len(got)-1] != "In Progress" || len(got) != 5 {
		t.Errorf("in progress: %v", got)
	}
}

func TestMyPlanReadsALoneCompleteRowAsItsForm(t *testing.T) {
	r := myPlanPage([]myPlanSection{
		{title: "Needs Attention", items: []workItem{{ID: "w2", Reference: "OPS-2", Title: "Item 2", Status: "in_progress", Severity: "medium"}}},
		{title: "Due Today", items: []workItem{{Reference: "a", Status: "in_progress"}, {Reference: "b", Status: "in_progress"}}},
		{title: "Planned Later", empty: "Nothing is planned beyond this week."},
	}, nil)
	f := r.Blocks[0].GetForm()
	if f == nil || f.Title != "Needs Attention 1" || f.Text != "Item 2" || f.Key != "/admin-ops/work-items/w2/complete" || f.SubmitLabel != "Complete" {
		t.Fatalf("form: %v", r.Blocks[0])
	}
	if fd := f.Items[0].GetField(); fd.Label != "How was OPS-2 verified?" || !fd.Required || fd.Placeholder != "How was this verified?" {
		t.Errorf("field: %v", fd)
	}
	if r.Blocks[1].GetSection() != "Due Today 2" || r.Blocks[2].GetPanel() == nil {
		t.Errorf("two rows: %v %v", r.Blocks[1], r.Blocks[2])
	}
	if p := r.Blocks[3].GetPanel(); p.Title != "Planned Later 0" || p.Items[0].GetText() != "Nothing is planned beyond this week." {
		t.Errorf("empty: %v", p)
	}
	if p := r.Blocks[4].GetPanel(); p.Title != "Recently Verified and Closed" || !strings.HasPrefix(p.Items[0].GetText(), "Nothing closed yet.") {
		t.Errorf("closed: %v", p)
	}
	long := workItem{Reference: "OPS-9", Title: strings.Repeat("t", 400), Status: "monitoring"}
	if completeForm("Monitoring and Verification 1", []workItem{long}) != nil {
		t.Error("a card with more than 400 characters around its form is not the form")
	}
}

func TestTruncateCharsEndsInAnEllipsisAtTheLimit(t *testing.T) {
	note := "Checked " + strings.Repeat("y", 130)
	got := truncateChars(note, 120)
	if n := len([]rune(got)); n != 120 || !strings.HasSuffix(got, "y…") {
		t.Errorf("%d %q", n, got)
	}
	if truncateChars("short", 120) != "short" {
		t.Error("short notes stay whole")
	}
}

func TestPlanningReadsTheBacklogIncidentsAndTickets(t *testing.T) {
	r := planningPage(
		[]workItem{{Title: "Item 9", Route: "/r", Reference: "OPS-9", Severity: "critical", Category: "preventive_maintenance"}},
		[]openIncident{{ID: "i0", Reference: "INC-1", Title: "Broken  route", Seen: 2}, {ID: "i1", Reference: "INC-2", Title: "B", Seen: 1}},
		nil, url.Values{})
	if m := r.Blocks[0].GetStrip().Metrics; m[0].Value != "2" || m[1].Value != "0" {
		t.Errorf("strip: %v", m)
	}
	row := r.Blocks[1].GetTable().Rows[0].Cells
	if row[0].Text != "Item 9/r" || row[2].Text != "Critical" || row[4].Text != "" || row[5].Text != "Schedule" {
		t.Errorf("backlog row: %v", row)
	}
	links := r.Blocks[2].GetPanel().Items[0].GetLinks().Links
	if len(links) != 2 || links[0].Text != "INC-1 seen 2×" || links[0].Caption != "Broken route" || links[0].Href != "/admin-ops/incidents/i0" {
		t.Errorf("incidents: %v", links)
	}
	if p := r.Blocks[3].GetPanel(); p.Title != "Tickets Awaiting Triage" || p.Items[0].GetText() != "No tickets are waiting for triage." {
		t.Errorf("no tickets: %v", p)
	}
	r = planningPage(nil, nil, []triageTicket{{Reference: "TCK-1", Title: "Help me", Category: "other"}}, url.Values{})
	if row := r.Blocks[3].GetTable().Rows[0].Cells; row[0].Text != "TCK-1Help me" || row[1].Text != "Other · user" || row[2].Text != "CriticalHighMediumLow" {
		t.Errorf("ticket row: %v", row)
	}
	if r.Blocks[1].GetPanel().Title != "Unscheduled Platform Work" || r.Blocks[2].GetPanel().Items[0].GetText() != "No open incidents." {
		t.Errorf("empty backlog and incidents: %v %v", r.Blocks[1], r.Blocks[2])
	}
}
