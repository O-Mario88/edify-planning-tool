package perfcycle

import (
	"net/url"
	"testing"
	"time"
)

func TestTheQuarterEndsAsTheReadinessCheckCountsIt(t *testing.T) {
	for _, c := range []struct {
		today    time.Time
		q        string
		end      time.Time
		daysLeft int
	}{
		{time.Date(2026, 11, 14, 0, 0, 0, 0, time.UTC), "Q1", time.Date(2026, 12, 31, 0, 0, 0, 0, time.UTC), 47},
		{time.Date(2027, 2, 1, 0, 0, 0, 0, time.UTC), "Q2", time.Date(2027, 3, 31, 0, 0, 0, 0, time.UTC), 58},
		{time.Date(2027, 6, 30, 0, 0, 0, 0, time.UTC), "Q3", time.Date(2027, 6, 30, 0, 0, 0, 0, time.UTC), 0},
		{time.Date(2027, 9, 23, 0, 0, 0, 0, time.UTC), "Q4", time.Date(2027, 9, 30, 0, 0, 0, 0, time.UTC), 7},
	} {
		q, end := quarterEnd(c.today)
		if q != c.q || !end.Equal(c.end) || int(end.Sub(c.today).Hours()/24) != c.daysLeft {
			t.Errorf("%v: %s %v", c.today, q, end)
		}
	}
}

func TestStagesReadInTheConsolesWords(t *testing.T) {
	if stageLabel("priorities_agreed") != "Approved & locked" || stageLabel("slt_calibrated") != "Slt Calibrated" {
		t.Errorf("%q %q", stageLabel("priorities_agreed"), stageLabel("slt_calibrated"))
	}
}

func TestTheControlsReadAsTheFeedReadsThem(t *testing.T) {
	if got := controls("2027", false, "none").GetPanel().Items[0].GetText(); got != "Open FY2027 cycle & draft agreements" {
		t.Errorf("no cycle: %q", got)
	}
	f := controls("2027", true, "none").GetForm()
	if f == nil || f.Key != "activate_window" || f.SubmitLabel != "Activate & freeze snapshots" || len(f.Items) != 2 ||
		f.Items[0].GetField().Value != "priority_setting" || len(f.Items[0].GetField().Options) != 5 || f.Items[1].GetField().Kind != "date" {
		t.Fatalf("window form: %v", f)
	}
	if got := controls("2027", true, "year_end").GetPanel().Items[0].GetText(); got != "Activate window FY priority settingQ1 conversationMid-year review (Q2)Q3 conversationEnd-of-year review (Q4) Deadline Activate & freeze snapshots Close window" {
		t.Errorf("open window: %q", got)
	}
}

func TestTheAgreementsTableKeepsOnlyTheConversationLink(t *testing.T) {
	r := page("2027", true, "year_end", readiness{quarter: "Q1", daysLeft: 47}, []agreement{{"sp1", "Grace  Alimo", "slt_calibrated"}}, url.Values{})
	if p := r.Blocks[4].GetPanel(); p.Items[1].GetText() != "year_end" || p.Items[2].GetText() != "form open" {
		t.Errorf("window panel: %v", p)
	}
	if r.Blocks[6].GetPanel().Title != "Agreements in scope (1)" {
		t.Errorf("heading: %v", r.Blocks[6])
	}
	cells := r.Blocks[7].GetTable().Rows[0].Cells
	if cells[0].Text != "Grace Alimo" || cells[1].Text != "Slt Calibrated" || len(cells[2].Actions) != 1 ||
		cells[2].Actions[0].Href != "/performance-conversation?staff=sp1" || cells[2].Actions[0].Key != "menu" {
		t.Errorf("row: %v", cells)
	}
	empty := page("2027", false, "none", readiness{}, nil, url.Values{})
	if rows := empty.Blocks[7].GetTable().Rows; len(rows) != 1 || rows[0].Cells[0].Text != "No agreements yet — open the cycle to draft them." {
		t.Errorf("empty: %v", rows)
	}
}
