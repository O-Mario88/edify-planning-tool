package hrtoday

import (
	"net/url"
	"testing"
	"time"
)

func TestAlikeRowsFoldFromThree(t *testing.T) {
	same := exception{title: "T", detail: "D", severity: "high", url: "/org-structure"}
	two := []exception{same, same}
	if rows := fold(two); len(rows) != 2 || rows[0].people != nil {
		t.Errorf("two alike stay two: %+v", rows)
	}
	three := []exception{same, {title: "Other", severity: "high"}, same, same}
	rows := fold(three)
	if len(rows) != 2 || len(rows[0].people) != 3 || rows[1].title != "Other" {
		t.Errorf("three alike fold, in the first one's place: %+v", rows)
	}
}

func TestAQueueSaysWhatItLeftOut(t *testing.T) {
	items := []exception{}
	for i := range 12 {
		items = append(items, exception{title: "T" + string(rune('a'+i)), severity: "medium", url: "/onboarding"})
	}
	blocks := queue([]string{"/onboarding"}, "Waiting on HR", items, 1, url.Values{})
	if got := blocks[0].GetPanel().Items[0].GetText(); got != "12 open — showing the 10 most urgent" {
		t.Errorf("count line: %q", got)
	}
	if len(blocks[1].GetTable().Rows) != 10 || blocks[len(blocks)-1].GetPanel().Items[0].GetText()[:2] != "2 " {
		t.Errorf("rows / overflow: %v", blocks)
	}
	if r := blocks[1].GetTable().Rows[0]; r.Cells[3].Text != "Open" || r.Cells[2].Text != "Medium" || r.Cells[2].Tone != "neutral" {
		t.Errorf("row: %v", r)
	}
	if empty := queue(nil, "Upcoming deadlines", nil, 4, url.Values{}); empty[0].GetPanel().Subtitle != "Nothing open." {
		t.Error("an empty queue says so")
	}
}

func TestLabelsReadAsTheTemplateDoes(t *testing.T) {
	today := time.Date(2026, 11, 14, 0, 0, 0, 0, time.UTC)
	if dueLabel(today.AddDate(0, 0, -1), today) != "1 days overdue" || dueLabel(today, today) != "due today" ||
		dueLabel(today.AddDate(0, 0, 1), today) != "due tomorrow" || dueLabel(today.AddDate(0, 0, 5), today) != "in 5 days" {
		t.Error("dueLabel")
	}
	if daysAgo(0) != "today" || daysAgo(1) != "1 day" || djangoTitle("waiting 4 days") != "Waiting 4 Days" || djangoTitle("the 2nd") != "The 2nd" {
		t.Errorf("titles: %q %q", djangoTitle("waiting 4 days"), djangoTitle("the 2nd"))
	}
	if opens([]string{"/leave/approvals"}, "") || !opens([]string{"/leave/approvals"}, "/leave/approvals?id=x") {
		t.Error("opens")
	}
}
