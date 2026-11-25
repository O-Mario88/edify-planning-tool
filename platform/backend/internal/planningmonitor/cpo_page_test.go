package planningmonitor

import (
	"fmt"
	"testing"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The Open Follow-ups panel reads as followups_panel.html reads through the
// feed (rendered by Django with these two rows, 2026-11-25): each card one
// line of its title, addressee, status and local date, and the note.
func TestFollowUpsPanelReadsAsTheFeedReadsIt(t *testing.T) {
	items := []cpoFollowUp{
		{id: "fu1", title: "Visits not yet planned · Kasana Primary", to: "Program Lead 1", status: "Sent to PL",
			date: time.Date(2026, 11, 3, 21, 30, 0, 0, time.UTC).In(cpoLocation), reminders: 2},
		{id: "fu2", title: "Training gap · Program Lead 2", to: "Program Lead 2", status: "Acknowledged",
			date: time.Date(2026, 10, 5, 8, 0, 0, 0, time.UTC).In(cpoLocation)},
	}
	note := "All values are for oversight only and are based on planned, assigned, and required records in Edify. They may differ from actual completed activities."
	blocks := followUpsPanel("fy=2027&period=fy", cpoReader{followUp: true}, 7, items)
	if len(blocks) != 1 {
		t.Fatalf("%d blocks", len(blocks))
	}
	p := blocks[0].GetPanel()
	if p.GetTitle() != "Open Follow-ups 7" || len(p.GetItems()) != 2 {
		t.Fatalf("panel %v", p)
	}
	links := p.GetItems()[0].GetLinks().GetLinks()
	want := []string{
		"Visits not yet planned · Kasana Primary To: Program Lead 1 (PL) · reminded 2× Sent to PL 04 Nov 2026",
		"Training gap · Program Lead 2 To: Program Lead 2 (PL) Acknowledged 05 Oct 2026",
	}
	if len(links) != 2 || links[0].GetText() != want[0] || links[1].GetText() != want[1] || links[0].GetHref() != "" {
		t.Errorf("cards %v", links)
	}
	if text, _ := p.GetItems()[1].GetKind().(*screensv1.PagePanelItem_Text); text == nil || text.Text != note {
		t.Errorf("note %v", p.GetItems()[1])
	}
	empty := map[bool]string{
		true:  "No follow-ups are open for this year. Use Follow Up with PL on a Programme Lead's row, or on a gap in any drawer.",
		false: "No follow-ups are open for this year.",
	}
	for may, text := range empty {
		p := followUpsPanel("fy=2027&period=fy", cpoReader{followUp: may}, 0, nil)[0].GetPanel()
		if p.GetTitle() != "Open Follow-ups 0" || p.GetItems()[0].GetText() != text || p.GetItems()[1].GetText() != note {
			t.Errorf("empty (may follow up %v): %v", may, p)
		}
	}
}

// read_filters: an unknown period falls back by what else the link names,
// a quarter or month left out is today's, and an unknown type is dropped.
func TestCPOReadFilters(t *testing.T) {
	today := date(2026, 11, 25)
	cases := []struct {
		q                       map[string]string
		fy, period, quarter, wk string
		month                   int
		schoolType              string
	}{
		{map[string]string{}, "2027", "fy", "", "", 0, ""},
		{map[string]string{"fy": "20x7", "quarter": "q3"}, "2027", "quarter", "Q3", "", 0, ""},
		{map[string]string{"period": "quarter"}, "2027", "quarter", "Q1", "", 0, ""},
		{map[string]string{"period": "month"}, "2027", "month", "", "", 11, ""},
		{map[string]string{"month": "13", "period": "nonsense"}, "2027", "fy", "", "", 0, ""},
		{map[string]string{"period": "week"}, "2027", "week", "", "2026-W48", 0, ""},
		{map[string]string{"school_type": "bogus", "family": "core_family"}, "2027", "fy", "", "", 0, "core"},
		{map[string]string{"school_type": "client", "quarter": "Q2", "period": "fy"}, "2027", "fy", "", "", 0, "client"},
	}
	for _, c := range cases {
		f := cpoReadFilters(c.q, today)
		if f.fy != c.fy || f.period != c.period || f.quarter != c.quarter || f.week != c.wk || f.month != c.month || f.schoolType != c.schoolType {
			t.Errorf("%v: %+v", c.q, f)
		}
	}
}

// The tables' words: _count_line's plurals, _balance, _expected_from, the
// header links' parameter order (page_blocks._resolved), the pager's pages
// and str.title for an activity type without a label.
func TestCPOTableWords(t *testing.T) {
	if got := countLine(1, "activity") + "|" + countLine(1200, "activity") + "|" + countLine(2, "school"); got != "1 activity|1,200 activities|2 schools" {
		t.Errorf("count lines %q", got)
	}
	if got := balance(6, 560) + "|" + balance(600, 560) + "|" + balance(3, 0); got != "6 of 560 · 554 to plan|600 of 560 · 0 to plan|no target" {
		t.Errorf("balances %q", got)
	}
	if got := expectedFrom(2, 2) + "|" + expectedFrom(0, 1) + "|" + expectedFrom(1, 0) + "|" + expectedFrom(0, 0); got != "Staff 2 · Partner 2|Partner|Staff|" {
		t.Errorf("expected from %q", got)
	}
	if got := resolvedHref("/x", "fy=2027&period=fy&cluster=c1&blank="); got != "/x?cluster=c1&fy=2027&period=fy" {
		t.Errorf("resolved %q", got)
	}
	if got := fmt.Sprint(cpoPageWindow(1, 13), cpoPageWindow(7, 13), cpoPageWindow(13, 13), cpoPageWindow(3, 5)); got != "[1 2 0 13] [1 0 6 7 8 0 13] [1 0 12 13] [1 2 3 4 5]" {
		t.Errorf("page windows %s", got)
	}
	if got := pyTitleWords("school visit"); got != "School Visit" {
		t.Errorf("title %q", got)
	}
}
