package iapages

import (
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

func TestStoryStatusDefaultsToSubmittedAndDropsAnUnknownOne(t *testing.T) {
	for _, c := range []struct {
		query url.Values
		want  string
	}{
		{url.Values{}, "submitted"},
		{url.Values{"status": {""}}, ""},
		{url.Values{"status": {"approved"}}, "approved"},
		{url.Values{"status": {"draft"}}, "draft"},
		{url.Values{"status": {"bogus"}}, ""},
	} {
		if got := storyStatus(c.query); got != c.want {
			t.Errorf("storyStatus(%v) = %q, want %q", c.query, got, c.want)
		}
	}
}

func TestStoryReachFollowsTheReadersCountry(t *testing.T) {
	args := []any{}
	if got := storyReach(schooldirectory.Scope{CountryScope: true}, &args); got != "TRUE" || len(args) != 0 {
		t.Errorf("unbounded: %q %v", got, args)
	}
	if got := storyReach(schooldirectory.Scope{}, &args); got != "FALSE" {
		t.Errorf("no authority: %q", got)
	}
	if got := storyReach(schooldirectory.Scope{CountryScope: true, Country: "Uganda"}, &args); got == "TRUE" || len(args) != 1 || args[0] != "Uganda" {
		t.Errorf("bounded: %q %v", got, args)
	}
}

func TestFYBoundsRunOctoberToOctober(t *testing.T) {
	start, end := fyBounds("2026")
	if !start.Equal(time.Date(2025, 10, 1, 0, 0, 0, 0, time.UTC)) || !end.Equal(time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC)) {
		t.Errorf("%v %v", start, end)
	}
}

func TestStoryRowsReadAsTheRegisterWritesThem(t *testing.T) {
	school, reason, reviewer := "Hill  Primary", "Needs names", "ia1"
	v := storiesView{me: "ia1", fy: "2027", status: "submitted",
		names: map[string]string{"u1": "Sarah N.", "ia1": "Grace Alimo"},
		areas: map[string]string{"discipleship": "Discipleship (not yet approved)"},
	}
	cells := v.row(story{ID: "s1", Title: "A  <changed> school", Author: "u1", Status: "submitted", School: &school,
		Intervention: "christlike_behaviour", Date: time.Date(2026, 10, 2, 0, 0, 0, 0, time.UTC)}).Cells
	want := []string{"A <changed> school", "Hill Primary", "Sarah N.", "2 Oct 2026", "Submitted", "Christlike Behaviour", "—", ""}
	for i, w := range want {
		if cells[i].Text != w {
			t.Errorf("cell %d = %q, want %q", i, cells[i].Text, w)
		}
	}
	if a := cells[7].Actions[0]; a.Label != "Review" || a.Href != "/ia/stories/s1/" || !a.Drawer || !a.Primary {
		t.Errorf("action: %v", a)
	}
	mine := v.row(story{ID: "s2", Title: "Mine", Author: "ia1", Status: "submitted"}).Cells
	if mine[1].Text != "—" || mine[7].Actions[0].Label != "Open" {
		t.Errorf("own story: %v", mine)
	}
	back := v.row(story{ID: "s3", Title: "R", Author: "gone", Status: "returned", ReturnReason: &reason, ReviewedBy: &reviewer,
		OutcomeArea: "zzz", Intervention: "exposure_to_word_of_god"}).Cells
	if back[2].Text != "Staff member" || back[4].Text != "Returned: Needs names" || back[5].Text != "zzz · Exposure to the Word of God" || back[6].Text != "Grace Alimo" || back[7].Actions[0].Label != "Open" {
		t.Errorf("returned: %v", back)
	}
	if tag := v.row(story{Author: "u1", OutcomeArea: "discipleship"}).Cells[5].Text; tag != "Discipleship (not yet approved)" {
		t.Errorf("area tag: %q", tag)
	}
}

func TestStoriesWithNothingListedReadTheEmptyRegister(t *testing.T) {
	r := storiesView{fy: "2027", status: "draft", fyChoices: []string{"2025", "2026", "2027", "2028"}, number: 1, pages: 1}.response(url.Values{})
	got := blockKinds(r)
	if len(got) != 4 || got[0] != "strip" || got[1] != "filters" || got[2] != "panel:Most Significant Change stories" || got[3] != "table:1" {
		t.Fatalf("blocks %v", got)
	}
	if f := r.Blocks[1].GetFilters().Filters; f[0].Value != "" || len(f[0].Options) != 6 || f[1].Value != "2027" || f[1].Options[0].Label != "FY2025" {
		t.Errorf("filters: %v", f)
	}
	if tb := r.Blocks[3].GetTable(); tb.EmptyMessage != "No stories here" || len(tb.Columns) != 0 {
		t.Errorf("empty table: %v", tb)
	}
	if m := r.Blocks[0].GetStrip().Metrics[1]; m.Note != "FY2027, 0 evidencing spiritual formation" {
		t.Errorf("approved note: %q", m.Note)
	}
}
