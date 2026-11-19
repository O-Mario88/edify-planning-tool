package financedesks

import (
	"testing"
	"time"
)

func TestADeskWordsAWeekAndAnIDAsTheExistingTemplates(t *testing.T) {
	monday := time.Date(2026, 4, 27, 0, 0, 0, 0, time.UTC)
	if got := isoWeek(&monday); got != "2026-W18" {
		t.Errorf("isoWeek: %q", got)
	}
	// Django's "Y" is the calendar year even where the ISO week belongs to
	// the next one.
	dec := time.Date(2025, 12, 29, 0, 0, 0, 0, time.UTC)
	if got := isoWeek(&dec); got != "2025-W1" {
		t.Errorf("isoWeek across the year: %q", got)
	}
	if isoWeek(nil) != "" || short("gdeskdone") != "gdeskdon" || short("abc") != "abc" {
		t.Errorf("short or a missing week: %q %q", short("gdeskdone"), isoWeek(nil))
	}
	if got := joined("#gdeskdon", "", " School Visit "); got != "#gdeskdon School Visit" {
		t.Errorf("joined: %q", got)
	}
	if ugx(18500) != "UGX 18,500" || ugx(-2500) != "UGX -2,500" || ugx(0.5) != "UGX 0" || ugx(1.5) != "UGX 2" {
		t.Errorf("ugx: %q %q %q %q", ugx(18500), ugx(-2500), ugx(0.5), ugx(1.5))
	}
}

func TestEveryDeskIsOpenToTheAccountantAndNoneToAnOfficer(t *testing.T) {
	for path := range desks {
		if !rules.Roles["Accountant"].Desks[path] || rules.Roles["CCEO"].Desks[path] {
			t.Errorf("%s: accountant %v, CCEO %v", path, rules.Roles["Accountant"].Desks[path], rules.Roles["CCEO"].Desks[path])
		}
	}
	if len(desks) != 9 {
		t.Errorf("%d desks", len(desks))
	}
}
